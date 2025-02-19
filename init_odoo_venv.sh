#!/bin/bash
set -euo pipefail

PYTHON_VERSION="3.13"
PYTHON_BIN="python$PYTHON_VERSION"
VENV_PATH="./.venv"
SITE_PACKAGES="$VENV_PATH/lib/python$PYTHON_VERSION/site-packages"
PTH_FILE="$SITE_PACKAGES/odoo_local.pth"
ODOO_ENTERPRISE_REL="../Odoo/odoo-enterprise"
ODOO_ENTERPRISE=$(cd "$ODOO_ENTERPRISE_REL" && pwd)

if ! command -v "$PYTHON_BIN" > /dev/null; then
    echo "Python $PYTHON_VERSION is not installed." >&2
    exit 1
fi

if [ ! -d "$ODOO_ENTERPRISE" ]; then
    echo "Odoo-enterprise path not found: $ODOO_ENTERPRISE" >&2
    exit 1
fi

echo "Removing existing virtual environment..."
rm -rf "$VENV_PATH" 2> /dev/null

echo "Creating virtual environment..."
$PYTHON_BIN -m venv "$VENV_PATH"
source "$VENV_PATH/bin/activate"

echo "Updating pip..."
$PYTHON_BIN -m pip install --upgrade pip

echo "Installing Odoo dependencies..."
pip install -r odoo-addons/requirements.txt -r odoo-addons/requirements-dev.txt


if [ ! -f "$PTH_FILE" ] || [ "$(cat "$PTH_FILE")" != "$ODOO_ENTERPRISE" ]; then
    echo "Creating/updating $PTH_FILE with the Odoo-enterprise path..."
    if echo "$ODOO_ENTERPRISE" > "$PTH_FILE"; then
        echo "Successfully updated $PTH_FILE."
    else
        echo "Failed to write to $PTH_FILE." >&2
        exit 1
    fi
else
    echo "$PTH_FILE is already up-to-date."
fi

echo "Virtual environment setup complete.  Restarting the IDE..."
ACTIVE_APP=$(osascript -e 'tell application "System Events" to get POSIX path of (application file of first process whose name contains "idea")')

if [ -z "$ACTIVE_APP" ]; then
    echo "No active IntelliJ process detected."
else
    echo "Found active IntelliJ app: $ACTIVE_APP"
fi

nohup sh -c "sleep 5; open -a \"$ACTIVE_APP\"" >/dev/null 2>&1 &
osascript -e "tell application \"$ACTIVE_APP\" to quit"
