#!/usr/bin/env bash
# Tail production logs. Existing so nobody has to remember the invocation.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source scripts/preflight.conf.example 2>/dev/null || true
: "${TARGET:?set TARGET=user@host}"
: "${SERVICE:?set SERVICE=name.service}"
exec ssh -t "$TARGET" "journalctl --user -u $SERVICE -f -n ${1:-100}"
