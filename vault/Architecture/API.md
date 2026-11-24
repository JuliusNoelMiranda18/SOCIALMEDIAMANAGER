# API Contract

The frontend uses only what is listed here. Backend: update this in the same change as the endpoint.

| Method | Path | Purpose | Request | Response | Errors | Stage |
|---|---|---|---|---|---|---|
| GET | /health | liveness | — | `{status}` | — | 0 |

## Fake platform (port 9000)
| Method | Path | Purpose | Stage |
|---|---|---|---|
| GET | /health | liveness | 0 |
