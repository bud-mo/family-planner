#!/usr/bin/env bash
# Deploy the project to a Raspberry Pi via rsync + SSH.
# Usage: ./scripts/deploy.sh pi@<ip>
set -euo pipefail

TARGET="${1:?Usage: deploy.sh user@host}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
REMOTE_USER="$(echo "$TARGET" | cut -d@ -f1)"
REMOTE_DIR="/home/$REMOTE_USER/family-planner"

echo "=== Family Planner — Deploy to $TARGET ==="

# Sync project files (exclude dev/build artifacts)
echo "[1/5] Syncing files to $TARGET:$REMOTE_DIR ..."
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
    --exclude='pictures/' \
    --exclude='config/config.local.yaml' \
    --exclude='scripts/deploy.sh' \
    --exclude='scripts/setup-autostart.sh' \
    --exclude='scripts/convert_icons.js' \
    --exclude='scripts/convert_icons.sh' \
    --exclude='scripts/extract_icons.py' \
    "$PROJECT_DIR/" "$TARGET:$REMOTE_DIR/"

# Sync the artwork pictures folder (used by artwork "folder" mode).
# Synced separately so its contents are copied as-is without being affected by
# the build-artifact excludes above.
echo "[2/5] Syncing pictures folder to $TARGET:$REMOTE_DIR/pictures ..."
ssh "$TARGET" "mkdir -p $REMOTE_DIR/pictures"
rsync -avz "$PROJECT_DIR/pictures/" "$TARGET:$REMOTE_DIR/pictures/"

# Install/update Python dependencies on target
echo "[3/5] Installing Python dependencies on target..."
ssh "$TARGET" "cd $REMOTE_DIR && \
    python3 -m venv venv && \
    venv/bin/pip install --upgrade pip --quiet && \
    venv/bin/pip install -r requirements.txt --quiet"

# Install/update systemd service
echo "[4/5] Installing systemd service..."
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

# Reload and restart systemd service
echo "[5/5] Restarting family-planner service..."
ssh -t "$TARGET" "sudo systemctl daemon-reload && \
    sudo systemctl enable family-planner && \
    sudo systemctl restart family-planner && \
    sudo systemctl status family-planner --no-pager"

echo ""
echo "=== Deploy complete ==="
