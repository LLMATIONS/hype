#!/usr/bin/env bash
# Configure Cloudflare Turnstile for the guild-name vote, then restart.
#
# The sitekey is public (it ships in the page). The secret is NOT — it is read
# without echo and written straight to the mode-600 service env file, so it
# never lands in shell history, the repo, or this terminal's scrollback.
#
# Get both from the Cloudflare dashboard: Turnstile > add a widget for
# getajob.swagcounty.com (Managed mode). Then run:  bash server/configure-turnstile.sh
set -euo pipefail

RUNTIME="$HOME/getajob-vote"
ENV_FILE="$RUNTIME/getajob-vote.env"
UNIT="getajob-vote.service"

mkdir -p "$RUNTIME"

read -r -p "Turnstile sitekey (public): " SITEKEY
read -r -s -p "Turnstile secret (hidden): " SECRET; echo
if [ -z "$SITEKEY" ] || [ -z "$SECRET" ]; then
  echo "configure-turnstile: both values are required." >&2
  exit 1
fi

umask 177
{
  echo "# Turnstile keys for the guild-name vote. Mode 600. Never commit."
  echo "TURNSTILE_SITEKEY=$SITEKEY"
  echo "TURNSTILE_SECRET=$SECRET"
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"
unset SECRET SITEKEY

echo "configure-turnstile: wrote $ENV_FILE (mode 600). Restarting…"
sudo -n /bin/systemctl restart "$UNIT" 2>/dev/null \
  && echo "configure-turnstile: $UNIT restarted; Turnstile is now enforced on submissions." \
  || echo "configure-turnstile: wrote keys, but restart needs: sudo systemctl restart $UNIT"
