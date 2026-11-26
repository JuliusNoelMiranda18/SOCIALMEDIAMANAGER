# Session Handoff — start here in a new conversation

Written 2026-11-26 at the end of the first long session (Stages 0–3). The vault is the source of truth; this note is the short version so a fresh session does not need the old chat.

## Where things stand
| Stage | Status | Report |
|---|---|---|
| 0 Foundation | APPROVED | [[Stage 0]] |
| 1 Fake platform | APPROVED | [[Stage 1]] |
| 2 Data + content | APPROVED | [[Stage 2]] |
| 3 Adapters + idempotency | **AWAITING_APPROVAL** (tester PASS on loop 3/3) | [[Stage 3]] |
| 4 Durable scheduler + worker | NOT_STARTED | — |

- Git: everything through Stage 3 is committed and pushed (`15f0be7` on `main`, remote `JuliusNoelMiranda18/SOCIALMEDIAMANAGER`, public).
- Uncommitted: agent model/testing-budget edits in `.claude/agents/*.md`, this note, the [[00 Home]] link to it. `.claude/settings.json` (Opus default) is local and gitignored.
- Open issues: none. Dead ends: none.

## How to start Stage 4 in the new session
1. Open a new Claude Code conversation in `/Users/jouleused/Desktop/SOCIALMEDIAMANAGER` (it should run on **Opus**; `.claude/settings.json` sets it, or pick it in the model menu).
2. The user did the [[Stage 3]] manual test on 2026-11-26.
3. Type `/approve 3`. That marks Stage 3 approved and runs Stage 4 to its gate.

## Read before planning Stage 4 (Senior Dev)
- `CLAUDE.md`, `.claude/agents/senior-dev.md` (protocol), Stage 4 in `PLAN.md`.
- [[ADR-002 Publish flow]]: Stage 4 moves `publish_campaign` into the jobs worker **unchanged**; the synchronous `POST /campaigns/{id}/publish` was a Stage 3 stopgap.
- [[Publishing Service]], [[Data Model]] (`jobs` table already exists from Stage 2: `kind, payload, run_at, status, attempts, locked_until`), [[Fake Platform]], [[System Map]].
- Stage 3 limitations Stage 4 should remove (from [[Stage 3]]): publishing blocks the HTTP request; no claim/lease (concurrent publishes are safe only via conditional writes + idempotency key); an entry that used its 5 attempts stays `failed` with no "retry later".

## Lessons from Stages 0–3 (follow these)
- **Check the handoff write landed before dispatching** (`head -1 "vault/Handoffs/Current Handoff.md"`). In Stage 1 a failed write sent backend-dev to a stale handoff.
- **Testing budget:** keep tester prompts within the "Testing budget" in `.claude/agents/tester.md`. No "run twice", no huge stress runs; fix iterations re-check only the fixed issues + quick regression. The long tester runs (25–37 min) came mostly from over-asking.
- **Models:** Senior Dev = Opus (main session), backend/tester/frontend = Sonnet (set in agent frontmatter).
- **Environment:** host Python is 3.9 with no ruff, so all Python runs in containers. The image copies code at build time: run `make up` (rebuild) before `make test` / `make lint`. First run on a new machine: `make env && make up`.
- **Concurrency pattern:** status writes on `social_post_entries` are conditional SQL updates (acceptance always wins, failure only when `platform_post_id IS NULL`, a late write can't undo `failed`). Keep that invariant when the worker takes over.
- After a DB reset, old files in `./media` can collide with new campaign ids.
- A new session is much cheaper than continuing a long one; the vault carries all state.

## Probes that must stay green (regression)
`make probe` (Stage 1), `make probe5` (Stage 2), `make probe1 probe2 probe6` (Stage 3), `make lint`, `make test`. Tester scripts: `scripts/probes/stage2_tester.sh`, `stage3_tester.py`, `stage3_bad_2xx.py`, `stage3_concurrency_stress.py` (run small, e.g. `0.5 8 10 3`).

## Parked items (not Stage 4 scope unless the user asks)
- Fake blog + real post images + `GET /posts/{id}` — see Follow-ups in [[Stage 2]].
- `.DS_Store` and `SOCIAL-MEDIA-VAULT/.obsidian/workspace.json` were committed in `cc69f98`; could be untracked and gitignored.
- `CLAUDE.md` and `.claude/` are in `.gitignore` but still tracked; untracking needs `git rm --cached -r CLAUDE.md .claude` (user has not decided).
- `SOCIAL-MEDIA-VAULT/` at the repo root is a separate test Obsidian vault, not the project vault.
- `pyyaml` dev dependency is unused.

Links: [[00 Home]] · [[Current Handoff]] · [[_Stages Index]]
