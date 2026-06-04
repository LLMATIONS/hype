#!/usr/bin/env bash
# Deploy the guild-name voting backend into its host runtime dir and restart it.
#
# The service code lives in this repo (server/), but it RUNS from a runtime dir
# outside any git checkout ($HOME/getajob-vote) so its writable SQLite DB never
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
RUNTIME="$HOME/getajob-vote"
UNIT="getajob-vote.service"

mkdir -p "$RUNTIME/data"
[ -d "$RUNTIME/venv" ] || python3 -m venv "$RUNTIME/venv"
"$RUNTIME/venv/bin/pip" install -q --upgrade pip
"$RUNTIME/venv/bin/pip" install -q -r "$SRC/requirements.txt"
cp "$SRC/app.py" "$RUNTIME/app.py"

if sudo -n /bin/systemctl restart "$UNIT" 2>/dev/null; then
  echo "deploy: restarted $UNIT"
else
  echo "deploy: code in place; could not restart unattended." >&2
  echo "        run: sudo systemctl restart $UNIT   (or run server/install.sh first)" >&2
fi
