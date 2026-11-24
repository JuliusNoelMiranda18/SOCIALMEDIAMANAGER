# SETUP — loop engineering kit

## 1. Prerequisites
- Claude Code (desktop app or `claude` CLI)
- Docker Desktop, Python 3.12, Node 20+, Git
- Obsidian (free): https://obsidian.md
- Skills enabled in Claude Code: `ponytail`, `ui-ux-pro-max`, `impeccable`, `emil-design-eng`

## 2. Create the repo
1. Create a **public** GitHub repo `flyrank-capstone-social-publisher` (the brief requires public from day one).
2. Clone it, then copy everything from this kit into the repo root:
   ```
   CLAUDE.md  PLAN.md  SETUP.md  .claude/  vault/
   ```
3. Add a `.gitignore` containing at least `.env`, `.venv/`, `node_modules/`, `vault/.obsidian/workspace*`.

## 3. Open the vault in Obsidian
Obsidian → "Open folder as vault" → choose `<repo>/vault`. Start at `00 Home`.
Settings → Files & links → Default location for new notes: "Same folder as current file". Turn on the Graph view to see how modules connect.

## 4. Open the repo in Claude Code
Open the repo folder as the session's project. Claude Code loads `CLAUDE.md`, the four agents in `.claude/agents/`, and the `/stage` and `/approve` commands automatically.
To check, type `/agents`. You should see `senior-dev`, `backend-dev`, `frontend-dev` and `tester`.

## 5. Run it
| You type | What happens |
|---|---|
| `/stage 0` | Senior Dev plans → Backend builds → Tester verifies → fix loops → gate report. It stops at `AWAITING_APPROVAL`. |
| (you test) | Follow "Your manual test" in `vault/Stages/Stage 0.md` |
| `/approve 0` | Marks Stage 0 approved and runs Stage 1 to its gate |
| feedback text | Stays in the current stage and loops on your feedback |

If a stage hits 3 failed loops, it stops as `BLOCKED` and asks you.

## 6. Tips
- Commit after each approved stage yourself, or ask Claude to. The agents never commit on their own.
- Use a stronger model for the main session (Senior Dev). Subagents inherit it; set `model:` in an agent file to change that.
- If context gets long, start a new session. The vault holds the state, so nothing is lost.
