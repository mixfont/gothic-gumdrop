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

# Apply the Google Fonts rendering setup for an unhinted TrueType export.
"$PYTHON" - <<'PY'
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables.ttProgram import Program

path = "fonts/ttf/GothicGumdrop-Regular.ttf"
with TTFont(path, recalcTimestamp=False) as font:
    font["gasp"] = newTable("gasp")
    font["gasp"].gaspRange = {65535: 15}
    font["prep"] = newTable("prep")
    font["prep"].program = Program()
    font["prep"].program.fromAssembly(
        ["PUSHW[]", "511", "SCANCTRL[]", "PUSHB[]", "4", "SCANTYPE[]"]
    )
    font.save(path)
PY
