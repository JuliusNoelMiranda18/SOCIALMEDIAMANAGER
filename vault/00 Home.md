# 🏠 Home — Social Campaign Publisher

## State
<!-- Agents: this block is the single source of truth. Edit values only. -->
```state
current_stage: 2
status: AWAITING_APPROVAL   # NOT_STARTED | IN_PROGRESS | AWAITING_APPROVAL | APPROVED | BLOCKED
loop_iteration: 2
last_updated: 2026-11-24
```

| Stage | Status | Report |
|---|---|---|
| 0 Foundation | APPROVED | [[Stage 0]] |
| 1 Fake platform | APPROVED | [[Stage 1]] |
| 2 Data + content | AWAITING_APPROVAL | [[Stage 2]] |
| 3 Adapters + idempotency | NOT_STARTED | [[Stage 3]] |
| 4 Durable scheduler | NOT_STARTED | [[Stage 4]] |
| 5 Signed webhook | NOT_STARTED | [[Stage 5]] |
| 6 Dashboard | NOT_STARTED | [[Stage 6]] |
| 7 AI quality layer | NOT_STARTED | [[Stage 7]] |
| 8 Submission | NOT_STARTED | [[Stage 8]] |

## Map
- Architecture: [[System Map]] · [[API]]
- Modules: [[Api Layer]] · [[Fake Platform]] · [[Data Model]] · [[Image Pipeline]] · [[Caption Composer]]
- Live work: [[Current Handoff]]
- Stages: [[_Stages Index]]
- Issues: [[_Issues Index]] · Dead ends (approaches that failed): [[_Dead Ends Index]]
- Decisions: [[ADR-001 Stack]]

## Linking rules (keeps the Obsidian graph connected)
- Every new note links to at least one existing note, and the matching index links back to it.
- Issue → its [[_Issues Index]] row, its Stage note and its module note.
- Stage report → its issues, the modules it changed, and [[_Stages Index]].
- Module note → [[System Map]] and the modules it depends on / is used by.
- Templates live in `Templates/` and are hidden from the graph; their `[[<placeholders>]]` are not real links.

## Reading order for agents
1. This note → 2. [[Current Handoff]] → 3. [[System Map]] → 4. module notes in scope → 5. open Issues + Dead-Ends in the area. Then open only the source files those notes name.
