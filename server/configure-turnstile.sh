#!/usr/bin/env bash
# Configure Cloudflare Turnstile for the guild-name vote, then restart.
#
# The sitekey is public (it ships in the page). The secret is NOT — it is read
# without echo and written straight to the mode-600 service env file, so it
# never lands in shell history, the repo, or this terminal's scrollback.
#
# Upserts: re-running rotates ONLY the Turnstile keys and preserves everything
# else already in the file (the apply delivery secrets). Same pattern as
# configure-apply.sh.
#
# Get both from the Cloudflare dashboard: Turnstile > add a widget for
# getajob.swagcounty.com (Managed mode). Then run:  bash server/configure-turnstile.sh
set -euo pipefail

RUNTIME="$HOME/getajob-vote"
ENV_FILE="$RUNTIME/getajob-vote.env"
UNIT="getajob-vote.service"

mkdir -p "$RUNTIME"
if [ ! -f "$ENV_FILE" ]; then
  umask 177
  printf '# Get a Job backend secrets — mode 600, never commit.\n' > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

# Upsert KEY=VALUE into the env file, preserving every other line.
set_kv() {
  local key="$1" val="$2" tmp
  tmp="$(mktemp)"
  grep -vE "^${key}=" "$ENV_FILE" > "$tmp" 2>/dev/null || true
  printf '%s=%s\n' "$key" "$val" >> "$tmp"
  install -m 600 "$tmp" "$ENV_FILE"
  rm -f "$tmp"
}

read -r -p "Turnstile sitekey (public): " SITEKEY
read -r -s -p "Turnstile secret (hidden): " SECRET; echo
if [ -z "$SITEKEY" ] || [ -z "$SECRET" ]; then
  echo "configure-turnstile: both values are required." >&2
  exit 1
fi

set_kv TURNSTILE_SITEKEY "$SITEKEY"
set_kv TURNSTILE_SECRET  "$SECRET"
unset SECRET SITEKEY

echo "configure-turnstile: wrote $ENV_FILE (mode 600). Restarting…"
sudo -n /bin/systemctl restart "$UNIT" 2>/dev/null \
  && echo "configure-turnstile: $UNIT restarted; Turnstile is now enforced on submissions." \
  || echo "configure-turnstile: wrote keys, but restart needs: sudo systemctl restart $UNIT"
