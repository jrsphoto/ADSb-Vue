#!/usr/bin/env bash
# Deploy to the production host. Refuses to run from a dirty tree or a branch
# other than main, because the deployed artifact must be reproducible from a
# commit hash. Override with FORCE=1 only when you know why.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source scripts/preflight.conf.example 2>/dev/null || true

: "${TARGET:?set TARGET=user@host in preflight.conf or the environment}"
: "${SERVICE:?set SERVICE=name.service}"
: "${REMOTE_DIR:=/opt/PROJECT}"

BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "${FORCE:-0}" != "1" ]]; then
  [[ "$BRANCH" == "main" ]] || { echo "refusing: on branch $BRANCH, not main"; exit 1; }
  [[ -z "$(git status --porcelain)" ]] || { echo "refusing: working tree dirty"; exit 1; }
fi

REV=$(git rev-parse --short HEAD)
echo "deploying $REV to $TARGET"

./scripts/check.sh
rsync -az --delete target/release/ "$TARGET:$REMOTE_DIR/bin/"
ssh "$TARGET" "systemctl --user restart $SERVICE"
sleep 2
ssh "$TARGET" "systemctl --user is-active $SERVICE"

git tag -f "deployed-$(date +%Y%m%d-%H%M)" "$REV"
echo "deployed $REV; tagged"
