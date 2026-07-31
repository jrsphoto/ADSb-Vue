# Runbook

Operational procedures for when something is broken at an inconvenient hour.
This is for humans and for Claude equally; keep it factual and imperative.

## Service will not start

1. `./scripts/preflight.sh` to isolate whether it is host, network, or app.
2. `./scripts/logs.sh 200`
3. TODO: the three failure modes you have actually seen, and their fixes.

## Roll back

    git checkout <last-good-tag>
    ./scripts/deploy.sh

Deploy tags are created automatically by `deploy.sh` as `deployed-YYYYMMDD-HHMM`.

## Known failure modes

TODO: Each entry should be symptom, cause, fix. Add one every time you debug
something twice.
