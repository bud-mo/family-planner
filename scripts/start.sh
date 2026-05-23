#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

if [[ -d ".venv" ]]; then
    source .venv/bin/activate
elif [[ -d "venv" ]]; then
    source venv/bin/activate
else
    echo "ERROR: No virtual environment found (.venv or venv). Run scripts/install.sh first." >&2
    exit 1
fi

if [[ $# -eq 0 ]]; then
    python app/main.py --config config/default.yaml
else
    python app/main.py "$@"
fi
