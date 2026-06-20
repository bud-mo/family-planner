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
echo "[1/7] Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y \
    python3-dev \
    python3-pip \
    python3-venv \
    python3-spidev \
    python3-gpiozero \
    --no-install-recommends

# 2. Enable I2C and SPI interfaces
echo "[2/7] Enabling I2C interface..."
sudo raspi-config nonint do_i2c 0
echo "    I2C enabled."

echo "[3/7] Enabling SPI interface..."
sudo raspi-config nonint do_spi 0
echo "    SPI enabled."
echo "    NOTE: I2C and SPI take effect at next boot (dtparam written to /boot/config.txt)."
echo "    To activate immediately without reboot, run:"
echo "      sudo modprobe i2c-dev && sudo dtoverlay spi0-2cs"

# 3. Create virtual environment
echo "[4/7] Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 4. Install Python dependencies
echo "[5/7] Installing Python packages..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# 5. Copy systemd service
echo "[6/7] Installing systemd service..."
SERVICE_SRC="$PROJECT_DIR/systemd/family-planner.service"
SERVICE_DST="/etc/systemd/system/family-planner.service"

if [[ -f "$SERVICE_SRC" ]]; then
    sudo cp "$SERVICE_SRC" "$SERVICE_DST"
    sudo systemctl daemon-reload
    echo "    Service installed at $SERVICE_DST"
else
    echo "    WARNING: $SERVICE_SRC not found, skipping service installation."
fi

# 6. Secure config file
echo "[7/7] Securing config file permissions..."
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
