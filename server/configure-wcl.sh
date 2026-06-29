#!/usr/bin/env bash
# Configure the Warcraft Logs attendance sync + the trial tracker, then restart.
#
# The trial tracker counts how many weekly lockouts each trial has actually
# raided (presence from Warcraft Logs, not loot) and flags them due for
# evaluation. It needs:
#   WCL_CLIENT_ID / WCL_CLIENT_SECRET  a Warcraft Logs API client
#                        (warcraftlogs.com/api/clients, client-credentials grant).
#                        The secret is read WITHOUT echo and written straight to
#                        the mode-600 env file — never shell history.
#   WCL_GUILD_NAME       the guild's display name exactly as it appears on WCL.
#   WCL_SERVER_SLUG      realm slug (default nightslayer).
#   WCL_SERVER_REGION    region (default us).
#   BLIZZARD_TRIAL_RANK  the in-game guild rank index (0..9, 0 = GM) that means
#                        "Trial". This is what turns the tracker ON — unset/blank
#                        leaves it off and no trials are surfaced.
#   TRIAL_LOCKOUTS       lockouts required before evaluation (default 3).
#
# Each value is independent; blank = skip (leaves whatever is already set). Every
# other key in the env file is preserved.
#
# Run on the serving host:  bash server/configure-wcl.sh
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

read -r    -p "WCL client id (visible, blank = skip):           " WID
read -r -s -p "WCL client secret (hidden, blank = skip):        " WSEC; echo
read -r    -p "WCL guild name (exact, blank = skip):            " WGUILD
read -r    -p "WCL server slug (default nightslayer, blank=skip):" WSLUG
read -r    -p "WCL server region (default us, blank = skip):    " WREGION
read -r    -p "In-game Trial rank index 0-9 (blank = skip):     " TRANK
read -r    -p "Lockouts required for eval (default 3, blank=skip):" TLOCK

changed=()
[ -n "$WID" ]     && { set_kv WCL_CLIENT_ID     "$WID";     changed+=("WCL_CLIENT_ID"); }
[ -n "$WSEC" ]    && { set_kv WCL_CLIENT_SECRET "$WSEC";    changed+=("WCL_CLIENT_SECRET"); }
[ -n "$WGUILD" ]  && { set_kv WCL_GUILD_NAME    "$WGUILD";  changed+=("WCL_GUILD_NAME"); }
[ -n "$WSLUG" ]   && { set_kv WCL_SERVER_SLUG   "$WSLUG";   changed+=("WCL_SERVER_SLUG"); }
[ -n "$WREGION" ] && { set_kv WCL_SERVER_REGION "$WREGION"; changed+=("WCL_SERVER_REGION"); }
[ -n "$TRANK" ]   && { set_kv BLIZZARD_TRIAL_RANK "$TRANK"; changed+=("BLIZZARD_TRIAL_RANK"); }
[ -n "$TLOCK" ]   && { set_kv TRIAL_LOCKOUTS    "$TLOCK";   changed+=("TRIAL_LOCKOUTS"); }
unset WSEC

if [ "${#changed[@]}" -eq 0 ]; then
  echo "configure-wcl: nothing entered; $ENV_FILE unchanged."
  exit 0
fi

echo "configure-wcl: updated ${changed[*]} in $ENV_FILE (mode 600). Restarting…"
sudo -n /bin/systemctl restart "$UNIT" 2>/dev/null \
  && echo "configure-wcl: $UNIT restarted. Run 'sudo systemctl start hype-wcl-sync.service' to pull attendance now." \
  || echo "configure-wcl: wrote keys, but restart needs: sudo systemctl restart $UNIT"
