# ADR-001 Stack

**Status:** accepted · 2026-11-24

**Decision:** Python 3.12 + FastAPI + Pydantic v2, PostgreSQL 16 with SQLAlchemy 2 + Alembic, a Postgres jobs table claimed with `FOR UPDATE SKIP LOCKED` as the durable queue, a separate FastAPI app as the fake platform, Pillow for images, AES-GCM (`cryptography`) for tokens, Vite + React + TS for the dashboard, pytest + ruff + Playwright, Docker Compose.

**Why:**
- Python/SQL/Docker fill the gaps on the owner's CV.
- A Postgres-backed queue is durable by construction and needs one less service than Redis/BullMQ (ponytail: fewer moving parts). Lease expiry gives crash recovery.
- A separate fake platform process makes timeouts, 429s and callbacks real network behaviour.

**Rejected:** Redis + RQ/BullMQ (extra service, and durability needs extra config); APScheduler (job store semantics are harder to prove for crash-resume).

**Revisit if:** throughput needs exceed one Postgres worker pool — not expected in scope.

**Shapes:** [[System Map]] · [[Data Model]] · [[Fake Platform]] · [[Api Layer]]
