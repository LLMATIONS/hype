#!/usr/bin/env bash
# Deploy the guild-name voting backend into its host runtime dir and restart it.
#
# The service code lives in this repo (server/), but it RUNS from a runtime dir
# outside any git checkout ($HOME/hype-vote) so its writable SQLite DB never
# sits inside a pull-only serving checkout. This script copies the current code
# in next to the venv + data dir and restarts the unit.
#
# Run it from wherever the code is checked out:
#   bash server/deploy.sh
# It resolves its own directory, so the source is always this script's folder.
#
# First-time setup (creates the unit + scoped sudoers) is server/install.sh.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="$HOME/hype-vote"
UNIT="hype-vote.service"

mkdir -p "$RUNTIME/data"
[ -d "$RUNTIME/venv" ] || python3 -m venv "$RUNTIME/venv"
"$RUNTIME/venv/bin/pip" install -q --upgrade pip
"$RUNTIME/venv/bin/pip" install -q -r "$SRC/requirements.txt"
cp "$SRC/app.py" "$RUNTIME/app.py"
cp "$SRC/ingest_gargul.py" "$RUNTIME/ingest_gargul.py"

if sudo -n /bin/systemctl restart "$UNIT" 2>/dev/null; then
  echo "deploy: restarted $UNIT"
else
  echo "deploy: code in place; could not restart unattended." >&2
  echo "        run: sudo systemctl restart $UNIT   (or run server/install.sh first)" >&2
fi

# Refresh the loot log once now so a deploy reflects the latest Gargul data
# immediately (the 15-min timer otherwise picks it up on its next tick).
if systemctl list-unit-files hype-gargul-ingest.service >/dev/null 2>&1; then
  if systemctl start hype-gargul-ingest.service 2>/dev/null; then
    echo "deploy: ran loot-log ingest once"
  else
    echo "deploy: loot ingest not run unattended; the timer will catch up" >&2
  fi
fi
