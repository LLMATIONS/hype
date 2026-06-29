"""Guild-name voting backend for hype.

A tiny FastAPI + SQLite service that backs the /guild-names/ page. It runs on
loopback only (127.0.0.1) behind a reverse proxy that forwards same-origin
/api/* to it. Submitted names are shown to every visitor, so all input is
treated as hostile. Layers, outermost first:

  * the reverse proxy enforces the document CSP (no inline script on the vote
    page) and can rate-limit at the edge;
  * this service requires application/json, caps the body size, NFC-normalizes
    input and strips control / zero-width / bidi-override characters, length-
    caps everything, and binds every SQL parameter;
  * a Cloudflare Turnstile token gates submissions (verified server-side) when
    a secret is configured;
  * a per-IP sliding-window rate limit plus an anonymous per-browser UUID give
    best-effort one-vote-per-idea. Output is escaped at render time in the
    browser (textContent), which is the real XSS defense — we store names
    faithfully and never trust them as markup.

None of the no-login defenses are airtight (clear localStorage, rotate IPs),
and the privacy page says so. The IP is read only to feed the rate limiter and
the Turnstile check; it is never written to the database.

Run for local preview:

    GUILDNAMES_DB=./data/guildnames.db python app.py    # serves 127.0.0.1:8794

In production it is launched by the hype-vote systemd unit via uvicorn.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Ed25519 verification for Discord interaction webhooks. Guarded so a missing
# dependency degrades to "interactions endpoint disabled" rather than a boot
# failure for the rest of the service.
try:
    from nacl.exceptions import BadSignatureError
    from nacl.signing import VerifyKey
    _HAVE_NACL = True
except Exception:  # pragma: no cover - dependency-presence guard
    _HAVE_NACL = False

# --- configuration ----------------------------------------------------------
# DB path is host-side and gitignored; default keeps preview self-contained.
DB_PATH = Path(os.environ.get("GUILDNAMES_DB", "./data/guildnames.db")).expanduser()

NAME_MAX = 24          # WoW's hard cap on guild names (in-game range is 2–24)
NAME_MIN = 2           # matches WoW's floor
WHY_MAX = 200          # one-liner pitch
VOTER_ID_MAX = 64      # a UUID is 36; allow slack but cap to stop abuse
MAX_IDEAS = 500        # global ceiling so the table can't be flooded
MAX_BODY = 16384       # request body cap (bytes); an application is two short
                       # paragraphs + a few fields + a ~2 KB Turnstile token
# Discord interaction payloads bundle the full source message + the clicker's
# member object (role-id array, permissions), so they run larger than our own
# writes. This path is Ed25519-verified downstream, so a roomier-but-bounded cap
# is safe; it only ever sees traffic Discord signed.
DISCORD_MAX_BODY = 262144

# Guild-application field caps (the /apply page). Free text is cleaned and
# length-capped, then stored faithfully and rendered with textContent.
CHAR_MAX = 40          # character name
DISCORD_MAX = 64       # discord handle
CLASS_MAX = 32         # class (free text — no expansion pinned)
EXPERIENCE_MAX = 1500  # raiding-experience paragraph
WHY_APPLY_MAX = 1500   # why-join paragraph
LOGS_MAX = 300         # optional logs URL
GEARSCORE_MAX = 5      # required gearscore — digits only (addon tops out ~4 digits)
MAX_APPLICATIONS = 2000  # global ceiling so the table can't be flooded

# per-IP sliding-window limits: (max events, window seconds)
SUBMIT_LIMIT = (6, 600)    # 6 new ideas per 10 minutes
VOTE_LIMIT = (90, 60)      # 90 vote actions per minute (covers fast toggling)
ADMIN_LIMIT = (30, 60)     # admin actions per minute per IP (brute-force throttle)
APPLY_LIMIT = (4, 600)     # 4 guild applications per 10 minutes per IP

# Cloudflare Turnstile (bot gate on submissions). Both come from the service
# env file, never the repo. With no secret set, verification is skipped so the
# tool still works before the keys land; once set, a bad/missing token is
# rejected and a verify error fails closed.
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET", "").strip()
TURNSTILE_SITEKEY = os.environ.get("TURNSTILE_SITEKEY", "").strip()
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# Admin moderation runs on a separate, internal-only subdomain
# (hype-admin.swagcounty.com, not exposed to the public internet) that
# Authentik forward-auth gates. Caddy
# verifies the SSO session and injects the authenticated user's name in
# X-Authentik-Username — overwriting any client-supplied copy — before proxying
# here, so an unauthenticated request never reaches an admin endpoint. The
# public origin never proxies /api/admin/* and never sets this header. There is
# no app-managed admin secret: the gate is the SSO session, owned by Authentik.
ADMIN_IDENTITY_HEADER = "x-authentik-username"

# Guild-application delivery. Each channel is independent and best-effort: an
# unset secret means that channel is skipped (status "off"), so the form works
# while delivery is still being wired up. All three live only in the mode-600
# service env file (set via server/configure-apply.sh), never the repo.
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
# A bot token unlocks what a webhook can't: a per-applicant thread titled
# "<character> — <class>" and pre-seeded ✅/❌ officer-vote reactions. When set,
# the bot path supersedes the webhook entirely (no double-posting). The target
# channel is auto-discovered from the webhook URL, or pinned explicitly below.
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
DISCORD_APPLICATIONS_CHANNEL_ID = os.environ.get(
    "DISCORD_APPLICATIONS_CHANNEL_ID", "").strip()
# Optional officer role id. When set, the per-applicant thread's starter message
# @mentions it — Discord adds every member of a (<100-member) role to the thread,
# which surfaces it in their sidebars and pings them that a new application
# landed. Unset ⇒ no mention (thread is reachable but not auto-pinned).
DISCORD_OFFICER_ROLE_ID = os.environ.get("DISCORD_OFFICER_ROLE_ID", "").strip()
# The bot app's public key (Discord Developer Portal → General Information).
# Used to Ed25519-verify interaction webhooks (officer-vote button clicks).
# Not a secret, but config-driven so it tracks the app. Empty ⇒ the
# interactions endpoint fails closed (rejects everything with 401).
DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY", "").strip()
DISCORD_API = "https://discord.com/api/v10"
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
APPLY_MAIL_FROM = os.environ.get("APPLY_MAIL_FROM", "").strip()
APPLY_MAIL_TO = os.environ.get("APPLY_MAIL_TO", "").strip()  # comma-separated
RESEND_API_URL = "https://api.resend.com/emails"
APPLY_CONTACT = "@ivorycrayon"  # the Discord handle applicants are told to reach
# Outbound calls MUST send a descriptive User-Agent. Discord's API is behind
# Cloudflare, which 403s the default "Python-urllib/x.y" UA as bot traffic; a
# named UA is also what Discord's API guidelines require. Resend is fine either
# way, but gets the same header for consistency.
APPLY_UA = "Hype-Apply/1.0 (+https://hype.swagcounty.com)"

_WS_RUN = re.compile(r"\s+")
_INLINE_WS = re.compile(r"[^\S\n]+")   # whitespace except newline (for paragraphs)
_BLANKLINES = re.compile(r"\n{3,}")
_VOTER_RE = re.compile(r"^[A-Za-z0-9._:-]{8,%d}$" % VOTER_ID_MAX)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _db
    _db = _connect()
    try:
        yield
    finally:
        _db.close()


app = FastAPI(
    title="hype — backend (guild-name vote + applications)",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


# --- request hardening middleware -------------------------------------------
@app.middleware("http")
async def guard_request(request: Request, call_next):
    """Reject non-JSON and oversized writes before they reach a handler."""
    if request.method in ("POST", "PUT", "PATCH"):
        ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return JSONResponse({"error": "Send JSON."}, status_code=415)
        clen = request.headers.get("content-length")
        cap = (DISCORD_MAX_BODY if request.url.path == "/api/discord/interactions"
               else MAX_BODY)
        if clen is not None:
            try:
                if int(clen) > cap:
                    return JSONResponse({"error": "That's too much data."}, status_code=413)
            except ValueError:
                return JSONResponse({"error": "Bad request."}, status_code=400)
    return await call_next(request)


# --- storage ----------------------------------------------------------------
# One connection guarded by a lock. FastAPI runs the sync handlers in a thread
# pool; the lock serializes DB access and the in-memory rate-limit buckets. At
# guild scale this is plenty and avoids SQLite write-lock surprises.
_lock = threading.Lock()
_db: sqlite3.Connection


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ideas (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            name_key    TEXT NOT NULL UNIQUE,   -- normalized, for case-insensitive dedup
            why         TEXT,
            created_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS votes (
            idea_id     TEXT NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
            voter_id    TEXT NOT NULL,
            value       INTEGER NOT NULL CHECK (value IN (-1, 1)),
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (idea_id, voter_id)
        );
        CREATE INDEX IF NOT EXISTS idx_votes_idea ON votes(idea_id);

        CREATE TABLE IF NOT EXISTS applications (
            id                TEXT PRIMARY KEY,
            character         TEXT NOT NULL,
            discord           TEXT NOT NULL,
            experience        TEXT NOT NULL,
            wow_class         TEXT NOT NULL,
            why               TEXT NOT NULL,
            logs              TEXT,
            gearscore         TEXT,
            ack_consumables   INTEGER NOT NULL,
            ack_friend        INTEGER NOT NULL,
            created_at        TEXT NOT NULL,
            delivered_discord TEXT,   -- 'sent' | 'failed' | 'off'
            delivered_email   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_apps_created ON applications(created_at);

        -- Officer votes on an application, cast via the Discord message buttons.
        -- voter_id is the Discord user id, stored ONLY to dedup and let a voter
        -- change/clear their vote — it is never displayed: the message shows
        -- aggregate counts, so voting is anonymous to other officers.
        CREATE TABLE IF NOT EXISTS app_votes (
            app_id      TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
            voter_id    TEXT NOT NULL,
            value       INTEGER NOT NULL CHECK (value IN (-1, 1)),
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (app_id, voter_id)
        );
        CREATE INDEX IF NOT EXISTS idx_app_votes_app ON app_votes(app_id);

        -- Loot log. Populated out-of-band by ingest_gargul.py (a systemd timer
        -- parses Gargul's award history off the gaming rig); this service only
        -- reads it for GET /api/loot. DDL is mirrored in ingest_gargul.py, both
        -- IF NOT EXISTS, so whichever runs first wins.
        CREATE TABLE IF NOT EXISTS loot_awards (
            checksum     TEXT PRIMARY KEY,   -- Gargul's per-award id; dedup/merge key
            winner       TEXT NOT NULL,
            winner_realm TEXT,
            winner_class TEXT,
            item_id      INTEGER,
            item_name    TEXT,
            item_link    TEXT,
            off_spec     INTEGER NOT NULL DEFAULT 0,   -- 1 = off-spec award
            awarded_at   TEXT NOT NULL,                -- ISO UTC
            awarded_by   TEXT,
            received     INTEGER,
            is_bonus     INTEGER,
            source_file  TEXT,
            ingested_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_loot_awarded_at ON loot_awards(awarded_at);
        CREATE INDEX IF NOT EXISTS idx_loot_winner ON loot_awards(winner);

        -- Guild roster. Populated out-of-band by fetch_roster.py (a systemd timer
        -- pulls the Blizzard guild-roster API); this service only reads it, to
        -- separate guildies from PUGs in the loot views. DDL is mirrored in
        -- fetch_roster.py, both IF NOT EXISTS. NOCASE PK => case-insensitive
        -- name match against loot winners.
        CREATE TABLE IF NOT EXISTS guild_roster (
            name        TEXT PRIMARY KEY COLLATE NOCASE,
            realm       TEXT,
            rank        INTEGER,                       -- 0 = guild master
            level       INTEGER,
            class_id    INTEGER,
            present     INTEGER NOT NULL DEFAULT 1,    -- 0 = left the guild
            last_synced TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_roster_present ON guild_roster(present);
        """
    )
    # Lightweight migration: CREATE TABLE IF NOT EXISTS never alters an existing
    # table, so add columns introduced after the table was first created.
    app_cols = {r["name"] for r in conn.execute("PRAGMA table_info(applications)")}
    if "gearscore" not in app_cols:
        conn.execute("ALTER TABLE applications ADD COLUMN gearscore TEXT")
    conn.commit()
    return conn


# --- helpers ----------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _client_ip(request: Request) -> str:
    """Best-effort real client IP for rate limiting and the Turnstile check.

    The app sits behind a CDN and a reverse proxy, so the direct peer is always
    loopback. Cloudflare sets CF-Connecting-IP to the real client (and strips
    any client-supplied copy), so prefer it; fall back to the left-most
    X-Forwarded-For entry, then the peer. A caller that bypasses the proxy can
    spoof these headers, which is fine: this is best-effort, not a security
    boundary.
    """
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


_buckets: dict[tuple[str, str], list[float]] = {}


def _rate_ok(scope: str, ip: str, limit: tuple[int, int]) -> bool:
    """Sliding-window limiter. Returns False when the caller is over budget."""
    max_events, window = limit
    now = time.monotonic()
    key = (scope, ip)
    events = [t for t in _buckets.get(key, ()) if now - t < window]
    if len(events) >= max_events:
        _buckets[key] = events
        return False
    events.append(now)
    _buckets[key] = events
    # opportunistic prune so the dict can't grow without bound
    if len(_buckets) > 4096:
        for k in [k for k, v in _buckets.items() if not any(now - t < window for t in v)]:
            _buckets.pop(k, None)
    return True


def _clean(text: str) -> str:
    """Normalize and de-spoof free text.

    NFC-normalize, collapse every whitespace run (newlines and tabs included)
    to a single space, then drop control (Cc) and format (Cf) characters —
    that kills zero-width spaces/joiners, the bidi overrides used for display
    spoofing, the BOM, and stray control bytes. Letters (including non-ASCII),
    digits, apostrophes, and hyphens are left intact.
    """
    text = unicodedata.normalize("NFC", text)
    text = _WS_RUN.sub(" ", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) not in ("Cc", "Cf"))
    return text.strip()


def _clean_multiline(text: str) -> str:
    """Like _clean but for paragraphs — keeps newlines, kills everything else hostile.

    NFC-normalize, drop every control / format character EXCEPT newline (that
    still removes zero-width spaces/joiners, bidi overrides, the BOM, stray
    control bytes, and CR), collapse inline whitespace runs, trim each line, and
    cap blank-line runs to one so the stored text can't be a screenful of voids.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse inline whitespace (tabs included) to a single space BEFORE dropping
    # control chars — a tab is itself a Cc char, so stripping first would delete it
    # and weld the words on either side together.
    text = _INLINE_WS.sub(" ", text)
    text = "".join(ch for ch in text if ch == "\n" or unicodedata.category(ch) not in ("Cc", "Cf"))
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BLANKLINES.sub("\n\n", text)
    return text.strip()


def _has_content(text: str) -> bool:
    """True if the cleaned text has at least one letter or number (any script)."""
    return any(unicodedata.category(ch)[0] in ("L", "N") for ch in text)


def _letters_and_spaces(text: str) -> bool:
    """True if every character is a Unicode letter or an ASCII space — the WoW
    guild-name charset. Rejects digits, punctuation (incl. apostrophes/hyphens),
    and symbols. Accented letters pass (WoW allows them in some locales)."""
    return all(ch == " " or unicodedata.category(ch).startswith("L") for ch in text)


def _is_http_url(s: str) -> bool:
    """True if s parses as an http(s) URL with a host — for the optional logs link."""
    try:
        u = urllib.parse.urlparse(s)
    except Exception:
        return False
    return u.scheme in ("http", "https") and bool(u.netloc)


_PT = ZoneInfo("America/Los_Angeles")


def _pacific(iso_utc: str) -> str:
    """Render a stored UTC ISO timestamp in Pacific for display (Discord/email)."""
    try:
        dt = datetime.fromisoformat(iso_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_PT).strftime("%b %-d, %Y %-I:%M %p %Z")
    except Exception:
        return iso_utc


def _name_key(name: str) -> str:
    return name.casefold()


def _turnstile_ok(token: Optional[str], ip: str) -> bool:
    """Verify a Turnstile token server-side.

    No secret configured -> skip (the tool works before keys land). Secret set
    -> a missing token or a failed/errored verification is rejected.
    """
    if not TURNSTILE_SECRET:
        return True
    if not token:
        return False
    data = urllib.parse.urlencode(
        {"secret": TURNSTILE_SECRET, "response": token, "remoteip": ip}
    ).encode()
    try:
        req = urllib.request.Request(TURNSTILE_VERIFY_URL, data=data)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return bool(json.load(resp).get("success"))
    except Exception:
        return False  # fail closed when enforcement is on


def _admin_identity(request: Request) -> str:
    """The Authentik-asserted username, or '' when the header is absent."""
    return (request.headers.get(ADMIN_IDENTITY_HEADER) or "").strip()


def _admin_ok(request: Request) -> bool:
    """Authorized iff Authentik forward-auth injected an identity header."""
    return bool(_admin_identity(request))


def _guard_admin(request: Request) -> Optional[JSONResponse]:
    """Rate-limit (to throttle token guessing) then authorize. Error or None."""
    ip = _client_ip(request)
    with _lock:
        if not _rate_ok("admin", ip, ADMIN_LIMIT):
            return _err(429, "Too many attempts. Wait a moment.")
    if not _admin_ok(request):
        return _err(403, "Not authorized.")
    return None


def _err(status: int, message: str, **extra) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


def _row_to_idea(row: sqlite3.Row, your_vote: int) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "why": row["why"],
        "score": row["score"],
        "ups": row["ups"],
        "downs": row["downs"],
        "created_at": row["created_at"],
        "your_vote": your_vote,
    }


_IDEAS_SQL = """
    SELECT i.id, i.name, i.why, i.created_at,
           COALESCE(SUM(v.value), 0)                      AS score,
           COALESCE(SUM(CASE WHEN v.value=1  THEN 1 END), 0) AS ups,
           COALESCE(SUM(CASE WHEN v.value=-1 THEN 1 END), 0) AS downs
      FROM ideas i
      LEFT JOIN votes v ON v.idea_id = i.id
     GROUP BY i.id
     ORDER BY score DESC, i.created_at ASC, i.rowid ASC
"""


def _wilson_lower_bound(ups: int, downs: int, z: float = 1.281551565545) -> float:
    """Lower bound of the Wilson score interval (90% confidence) on the
    up-vote proportion — the standard ballot-ranking estimator (E. Miller,
    "How Not To Sort By Average Rating"). Ranks "probably good" above
    "barely voted": 5 ups / 1 down outranks 1 up / 0 downs, and 10 ups /
    9 downs no longer ties a clean +1. Raw net score keeps displaying;
    only the ordering uses this."""
    n = ups + downs
    if n == 0:
        return 0.0
    p = ups / n
    z2 = z * z
    centre = p + z2 / (2 * n)
    spread = z * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n)
    return (centre - spread) / (1 + z2 / n)


def _list_ideas(voter_id: Optional[str]) -> list[dict]:
    rows = _db.execute(_IDEAS_SQL).fetchall()
    # Wilson-rank the ballot (confidence-adjusted), oldest-first on ties so
    # early pitches don't shuffle. The SQL ORDER BY stays as a stable base.
    rows = sorted(
        rows,
        key=lambda r: (-_wilson_lower_bound(r["ups"], r["downs"]), r["created_at"], r["id"]),
    )
    mine: dict[str, int] = {}
    if voter_id:
        for r in _db.execute(
            "SELECT idea_id, value FROM votes WHERE voter_id = ?", (voter_id,)
        ):
            mine[r["idea_id"]] = r["value"]
    return [_row_to_idea(r, mine.get(r["id"], 0)) for r in rows]


def _one_idea(idea_id: str, voter_id: Optional[str]) -> Optional[dict]:
    row = _db.execute(_IDEAS_SQL.replace("GROUP BY i.id", "WHERE i.id = ? GROUP BY i.id"),
                      (idea_id,)).fetchone()
    if not row:
        return None
    yv = 0
    if voter_id:
        vr = _db.execute(
            "SELECT value FROM votes WHERE idea_id = ? AND voter_id = ?",
            (idea_id, voter_id),
        ).fetchone()
        yv = vr["value"] if vr else 0
    return _row_to_idea(row, yv)


# --- guild-application delivery ---------------------------------------------
# An application is stored first (so it's never lost), then pushed to a Discord
# webhook and emailed via Resend. Both are best-effort and independent: a
# missing secret -> "off" (skipped), a network/HTTP error -> "failed". The
# applicant always gets a success response; the stored row + the admin page are
# the safety net for anything that didn't deliver.

_MD_SPECIAL = set("\\*_~`|>[]()")


def _escape_md(s: str) -> str:
    """Backslash-escape Discord markdown so applicant text can't render as
    bold/italic/code/quotes or a masked [label](link). Mentions are separately
    neutralized by allowed_mentions; this stops the formatting/link vectors."""
    return "".join("\\" + ch if ch in _MD_SPECIAL else ch for ch in s)


def _http_post_json(url: str, payload: dict, headers: Optional[dict] = None) -> int:
    """POST JSON and return the HTTP status (or 0 on transport error). 8s cap."""
    data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "User-Agent": APPLY_UA}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def _application_embed(a: dict) -> dict:
    """The rich embed for one application — shared by the bot and webhook paths."""

    def field(name: str, value: Optional[str], inline: bool = False) -> dict:
        v = _escape_md(value) if value else "—"
        if len(v) > 1024:
            v = v[:1023] + "…"
        return {"name": name, "value": v, "inline": inline}

    fields = [
        field("Character", a["character"], True),
        field("Class", a["wow_class"], True),
        field("Discord", a["discord"], True),
    ]
    if a.get("gearscore"):
        fields.append(field("Gearscore", a["gearscore"], True))
    fields.extend([
        field("Raiding experience", a["experience"]),
        field("Why they want to join", a["why"]),
    ])
    if a.get("logs"):
        fields.append(field("Logs", a["logs"]))
    fields.append(field(
        "Acknowledged",
        "✅ Full consumables, gear gemmed + enchanted\n✅ Will reach out to "
        + APPLY_CONTACT + " on Discord",
    ))
    fields.append(field("Submitted", _pacific(a["created_at"]), True))

    return {
        "title": "New guild application",
        "color": 0xC0A0FF,
        "fields": fields,
    }


def _thread_title(a: dict) -> str:
    """'<character> — <class>' for the per-applicant discussion thread. Both
    fields are already NFC-normalized and length-capped on intake; thread names
    render as plain text (no markdown), so no escaping is needed. Discord caps
    thread names at 100 chars."""
    return f'{a["character"]} — {a["wow_class"]}'[:100]


def _discord_bot(method: str, url: str, payload: Optional[dict] = None):
    """Bot-authed Discord REST call. Returns (status, parsed_json_or_None);
    status 0 on transport error. 8s cap, same as the webhook path."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    hdrs = {
        "User-Agent": APPLY_UA,
        "Authorization": "Bot " + DISCORD_BOT_TOKEN,
    }
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


_app_channel_id: Optional[str] = None


def _applications_channel_id() -> str:
    """The channel the bot posts into. Explicit env wins; otherwise it's read
    once off the webhook (GET on the webhook URL returns its channel_id — the
    webhook token authorizes that, no bot needed) and cached."""
    global _app_channel_id
    if DISCORD_APPLICATIONS_CHANNEL_ID:
        return DISCORD_APPLICATIONS_CHANNEL_ID
    if _app_channel_id is not None:
        return _app_channel_id
    _app_channel_id = ""
    if DISCORD_WEBHOOK_URL:
        req = urllib.request.Request(
            DISCORD_WEBHOOK_URL, headers={"User-Agent": APPLY_UA}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                body = json.loads(resp.read() or b"{}")
                _app_channel_id = str(body.get("channel_id") or "")
        except Exception:
            pass
    return _app_channel_id


def _vote_tally_text(up: int, down: int) -> str:
    return f"✅ {up}  ·  ❌ {down}"


def _set_vote_field(embed: dict, up: int, down: int) -> None:
    """Set (or append) the 'Votes' tally field on an application embed in place."""
    fields = embed.setdefault("fields", [])
    for f in fields:
        if f.get("name") == "Votes":
            f["value"] = _vote_tally_text(up, down)
            f["inline"] = False
            return
    fields.append({"name": "Votes", "value": _vote_tally_text(up, down), "inline": False})


def _vote_components(app_id: str) -> list:
    """The Approve/Reject button row. custom_id carries the application id so the
    interaction webhook knows which row to tally; it's `vote:<up|down>:<id>`."""
    return [{
        "type": 1,  # action row
        "components": [
            {"type": 2, "style": 3, "label": "Approve",  # 3 = green
             "emoji": {"name": "✅"}, "custom_id": f"vote:up:{app_id}"},
            {"type": 2, "style": 4, "label": "Reject",   # 4 = red
             "emoji": {"name": "❌"}, "custom_id": f"vote:down:{app_id}"},
        ],
    }]


def _post_discord_bot(a: dict) -> str:
    """Post the embed with a 0/0 vote tally + Approve/Reject buttons, then open a
    thread named '<character> — <class>' off it for discussion. The message post
    is the gate; the thread is a best-effort follow-up. Officers vote via the
    buttons (anonymous — see the /api/discord/interactions handler), not real
    reactions, so nothing is pre-seeded here."""
    channel_id = _applications_channel_id()
    if not channel_id:
        return "failed"
    embed = _application_embed(a)
    _set_vote_field(embed, 0, 0)
    status, body = _discord_bot(
        "POST", f"{DISCORD_API}/channels/{channel_id}/messages",
        {"embeds": [embed], "components": _vote_components(a["id"]),
         "allowed_mentions": {"parse": []}},
    )
    if not (200 <= status < 300 and body and body.get("id")):
        return "failed"
    msg_id = body["id"]
    tstatus, tbody = _discord_bot(
        "POST",
        f"{DISCORD_API}/channels/{channel_id}/messages/{msg_id}/threads",
        {"name": _thread_title(a), "auto_archive_duration": 4320},
    )
    # Seed one line into the new thread. Discord hides empty threads from the
    # channel's thread list, so without this the per-applicant thread doesn't
    # surface until someone posts; the starter also gives officers a prompt. A
    # thread started from a message has id == that message id, so we post there.
    if 200 <= tstatus < 300:
        thread_id = (tbody or {}).get("id") or msg_id
        # An officer-role @mention adds every member of the role to the thread,
        # so it surfaces in their sidebars (a bot post alone doesn't make them
        # members) and pings them. allowed_mentions scopes the ping to that role.
        if DISCORD_OFFICER_ROLE_ID:
            mention = f"<@&{DISCORD_OFFICER_ROLE_ID}> "
            allowed = {"parse": [], "roles": [DISCORD_OFFICER_ROLE_ID]}
        else:
            mention, allowed = "", {"parse": []}
        _discord_bot(
            "POST",
            f"{DISCORD_API}/channels/{thread_id}/messages",
            {"content": mention + "New application — vote with the **Approve** / "
                        "**Reject** buttons above (anonymous). Discuss the "
                        "applicant here.",
             "allowed_mentions": allowed},
        )
    return "sent"


def _post_discord(a: dict) -> str:
    """Deliver the application to Discord. A bot token (preferred) gets the
    per-applicant thread + officer-vote buttons; otherwise fall back to a plain
    webhook embed. Either path is best-effort and never blocks the form."""
    if DISCORD_BOT_TOKEN:
        return _post_discord_bot(a)
    if not DISCORD_WEBHOOK_URL:
        return "off"
    payload = {
        "username": "hype — applications",
        "embeds": [_application_embed(a)],
        "allowed_mentions": {"parse": []},  # applicant text can never ping
    }
    status = _http_post_json(DISCORD_WEBHOOK_URL, payload)
    return "sent" if 200 <= status < 300 else "failed"


# --- Discord interaction webhook (officer-vote buttons) ---------------------
# Discord POSTs button clicks here. Every request is Ed25519-signed with the
# app's key; we MUST verify and reject bad/unsigned requests with 401 (Discord
# tests exactly this when you register the endpoint URL). A click toggles the
# clicker's vote in app_votes and updates the message's aggregate tally —
# individual votes are never revealed, so officers vote anonymously.

def _verify_discord_sig(raw: bytes, signature: str, timestamp: str) -> bool:
    """True iff `raw` carries a valid Ed25519 signature for the app key. Fails
    closed: no library, no key, or any malformed input ⇒ False."""
    if not (_HAVE_NACL and DISCORD_PUBLIC_KEY and signature and timestamp):
        return False
    try:
        key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
        key.verify(timestamp.encode("utf-8") + raw, bytes.fromhex(signature))
        return True
    except (BadSignatureError, ValueError):
        return False


def _ephemeral(content: str) -> dict:
    """A type-4 interaction response only the clicker sees (flags=64)."""
    return {"type": 4, "data": {"content": content, "flags": 64}}


def _handle_vote_component(payload: dict) -> dict:
    """Record an officer's anonymous Approve/Reject click and return an updated
    message (type 7) so the public tally ticks; clicking your current choice
    again clears it. Errors fall back to an ephemeral note to the clicker."""
    data = payload.get("data") or {}
    parts = (data.get("custom_id") or "").split(":")
    if len(parts) != 3 or parts[0] != "vote":
        return _ephemeral("That button isn't one I know.")
    value = {"up": 1, "down": -1}.get(parts[1])
    app_id = parts[2]
    user = (payload.get("member") or {}).get("user") or payload.get("user") or {}
    voter_id = user.get("id") or ""
    if value is None or not voter_id:
        return _ephemeral("Couldn't record that vote — try again.")

    with _lock:
        if not _db.execute(
                "SELECT 1 FROM applications WHERE id = ?", (app_id,)).fetchone():
            return _ephemeral("That application's no longer on file.")
        current = _db.execute(
            "SELECT value FROM app_votes WHERE app_id = ? AND voter_id = ?",
            (app_id, voter_id)).fetchone()
        if current and current["value"] == value:
            _db.execute(
                "DELETE FROM app_votes WHERE app_id = ? AND voter_id = ?",
                (app_id, voter_id))
        else:
            _db.execute(
                """INSERT INTO app_votes (app_id, voter_id, value, updated_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(app_id, voter_id)
                   DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (app_id, voter_id, value, _now()))
        up = _db.execute(
            "SELECT COUNT(*) AS n FROM app_votes WHERE app_id = ? AND value = 1",
            (app_id,)).fetchone()["n"]
        down = _db.execute(
            "SELECT COUNT(*) AS n FROM app_votes WHERE app_id = ? AND value = -1",
            (app_id,)).fetchone()["n"]
        _db.commit()

    msg = payload.get("message") or {}
    embeds = msg.get("embeds") or []
    embed = embeds[0] if embeds else {
        "title": "New guild application", "color": 0xC0A0FF, "fields": []}
    _set_vote_field(embed, up, down)
    # type 7 = UPDATE_MESSAGE: edit the source message in place (anonymous
    # aggregate counts), no extra REST round-trip, well within the 3s ack window.
    return {"type": 7, "data": {"embeds": [embed], "components": _vote_components(app_id)}}


def _email_text(a: dict) -> str:
    """Plaintext application body — no HTML, so nothing in it can be injected."""
    lines = [
        "New guild application — hype",
        "",
        "Character:  " + a["character"],
        "Class:      " + a["wow_class"],
        "Gearscore:  " + (a["gearscore"] if a.get("gearscore") else "(not provided)"),
        "Discord:    " + a["discord"],
        "Submitted:  " + _pacific(a["created_at"]),
        "",
        "Raiding experience",
        "------------------",
        a["experience"],
        "",
        "Why they want to join",
        "---------------------",
        a["why"],
        "",
        "Logs: " + (a["logs"] if a.get("logs") else "(none provided)"),
        "",
        "Acknowledged",
        "------------",
        "[x] Brings full consumables; gear fully gemmed and enchanted",
        "[x] Will send a friend request / DM " + APPLY_CONTACT + " on Discord",
        "",
        "--",
        "Sent by the hype apply form. Manage entries on the admin review page.",
    ]
    return "\n".join(lines)


def _send_email(a: dict) -> str:
    """Email the application to the configured recipient list via Resend."""
    if not (RESEND_API_KEY and APPLY_MAIL_FROM and APPLY_MAIL_TO):
        return "off"
    to_list = [x.strip() for x in APPLY_MAIL_TO.split(",") if x.strip()]
    if not to_list:
        return "off"
    payload = {
        "from": APPLY_MAIL_FROM,
        "to": to_list,
        "subject": "New guild application — " + a["character"],  # cleaned: single line
        "text": _email_text(a),
    }
    status = _http_post_json(
        RESEND_API_URL, payload, {"Authorization": "Bearer " + RESEND_API_KEY}
    )
    return "sent" if 200 <= status < 300 else "failed"


# --- request models ---------------------------------------------------------
class SubmitBody(BaseModel):
    name: str
    why: Optional[str] = None
    voter_id: str
    token: Optional[str] = None   # Cloudflare Turnstile token


class VoteBody(BaseModel):
    voter_id: str
    value: int  # -1, 0 (clear), or 1


class ApplyBody(BaseModel):
    character: str
    discord: str
    experience: str
    wow_class: str
    why: str
    logs: Optional[str] = None
    gearscore: Optional[str] = None
    ack_consumables: bool = False
    ack_friend: bool = False
    token: Optional[str] = None   # Cloudflare Turnstile token


# --- loot log ---------------------------------------------------------------
# The 2/3 rule (win 2-3 pieces in a run -> you're loot-locked) is per weekly
# lockout, so "this lockout" = awards since the most recent raid reset. US TBC
# realms reset Tuesday ~15:00 UTC; both are env-overridable.
LOOT_RESET_WEEKDAY = int(os.environ.get("LOOT_RESET_WEEKDAY", "1"))  # Mon=0 .. Sun=6
LOOT_RESET_HOUR_UTC = int(os.environ.get("LOOT_RESET_HOUR_UTC", "15"))
LOOT_LOCK_THRESHOLD = 2     # >= this many MS pieces this lockout => loot-locked
LOOT_RECENT_LIMIT = 25      # awards in the recent-drops feed
LOOT_HURTING_LIMIT = 8      # players surfaced in the "needs gear" panel

# Honorary members: regulars who raid with us but aren't on the Blizzard guild
# roster (so fetch_roster.py never sees them). We treat them as guildies in the
# loot views anyway. Matched case-insensitively, same as the synced roster; only
# applied once a real roster has synced (see the loot handler), so the empty-
# roster "show everyone" fallback is preserved.
LOOT_HONORARY_MEMBERS = frozenset({"goshi", "darkside", "ysl"})


def _pacific_date(iso_utc: Optional[str]) -> Optional[str]:
    if not iso_utc:
        return None
    try:
        dt = datetime.fromisoformat(iso_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_PT).strftime("%b %-d, %Y")
    except Exception:
        return None


def _lockout_start() -> datetime:
    """Most recent weekly reset boundary, in UTC."""
    now = datetime.now(timezone.utc)
    anchor = now.replace(hour=LOOT_RESET_HOUR_UTC, minute=0, second=0, microsecond=0)
    # step back to the configured weekday at/<= now
    delta_days = (anchor.weekday() - LOOT_RESET_WEEKDAY) % 7
    start = anchor - timedelta(days=delta_days)
    if start > now:
        start -= timedelta(days=7)
    return start


def _loot_payload() -> dict:
    """Aggregate loot_awards into standings / hurting / recent. Read-only."""
    now = datetime.now(timezone.utc)
    lockout_start = _lockout_start()
    lockout_iso = lockout_start.isoformat()

    rows = _db.execute(
        """
        SELECT winner,
               MAX(winner_class)                                       AS class,
               SUM(CASE WHEN off_spec = 0 THEN 1 ELSE 0 END)           AS ms,
               SUM(CASE WHEN off_spec = 1 THEN 1 ELSE 0 END)           AS os,
               COUNT(*)                                                AS total,
               MAX(CASE WHEN off_spec = 0 THEN awarded_at END)         AS last_ms,
               MAX(awarded_at)                                         AS last_any,
               SUM(CASE WHEN off_spec = 0 AND awarded_at >= ? THEN 1 ELSE 0 END) AS lockout_ms
        FROM loot_awards
        GROUP BY winner
        """,
        (lockout_iso,),
    ).fetchall()

    # Guild roster -> separate guildies from the PUGs we raided with. Keyed by
    # lower-cased name (the table PK is NOCASE, but we also match here for the
    # recent feed). When the roster has never synced (no creds, API down), the
    # set is empty and we fall back to showing everyone, so the page degrades to
    # its pre-filter behaviour instead of looking empty.
    roster = {
        row["name"].lower(): row["rank"]
        for row in _db.execute(
            "SELECT name, rank FROM guild_roster WHERE present = 1"
        ).fetchall()
    }
    roster_active = bool(roster)

    # Fold in honorary regulars once a real roster exists (rank None => no tag).
    # setdefault so a real rank wins if one of them ever joins for real. Guarded
    # by roster_active so an unsynced roster still falls back to showing everyone
    # rather than collapsing to just the honorary three.
    if roster_active:
        for _name in LOOT_HONORARY_MEMBERS:
            roster.setdefault(_name, None)

    def _is_guildie(name: str) -> bool:
        return (not roster_active) or (name.lower() in roster)

    standings = []
    for r in rows:
        last_ms = r["last_ms"]
        days_since_ms = None
        if last_ms:
            try:
                d = datetime.fromisoformat(last_ms)
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                days_since_ms = (now - d).days
            except Exception:
                days_since_ms = None
        standings.append({
            "player": r["winner"],
            "class": r["class"],
            "ms": r["ms"],
            "os": r["os"],
            "total": r["total"],
            "last_ms": _pacific_date(last_ms),
            "days_since_ms": days_since_ms,
            "lockout_ms": r["lockout_ms"],
            "locked": r["lockout_ms"] >= LOOT_LOCK_THRESHOLD,
            "rank": roster.get(r["winner"].lower()),
        })

    # Guild-only views: standings + needs-gear show members only (a PUG who won a
    # piece is not who the council weighs for need). The recent feed below keeps
    # everyone but tags non-members. No-op when the roster hasn't synced yet.
    if roster_active:
        standings = [s for s in standings if s["player"].lower() in roster]

    # leaderboard: most MS gear first (ties -> more total, then name)
    standings.sort(key=lambda s: (-s["ms"], -s["total"], s["player"].lower()))

    # hurting: fewest MS first; among equals, longest drought (never = worst).
    # NULL days_since_ms (no MS ever) sorts as most hurting.
    def _hurt_key(s):
        never = s["days_since_ms"] is None
        return (s["ms"], 0 if never else 1, -(s["days_since_ms"] or 0), s["player"].lower())
    hurting = sorted(standings, key=_hurt_key)[:LOOT_HURTING_LIMIT]

    recent_rows = _db.execute(
        """
        SELECT winner, winner_class, item_id, item_name, off_spec, awarded_at, awarded_by
        FROM loot_awards
        ORDER BY awarded_at DESC
        LIMIT ?
        """,
        (LOOT_RECENT_LIMIT,),
    ).fetchall()
    recent = [{
        "player": r["winner"],
        "class": r["winner_class"],
        "item_id": r["item_id"],
        "item_name": r["item_name"],
        "off_spec": bool(r["off_spec"]),
        "at": _pacific_date(r["awarded_at"]),
        "awarded_by": (r["awarded_by"] or "").split("-")[0] or None,
        "guildie": _is_guildie(r["winner"]),
    } for r in recent_rows]

    agg = _db.execute(
        """
        SELECT MAX(ingested_at) AS updated,
               MAX(awarded_at)  AS last_award
        FROM loot_awards
        """
    ).fetchone()

    # Summary chips reflect the guild view so they match the (filtered) standings
    # table — sum over standings, not over every logged award (which includes the
    # PUG drops still shown, tagged, in the recent feed).
    ms_total = sum(s["ms"] for s in standings)
    os_total = sum(s["os"] for s in standings)

    return {
        "generated_at": _pacific(now.isoformat()),
        "data_updated": _pacific(agg["updated"]) if agg["updated"] else None,
        "last_award": _pacific_date(agg["last_award"]),
        "lockout_start": _pacific_date(lockout_iso),
        "lockout_threshold": LOOT_LOCK_THRESHOLD,
        "roster_synced": roster_active,
        "totals": {
            "awards": ms_total + os_total,
            "ms": ms_total,
            "os": os_total,
            "players": len(standings),
        },
        "standings": standings,
        "hurting": hurting,
        "recent": recent,
    }


# --- routes -----------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/config")
def config() -> dict:
    """Public front-end config. The sitekey is public by design."""
    return {"turnstile_sitekey": TURNSTILE_SITEKEY or None}


@app.get("/api/loot")
def get_loot():
    """Public, read-only loot standings for the /loot/ page.

    Aggregates the Gargul-sourced loot_awards table into a per-player MS/OS
    leaderboard, a "needs gear" view, and a recent-drops feed. No auth: loot is
    public by design ("visible to the raid"). Character names only, no PII.
    """
    with _lock:
        return _loot_payload()


@app.get("/api/ideas")
def get_ideas(voter_id: Optional[str] = None) -> dict:
    vid = voter_id if voter_id and _VOTER_RE.match(voter_id) else None
    with _lock:
        return {"ideas": _list_ideas(vid)}


@app.post("/api/ideas")
def submit_idea(body: SubmitBody, request: Request):
    if not _VOTER_RE.match(body.voter_id):
        return _err(400, "Missing or malformed browser id.")

    name = _clean(body.name or "")
    if len(name) < NAME_MIN or not _has_content(name):
        return _err(422, "Give it a real name — at least a couple of characters.")
    if len(name) > NAME_MAX:
        return _err(422, f"WoW caps guild names at {NAME_MAX} characters.")
    if not _letters_and_spaces(name):
        return _err(422, "Guild names can only use letters and spaces.")

    why = _clean(body.why or "")
    if len(why) > WHY_MAX:
        return _err(422, f"Keep the reason under {WHY_MAX} characters.")
    why = why or None

    ip = _client_ip(request)
    if not _turnstile_ok(body.token, ip):
        return _err(403, "Bot check didn't pass. Refresh the page and try again.")

    with _lock:
        if not _rate_ok("submit", ip, SUBMIT_LIMIT):
            return _err(429, "Slow down a sec — too many submissions just now.")

        total = _db.execute("SELECT COUNT(*) AS n FROM ideas").fetchone()["n"]
        if total >= MAX_IDEAS:
            return _err(409, "The ballot's full for now. Vote on what's there.")

        key = _name_key(name)
        existing = _db.execute(
            "SELECT id FROM ideas WHERE name_key = ?", (key,)
        ).fetchone()
        if existing:
            return _err(409, "Someone already pitched that one — go vote it up.",
                        existing_id=existing["id"])

        idea_id = uuid.uuid4().hex
        _db.execute(
            "INSERT INTO ideas (id, name, name_key, why, created_at) VALUES (?,?,?,?,?)",
            (idea_id, name, key, why, _now()),
        )
        # the submitter implicitly upvotes their own pitch
        _db.execute(
            "INSERT INTO votes (idea_id, voter_id, value, updated_at) VALUES (?,?,?,?)",
            (idea_id, body.voter_id, 1, _now()),
        )
        _db.commit()
        idea = _one_idea(idea_id, body.voter_id)
    return JSONResponse({"idea": idea}, status_code=201)


@app.post("/api/ideas/{idea_id}/vote")
def vote(idea_id: str, body: VoteBody, request: Request):
    if not _VOTER_RE.match(body.voter_id):
        return _err(400, "Missing or malformed browser id.")
    if body.value not in (-1, 0, 1):
        return _err(422, "Vote must be up, down, or cleared.")

    ip = _client_ip(request)
    with _lock:
        if not _rate_ok("vote", ip, VOTE_LIMIT):
            return _err(429, "Easy on the clicks — try again in a moment.")

        if not _db.execute("SELECT 1 FROM ideas WHERE id = ?", (idea_id,)).fetchone():
            return _err(404, "That idea's gone.")

        if body.value == 0:
            _db.execute(
                "DELETE FROM votes WHERE idea_id = ? AND voter_id = ?",
                (idea_id, body.voter_id),
            )
        else:
            _db.execute(
                """INSERT INTO votes (idea_id, voter_id, value, updated_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(idea_id, voter_id)
                   DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (idea_id, body.voter_id, body.value, _now()),
            )
        _db.commit()
        idea = _one_idea(idea_id, body.voter_id)
    return {"idea": idea}


@app.get("/api/admin/whoami")
def admin_whoami(request: Request):
    """Return the signed-in admin's username for the admin page header."""
    err = _guard_admin(request)
    return err or {"username": _admin_identity(request)}


@app.delete("/api/admin/ideas/{idea_id}")
def delete_idea(idea_id: str, request: Request):
    """Admin-only: remove an idea and its votes (e.g. to take down abuse)."""
    err = _guard_admin(request)
    if err:
        return err
    with _lock:
        cur = _db.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))
        _db.commit()
        deleted = cur.rowcount
    if not deleted:
        return _err(404, "That idea's already gone.")
    return {"ok": True, "deleted": idea_id}


# --- guild applications -----------------------------------------------------
TBC_CLASSES = (
    "druid", "hunter", "mage", "paladin", "priest",
    "rogue", "shaman", "warlock", "warrior",
)


@app.post("/api/apply")
def submit_application(body: ApplyBody, request: Request):
    """Public: accept a guild application, store it, fan it out to Discord + email."""
    character = _clean(body.character or "")
    if not character or not _has_content(character):
        return _err(422, "Your character name's required.")
    if len(character) > CHAR_MAX:
        return _err(422, f"Keep the character name under {CHAR_MAX} characters.")

    discord = _clean(body.discord or "")
    if not discord or not _has_content(discord):
        return _err(422, "Your Discord username's required.")
    if len(discord) > DISCORD_MAX:
        return _err(422, f"Keep the Discord username under {DISCORD_MAX} characters.")

    wow_class = _clean(body.wow_class or "")
    if not wow_class or not _has_content(wow_class):
        return _err(422, "Your class is required.")
    if len(wow_class) > CLASS_MAX:
        return _err(422, f"Keep the class under {CLASS_MAX} characters.")
    # The form sends "<spec> <Class>" from a fixed select, so a real class
    # name is always present. This only rejects direct-API garbage, which
    # otherwise lands in the officers' review queue unfilterable by class.
    if not any(c in wow_class.casefold() for c in TBC_CLASSES):
        return _err(422, "Pick one of the nine TBC classes.")

    experience = _clean_multiline(body.experience or "")
    if not _has_content(experience):
        return _err(422, "Tell us a bit about your raiding experience.")
    if len(experience) > EXPERIENCE_MAX:
        return _err(422, f"Keep the experience under {EXPERIENCE_MAX} characters.")

    why = _clean_multiline(body.why or "")
    if not _has_content(why):
        return _err(422, "Tell us why you want to join.")
    if len(why) > WHY_APPLY_MAX:
        return _err(422, f"Keep the reason under {WHY_APPLY_MAX} characters.")

    logs = _clean(body.logs or "")
    if logs:
        if len(logs) > LOGS_MAX:
            return _err(422, f"Keep the logs link under {LOGS_MAX} characters.")
        if not _is_http_url(logs):
            return _err(422, "That logs link needs to start with http:// or https://.")
    logs = logs or None

    gearscore = _clean(body.gearscore or "")
    if not gearscore:
        return _err(422, "Your gearscore is required.")
    if len(gearscore) > GEARSCORE_MAX or not gearscore.isascii() or not gearscore.isdigit():
        return _err(422, "Gearscore should be numbers only.")

    if not body.ack_consumables:
        return _err(422, "Please confirm the consumables and gear requirement.")
    if not body.ack_friend:
        return _err(422, "Please confirm you'll reach out on Discord.")

    ip = _client_ip(request)
    if not _turnstile_ok(body.token, ip):
        return _err(403, "Bot check didn't pass. Refresh the page and try again.")

    app_id = uuid.uuid4().hex
    created = _now()
    with _lock:
        if not _rate_ok("apply", ip, APPLY_LIMIT):
            return _err(429, "Slow down a sec — too many applications just now.")
        total = _db.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"]
        if total >= MAX_APPLICATIONS:
            return _err(409, "We can't take applications right now. Reach out on Discord.")
        _db.execute(
            """INSERT INTO applications
                 (id, character, discord, experience, wow_class, why, logs, gearscore,
                  ack_consumables, ack_friend, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (app_id, character, discord, experience, wow_class, why, logs, gearscore, 1, 1, created),
        )
        _db.commit()

    # Deliver OUTSIDE the lock — these are network calls and must not serialize
    # every other request behind a slow webhook. The row is already safe.
    record = {
        "id": app_id, "character": character, "discord": discord,
        "experience": experience, "wow_class": wow_class, "why": why,
        "logs": logs, "gearscore": gearscore, "created_at": created,
    }
    d_status = _post_discord(record)
    e_status = _send_email(record)
    with _lock:
        _db.execute(
            "UPDATE applications SET delivered_discord = ?, delivered_email = ? WHERE id = ?",
            (d_status, e_status, app_id),
        )
        _db.commit()

    return JSONResponse({"ok": True}, status_code=201)


@app.post("/api/discord/interactions")
async def discord_interactions(request: Request):
    """Public Discord interactions webhook for the officer-vote buttons. Every
    request is Ed25519-verified; PING is answered, button clicks are tallied
    anonymously. Reached via the same-origin /api/* Caddy route → loopback."""
    raw = await request.body()
    if not _verify_discord_sig(
            raw,
            request.headers.get("x-signature-ed25519", ""),
            request.headers.get("x-signature-timestamp", "")):
        return JSONResponse({"error": "invalid request signature"}, status_code=401)
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        return _err(400, "Bad request.")
    itype = payload.get("type")
    if itype == 1:          # PING (URL registration + Discord health checks)
        return {"type": 1}  # PONG
    if itype == 3:          # MESSAGE_COMPONENT (a button click)
        return _handle_vote_component(payload)
    return _err(400, "Unsupported interaction type.")


@app.get("/api/admin/applications")
def list_applications(request: Request):
    """Admin-only: every stored application, newest first, with delivery status."""
    err = _guard_admin(request)
    if err:
        return err
    with _lock:
        rows = _db.execute(
            "SELECT * FROM applications ORDER BY created_at DESC"
        ).fetchall()
    return {"applications": [dict(r) for r in rows]}


@app.delete("/api/admin/applications/{app_id}")
def delete_application(app_id: str, request: Request):
    """Admin-only: remove an application (handled, or spam)."""
    err = _guard_admin(request)
    if err:
        return err
    with _lock:
        cur = _db.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        _db.commit()
        deleted = cur.rowcount
    if not deleted:
        return _err(404, "That application's already gone.")
    return {"ok": True, "deleted": app_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("GUILDNAMES_HOST", "127.0.0.1"),
        port=int(os.environ.get("GUILDNAMES_PORT", "8794")),
        log_level="info",
    )
