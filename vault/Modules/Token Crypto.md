# Token Crypto

**Purpose:** AES-GCM encryption of platform access tokens at rest, key validation at api start, and the token store that fetches, encrypts and refreshes tokens.
**Files:** `app/crypto.py`, `app/publishers/tokens.py`, `app/repos/tokens.py`, `app/main.py` (startup check), `scripts/make_env.py` (`make env`)
**Last changed:** Stage 3 iteration 2, 2026-11-26

## Key functions / classes
| Name | Signature | What it does |
|---|---|---|
| `load_key` | `(b64) -> bytes` | base64 of exactly 32 bytes, else `ValueError` naming `make env` |
| `encrypt` | `(key, plaintext, aad) -> (nonce, ciphertext)` | fresh 12-byte `os.urandom` nonce per call; AAD = platform |
| `decrypt` | `(key, nonce, ciphertext, aad) -> str` | `InvalidTag` on any tamper, wrong key or wrong AAD; `ValueError` on a wrong-length nonce |
| `get_token` | `(client, platform, *, refresh=False) -> str` | decrypt stored row; if missing, undecryptable (`InvalidTag`, `ValueError`, `TypeError`), or `refresh`, POST `/oauth/token` (`FAKE_CLIENT_ID/SECRET`), encrypt, upsert, commit. A 2xx without a string `access_token` (or non-JSON) raises `BadTokenResponse` |
| `repos.tokens.get/upsert` | `(session, platform, ...)` | upsert is `INSERT ... ON CONFLICT (platform) DO UPDATE` (no read-then-write) |
| startup check | `app/main.py` import | bad key → `SystemExit("api refuses to start: ...")` |

## Connections
- Depends on: [[Data Model]] (`platform_tokens`), `cryptography`, [[Fake Platform]] `/oauth/token`
- Used by: [[Publisher Adapters]] · map: [[System Map]]

## Invariants
- Key is validated when the **api** starts, not in `Settings` (the fake platform imports `Settings` too).
- Plaintext tokens never reach the DB or the logs (`probe6_tokens.sh`, `test_token_never_logged`).
- `make env` never replaces a valid key (that would orphan stored tokens); it only fills an empty or invalid one.

## Tests
- `tests/unit/test_crypto.py` — round trip, nonce/ciphertext differ for the same token, tampered nonce/ciphertext/AAD/key fail, bad keys rejected, `import app.main` exits with the message
- `tests/unit/test_publishers.py::test_401_refreshes_token_once` — refreshed token replaces the stored row
- `tests/unit/test_publishers.py::test_undecryptable_token_row_fetches_fresh_token` — 4-byte nonce, zeroed nonce, short ciphertext, wrong AAD → fresh token, one row ([[ISSUE-006 short nonce in platform_tokens returns 500]])
- `tests/unit/test_publishers.py::test_bad_token_response_is_retryable` — `{}`, non-JSON, null token, list ([[ISSUE-007 2xx without id or bad token body returns 500]])
- `scripts/probes/probe6_tokens.sh` (`make probe6`) — pg_dump + api/worker logs contain no issued token

## Gotchas
- If the key changes, stored rows fail with `InvalidTag` and `get_token` silently fetches a fresh token. A wrong-length nonce raises `ValueError` before the tag check, so it is caught too (ISSUE-006).
- Tests set a fixed test key in `tests/conftest.py`.
