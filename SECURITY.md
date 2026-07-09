# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.9.x   | Yes |
| < 1.9   | Best effort |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do not** open a public GitHub issue
2. Email: 3508137206@qq.com
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact

You should receive a response within 48 hours. We will work with you to understand and address the issue before any public disclosure.

## Security Measures

### Local API authentication

- **Source / uvicorn startup**: if `ALPHASCOPE_LOCAL_API_TOKEN` is unset, the backend **auto-generates** a token, persists it under `data/runtime/local_api_token.txt`, and writes `apps/web/public/runtime-config.js` so the Vite frontend can send `X-AlphaScope-Local-Token`.
- **Packaged desktop**: `launcher.py` always generates a per-run token and injects it into runtime config.
- **Sensitive GET** paths (conversations, credentials, audit, settings providers, research memory) require the token even for GET.
- **Opt-out (dev/test only)**: set `ALPHASCOPE_ALLOW_OPEN_API=1` to disable token checks. Never use this on a non-localhost exposure.
- **CORS**: defaults to localhost regex; `ALPHASCOPE_ALLOW_ALL_CORS=1` is discouraged.

### Credentials

- Provider API keys encrypted at rest with **AES-GCM** (`cryptography` + `AI_FINANCE_MASTER_KEY`).
- **XOR encryption is not allowed for new keys** unless `AI_FINANCE_ALLOW_DEV_KEY_FALLBACK=1` (local dev only). Decrypt still accepts legacy `xor:` blobs.
- Keys are not injected into `os.environ` for credential-store providers (table-first).

### Network / data plane

- **SSRF guard** (`backend/security/url_guard.py`) for TickFlow / URL fetch: blocks loopback, private, link-local, metadata endpoints; DNS rebinding checked via `getaddrinfo`.
- **Data lake SQL**: select-only + blocklist for DuckDB file-read functions (`read_csv*`, `read_parquet`, …).
- **Prompt injection** filters and stock-code validation on research paths.

### Compliance

- Research tool only: no live order placement, no guaranteed returns, disclaimer wrapping on agent outputs.

## Known Limitations

- Single-user local research tool: **not multi-tenant SaaS auth**.
- LLM outputs are not independently audited for financial advice compliance.
- Binding the API to `0.0.0.0` on an untrusted network remains risky even with a local token; prefer `127.0.0.1`.
