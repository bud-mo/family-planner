#!/usr/bin/env bash
# Deploy the project to a Raspberry Pi via rsync + SSH.
# Usage: ./scripts/deploy.sh pi@<ip>
set -euo pipefail

TARGET="${1:?Usage: deploy.sh user@host}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
REMOTE_DIR="/home/pi/family-planner"

echo "=== Family Planner — Deploy to $TARGET ==="

# Sync project files (exclude dev/build artifacts)
echo "[1/3] Syncing files to $TARGET:$REMOTE_DIR ..."
rsync -avz \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.venv' \
    --exclude='venv' \
    --exclude='.env' \
    --exclude='*.egg-info' \
    "$PROJECT_DIR/" "$TARGET:$REMOTE_DIR/"

# Install/update Python dependencies on target
echo "[2/3] Installing Python dependencies on target..."
ssh "$TARGET" "cd $REMOTE_DIR && \
    python3 -m venv venv && \
    venv/bin/pip install --upgrade pip --quiet && \
    venv/bin/pip install -r requirements.txt --quiet"

# Reload and restart systemd service
echo "[3/3] Restarting family-planner service..."
ssh "$TARGET" "sudo systemctl daemon-reload && \
    sudo systemctl restart family-planner && \
    sudo systemctl status family-planner --no-pager"

echo ""
echo "=== Deploy complete ==="
