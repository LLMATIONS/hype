#!/usr/bin/env bash
# Configure guild-application delivery (Discord webhook + Resend email), then restart.
#
# Values are all optional and each independent — set only the ones you have and
# re-run any time to update one. An unset value leaves whatever is already there;
# a blank entry is skipped. Each delivery channel works the moment its secret lands:
#   DISCORD_WEBHOOK_URL  the channel webhook (Server Settings > Integrations > Webhooks)
#   DISCORD_BOT_TOKEN    a bot token (Discord Developer Portal). When present it
#                        SUPERSEDES the webhook for posting and unlocks the
#                        per-applicant thread ("<character> — <class>") plus the
#                        pre-seeded ✅/❌ officer-vote reactions. Keep the webhook
#                        URL set too — the channel is auto-read from it.
#   RESEND_API_KEY       a Resend API key (re_...)
#   APPLY_MAIL_FROM      verified sender, e.g.  hype <apply@send.swagcounty.com>
#   APPLY_MAIL_TO        comma-separated recipient address(es)
#
# The webhook URL, bot token, and API key carry secrets, so they are read WITHOUT
# echo and written straight to the mode-600 service env file — never shell history.
# Upserts: the Turnstile and admin keys already in the file are preserved.
#
# Run on the serving host:  bash server/configure-apply.sh
set -euo pipefail

RUNTIME="$HOME/hype-vote"
ENV_FILE="$RUNTIME/hype-vote.env"
UNIT="hype-vote.service"

mkdir -p "$RUNTIME"
if [ ! -f "$ENV_FILE" ]; then
  umask 177
  printf '# hype backend secrets — mode 600, never commit.\n' > "$ENV_FILE"
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

read -r -s -p "Discord webhook URL (hidden, blank = skip): " WEBHOOK; echo
read -r -s -p "Discord bot token (hidden, blank = skip):    " BTOKEN; echo
read -r -s -p "Resend API key (hidden, blank = skip):      " RKEY; echo
read -r    -p "Mail FROM (e.g. hype <apply@send.swagcounty.com>, blank = skip): " MFROM
read -r    -p "Mail TO   (comma-separated, blank = skip):   " MTO

changed=()
[ -n "$WEBHOOK" ] && { set_kv DISCORD_WEBHOOK_URL "$WEBHOOK"; changed+=("DISCORD_WEBHOOK_URL"); }
[ -n "$BTOKEN" ]  && { set_kv DISCORD_BOT_TOKEN   "$BTOKEN";  changed+=("DISCORD_BOT_TOKEN"); }
[ -n "$RKEY" ]    && { set_kv RESEND_API_KEY     "$RKEY";    changed+=("RESEND_API_KEY"); }
[ -n "$MFROM" ]   && { set_kv APPLY_MAIL_FROM    "$MFROM";   changed+=("APPLY_MAIL_FROM"); }
[ -n "$MTO" ]     && { set_kv APPLY_MAIL_TO      "$MTO";     changed+=("APPLY_MAIL_TO"); }
unset WEBHOOK BTOKEN RKEY

if [ "${#changed[@]}" -eq 0 ]; then
  echo "configure-apply: nothing entered; $ENV_FILE unchanged."
  exit 0
fi

echo "configure-apply: updated ${changed[*]} in $ENV_FILE (mode 600). Restarting…"
sudo -n /bin/systemctl restart "$UNIT" 2>/dev/null \
  && echo "configure-apply: $UNIT restarted; delivery is live for the configured channels." \
  || echo "configure-apply: wrote keys, but restart needs: sudo systemctl restart $UNIT"
