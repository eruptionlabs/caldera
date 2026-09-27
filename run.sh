#!/bin/bash
# Caldera HUD Designer. Precisa da Eruption Engine por perto:
#   - clonado como submodulo em <engine>/tools/caldera (achado sozinho), ou
#   - ERUPTION_ROOT=/caminho/da/engine ./run.sh
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv"
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -q -r "$HERE/requirements.txt"
fi
exec "$VENV/bin/python" "$HERE/caldera_designer.py" "$@"
