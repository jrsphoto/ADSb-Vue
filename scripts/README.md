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
| `check.sh` | Everything CI runs. Must pass before pushing to main. |
| `deploy.sh` | Ship main to the production host and restart the service. |
| `logs.sh` | Tail production logs. |

`preflight.conf` is gitignored if it contains anything host-specific you would
rather not publish; otherwise commit it, since a shared definition of "healthy"
is worth more than the mild disclosure of internal IPs on a private Gitea.
