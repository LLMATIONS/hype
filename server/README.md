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
`~/hype-vote/hype-vote.env` (mode 600) and restarts the unit.

## Application delivery (Discord + email)

A submitted application is stored first (so it's never lost), then fanned out to
Discord and email. Both are best-effort and independent — an unset secret means
that channel is skipped, a transport error is recorded as `failed` on the stored
row, and the applicant always gets a success response. Configure with:

```sh
bash server/configure-apply.sh   # prompts (hidden) for each secret, restarts
```

Discord has two modes:

- **Webhook only** (`DISCORD_WEBHOOK_URL`) — posts the application as a rich
  embed. It cannot create a named thread or attach vote buttons, so thread titles
  and officer voting depend on whatever else is watching the channel.
- **Bot token** (`DISCORD_BOT_TOKEN`, preferred) — supersedes the webhook for
  posting, opens a thread titled **`<character> — <class>`** off each
  application, and attaches **Approve / Reject** buttons for anonymous officer
  voting (see below). Keep `DISCORD_WEBHOOK_URL` set alongside it: the target
  channel is read off the webhook automatically (override with
  `DISCORD_APPLICATIONS_CHANNEL_ID`).

Bot setup (Discord Developer Portal → New Application → Bot → copy token):
invite it to the server and grant it, in the applications channel, **View
Channel · Send Messages · Create Public Threads · Send Messages in Threads**.
No gateway connection or privileged intents are needed — it's pure outbound REST.

> If a separate bot is already auto-creating threads in that channel, turn its
> auto-threading **off** for the applications channel — otherwise every
> submission gets two threads.

### Anonymous officer voting (buttons)

When the bot posts an application it adds **Approve / Reject** buttons and a
`Votes: ✅ 0 · ❌ 0` tally line. A click is recorded in `app_votes` keyed by the
clicker's Discord id — stored only to dedupe and let someone change or clear
their vote (click your current choice again to clear). The id is **never shown**:
the message displays aggregate counts only, so officers vote anonymously. Anyone
who can see the channel can vote; `#guild-applicants` being officer-only is the
gate.

Set `DISCORD_OFFICER_ROLE_ID` (optional) to have the per-applicant thread's
starter message @mention that role. Discord adds every member of a sub-100-member
role to the thread when it's mentioned, so the thread surfaces in each officer's
sidebar (a bot post alone doesn't make them members) and pings them that a new
application landed. Unset ⇒ no mention; the thread is still reachable via the
message's **See Thread** link and the channel's threads browser.

Clicks arrive as Discord *interaction webhooks* at `POST /api/discord/interactions`
(reached through the same-origin `/api/*` Caddy route). Every request is
Ed25519-verified against the app's public key; unsigned/forged requests get a
`401`. Two one-time setup steps in the Developer Portal:

1. **Public key** — copy it from *General Information* and set `DISCORD_PUBLIC_KEY`
   (via `configure-apply.sh`; it's not a secret). Voting fails closed until it's set.
2. **Interactions Endpoint URL** — paste `https://<public-host>/api/discord/interactions`
   into the field on *General Information* and save. Discord sends a signed PING
   to validate it; it only saves if verification is working, so a successful save
   is itself the smoke test. (Requires `PyNaCl`, already in `requirements.txt`.)

## Admin moderation (owner-only)

The admin endpoints — `GET /api/admin/whoami`, `DELETE /api/admin/ideas/{id}`,
`GET /api/admin/applications`, `DELETE /api/admin/applications/{id}` — are
authorized by the `X-Authentik-Username` header. There is **no app-managed admin
secret**.

The gate lives one layer out: the admin UI is served on its own subdomain
(`hype-admin.swagcounty.com`) behind Authentik forward-auth. That subdomain
is deliberately internal-only (not a public hostname), so the moderation
surface never touches the public internet. The reverse proxy
verifies the SSO session and injects `X-Authentik-Username` — overwriting any
client-supplied copy — before forwarding to this service; an unauthenticated
request never reaches an admin endpoint, and the request reaching the app
carries a trustworthy identity. The public origin never proxies `/api/admin/*`
and never sets that header, so the same endpoints are unreachable from it
(belt-and-suspenders: the app also returns 403 without the header).

To moderate, open `https://hype-admin.swagcounty.com/` from the internal
network and sign in with your usual SSO. No token to set, save, or rotate.

## Runtime layout

Code lives in the repo; the service runs from `~/hype-vote/` outside any git
checkout, so its writable DB never lands inside a pull-only serving tree:

```
~/hype-vote/
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
