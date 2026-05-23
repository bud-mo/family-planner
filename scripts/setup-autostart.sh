#!/usr/bin/env bash
# Enable the family-planner systemd service to start on boot.
# Usage: ./scripts/setup-autostart.sh pi@<ip>
set -euo pipefail

TARGET="${1:?Usage: setup-autostart.sh user@host}"

echo "=== Family Planner — Enable autostart on $TARGET ==="
ssh "$TARGET" "sudo systemctl enable family-planner && \
    sudo systemctl start family-planner && \
    sudo systemctl status family-planner --no-pager"
echo "=== Autostart enabled ==="
