---
description: Write the session handoff before context runs out
---

Update `STATUS.md` to reflect the current state of this session. Overwrite the
existing content rather than appending; this file is a snapshot, not a log.

Fill in every section:
- Current objective, in one paragraph.
- State: branch, working tree, deployed version.
- What actually got done this session.
- The next concrete step, phrased as an action someone could start on cold.
- Tried and rejected: any approach we abandoned, why, and what the evidence
  was. This is the most valuable section. Be specific enough that a fresh
  session will not repeat the dead end.
- Open questions and blockers.

Then review `CLAUDE.md`. If anything in it turned out to be wrong, stale, or
missing during this session, fix it now. If you needed a fact that was not
written down anywhere, add it. If a sequence of commands came up twice, propose
a script in `scripts/` instead of a prose description.

Finally, tell me whether the working tree should be committed before I close.
