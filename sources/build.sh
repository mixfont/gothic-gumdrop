#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p fonts/ttf
python3 -m fontTools.ttx -q -o fonts/ttf/GothicGumdrop-Regular.ttf sources/GothicGumdrop-Regular.ttx
