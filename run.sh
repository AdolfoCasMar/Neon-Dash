#!/usr/bin/env bash
# Lanza Neon Dash usando el entorno virtual de la carpeta si existe.
set -euo pipefail
cd "$(dirname "$0")"

if [ -x .venv/bin/python ]; then
    exec .venv/bin/python main.py "$@"
fi

if python3 -c "import pygame" 2>/dev/null; then
    exec python3 main.py "$@"
fi

echo "No encuentro pygame. Crea el entorno así:" >&2
echo "  python3 -m venv .venv" >&2
echo "  .venv/bin/pip install -r requirements.txt" >&2
exit 1
