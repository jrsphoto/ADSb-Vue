#!/usr/bin/env bash
# Everything CI will run, run locally. If this passes, main stays deployable.
# Keep this file and the CI workflow in lockstep; drift between them is the
# usual reason "it passed locally" stops meaning anything.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

step "format";  cargo fmt --check
step "lint";    cargo clippy --all-targets -- -D warnings
step "test";    cargo test --all
step "build";   cargo build --release

printf '\n\033[32mall checks passed\033[0m\n'
