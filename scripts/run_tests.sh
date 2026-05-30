#!/usr/bin/env bash
# Run the full test suite for Family Planner.
# Usage: ./scripts/run_tests.sh [pytest options]
#
# Examples:
#   ./scripts/run_tests.sh                  # all tests
#   ./scripts/run_tests.sh -x               # stop on first failure
#   ./scripts/run_tests.sh -k test_agenda   # filter by name
#   ./scripts/run_tests.sh -v               # verbose output
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Activate virtual environment if not already active
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f ".venv/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source .venv/bin/activate
    else
        echo "ERROR: .venv not found. Run: python -m venv .venv && pip install -r requirements.txt" >&2
        exit 1
    fi
fi

echo "=== Family Planner — Test Suite ==="
echo "Python: $(python --version)"
echo "pytest: $(python -m pytest --version)"
echo ""

python -m pytest tests/ "$@"
