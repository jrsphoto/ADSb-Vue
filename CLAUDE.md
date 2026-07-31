# PROJECT_NAME

<!--
RULES FOR THIS FILE (delete this comment once you internalize them):

1. Keep it under ~150 lines. Adherence drops as it grows.
2. Only write what CANNOT be derived from the repo. No directory listings,
   no dependency lists, no architecture prose. Claude can read the code.
3. Write commands and constraints, not description.
   BAD:  "The daemon is managed by systemd as a user service."
   GOOD: "Restart with: ssh HOST 'systemctl --user restart SERVICE'. Never kill -9."
4. Anything volatile (what we're working on now) goes in STATUS.md, not here.
5. Wrong information is worse than missing information. Prune aggressively.
   Run /doctor periodically; it will propose trims.
-->

## Session start

Run `./scripts/preflight.sh` before doing anything else. It verifies host
reachability, service health, and toolchain. Its output is ground truth;
this file is only a claim. If preflight fails, fix that before writing code.

Then read `STATUS.md` for where the last session left off.

## What this project is

<!-- Two sentences. What it does and what it runs on. Nothing more. -->

TODO: one-line purpose. Runs on TODO_HOST as TODO_SERVICE.

## Hosts and access

<!-- List only what you actually need. SSH keys are already configured;
     say so explicitly or a fresh session will ask permission it doesn't need. -->

SSH key auth is configured and working for all hosts below. No passwords,
no sudo prompts. Do not ask whether you have access; run preflight to confirm.

| Host | Address | Role |
|------|---------|------|
| TODO | TODO    | TODO |

## Operational invariants

<!-- The rules that, if broken, cost you real time or break production.
     These are the highest-value lines in the file. -->

- `main` is deployed. Never push to `main` anything that has not built and
  passed `./scripts/check.sh` locally.
- TODO: add project-specific invariants (hardware in use, ports that must
  stay free, files that must not be regenerated, etc.)

## Commands

<!-- Every multi-step operation should be a script, not a paragraph.
     If you catch yourself explaining a sequence, write a script instead. -->

| Task | Command |
|------|---------|
| Preflight / health check | `./scripts/preflight.sh` |
| Build + lint + test | `./scripts/check.sh` |
| Deploy | `./scripts/deploy.sh` |
| Tail production logs | `./scripts/logs.sh` |

## Conventions that differ from the defaults

<!-- Only list where this project diverges from what a competent person
     would assume. Do not restate the obvious. -->

- TODO: e.g. "clippy runs with -D warnings in CI; treat warnings as errors."
- TODO: e.g. "Config lives in TOML, not env vars. Do not add dotenv."

## Workflow

Small, understood changes: commit directly to `main`.
Anything multi-session, risky, or touching the deployed path: branch first
(`feat/...`, `fix/...`), commit at meaningful checkpoints so there are clean
reset targets, then open a PR for review before merging.

Before ending a session, update `STATUS.md`. If something in this file turned
out to be wrong or missing, fix it now rather than next time.
