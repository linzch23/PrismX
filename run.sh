#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
UV="${UV:-/Users/ipsc_gummy/.local/bin/uv}"

exec "$UV" --directory "$ROOT" run --no-editable my-agent2
