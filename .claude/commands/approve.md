---
description: Approve a finished stage after your manual test, then start the next stage
argument-hint: <stage number>
---

I tested Stage $ARGUMENTS and approve it.

1. In `vault/00 Home.md`, confirm Stage $ARGUMENTS is `AWAITING_APPROVAL`. If it isn't, stop and tell me the current state.
2. Set Stage $ARGUMENTS to `APPROVED`. Add "Approved by user on <date>" to `vault/Stages/Stage $ARGUMENTS.md`.
3. If this was the last stage in PLAN.md, say so and stop.
4. Otherwise start Stage $ARGUMENTS+1 exactly as `/stage` would, and run it through to its gate.
