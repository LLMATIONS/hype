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
RUNTIME="$SVC_HOME/getajob-vote"
PORT="${GUILDNAMES_PORT:-8794}"
UNIT="getajob-vote.service"
UNIT_PATH="/etc/systemd/system/$UNIT"
SUDOERS_PATH="/etc/sudoers.d/getajob-vote-restart"

if [ "$(id -u)" -ne 0 ]; then
  echo "install: re-run with sudo (sudo -E bash server/install.sh)" >&2
  exit 1
fi

# --- systemd unit: loopback-only, hardened, auto-restart --------------------
cat > "$UNIT_PATH" <<UNIT_EOF
[Unit]
Description=Get a Job — guild-name voting backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SVC_USER
WorkingDirectory=$RUNTIME
Environment=GUILDNAMES_DB=$RUNTIME/data/guildnames.db
EnvironmentFile=-$RUNTIME/getajob-vote.env
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
ENV_FILE="$RUNTIME/getajob-vote.env"
if [ ! -f "$ENV_FILE" ]; then
  printf '%s\n' \
    '# Get a Job backend secrets — mode 600, never commit.' \
    '# Turnstile (configure-turnstile.sh): TURNSTILE_SITEKEY, TURNSTILE_SECRET' \
    '# Admin     (configure-admin.sh):     ADMIN_TOKEN' \
    '# Apply     (configure-apply.sh):     DISCORD_WEBHOOK_URL, RESEND_API_KEY, APPLY_MAIL_FROM, APPLY_MAIL_TO' \
    > "$ENV_FILE"
  chown "$SVC_USER:$SVC_USER" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

# --- scoped sudoers: only the one restart verb, validated before install ----
TMP_SUDOERS="$(mktemp)"
trap 'rm -f "$TMP_SUDOERS"' EXIT
printf '%s ALL=(root) NOPASSWD: /bin/systemctl restart %s\n' "$SVC_USER" "$UNIT" > "$TMP_SUDOERS"
visudo -cf "$TMP_SUDOERS"
install -m 0440 -o root -g root "$TMP_SUDOERS" "$SUDOERS_PATH"

systemctl daemon-reload
systemctl enable "$UNIT"
echo "install: $UNIT_PATH + $SUDOERS_PATH written. Now run: bash server/deploy.sh"
