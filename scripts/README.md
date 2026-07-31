# scripts/

Every multi-step operation lives here as a script rather than as a paragraph
in CLAUDE.md. Scripts are discoverable by listing this directory, they are
self-documenting, and when the environment changes underneath them they fail
loudly instead of quietly misleading the next session.

Rule of thumb: the second time you explain a sequence of commands to a Claude
Code session, stop and write it down here instead.

| Script | Purpose |
|--------|---------|
| `preflight.sh` | Session-start verification. Run first, always. |
| `check.sh` | Server compiles, image builds, container serves `/health`. Pass before pushing to main. |
| `deploy.sh` | Pull the freshly built image on the production host and recreate the container. |
| `logs.sh` | Tail the production container's logs. |

`preflight.conf` is **committed** (not gitignored): a worktree that gets
`preflight.sh` without it has a script and no definition of "healthy". It holds
only generic defaults, so it is safe on a public repo. Your real hosts go in
`~/.config/adsb-volume/preflight.local.conf`, outside the repo, which
`preflight.sh` (and `deploy.sh` / `logs.sh`) source after it. It lives outside the
repo rather than being gitignored so that every git worktree finds it; a gitignored
file is absent from a fresh worktree checkout.
