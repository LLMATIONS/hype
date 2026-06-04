# Guild-name voting backend

The service behind `/guild-names/`. FastAPI + SQLite, loopback-only, fronted by
the same web server that serves the static site so the browser talks to it
same-origin at `/api/*`.

## What it does

- `GET  /api/health` — liveness check.
- `GET  /api/ideas?voter_id=<id>` — all ideas, highest score first, each tagged
  with the caller's current vote.
- `POST /api/ideas` — submit `{name, why?, voter_id}`. Trims and length-caps the
  name (2–60) and reason (≤140), rejects blanks and case-insensitive duplicates,
  and counts the submitter as the first upvote.
- `POST /api/ideas/{id}/vote` — `{voter_id, value}` with `value` of `1` / `-1` /
  `0` (clear). Upserts, so one effective vote per browser per idea.

## Anti-ballot-stuffing (best-effort, not airtight)

There's no login, so two cheap defenses stack:

1. **Per-browser id** — the page generates an anonymous UUID and keeps it in
   `localStorage`; it's the vote key. Clearing storage gets you a new identity,
   so this stops casual double-voting, not a determined one.
2. **Per-IP rate limit** — a sliding window on writes (submits and votes),
   keyed on the real client IP (`CF-Connecting-IP`, else `X-Forwarded-For`).
   The IP is used only for the limiter and is never written to the database.

## Runtime layout

Code lives in the repo; the service runs from `~/getajob-vote/` outside any git
checkout, so its writable DB never lands inside a pull-only serving tree:

```
~/getajob-vote/
  venv/                 # the virtualenv
  app.py                # deployed copy of server/app.py
  data/guildnames.db    # SQLite, created at runtime — gitignored, never committed
```

Config is environment-driven (`GUILDNAMES_DB`, `GUILDNAMES_PORT`), so the code
carries no host paths.

## Setup

```sh
sudo -E bash server/install.sh   # systemd unit + scoped sudoers (one time)
bash server/deploy.sh            # venv + deps + copy code + restart
```

`install.sh` writes a hardened, loopback-only unit (`NoNewPrivileges`,
`ProtectSystem=strict`, `Restart=on-failure`) and a sudoers entry scoped to the
single `systemctl restart` verb, validated with `visudo -cf` before install. It
reads the user and home from the environment, so nothing host-specific is
hard-coded here. `deploy.sh` is re-run on every update — it refreshes the code
and restarts the unit.

## Local preview

```sh
cd server
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
GUILDNAMES_DB=./data/guildnames.db .venv/bin/python app.py   # 127.0.0.1:8794
```
