#!/bin/bash
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

PY_BIN="python3"
if [ -f ".venv/bin/python" ]; then
    PY_BIN=".venv/bin/python"
fi

if [ "$1" = "--cli" ]; then
    shift
    "$PY_BIN" main.py "$@"
else
    "$PY_BIN" gui_server.py "$@"
fi
