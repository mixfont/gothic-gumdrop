#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  PYTHON="$VIRTUAL_ENV/bin/python"
elif [[ -x .venv/bin/python ]]; then
  PYTHON=.venv/bin/python
else
  PYTHON=python3
fi

# Packages compiled exports; see sources/README.md for the source-build blocker.
"$PYTHON" sources/prepare_release.py
