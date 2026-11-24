---
description: Run one full loop-engineering stage (plan → build → test → fix → gate), then pause for approval
argument-hint: <stage number>
---

Run Stage $ARGUMENTS of PLAN.md as the Senior Dev, following CLAUDE.md and .claude/agents/senior-dev.md.

1. Read the `state` block in `vault/00 Home.md`.
   - If $ARGUMENTS > 0 and Stage $ARGUMENTS-1 is not `APPROVED`, stop. Tell me which stage still needs `/approve`.
   - If any stage is `AWAITING_APPROVAL`, stop and remind me.
2. Otherwise run the full loop for Stage $ARGUMENTS without pausing:
   plan → backend-dev → frontend-dev (only if there are UI tasks) → tester → fix loops (max 3) → review → gate report.
3. Finish by setting `status: AWAITING_APPROVAL`, then give me the gate summary and my manual test steps. Stop there.
