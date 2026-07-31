#!/usr/bin/env bash
# Session-start environment verification.
#
# Run this first, every session. It replaces twenty minutes of explaining the
# environment with a single authoritative output. Edit scripts/preflight.conf
# to describe THIS project; this file should not need changing.
#
# Exit 0 = environment good. Nonzero = fix before writing code.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=lib/checks.sh
source "$ROOT/scripts/lib/checks.sh"

printf '%s%s preflight%s  %s\n' "$C_BOLD" "$(basename "$ROOT")" "$C_OFF" "$(date -Is)"

if [[ ! -f "$ROOT/scripts/preflight.conf" ]]; then
  printf '%sNo scripts/preflight.conf found.%s Copy preflight.conf.example and edit it.\n' "$C_BAD" "$C_OFF"
  exit 2
fi

# shellcheck source=preflight.conf
source "$ROOT/scripts/preflight.conf"

summary
