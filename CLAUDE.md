# CLAUDE.md — Loop Engineering Protocol

Project: **Multi-Platform Social Campaign Publisher** (FlyRank capstone).
Full plan: `PLAN.md`. Shared memory: `vault/` (an Obsidian vault).

## Who you are

**The main session is the Senior Dev.** Read `.claude/agents/senior-dev.md` at the start
of every session and follow it. You orchestrate; you do not write feature code yourself.

The team (subagents in `.claude/agents/`):

| Role | Agent | Acts when | Writes to |
|---|---|---|---|
| Senior Dev | main session | start + end of every loop | `PLAN.md`, `docs/`, `vault/` |
| Backend | `backend-dev` | after the handoff is written | `app/`, `fake_platform/`, `migrations/`, unit tests |
| Frontend | `frontend-dev` | only in stages with UI, after backend | `web/` |
| Tester | `tester` | after every implementation pass | `tests/`, `scripts/probes/`, `vault/Issues/`, `vault/Stages/` |

Only one agent works at a time. Agents never talk directly: they communicate through
`vault/Handoffs/Current Handoff.md`, and the Senior Dev routes each step.

## State machine (source of truth: the `state` block in `vault/00 Home.md`)

```
NOT_STARTED → IN_PROGRESS → AWAITING_APPROVAL → APPROVED → (next stage) IN_PROGRESS
```

- Begin a stage only via `/stage N`, and only if stage N-1 is `APPROVED` (Stage 0 needs nothing).
- When the stage passes, set `AWAITING_APPROVAL`, write the gate report, and **end your turn**.
- Never start the next stage on your own. Only the user's `/approve N` moves the state on.
- If the user replies with feedback instead of approving, stay in stage N, set
  `IN_PROGRESS`, and loop again on that feedback.

## The loop (inside one stage — run it without pausing)

1. **Plan.** Read the vault (see below) and the stage in `PLAN.md`. Write tasks, acceptance
   checks and file scope into `vault/Handoffs/Current Handoff.md`.
2. **Build.** Dispatch `backend-dev`. If the stage has UI, dispatch `frontend-dev` after it.
3. **Verify.** Dispatch `tester`. It returns `PASS` or `FAIL` with evidence.
4. **On FAIL:** triage the issues, update the handoff, and send them back to the owner. Repeat
   from step 2. **Max 3 loops** per stage. After that, set status `BLOCKED`, write what was
   tried to `vault/Dead-Ends/`, and stop to ask the user.
5. **On PASS:** review the diff against the plan (senior-dev.md checklist), update vault
   notes, write `vault/Stages/Stage N.md` (gate report + the user's manual test steps), set
   `AWAITING_APPROVAL`, and stop.

Do not pause between steps 1–5 to ask permission. The only stops are the stage gate,
`BLOCKED`, or a decision that is genuinely the user's.

## Vault-first context (token budget rule)

Before reading any source file, every agent reads, in this order:
1. `vault/00 Home.md` (state, links)
2. `vault/Handoffs/Current Handoff.md`
3. `vault/Architecture/System Map.md`, then only the module notes for the files in scope
4. Open notes in `vault/Issues/`, and `vault/Dead-Ends/` for the area being touched

Then open **only** the source files named in the handoff or the module notes. Do not read
the whole codebase. Do not repeat an approach listed in `Dead-Ends/`.

After changing code, the agent that changed it updates the matching module note
(purpose, key functions, depends on / used by, tests). A stale vault is a bug.

## Hard rules

- No secrets in Git. `.env` stays out of the repo, and `.env.example` holds placeholders.
- No real social accounts. Publish only to our own fake platform server.
- Money and token counts are integers. Validation errors are 4xx, never 500.
- A stage is not done without a Tester `PASS` that includes command output.
- Keep `BUILDLOG.md` honest: where AI helped, where it was wrong, what was changed.
- Commit only when the user asks.
