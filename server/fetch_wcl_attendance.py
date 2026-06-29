"""Sync raid attendance from Warcraft Logs into the loot-log store.

Pulls our guild's per-report attendance from the Warcraft Logs v2 GraphQL API and
upserts it into the `raid_attendance` table that backs the trial tracker on the
loot log. Each WCL report is one raid night; bucketed by weekly lockout, the
distinct-lockout count is how we tell whether a trial has actually raided their
three lockouts — independent of whether they won any loot.

Why this exists: Gargul's award history only records *winners*, so a trial who
shows for a whole lockout and wins nothing leaves no trace in `loot_awards`. WCL
records every player present in every pull, so it is the authoritative "did they
raid with us" signal. Attendance is presence, not loot.

Design notes (mirrors fetch_roster.py — same OAuth2 client-credentials shape):

  * **Auth.** OAuth2 client-credentials (server-to-server, no user login) against
    WCL's token endpoint. The client id/secret are host-side in hype-vote.env,
    never the repo. Register a client at warcraftlogs.com/api/clients.
  * **Cloudflare.** WCL sits behind Cloudflare like Blizzard; every request
    carries a descriptive User-Agent so a default urllib UA isn't 403'd.
  * **Append-only, never blank.** Attendance is immutable history: we upsert
    rows keyed by (report_code, character) and never delete. A failed or empty
    fetch raises and touches nothing, so a transient API blip can't wipe a
    trial's progress.
  * **Lockout bucketing.** start_time is bucketed to the weekly raid reset
    (Tue ~15:00 UTC by default, env-overridable to match the loot log's
    LOOT_RESET_* constants) so "lockouts raided" counts distinct reset weeks.

  * **Classic partition / subdomain.** WCL splits Classic data by subdomain —
    retail on `www.`, Anniversary/Fresh on `fresh.`, etc. — each with its own
    GraphQL host, OAuth token endpoint, and guild ids. A Fresh guild is invisible
    to the retail host and to a name+realm lookup, so the host is configurable
    (`WCL_API_URL` / `WCL_TOKEN_URL`, both default to `www.`) and the guild can be
    addressed by its stable WCL id (`WCL_GUILD_ID`) instead of name+realm. For our
    guild: `WCL_API_URL=https://fresh.warcraftlogs.com/api/v2/client`,
    `WCL_TOKEN_URL=https://fresh.warcraftlogs.com/oauth/token`, `WCL_GUILD_ID=828086`.

Run standalone:

    # Fresh/Anniversary guild, addressed by WCL id:
    WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... WCL_GUILD_ID=828086 \
        WCL_API_URL=https://fresh.warcraftlogs.com/api/v2/client \
        WCL_TOKEN_URL=https://fresh.warcraftlogs.com/oauth/token \
        GUILDNAMES_DB=./data/guildnames.db python fetch_wcl_attendance.py

    # Retail guild, addressed by name + realm (the www. defaults):
    WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... WCL_GUILD_NAME="Hype" \
        WCL_SERVER_SLUG=nightslayer WCL_SERVER_REGION=us \
        GUILDNAMES_DB=./data/guildnames.db python fetch_wcl_attendance.py
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- configuration ----------------------------------------------------------
# All host-specific; the repo carries no credentials or guild names. On the
# serving host these come from hype-vote.env (mode 600).
CLIENT_ID = os.environ.get("WCL_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("WCL_CLIENT_SECRET", "")
GUILD_NAME = os.environ.get("WCL_GUILD_NAME", "")
SERVER_SLUG = os.environ.get("WCL_SERVER_SLUG", "nightslayer")
SERVER_REGION = os.environ.get("WCL_SERVER_REGION", "us")
# WCL id of the guild (warcraftlogs.com/guild/id/<n>). When set it addresses the
# guild directly — required for Classic/Fresh guilds, which a name+realm lookup on
# the wrong subdomain can't see. Blank => fall back to WCL_GUILD_NAME + realm.
GUILD_ID = os.environ.get("WCL_GUILD_ID", "").strip()
# Each page is one API call; a trial window is three weeks, so a few pages of the
# most recent reports is plenty. Bounded so a misconfig can't page forever.
PER_PAGE = int(os.environ.get("WCL_PER_PAGE", "25"))
MAX_PAGES = int(os.environ.get("WCL_MAX_PAGES", "4"))
DB_PATH = Path(os.environ.get("GUILDNAMES_DB", "./data/guildnames.db")).expanduser()

# Weekly raid-reset boundary, kept in sync with the loot log's defaults so a
# trial's lockout count and the loot 2/3 lock agree on what "this week" means.
RESET_WEEKDAY = int(os.environ.get("LOOT_RESET_WEEKDAY", "1"))   # Mon=0 .. Sun=6
RESET_HOUR_UTC = int(os.environ.get("LOOT_RESET_HOUR_UTC", "15"))

# Both default to the retail (`www.`) host; override per Classic subdomain. The
# token endpoint and the GraphQL host must match — a token minted on `fresh.` is
# only valid against `fresh.`.
TOKEN_URL = os.environ.get("WCL_TOKEN_URL", "https://www.warcraftlogs.com/oauth/token")
API_URL = os.environ.get("WCL_API_URL", "https://www.warcraftlogs.com/api/v2/client")
USER_AGENT = "hype-portal/1.0 (+https://hype.swagcounty.com)"
HTTP_TIMEOUT = 25

# raid_attendance is created identically here and in the backend's _connect() —
# both IF NOT EXISTS, so whichever runs first wins and the other is a no-op.
SCHEMA = """
CREATE TABLE IF NOT EXISTS raid_attendance (
    report_code TEXT NOT NULL,                       -- WCL report code (one raid night)
    character   TEXT NOT NULL COLLATE NOCASE,        -- char name; NOCASE => case-insensitive match
    present     INTEGER NOT NULL DEFAULT 1,          -- 1 = appeared in the report
    presence    INTEGER,                             -- raw WCL presence value (1 full, 2 partial)
    start_time  TEXT NOT NULL,                       -- report start, ISO UTC
    reset_week  TEXT NOT NULL,                       -- weekly-lockout bucket, ISO date (UTC)
    zone        TEXT,
    ingested_at TEXT NOT NULL,
    PRIMARY KEY (report_code, character)
);
CREATE INDEX IF NOT EXISTS idx_attend_char ON raid_attendance(character);
CREATE INDEX IF NOT EXISTS idx_attend_week ON raid_attendance(reset_week);
"""

# The attendance query. guild.attendance returns the per-report player list with
# a presence flag — exactly the "who raided this night" data the trial tracker
# needs. Kept small: code + startTime for bucketing, players{name,presence}.
#
# The guild can be addressed two ways: by WCL id (stable, subdomain-correct) when
# WCL_GUILD_ID is set, else by name + realm. We build the matching query/variables
# so an unused variable never reaches the API (WCL rejects declared-but-unused).
_ATTENDANCE_FIELDS = """
      id
      attendance(limit:$limit, page:$page){
        has_more_pages
        current_page
        data{
          code
          startTime
          zone{ name }
          players{ name type presence }
        }
      }"""

ATTENDANCE_QUERY_BY_ID = (
    "query($id:Int!,$limit:Int!,$page:Int!){\n"
    "  guildData{\n"
    "    guild(id:$id){" + _ATTENDANCE_FIELDS + "\n"
    "    }\n  }\n}"
)

ATTENDANCE_QUERY_BY_NAME = (
    "query($name:String!,$server:String!,$region:String!,$limit:Int!,$page:Int!){\n"
    "  guildData{\n"
    "    guild(name:$name, serverSlug:$server, serverRegion:$region){" + _ATTENDANCE_FIELDS + "\n"
    "    }\n  }\n}"
)


class WclError(RuntimeError):
    pass


def reset_week(dt: datetime) -> str:
    """ISO date (UTC) of the weekly raid-reset boundary at/just before `dt`."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    anchor = dt.replace(hour=RESET_HOUR_UTC, minute=0, second=0, microsecond=0)
    delta_days = (anchor.weekday() - RESET_WEEKDAY) % 7
    start = anchor - timedelta(days=delta_days)
    if start > dt:
        start -= timedelta(days=7)
    return start.date().isoformat()


def _token() -> str:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise WclError("WCL_CLIENT_ID / WCL_CLIENT_SECRET not set")
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    req = urllib.request.Request(
        TOKEN_URL, data=body,
        headers={"User-Agent": USER_AGENT, "Authorization": f"Basic {basic}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            tok = json.loads(resp.read()).get("access_token")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:200]
        raise WclError(f"token HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise WclError(f"token network error: {exc.reason}") from exc
    if not tok:
        raise WclError("token response had no access_token")
    return tok


def _graphql(token: str, query: str, variables: dict) -> dict:
    payload = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API_URL, data=payload,
        headers={
            "User-Agent": USER_AGENT,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            doc = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise WclError(f"API HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise WclError(f"API network error: {exc.reason}") from exc
    if doc.get("errors"):
        # GraphQL errors come back 200 with an errors array.
        msg = "; ".join(e.get("message", "?") for e in doc["errors"])[:300]
        raise WclError(f"GraphQL error: {msg}")
    return doc.get("data") or {}


def _ms_to_iso(start_time) -> str:
    """WCL startTime is epoch milliseconds (Float). -> ISO UTC."""
    secs = float(start_time) / 1000.0
    return datetime.fromtimestamp(secs, tz=timezone.utc).isoformat()


def fetch_attendance() -> list[dict]:
    """Return [{report_code, character, presence, start_time, reset_week, zone}, ...]."""
    # Address the guild by WCL id when given (subdomain-correct, exact), else by
    # name + realm. Id wins because a Classic/Fresh guild can't be name-resolved
    # against the wrong subdomain.
    if GUILD_ID:
        try:
            gid = int(GUILD_ID)
        except ValueError as exc:
            raise WclError(f"WCL_GUILD_ID must be an integer, got {GUILD_ID!r}") from exc
        query = ATTENDANCE_QUERY_BY_ID
        base_vars = {"id": gid}
        who = f"guild id {gid}"
    elif GUILD_NAME:
        query = ATTENDANCE_QUERY_BY_NAME
        base_vars = {"name": GUILD_NAME, "server": SERVER_SLUG, "region": SERVER_REGION}
        who = f"guild '{GUILD_NAME}' on {SERVER_REGION}/{SERVER_SLUG}"
    else:
        raise WclError("set WCL_GUILD_ID (preferred) or WCL_GUILD_NAME")

    token = _token()
    out: list[dict] = []
    page = 1
    while page <= MAX_PAGES:
        data = _graphql(token, query, {**base_vars, "limit": PER_PAGE, "page": page})
        guild = ((data.get("guildData") or {}).get("guild")) or {}
        if not guild:
            raise WclError(
                f"no {who} on {API_URL} — check WCL_GUILD_ID / WCL_GUILD_NAME and "
                "that WCL_API_URL points at the right Classic subdomain (e.g. "
                "fresh.warcraftlogs.com for an Anniversary/Fresh guild)")
        att = guild.get("attendance") or {}
        reports = att.get("data") or []
        for rep in reports:
            code = rep.get("code")
            st = rep.get("startTime")
            if not code or st is None:
                continue
            iso = _ms_to_iso(st)
            week = reset_week(datetime.fromisoformat(iso))
            zone = (rep.get("zone") or {}).get("name")
            for p in rep.get("players") or []:
                name = p.get("name")
                if not name:
                    continue
                out.append({
                    "report_code": code,
                    "character": name,
                    "presence": p.get("presence"),
                    "start_time": iso,
                    "reset_week": week,
                    "zone": zone,
                })
        if not att.get("has_more_pages"):
            break
        page += 1
    return out


def sync() -> dict:
    rows = fetch_attendance()
    if not rows:
        # No reports at all is suspicious (we only get here on a successful
        # fetch). Treat it like a failed fetch and touch nothing, same as the
        # roster sync's empty-guard — never blank a trial's progress on a blip.
        raise WclError("attendance came back empty — refusing to touch the table")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    ingested_at = datetime.now(tz=timezone.utc).isoformat()
    reports = set()
    with conn:
        for r in rows:
            reports.add(r["report_code"])
            conn.execute(
                """
                INSERT INTO raid_attendance
                    (report_code, character, present, presence, start_time, reset_week, zone, ingested_at)
                VALUES (?, ?, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(report_code, character) DO UPDATE SET
                    present=1, presence=excluded.presence, start_time=excluded.start_time,
                    reset_week=excluded.reset_week, zone=excluded.zone, ingested_at=excluded.ingested_at
                """,
                (r["report_code"], r["character"], r["presence"],
                 r["start_time"], r["reset_week"], r["zone"], ingested_at),
            )
    total = conn.execute("SELECT COUNT(*) FROM raid_attendance").fetchone()[0]
    conn.close()
    return {"reports": len(reports), "rows": len(rows), "total_rows": total}


if __name__ == "__main__":
    try:
        s = sync()
    except WclError as exc:
        print(f"wcl: FAILED — {exc}", file=sys.stderr)
        sys.exit(1)
    print(
        f"wcl: synced {s['reports']} report(s), {s['rows']} attendance row(s) "
        f"({s['total_rows']} total) -> {DB_PATH}"
    )
