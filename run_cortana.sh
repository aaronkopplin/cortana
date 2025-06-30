#!/usr/bin/env bash
# Activate virtual environment and start Cortana CLI
set -euo pipefail

VENV_DIR="${VENV_DIR:-.venv}"

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

exec python3 cortana.py "$@"
