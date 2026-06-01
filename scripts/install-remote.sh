#!/usr/bin/env bash
# First-time installation of Family Planner on a remote Raspberry Pi.
# Usage: ./scripts/install-remote.sh user@host
#
# What this script does:
#   1. Syncs project files to the target via rsync
#   2. Runs install.sh on the target (apt deps, I2C/SPI, venv, pip)
#   3. Reboots the target (required for I2C/SPI to take effect)
#   4. Waits for the target to come back online
#   5. Patches and installs the systemd service
#   6. Enables and starts the service
set -euo pipefail

TARGET="${1:?Usage: install-remote.sh user@host}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
REMOTE_USER="$(echo "$TARGET" | cut -d@ -f1)"
REMOTE_DIR="/home/$REMOTE_USER/family-planner"

REBOOT_TIMEOUT=180  # seconds to wait for Pi to come back online
REBOOT_POLL=5       # polling interval in seconds

echo "=== Family Planner — Remote Install to $TARGET ==="

# ---------------------------------------------------------------------------
# 1. Sync project files
# ---------------------------------------------------------------------------
echo "[1/6] Syncing files to $TARGET:$REMOTE_DIR ..."
rsync -avz \
    --exclude='.git' \
    --exclude='.github' \
    --exclude='.gitignore' \
    --exclude='.venv' \
    --exclude='venv' \
    --exclude='.env' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='*.egg-info' \
    --exclude='.pytest_cache' \
    --exclude='node_modules' \
    --exclude='package.json' \
    --exclude='package-lock.json' \
    --exclude='.nvmrc' \
    --exclude='.vscode' \
    --exclude='AGENTS.md' \
    --exclude='README.md' \
    --exclude='docs/' \
    --exclude='tests/' \
    --exclude='config/config.local.yaml' \
    --exclude='scripts/deploy.sh' \
    --exclude='scripts/install-remote.sh' \
    --exclude='scripts/setup-autostart.sh' \
    --exclude='scripts/convert_icons.js' \
    --exclude='scripts/convert_icons.sh' \
    --exclude='scripts/extract_icons.py' \
    "$PROJECT_DIR/" "$TARGET:$REMOTE_DIR/"

# ---------------------------------------------------------------------------
# 2. Run install.sh on target (apt, I2C/SPI, venv, pip, base service copy)
# ---------------------------------------------------------------------------
echo "[2/6] Running install.sh on target..."
ssh -t "$TARGET" "bash $REMOTE_DIR/scripts/install.sh"

# ---------------------------------------------------------------------------
# 3. Reboot (required for I2C/SPI dtparams to take effect)
# ---------------------------------------------------------------------------
echo "[3/6] Rebooting target for I2C/SPI activation..."
ssh "$TARGET" "sudo reboot" || true  # SSH exits non-zero when connection drops — that's expected

# ---------------------------------------------------------------------------
# 4. Wait for Pi to come back online
# ---------------------------------------------------------------------------
echo "[4/6] Waiting for $TARGET to come back online (max ${REBOOT_TIMEOUT}s)..."
elapsed=0
until ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes \
        "$TARGET" exit 2>/dev/null; do
    if (( elapsed >= REBOOT_TIMEOUT )); then
        echo "ERROR: $TARGET did not come back online within ${REBOOT_TIMEOUT}s." >&2
        exit 1
    fi
    printf "  Waiting... (%ds elapsed)\r" "$elapsed"
    sleep "$REBOOT_POLL"
    elapsed=$(( elapsed + REBOOT_POLL ))
done
echo "  Target is online after ${elapsed}s.                "

# ---------------------------------------------------------------------------
# 5. Patch and install systemd service; deploy default config
# ---------------------------------------------------------------------------
echo "[5/6] Installing systemd service..."
# shellcheck disable=SC2029
ssh -t "$TARGET" "sed \"s|/home/pi|/home/$REMOTE_USER|g; s|User=pi|User=$REMOTE_USER|g\" \
    $REMOTE_DIR/systemd/family-planner.service | \
    sudo tee /etc/systemd/system/family-planner.service > /dev/null && \
    if [ ! -f /boot/firmware/family-planner.config.yaml ]; then \
        sudo cp $REMOTE_DIR/config/default.yaml /boot/firmware/family-planner.config.yaml && \
        sudo chmod 644 /boot/firmware/family-planner.config.yaml && \
        echo 'Default config written to /boot/firmware/family-planner.config.yaml'; \
    else \
        echo '/boot/firmware/family-planner.config.yaml already exists, skipping.'; \
    fi"

# ---------------------------------------------------------------------------
# 6. Enable and start the service
# ---------------------------------------------------------------------------
echo "[6/6] Enabling and starting family-planner service..."
ssh -t "$TARGET" "sudo systemctl daemon-reload && \
    sudo systemctl enable family-planner && \
    sudo systemctl start family-planner && \
    sudo systemctl status family-planner --no-pager"

echo ""
echo "=== Remote install complete ==="
echo "To deploy future updates:  ./scripts/deploy.sh $TARGET"
echo "To view logs:              ssh $TARGET 'journalctl -u family-planner -f'"
