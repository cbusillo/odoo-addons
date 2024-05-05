#!/bin/bash
set -euo pipefail
IFS=$'\n\t'

TAILSCALE_PATH="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
FLAG="${1:-}"

set +e  # Temporarily disable 'exit on error'
$TAILSCALE_PATH status > /dev/null 2>&1
INITIAL_STATE=$?
set -e  # Re-enable 'exit on error'

if ! ($TAILSCALE_PATH status > /dev/null 2>&1); then
    echo "Starting Tailscale..."
    $TAILSCALE_PATH up
else
    INITIAL_STATE=0
fi

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ -z "$CURRENT_BRANCH" ]; then
    echo "Error: Cannot find the current Git branch. Are you in a Git repository?"
    exit 1
fi

ssh opw-dev "bash -s" -- "$CURRENT_BRANCH" "$FLAG" << 'EOF'
FLAG=$2
CURRENT_BRANCH=$1

cd /opt/odoo/odoo17-addons
service odoo stop
echo "Current branch: $CURRENT_BRANCH"

git checkout $CURRENT_BRANCH
git pull origin $CURRENT_BRANCH

if [ "$FLAG" = "init" ]; then
    rm -f init-done.flag
    ./init-and-run-odoo-dev.sh sync-prod testing
fi
EOF

echo "Starting Odoo..."
ssh opw-dev "service odoo start"

if [ "$INITIAL_STATE" -ne 0 ]; then
    echo "Stopping Tailscale..."
    $TAILSCALE_PATH down
fi
