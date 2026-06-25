#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

FONT="fonts/ttf/GothicGumdrop-Regular.ttf"

if [[ -x ".venv/bin/fontmake" ]]; then
  FONTMAKE=".venv/bin/fontmake"
else
  FONTMAKE="fontmake"
fi

if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python3"
fi

"$FONTMAKE" -g sources/GothicGumdrop-Regular.glyphs \
  -o ttf \
  --output-dir fonts/ttf \
  --keep-overlaps \
  --ttf-curves keep-quad \
  --autohint

"$PYTHON" scripts/cleanup_ttf.py "$FONT"
