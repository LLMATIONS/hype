"""Ingest Gargul award history into the loot-log store.

Reads one or more Gargul SavedVariables files (`Gargul.lua`), parses the
`GargulDB.AwardHistory` table, and upserts each award into the `loot_awards`
table that backs `GET /api/loot` on the hype portal.

Design notes:

  * **Source.** `GARGUL_LUA_PATH` may be a single `Gargul.lua` file OR a
    directory; a directory ingests every `*.lua` inside it. When more than one
    person master-loots, each produces their own award history — drop every
    export into the directory and they merge.
  * **Dedup / merge.** Every Gargul award carries a unique `checksum`. That is
    the primary key, so re-ingesting the same file, or ingesting overlapping
    histories from two looters, is idempotent — no double counting.
  * **Upsert only, never delete.** A source file that is briefly truncated or
    missing must not wipe history we already have from another looter, so this
    only inserts/updates; it never deletes rows that vanished from a source.
  * **Disenchants excluded.** Items sharded for dust are awarded to Gargul's
    disenchanter sentinel (`||de||`, plus the configurable identifier under
    `Settings.ExportingLoot.disenchanterIdentifier`). Those are not gear and
    are skipped.

  The web request path never touches the source file: this runs on a timer
  (hype-gargul-ingest.timer), and the backend serves aggregates from SQLite —
  so a network-mounted source is fine (it is never in the request path).

Run standalone:

    GARGUL_LUA_PATH=/path/to/gargul GUILDNAMES_DB=./data/guildnames.db \
        python ingest_gargul.py
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from slpp import slpp as lua

# --- configuration ----------------------------------------------------------
# GARGUL_LUA_PATH (a Gargul.lua file or a directory of them) and GUILDNAMES_DB
# are host-side; the defaults are generic so the repo carries no host paths. On
# the serving host the real source path is set in hype-vote.env.
SRC_PATH = Path(os.environ.get("GARGUL_LUA_PATH", "./gargul")).expanduser()
DB_PATH = Path(os.environ.get("GUILDNAMES_DB", "./data/guildnames.db")).expanduser()

# Gargul's built-in disenchanter sentinel (the value stored in awardedTo when an
# item is sharded). The configurable identifier is read per-file from Settings
# and added to this set.
DE_SENTINELS = {"||de||", "_disenchanted"}

# WoW class id -> name (TBC set; full map is harmless). Used for class colours
# on the page. The colour hexes live on the front-end (presentation).
CLASS_BY_ID = {
    1: "warrior", 2: "paladin", 3: "hunter", 4: "rogue", 5: "priest",
    6: "deathknight", 7: "shaman", 8: "mage", 9: "warlock", 10: "monk",
    11: "druid", 12: "demonhunter", 13: "evoker",
}

_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*=\s*")
_ITEM_NAME_RE = re.compile(r"\[(.+?)\]")
_ITEM_ID_RE = re.compile(r"Hitem:(\d+)")

# loot_awards is created identically here and in the backend's _connect() — both
# use IF NOT EXISTS so whichever runs first wins and the other is a no-op.
SCHEMA = """
CREATE TABLE IF NOT EXISTS loot_awards (
    checksum     TEXT PRIMARY KEY,
    winner       TEXT NOT NULL,
    winner_realm TEXT,
    winner_class TEXT,
    item_id      INTEGER,
    item_name    TEXT,
    item_link    TEXT,
    off_spec     INTEGER NOT NULL DEFAULT 0,
    awarded_at   TEXT NOT NULL,
    awarded_by   TEXT,
    received     INTEGER,
    is_bonus     INTEGER,
    source_file  TEXT,
    ingested_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_loot_awarded_at ON loot_awards(awarded_at);
CREATE INDEX IF NOT EXISTS idx_loot_winner ON loot_awards(winner);
"""


def _iso_utc(unix_ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _split_realm(name: str) -> tuple[str, str | None]:
    """'Gdnn-Nightslayer' -> ('Gdnn', 'Nightslayer'); 'Varzi' -> ('Varzi', None)."""
    if "-" in name:
        char, realm = name.rsplit("-", 1)
        return char, realm
    return name, None


def _item_name(link: str | None) -> str | None:
    if not link:
        return None
    m = _ITEM_NAME_RE.search(link)
    return m.group(1) if m else None


def _item_id(award: dict) -> int | None:
    iid = award.get("itemID")
    if isinstance(iid, (int, float)):
        return int(iid)
    m = _ITEM_ID_RE.search(award.get("itemLink") or "")
    return int(m.group(1)) if m else None


def parse_file(path: Path) -> tuple[list[dict], set[str]]:
    """Parse one Gargul.lua. Returns (awards, extra_de_sentinels)."""
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    body = _ASSIGN_RE.sub("", raw, count=1)
    try:
        data = lua.decode(body)
    except Exception as exc:  # slpp raises bare exceptions; surface the file
        raise ValueError(f"could not parse Lua in {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: top-level is not a table")

    # honour a per-file custom disenchanter identifier
    extra: set[str] = set()
    de_id = (
        data.get("Settings", {})
        .get("ExportingLoot", {})
        .get("disenchanterIdentifier")
    )
    if isinstance(de_id, str) and de_id.strip():
        extra.add(de_id.strip())

    history = data.get("AwardHistory") or {}
    entries = history.values() if isinstance(history, dict) else history
    awards = [a for a in entries if isinstance(a, dict)]
    return awards, extra


def normalize(award: dict, source: str) -> dict | None:
    """Map a raw Gargul award to a loot_awards row, or None to skip."""
    awarded_to = (award.get("awardedTo") or "").strip()
    if not awarded_to:
        return None
    checksum = str(award.get("checksum") or "").strip()
    if not checksum:
        return None
    ts = _iso_utc(award.get("timestamp"))
    if not ts:
        return None

    winner, realm = _split_realm(awarded_to)
    cls = CLASS_BY_ID.get(award.get("winnerClass"))
    return {
        "checksum": checksum,
        "winner": winner,
        "winner_realm": realm,
        "winner_class": cls,
        "item_id": _item_id(award),
        "item_name": _item_name(award.get("itemLink")),
        "item_link": award.get("itemLink"),
        "off_spec": 1 if award.get("OS") else 0,
        "awarded_at": ts,
        "awarded_by": award.get("awardedBy"),
        "received": 1 if award.get("received") else 0,
        "is_bonus": 1 if award.get("isBonusLoot") else 0,
        "source_file": source,
        "_awarded_to_raw": awarded_to,
    }


def ingest() -> dict:
    if SRC_PATH.is_dir():
        files = sorted(SRC_PATH.glob("*.lua"))
    elif SRC_PATH.is_file():
        files = [SRC_PATH]
    else:
        raise SystemExit(f"ingest: GARGUL_LUA_PATH not found: {SRC_PATH}")
    if not files:
        raise SystemExit(f"ingest: no *.lua under {SRC_PATH}")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    seen: dict[str, dict] = {}
    de_skipped = 0
    parsed_files = 0
    for path in files:
        try:
            awards, extra_de = parse_file(path)
        except ValueError as exc:
            print(f"ingest: WARN skipping {path.name}: {exc}", file=sys.stderr)
            continue
        parsed_files += 1
        de_set = DE_SENTINELS | extra_de
        for raw in awards:
            row = normalize(raw, path.name)
            if row is None:
                continue
            if row.pop("_awarded_to_raw") in de_set:
                de_skipped += 1
                continue
            # last writer wins within a run; checksum-dedup across files
            seen[row["checksum"]] = row

    now = datetime.now(tz=timezone.utc).isoformat()
    cols = ["checksum", "winner", "winner_realm", "winner_class", "item_id",
            "item_name", "item_link", "off_spec", "awarded_at", "awarded_by",
            "received", "is_bonus", "source_file"]
    placeholders = ", ".join("?" for _ in cols) + ", ?"  # + ingested_at
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "checksum")
    sql = (
        f"INSERT INTO loot_awards ({', '.join(cols)}, ingested_at) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(checksum) DO UPDATE SET {updates}, ingested_at=excluded.ingested_at"
    )
    with conn:
        for row in seen.values():
            conn.execute(sql, [row[c] for c in cols] + [now])

    total = conn.execute("SELECT COUNT(*) FROM loot_awards").fetchone()[0]
    ms = conn.execute("SELECT COUNT(*) FROM loot_awards WHERE off_spec=0").fetchone()[0]
    os_ = conn.execute("SELECT COUNT(*) FROM loot_awards WHERE off_spec=1").fetchone()[0]
    conn.close()

    summary = {
        "files": parsed_files,
        "awards_in_source": len(seen),
        "de_skipped": de_skipped,
        "db_total": total,
        "db_ms": ms,
        "db_os": os_,
    }
    return summary


if __name__ == "__main__":
    s = ingest()
    print(
        f"ingest: {s['files']} file(s), {s['awards_in_source']} gear award(s) "
        f"({s['de_skipped']} disenchant skipped) -> db now {s['db_total']} "
        f"({s['db_ms']} MS / {s['db_os']} OS)"
    )
