#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")" && pwd)
VENV_DIR="$ROOT_DIR/.venv"
SERVICE_SRC="$ROOT_DIR/deploy/raspberrypi.service"
SERVICE_DST="/etc/systemd/system/raspberrypi.service"

echo "Setting up Raspberry Pi project environment..."

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
  echo "Created virtualenv at $VENV_DIR"
fi

# Activate and install
# shellcheck disable=SC1091
. "$VENV_DIR/bin/activate"
python3 -m pip install --upgrade pip
pip install -r server/requirements.txt

echo "Python dependencies installed in $VENV_DIR"

echo "You can run the API with:"
echo "  . $VENV_DIR/bin/activate && python3 server/app.py"
echo "Or with gunicorn:"
echo "  . $VENV_DIR/bin/activate && gunicorn -w 3 -b 0.0.0.0:5000 server.app:app"

if [ -f "$SERVICE_SRC" ]; then
  read -p "Install systemd service (requires sudo)? [y/N] " yn
  yn=${yn:-N}
  if [[ "$yn" =~ ^[Yy]$ ]]; then
    if [ "$EUID" -ne 0 ]; then
      echo "Copying service file with sudo..."
      sudo cp "$SERVICE_SRC" "$SERVICE_DST"
      sudo systemctl daemon-reload
      sudo systemctl enable raspberrypi.service
      sudo systemctl start raspberrypi.service
    else
      cp "$SERVICE_SRC" "$SERVICE_DST"
      systemctl daemon-reload
      systemctl enable raspberrypi.service
      systemctl start raspberrypi.service
    fi
    echo "Service installed and started. Check status with: sudo systemctl status raspberrypi.service"
  else
    echo "Skipping systemd installation. You can manually copy $SERVICE_SRC to $SERVICE_DST when ready."
  fi
else
  echo "Service template $SERVICE_SRC not found. Skipping systemd steps."
fi

echo "Setup complete."
