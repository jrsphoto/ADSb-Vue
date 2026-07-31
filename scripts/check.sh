#!/usr/bin/env bash
# Everything CI effectively verifies, run locally: the server imports cleanly and
# the image builds and serves. If this passes, main stays deployable. Keep it in
# lockstep with .github/workflows/docker.yml (which builds the same image).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

step "python compiles (server.py)"
python3 -m py_compile server.py
echo "  ok"

step "docker image builds"
docker build -t adsbvue:check .

step "smoke: the built image serves /health"
# Host networking, matching the real deployment (network_mode: host) and avoiding
# bridge/veth setup that some sandboxed Docker hosts can't do. ADSB_WEB_PORT is
# an unlikely-to-clash port since host networking binds it on the host directly.
cid=$(docker run -d --network host -e ADSB_WEB_PORT=24599 adsbvue:check)
trap 'docker rm -f "$cid" >/dev/null 2>&1 || true' EXIT
code=000
for _ in $(seq 1 15); do
  code=$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:24599/health 2>/dev/null) || code=000
  [[ "$code" == "200" ]] && break
  sleep 1
done
if [[ "$code" != "200" ]]; then
  echo "  /health -> $code (wanted 200)"; docker logs "$cid" 2>&1 | tail -20; exit 1
fi
echo "  /health -> 200"

printf '\n\033[32mall checks passed\033[0m\n'
