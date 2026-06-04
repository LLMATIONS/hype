# Guild-name voting backend

The service behind `/guild-names/`. FastAPI + SQLite, loopback-only, fronted by
the same web server that serves the static site so the browser talks to it
same-origin at `/api/*`.

## What it does

- `GET  /api/health` — liveness check.
- `GET  /api/config` — public front-end config (the Turnstile sitekey, or null).
- `GET  /api/ideas?voter_id=<id>` — all ideas, highest score first, each tagged
  with the caller's current vote.
- `POST /api/ideas` — submit `{name, why?, voter_id, token?}`. Trims and
  length-caps the name (2–40) and reason (≤200), strips control / zero-width /
  bidi-override characters and NFC-normalizes, rejects blanks and
  case-insensitive duplicates, and counts the submitter as the first upvote.
- `POST /api/ideas/{id}/vote` — `{voter_id, value}` with `value` of `1` / `-1` /
  `0` (clear). Validates the idea exists and the value is in-set; upserts, so
  one effective vote per browser per idea.

All writes require `Content-Type: application/json` and a body under 4 KB. SQL
uses bound parameters throughout. Names are stored faithfully (after
normalization) and escaped at render time by the browser (`textContent`) — the
output encoding is the XSS defense, not input scrubbing.

## Anti-ballot-stuffing (best-effort, not airtight)

There's no login, so the defenses stack rather than rely on any one:

1. **Cloudflare Turnstile** — gates submissions. The page renders the widget
   (only if a sitekey is configured) and sends the token; the server verifies it
   via `siteverify` before storing. Votes are not gated (a challenge per upvote
   is annoying); the rate limit and browser id cover those.
2. **Per-browser id** — the page generates an anonymous UUID and keeps it in
   `localStorage`; it's the vote key. Clearing storage gets you a new identity,
   so this stops casual double-voting, not a determined one.
3. **Per-IP rate limit** — a sliding window on writes (submits and votes),
   keyed on the real client IP (`CF-Connecting-IP`, else `X-Forwarded-For`).
   The IP is used only for the limiter (and the Turnstile check) and is never
   written to the database.

An edge rate-limit (e.g. a Cloudflare WAF rule on `POST /api/*`) could sit on
top of these, but it's optional — the in-app per-IP limit plus Turnstile are the
baseline.

## Turnstile setup

Turnstile is optional and config-driven: with no secret set the tool works and
submissions aren't gated; once configured, a missing or invalid token is
rejected (and a verify error fails closed). Keys live only in the mode-600
service env file, never in the repo.

```sh
bash server/configure-turnstile.sh   # prompts for sitekey (echoed) + secret (hidden), restarts
```

Create the widget in the Cloudflare dashboard (Turnstile → add a widget for the
site's hostname). The script writes `TURNSTILE_SITEKEY` + `TURNSTILE_SECRET` to
`~/getajob-vote/getajob-vote.env` (mode 600) and restarts the unit.

## Admin moderation (owner-only delete)

`DELETE /api/ideas/{id}` removes a name and its votes — for taking down abuse.
It is gated by a bearer token (`X-Admin-Token`), compared in constant time and
rate-limited; with no token set the endpoint always 403s, so admin is off until
configured. The token lives only in the mode-600 env file.

```sh
bash server/configure-admin.sh   # generates a token, prints it once, restarts
```

Save the printed token (it is shown once). To moderate, open `/guild-names/?admin`
and paste it — the page checks it against `GET /api/admin/ping`, stores it in
`localStorage`, and shows a delete control on each entry. "Exit admin" clears it.
Anyone holding the token can delete, so treat it like a password; rotate by
re-running the script.

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
