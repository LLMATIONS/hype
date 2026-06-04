#!/usr/bin/env bash
# Generate (or rotate) the admin token for the guild-name vote and restart.
#
# The token gates deleting entries. It is generated on the box, written to the
# mode-600 service env file, and printed ONCE to this terminal so you can save
# it in your password manager — it never goes through chat, the repo, or an
# argument. Re-running rotates it (old token stops working after the restart).
#
#   bash server/configure-admin.sh
# Then open /guild-names/?admin and paste it to unlock the delete buttons.
set -euo pipefail

RUNTIME="$HOME/getajob-vote"
ENV_FILE="$RUNTIME/getajob-vote.env"
UNIT="getajob-vote.service"

mkdir -p "$RUNTIME"
TOKEN="$(openssl rand -hex 32)"

umask 177
touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
# preserve any other keys (Turnstile), replace only ADMIN_TOKEN
{ grep -v '^ADMIN_TOKEN=' "$ENV_FILE" 2>/dev/null || true; echo "ADMIN_TOKEN=$TOKEN"; } > "$ENV_FILE.tmp"
mv "$ENV_FILE.tmp" "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "Admin token (save it now — shown once, not stored anywhere you can read it back):"
echo
echo "    $TOKEN"
echo
unset TOKEN

sudo -n /bin/systemctl restart "$UNIT" 2>/dev/null \
  && echo "Restarted $UNIT — admin delete is live. Unlock at /guild-names/?admin" \
  || echo "Wrote the token, but restart needs: sudo systemctl restart $UNIT"
