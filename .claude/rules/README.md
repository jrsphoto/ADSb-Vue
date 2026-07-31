# .claude/rules/

Path-scoped instructions. Unlike CLAUDE.md and unlike `@imports` (which load
at launch regardless), rules in here load only when Claude is working on files
matching their scope. This is where component-specific conventions belong, so
the always-loaded root file stays small.

One file per concern. Keep each one short. A rule that applies everywhere is
not a rule, it is a CLAUDE.md line.
