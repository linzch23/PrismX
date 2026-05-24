#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"

MY_AGENT_ROOT="$ROOT" \
PYTHONPATH="$ROOT/src" \
exec "$ROOT/.venv/bin/python" -m my_agent2.server
