#!/usr/bin/env bash
# Convert Tabler Icons outline SVGs to PNG files.
# Delegates to scripts/convert_icons.js via Node.js.
#
# Usage:
#   ./scripts/convert_icons.sh                   # 24px, skip existing
#   ./scripts/convert_icons.sh --force           # overwrite all
#   ./scripts/convert_icons.sh --size=48         # custom size
#   ./scripts/convert_icons.sh --name=heart,star # specific icons

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Install JS dependencies if not present
if [[ ! -d "$SCRIPT_DIR/node_modules" ]]; then
  echo "Installing script dependencies…"
  (cd "$SCRIPT_DIR" && npm install --silent)
fi

node "$SCRIPT_DIR/convert_icons.js" "$@"
