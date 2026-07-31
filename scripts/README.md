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

`preflight.conf` is **committed** here (not gitignored): a worktree that gets
`preflight.sh` without it has a script and no definition of "healthy". It defines
the host variables `deploy.sh` and `logs.sh` also read. Note the host names in it
are private (RFC1918 / `.lan`, not internet-reachable), but committing it does
publish them if this branch reaches public GitHub.
