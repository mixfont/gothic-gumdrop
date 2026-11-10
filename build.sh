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

# Builder launches fontmake and its other tools as subprocesses.
export PATH="$(dirname "$("$PYTHON" -c 'import sys; print(sys.executable)')"):$PATH"
# Fix timestamps for reproducible binaries (2026-11-05 14:30:00 UTC).
export SOURCE_DATE_EPOCH=1793889000
gftools builder sources/config.yaml
