# ADSb-Vue

## Session start

Run `./scripts/preflight.sh` before anything else. It verifies the hosts, the
upstream feed, and the deployed service, and prints which worktree you are in.
Its output is ground truth; this file is only a claim. Then read `STATUS.md` for
where the last session left off.

## What this project is

A standalone 3D volumetric viewer of an ADS-B antenna's reception envelope. Two
files, no build step: a stdlib-only Python HTTP server (`server.py`) and a
self-contained Three.js page (`index.html`). Deployed on skyscanner via Docker.

## Code is authority

Read the code before trusting prose. In particular, `DETAILS.md` currently
describes the OLD chunk-ingest path; the deployed service and the `ingest-poll`
branch poll `aircraft.json` instead. When a doc and the code disagree, the code
wins.

## Hosts and access

SSH key auth is configured and non-interactive for skyscanner (`docker` group, no
sudo). Do not ask whether you have access; run preflight to confirm. Host
addresses live in `scripts/preflight.conf`.

## Operational invariants

- **Zero third-party dependencies.** `server.py` is Python 3 standard library
  only; the frontend has no build step. Never add a `pip install`, a
  `requirements.txt`, or a bundler. SQLite, gzip, and http.server are all stdlib.
- **Two git remotes, push both.** `git push` goes to Gitea (`origin`); also run
  `git push github <branch>`. Only the GitHub push builds the container image.
  Someone may edit on GitHub web, so fetch and reconcile before pushing.
- **`main` is deployed** (as `ghcr.io/jrsphoto/adsbvue:latest`). Branch anything
  multi-session or risky and commit at checkpoints; direct-to-main is fine for
  small, understood changes.
- **Config is `ADSB_*` environment variables**, read once at import. A
  hand-rolled `_load_dotenv` loads a `.env` next to `server.py`, and a real env
  var always wins over the file. Do not add python-dotenv or a config framework.
- **Docs style:** no em-dashes, no emoji icons in Markdown.

## Commands

| Task | Command |
|------|---------|
| Preflight / health check | `./scripts/preflight.sh` |
| Build image + smoke check | `./scripts/check.sh` |
| Deploy to skyscanner | `./scripts/deploy.sh` |
| Tail production logs | `./scripts/logs.sh` |

## Deploy shape

Deploy is a registry pull, not a file copy. CI builds the image on push to
GitHub; on skyscanner, `cd /opt/adsbvue && docker compose pull && docker compose
up -d`. Watchtower auto-update is DISABLED on the box (a compose label) while it
runs a branch image; when it returns to `:latest`, remove that label or it stops
auto-updating.

## Conventions that differ from the defaults

- Verify visual / WebGL changes by driving the live page and capturing the
  canvas (`window.__adsb` hooks: `freeze`, `stats`, `terrain`, `floorAt`, ...),
  not with screenshot tooling, which stalls on the continuously-animating canvas.
- A local `python3 server.py` binds a socket and does LAN egress, so the sandbox
  SIGSTKFLT-kills it unless it is launched with `dangerouslyDisableSandbox`.
  Always kill a dev server you started in the same session.

## Workflow

Small, understood changes: commit to `main`. Risky or multi-session, or touching
the deployed path: branch first (`feat/...`, `fix/...`), then push both remotes.
Update `STATUS.md` before ending a session, and fix anything in this file that
turned out wrong rather than leaving it for next time.
