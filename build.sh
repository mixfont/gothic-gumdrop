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

# Build a TrueType export from the editable UFO source.
export SOURCE_DATE_EPOCH=1792188073
"$PYTHON" -m fontmake -u sources/GothicGumdrop-Regular.ufo -o ttf \
  --output-path fonts/ttf/GothicGumdrop-Regular.ttf --validate-ufo \
  --no-production-names
