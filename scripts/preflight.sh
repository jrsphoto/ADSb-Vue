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

# The committed conf holds generic defaults and the run_checks function. Real
# host addresses come from a per-machine override OUTSIDE the repo, so every git
# worktree finds it (an in-repo gitignored file would be absent from a fresh
# worktree checkout). Sourced AFTER the committed conf, so its values win.
# shellcheck source=preflight.conf
source "$ROOT/scripts/preflight.conf"

LOCAL_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/adsb-volume/preflight.local.conf"
if [[ -f "$LOCAL_CONF" ]]; then
  # shellcheck disable=SC1090
  source "$LOCAL_CONF"
else
  note "no per-machine override ($LOCAL_CONF); using generic defaults."
fi

if ! declare -f run_checks >/dev/null; then
  printf '%spreflight.conf did not define run_checks.%s\n' "$C_BAD" "$C_OFF"
  exit 2
fi
run_checks

summary
