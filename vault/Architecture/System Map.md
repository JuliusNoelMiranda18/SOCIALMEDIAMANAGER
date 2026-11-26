# System Map

How the codebase connects. Each box links to a module note; unresolved links are modules not built yet.
Agents: update this when a module is added, removed or rewired.

```mermaid
flowchart LR
  API[app/api] --> SVC[app/services]
  SVC --> REPO[app/repos]
  SVC --> CONTENT[app/content]
  SVC --> MEDIA[(MEDIA_DIR PNGs, served at /media)]
  CONTENT --> LLM[Gemini REST, optional]
  SVC --> PUBSVC[publishing service]
  PUBSVC --> PUB[SocialPublisher]
  PUB --> TOK[token store, AES-GCM]
  TOK --> REPO
  PUB --> AIG[FakeInstagram adapter]
  PUB --> AX[FakeX adapter]
  API -- enqueue job --> DB
  WORKER[app/worker: claim + lease] --> PUBSVC
  AIG --> FAKE[fake_platform]
  AX --> FAKE
  FAKE -- signed callback, built in Stage 5 --> HOOK[app/api webhook: verify, dedupe, apply]
  HOOK --> SVC
  WEB[web dashboard] --> API
  REPO --> DB[(Postgres)]
```

## Modules
| Module | Note | Stage |
|---|---|---|
| HTTP layer | [[Api Layer]] | 0+ |
| Fake platform server | [[Fake Platform]] | 1 |
| Data model + migrations | [[Data Model]] | 2 |
| Image pipeline | [[Image Pipeline]] | 2 |
| Caption composer + LLM wrapper | [[Caption Composer]] | 2, 7 |
| Publish flow + retry policy | [[Publishing Service]] | 3 |
| Publisher interface + adapters | [[Publisher Adapters]] | 3 |
| Token crypto | [[Token Crypto]] | 3 |
| Worker + scheduler | [[Worker]] | 4 |
| Webhook + status machine | [[Webhook]] (built) | 5 |
| Dashboard | [[Web]] | 6 |
| Evals | [[Evals]] | 7 |

API contract: [[API]]
