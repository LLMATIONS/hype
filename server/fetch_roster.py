"""Sync the WoW guild roster into the loot-log store.

Fetches our guild's member list from the Blizzard Profile API and upserts it
into the `guild_roster` table that backs the guild-only filter on the loot log
(`GET /api/loot`). With this table populated, the standings / "needs gear" views
show only guild members instead of every PUG we happened to raid with; the
recent-drops feed keeps showing everyone but tags non-members.

Why this exists: Gargul's award history carries no guild flag — a PUG who wins a
piece lands in `loot_awards` exactly like a guildie. The roster is the only
signal that separates the two, and Blizzard is the authoritative source for it.

Design notes:

  * **Auth.** OAuth2 client-credentials (server-to-server, no user login). The
    client id/secret are host-side in hype-vote.env, never the repo.
  * **Cloudflare.** Blizzard's OAuth + API sit behind Cloudflare, which 403s a
    default `Python-urllib/x.y` User-Agent. Every request carries a descriptive
    UA. (Same gotcha that bit the Discord webhook path.)
  * **Anniversary namespace.** TBC Anniversary realms use `profile-classicann-us`
    (the `classic1x`/`classic` namespaces 404 for these realms). Override via
    BLIZZARD_NAMESPACE if Blizzard migrates it again.
  * **Upsert + soft-delete, never hard-delete.** A successful sync marks fetched
    members present=1 and everyone else present=0 (they left the guild). A failed
    or empty fetch touches nothing, so a transient API blip can't blank the
    roster and make the whole guild look like PUGs. The web path only ever reads
    `WHERE present=1`.

Run standalone:

    BLIZZARD_CLIENT_ID=... BLIZZARD_CLIENT_SECRET=... \
        BLIZZARD_REALM_SLUG=nightslayer BLIZZARD_GUILD_SLUG=hype \
        GUILDNAMES_DB=./data/guildnames.db python fetch_roster.py
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
from datetime import datetime, timezone
from pathlib import Path

# --- configuration ----------------------------------------------------------
# All host-specific; the repo carries no credentials or realm names. On the
# serving host these come from hype-vote.env (mode 600).
CLIENT_ID = os.environ.get("BLIZZARD_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("BLIZZARD_CLIENT_SECRET", "")
REGION = os.environ.get("BLIZZARD_REGION", "us")
REALM_SLUG = os.environ.get("BLIZZARD_REALM_SLUG", "nightslayer")
GUILD_SLUG = os.environ.get("BLIZZARD_GUILD_SLUG", "hype")
NAMESPACE = os.environ.get("BLIZZARD_NAMESPACE", "profile-classicann-us")
LOCALE = os.environ.get("BLIZZARD_LOCALE", "en_US")
DB_PATH = Path(os.environ.get("GUILDNAMES_DB", "./data/guildnames.db")).expanduser()

# Descriptive UA so Cloudflare doesn't 403 us at the edge (see module docstring).
USER_AGENT = "hype-portal/1.0 (+https://hype.swagcounty.com)"
HTTP_TIMEOUT = 20

# guild_roster is created identically here and in the backend's _connect() —
# both IF NOT EXISTS, so whichever runs first wins and the other is a no-op.
SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_roster (
    name        TEXT PRIMARY KEY COLLATE NOCASE,   -- char name; NOCASE => match is case-insensitive
    realm       TEXT,
    rank        INTEGER,                            -- 0 = guild master
    level       INTEGER,
    class_id    INTEGER,
    present     INTEGER NOT NULL DEFAULT 1,         -- 0 = left the guild (kept for history, filtered out)
    last_synced TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_roster_present ON guild_roster(present);
"""


class RosterError(RuntimeError):
    pass


def _get(url: str, headers: dict) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise RosterError(f"HTTP {exc.code} for {url.split('?')[0]}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RosterError(f"network error for {url.split('?')[0]}: {exc.reason}") from exc


def _token() -> str:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RosterError("BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET not set")
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    req = urllib.request.Request(
        "https://oauth.battle.net/token",
        data=body,
        headers={"User-Agent": USER_AGENT, "Authorization": f"Basic {basic}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            tok = json.loads(resp.read()).get("access_token")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:200]
        raise RosterError(f"token HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RosterError(f"token network error: {exc.reason}") from exc
    if not tok:
        raise RosterError("token response had no access_token")
    return tok


def fetch_members() -> list[dict]:
    """Return [{name, realm, rank, level, class_id}, ...] from the live roster."""
    token = _token()
    qs = urllib.parse.urlencode({"namespace": NAMESPACE, "locale": LOCALE})
    url = (
        f"https://{REGION}.api.blizzard.com/data/wow/guild/"
        f"{REALM_SLUG}/{GUILD_SLUG}/roster?{qs}"
    )
    data = json.loads(_get(url, {"Authorization": f"Bearer {token}"}))
    members = []
    for m in data.get("members", []):
        c = m.get("character") or {}
        name = c.get("name")
        if not name:
            continue
        realm = (c.get("realm") or {}).get("slug")
        members.append({
            "name": name,
            "realm": realm,
            "rank": m.get("rank"),
            "level": c.get("level"),
            "class_id": (c.get("playable_class") or {}).get("id"),
        })
    return members


def sync() -> dict:
    members = fetch_members()
    if not members:
        # Treat an empty roster as a failed fetch: never blank the table on it.
        raise RosterError("roster came back empty — refusing to wipe present flags")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    synced_at = datetime.now(tz=timezone.utc).isoformat()
    with conn:
        for m in members:
            conn.execute(
                """
                INSERT INTO guild_roster (name, realm, rank, level, class_id, present, last_synced)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(name) DO UPDATE SET
                    realm=excluded.realm, rank=excluded.rank, level=excluded.level,
                    class_id=excluded.class_id, present=1, last_synced=excluded.last_synced
                """,
                (m["name"], m["realm"], m["rank"], m["level"], m["class_id"], synced_at),
            )
        # Anyone not in this fetch has left the guild: soft-delete (keep the row
        # for history, but the web path filters present=1). Safe because we only
        # reach here on a non-empty fetch.
        left = conn.execute(
            "UPDATE guild_roster SET present=0 WHERE last_synced != ?", (synced_at,)
        ).rowcount
    present = conn.execute("SELECT COUNT(*) FROM guild_roster WHERE present=1").fetchone()[0]
    conn.close()
    return {"fetched": len(members), "present": present, "departed": left}


if __name__ == "__main__":
    try:
        s = sync()
    except RosterError as exc:
        print(f"roster: FAILED — {exc}", file=sys.stderr)
        sys.exit(1)
    print(
        f"roster: synced {s['fetched']} member(s) "
        f"({s['present']} present, {s['departed']} now departed) -> {DB_PATH}"
    )
