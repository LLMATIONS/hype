#!/usr/bin/env bash
# One-time host setup for the guild-name voting backend.
#
# Creates the systemd unit and a tightly-scoped passwordless sudoers entry that
# lets the unattended deploy restart the service (only that one systemctl verb,
# nothing else). Host-specific values (user, home) are read from the environment
# at install time, so this script — and the repo — carry no literal paths.
#
# Run on the serving host:   sudo -E bash server/install.sh
# Then deploy the code:       bash server/deploy.sh
set -euo pipefail

SVC_USER="${SUDO_USER:-$USER}"
SVC_HOME="$(getent passwd "$SVC_USER" | cut -d: -f6)"
RUNTIME="$SVC_HOME/hype-vote"
PORT="${GUILDNAMES_PORT:-8794}"
UNIT="hype-vote.service"
UNIT_PATH="/etc/systemd/system/$UNIT"
SUDOERS_PATH="/etc/sudoers.d/hype-vote-restart"
# Loot-log ingest (parses Gargul.lua, writes loot_awards). The source path is
# host-specific, so it is NOT baked into this repo — pass it at install time
# (sudo -E GARGUL_LUA_PATH=/path ...) or set it in hype-vote.env afterward.
INGEST_UNIT="hype-gargul-ingest.service"
INGEST_TIMER="hype-gargul-ingest.timer"
INGEST_UNIT_PATH="/etc/systemd/system/$INGEST_UNIT"
INGEST_TIMER_PATH="/etc/systemd/system/$INGEST_TIMER"
GARGUL_LUA_PATH="${GARGUL_LUA_PATH:-}"
# Guild-roster sync (pulls the Blizzard guild-roster API, writes guild_roster).
# Credentials + realm/guild slugs live in hype-vote.env (BLIZZARD_*), never the
# repo. Hourly is plenty — a guild roster moves slowly.
ROSTER_UNIT="hype-roster-sync.service"
ROSTER_TIMER="hype-roster-sync.timer"
ROSTER_UNIT_PATH="/etc/systemd/system/$ROSTER_UNIT"
ROSTER_TIMER_PATH="/etc/systemd/system/$ROSTER_TIMER"

if [ "$(id -u)" -ne 0 ]; then
  echo "install: re-run with sudo (sudo -E bash server/install.sh)" >&2
  exit 1
fi

# --- systemd unit: loopback-only, hardened, auto-restart --------------------
cat > "$UNIT_PATH" <<UNIT_EOF
[Unit]
Description=hype — guild-name voting backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SVC_USER
WorkingDirectory=$RUNTIME
Environment=GUILDNAMES_DB=$RUNTIME/data/guildnames.db
EnvironmentFile=-$RUNTIME/hype-vote.env
ExecStart=$RUNTIME/venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port $PORT
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$RUNTIME/data
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6
LockPersonality=true

[Install]
WantedBy=multi-user.target
UNIT_EOF
chmod 644 "$UNIT_PATH"

# --- secret env file — mode 600, never in the repo --------------------------
# EnvironmentFile above is optional (the `-`), so the service runs without it.
# Populate it with the configure-*.sh scripts; each key is independent.
install -d -o "$SVC_USER" -g "$SVC_USER" "$RUNTIME"
ENV_FILE="$RUNTIME/hype-vote.env"
if [ ! -f "$ENV_FILE" ]; then
  printf '%s\n' \
    '# hype backend secrets — mode 600, never commit.' \
    '# Turnstile (configure-turnstile.sh): TURNSTILE_SITEKEY, TURNSTILE_SECRET' \
    '# Apply     (configure-apply.sh):     DISCORD_WEBHOOK_URL, RESEND_API_KEY, APPLY_MAIL_FROM, APPLY_MAIL_TO' \
    '# Loot      (loot ingest):            GARGUL_LUA_PATH (Gargul.lua file or dir of them)' \
    '# Admin: no secret here — moderation is Authentik SSO on hype-admin.swagcounty.com' \
    > "$ENV_FILE"
  chown "$SVC_USER:$SVC_USER" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi
# Record the host-specific Gargul source path in the env file (not the repo) if
# it was passed at install time and isn't already set.
if [ -n "$GARGUL_LUA_PATH" ] && ! grep -q '^GARGUL_LUA_PATH=' "$ENV_FILE"; then
  printf 'GARGUL_LUA_PATH=%s\n' "$GARGUL_LUA_PATH" >> "$ENV_FILE"
  echo "install: recorded GARGUL_LUA_PATH=$GARGUL_LUA_PATH in $ENV_FILE"
fi

# --- scoped sudoers: only the one restart verb, validated before install ----
TMP_SUDOERS="$(mktemp)"
trap 'rm -f "$TMP_SUDOERS"' EXIT
printf '%s ALL=(root) NOPASSWD: /bin/systemctl restart %s\n' "$SVC_USER" "$UNIT" > "$TMP_SUDOERS"
visudo -cf "$TMP_SUDOERS"
install -m 0440 -o root -g root "$TMP_SUDOERS" "$SUDOERS_PATH"

# --- loot-log ingest: oneshot service + 15-min timer ------------------------
# Parses Gargul.lua (GARGUL_LUA_PATH, from hype-vote.env) and upserts the
# loot_awards table the backend serves at /api/loot. Reads a possibly
# network-mounted source but only on a timer, never in the web request path.
# Hardened like the backend; ProtectSystem=strict keeps the source readable
# (read-only) while the DB dir is the only writable path.
cat > "$INGEST_UNIT_PATH" <<INGEST_EOF
[Unit]
Description=hype — Gargul loot-log ingest (parse -> loot_awards)
After=network-online.target remote-fs.target
Wants=network-online.target

[Service]
Type=oneshot
User=$SVC_USER
WorkingDirectory=$RUNTIME
Environment=GUILDNAMES_DB=$RUNTIME/data/guildnames.db
EnvironmentFile=-$RUNTIME/hype-vote.env
ExecStart=$RUNTIME/venv/bin/python $RUNTIME/ingest_gargul.py
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$RUNTIME/data
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
LockPersonality=true
INGEST_EOF
chmod 644 "$INGEST_UNIT_PATH"

cat > "$INGEST_TIMER_PATH" <<TIMER_EOF
[Unit]
Description=hype — run the Gargul loot-log ingest every 15 minutes

[Timer]
OnBootSec=2min
OnCalendar=*:0/15
Persistent=true
AccuracySec=30s

[Install]
WantedBy=timers.target
TIMER_EOF
chmod 644 "$INGEST_TIMER_PATH"

# --- guild-roster sync: oneshot service + hourly timer ----------------------
# Pulls the Blizzard guild-roster API (BLIZZARD_* in hype-vote.env) and upserts
# the guild_roster table the backend reads to separate guildies from PUGs. Needs
# outbound HTTPS (unlike the loot ingest, which reads a file), so the unit is
# otherwise hardened the same way: writable DB dir only, no new privileges.
cat > "$ROSTER_UNIT_PATH" <<ROSTER_EOF
[Unit]
Description=hype — Blizzard guild-roster sync (API -> guild_roster)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$SVC_USER
WorkingDirectory=$RUNTIME
Environment=GUILDNAMES_DB=$RUNTIME/data/guildnames.db
EnvironmentFile=-$RUNTIME/hype-vote.env
ExecStart=$RUNTIME/venv/bin/python $RUNTIME/fetch_roster.py
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$RUNTIME/data
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
LockPersonality=true
ROSTER_EOF
chmod 644 "$ROSTER_UNIT_PATH"

cat > "$ROSTER_TIMER_PATH" <<ROSTER_TIMER_EOF
[Unit]
Description=hype — sync the guild roster hourly

[Timer]
OnBootSec=3min
OnCalendar=hourly
Persistent=true
AccuracySec=2min

[Install]
WantedBy=timers.target
ROSTER_TIMER_EOF
chmod 644 "$ROSTER_TIMER_PATH"

systemctl daemon-reload
systemctl enable "$UNIT"
systemctl enable --now "$INGEST_TIMER"   # --now arms the timer this session, not just at boot
systemctl enable --now "$ROSTER_TIMER"
echo "install: $UNIT_PATH + $SUDOERS_PATH written."
echo "install: $INGEST_UNIT_PATH + $INGEST_TIMER_PATH written (timer enabled)."
echo "install: $ROSTER_UNIT_PATH + $ROSTER_TIMER_PATH written (timer enabled)."
echo "install: set GARGUL_LUA_PATH + BLIZZARD_* in $RUNTIME/hype-vote.env if not already. Now run: bash server/deploy.sh"
