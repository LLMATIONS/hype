"""Guild-name voting backend for Get a Job.

A tiny FastAPI + SQLite service that backs the /guild-names/ page. It runs on
loopback only (127.0.0.1) behind a reverse proxy that forwards same-origin
/api/* to it. There is no login, so anti-ballot-stuffing is best-effort:

  * one effective vote per idea per browser, keyed by an anonymous UUID the
    browser generates and stores in localStorage (sent as `voter_id`);
  * a per-IP sliding-window rate limit on writes, so a single source can't
    spray submissions or flip votes in a loop.

Neither is airtight (a determined person can clear localStorage or rotate IPs),
and the privacy page says so plainly. The IP is read from the request only to
feed the rate limiter and is never written to the database.

Run for local preview:

    GUILDNAMES_DB=./data/guildnames.db python app.py    # serves 127.0.0.1:8794

In production it is launched by the getajob-vote systemd unit via uvicorn.
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# --- configuration ----------------------------------------------------------
# DB path is host-side and gitignored; default keeps preview self-contained.
DB_PATH = Path(os.environ.get("GUILDNAMES_DB", "./data/guildnames.db")).expanduser()

NAME_MAX = 60          # guild names are short; WoW caps at 24, we're generous
NAME_MIN = 2
WHY_MAX = 140          # one-liner, tweet-ish
VOTER_ID_MAX = 64      # a UUID is 36; allow slack but cap to stop abuse
MAX_IDEAS = 500        # global ceiling so the table can't be flooded

# per-IP sliding-window limits: (max events, window seconds)
SUBMIT_LIMIT = (6, 600)    # 6 new ideas per 10 minutes
VOTE_LIMIT = (90, 60)      # 90 vote actions per minute (covers fast toggling)

_CONTROL_CHARS = dict.fromkeys(range(0x20)) | {0x7F: None}
_WS_RUN = re.compile(r"\s+")
_VOTER_RE = re.compile(r"^[A-Za-z0-9._:-]{8,%d}$" % VOTER_ID_MAX)
_HAS_ALNUM = re.compile(r"[0-9A-Za-z]")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _db
    _db = _connect()
    try:
        yield
    finally:
        _db.close()


app = FastAPI(
    title="Get a Job — guild-name vote",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


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
        """
    )
    conn.commit()
    return conn


# --- helpers ----------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _client_ip(request: Request) -> str:
    """Best-effort real client IP for rate limiting.

    The app sits behind a CDN and a reverse proxy, so the direct peer is always
    loopback. Cloudflare sets CF-Connecting-IP to the real client (and strips
    any client-supplied copy), so prefer it; fall back to the left-most
    X-Forwarded-For entry, then the peer. A caller that bypasses the proxy can
    spoof these headers, which is fine: this is best-effort rate limiting, not a
    security boundary.
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
    """Strip control chars, collapse whitespace runs, trim."""
    return _WS_RUN.sub(" ", text.translate(_CONTROL_CHARS)).strip()


def _name_key(name: str) -> str:
    return name.casefold()


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


def _list_ideas(voter_id: Optional[str]) -> list[dict]:
    rows = _db.execute(_IDEAS_SQL).fetchall()
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


# --- request models ---------------------------------------------------------
class SubmitBody(BaseModel):
    name: str
    why: Optional[str] = None
    voter_id: str


class VoteBody(BaseModel):
    voter_id: str
    value: int  # -1, 0 (clear), or 1


# --- routes -----------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


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
    if len(name) < NAME_MIN or not _HAS_ALNUM.search(name):
        return _err(422, "Give it a real name — at least a couple of characters.")
    if len(name) > NAME_MAX:
        return _err(422, f"Keep it under {NAME_MAX} characters.")

    why = _clean(body.why or "")
    if len(why) > WHY_MAX:
        return _err(422, f"Keep the reason under {WHY_MAX} characters.")
    why = why or None

    ip = _client_ip(request)
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("GUILDNAMES_HOST", "127.0.0.1"),
        port=int(os.environ.get("GUILDNAMES_PORT", "8794")),
        log_level="info",
    )
