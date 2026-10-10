#!/usr/bin/env bash
# Quantum Playground Studio v9 - one-time setup (creates .venv in the project folder)
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[all]"
echo "Installed. Start the studio with scripts/run_studio.sh"
