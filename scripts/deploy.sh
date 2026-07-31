#!/usr/bin/env bash
# Deploy = pull the freshly built image on the production host and recreate the
# container. The image itself is built by CI on push to GitHub (see CLAUDE.md);
# this does NOT copy local files, so what ships is whatever CI last built for the
# tag the host's compose references. Host vars come from scripts/preflight.conf.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source scripts/preflight.conf
LOCAL_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/adsb-volume/preflight.local.conf"
[[ -f "$LOCAL_CONF" ]] && source "$LOCAL_CONF"

: "${TARGET:?set TARGET in ~/.config/adsb-volume/preflight.local.conf}"
[[ "$TARGET" == "user@feeder.example" ]] && { echo "TARGET is still the placeholder; set it in $LOCAL_CONF"; exit 1; }
: "${REMOTE_DIR:=/opt/adsbvue}"
: "${CONTAINER:=adsbvue}"

echo "deploying on $TARGET ($REMOTE_DIR): docker compose pull && up -d"
ssh "$TARGET" "cd '$REMOTE_DIR' && docker compose pull && docker compose up -d"

echo "waiting for the container to come healthy..."
state="?"
for _ in $(seq 1 20); do
  state=$(ssh "$TARGET" "docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' '$CONTAINER'" 2>/dev/null) || state="unreachable"
  echo "  $state"
  [[ "$state" == "healthy" || "$state" == "running" ]] && break
  sleep 3
done
[[ "$state" == "healthy" || "$state" == "running" ]] || { echo "container is '$state'"; exit 1; }
echo "deployed. Verify the served page if the change was user-facing:"
echo "  curl -s $WEB_URL/ | grep -c fetchCone   # or whatever the change added"
