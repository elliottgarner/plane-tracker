#!/usr/bin/env bash
# Pull the latest version from git and restart the service if anything changed.
# Run by plane-tracker-update.timer (as your normal user), or by hand: bash deploy/update.sh
set -euo pipefail
APPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APPDIR"
log() { echo "[update] $*"; }

git fetch --quiet origin
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse '@{u}')"
if [ "$LOCAL" = "$REMOTE" ]; then log "already up to date ($(git rev-parse --short HEAD))"; exit 0; fi

# Never clobber local edits: tracked-file changes block the update (data/ is git-ignored).
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  log "local changes present - skipping update"; exit 1
fi

OLD_REQ="$(git rev-parse HEAD:requirements.txt)"
git pull --ff-only --quiet
log "updated $(git rev-parse --short "$LOCAL") -> $(git rev-parse --short HEAD)"

if [ "$OLD_REQ" != "$(git rev-parse HEAD:requirements.txt)" ]; then
  log "requirements changed - installing"
  .venv/bin/pip install --quiet -r requirements.txt
fi

sudo -n /usr/bin/systemctl restart plane-tracker.service
log "service restarted (open kiosk page reloads itself)"
