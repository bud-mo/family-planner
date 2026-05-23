#!/usr/bin/env bash
# Install script for Raspberry Pi.
# Run once after cloning the repository:
#   bash scripts/install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=== Family Planner — Install ==="

# 1. System dependencies
echo "[1/5] Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    libsdl2-dev \
    libsdl2-image-dev \
    libsdl2-mixer-dev \
    libsdl2-ttf-dev \
    python3-spidev \
    python3-gpiozero \
    --no-install-recommends

# 2. Create virtual environment
echo "[2/5] Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 3. Install Python dependencies
echo "[3/5] Installing Python packages..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# 4. Copy systemd service
echo "[4/5] Installing systemd service..."
SERVICE_SRC="$PROJECT_DIR/systemd/family-planner.service"
SERVICE_DST="/etc/systemd/system/family-planner.service"

if [[ -f "$SERVICE_SRC" ]]; then
    sudo cp "$SERVICE_SRC" "$SERVICE_DST"
    sudo systemctl daemon-reload
    echo "    Service installed at $SERVICE_DST"
else
    echo "    WARNING: $SERVICE_SRC not found, skipping service installation."
fi

# 5. Secure config file
echo "[5/5] Securing config file permissions..."
CONFIG_FILE="$PROJECT_DIR/config.yaml"
if [[ -f "$CONFIG_FILE" ]]; then
    chmod 600 "$CONFIG_FILE"
    echo "    Permissions set to 600 on $CONFIG_FILE"
else
    echo "    No config.yaml found — remember to set permissions after creating it."
fi

echo ""
echo "=== Installation complete ==="
echo "Start the service:    sudo systemctl start family-planner"
echo "Enable on boot:       sudo systemctl enable family-planner"
echo "Or run directly:      bash scripts/start.sh"
