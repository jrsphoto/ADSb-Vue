#!/usr/bin/env bash
# Tail the production container's logs. Exists so nobody has to remember the
# invocation. Optional first arg = how many lines of history (default 100).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source scripts/preflight.conf
: "${TARGET:?set TARGET=user@host in scripts/preflight.conf}"
: "${CONTAINER:=adsbvue}"
exec ssh -t "$TARGET" "docker logs -f --tail ${1:-100} '$CONTAINER'"
