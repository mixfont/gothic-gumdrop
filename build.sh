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

# The source is cubic; cu2qu converts curves to quadratic for the TTF.
# -e 0.002 (2 units at 1000 UPM) keeps the point count down with no
# visible difference at text sizes.
"$FONTMAKE" -g sources/GothicGumdrop-Regular.glyphs \
  -o ttf \
  --output-dir fonts/ttf \
  --keep-overlaps \
  -e 0.002 \
  --autohint ""

"$FONTMAKE" -g sources/GothicGumdrop-Regular.glyphs \
  -o otf \
  --output-dir fonts/otf \
  --keep-overlaps

# Outline cleanup is skipped: the refit source (scripts/refit_outlines.py)
# already has clean outlines, and editing points after autohinting would
# invalidate the hint programs.
"$PYTHON" scripts/cleanup_ttf.py "$FONT" --skip-outline-cleanup
