# PR1D12 Inbound Request Protection

PR1D12 applies bounded request-rate protection in the frozen one-process, one-Uvicorn-worker topology. It is a process-local token-bucket limiter: counters reset on restart and there is no cross-worker, cross-host, Redis, or distributed enforcement guarantee.

## Trust and privacy

The limiter uses only post-Uvicorn `request.client.host`. Application code does not parse `X-Forwarded-For`, `Forwarded`, `X-Real-IP`, or other proxy headers. Valid IPv4/IPv6 addresses are canonicalized transiently and converted to a keyed, process-local BLAKE2 fingerprint. Raw IPs, fingerprints, credentials, cookies, session IDs, query strings, and route values are not retained in limiter keys, logged, exposed, or persisted. Missing or malformed client values share `unknown`.

Repository tests do not prove live Caddy/Uvicorn forwarded-client behavior, NAT/proxy-chain handling, or loopback edge isolation; those require approved host validation.

## Policies

All values are **PROVISIONAL** and require live traffic, false-positive, memory, and load validation before production cutover.

| Protection class | Sustained rate | Burst |
| --- | ---: | ---: |
| PUBLIC | 60/min | 20 |
| DUAL | 120/min | 30 |
| OPERATOR | 120/min | 30 |
| SERVICE | 240/min | 60 |
| OPERATOR_CONSOLE | 240/min | 60 |
| HEALTH | 30/min | 10 |
| READY | 30/min | 10 |
| METRICS | 30/min | 5 |
| PREFLIGHT | 60/min | 20 |
| UNKNOWN | 30/min | 10 |

Every inbound category receives one fixed policy; no endpoint is unlimited. `/health`, `/ready`, `/metrics`, mounted operator-console traffic, and CORS preflight are separate classes. API routes use the existing frozen PUBLIC, DUAL, OPERATOR, and SERVICE authority vocabulary.

The limiter has at most 4096 normal identity buckets and removes up to a bounded number of oldest buckets after 600 seconds idle. Once normal capacity is full, new identities share one fixed overflow bucket per protection class. This prevents attacker-controlled map growth and active-identity churn eviction.

## Rejections and frozen interactions

Rejected requests return `429` with exactly `{"detail":"Too Many Requests"}`, a positive whole-second `Retry-After`, and `Cache-Control: no-store`. PR1D10 correlation/logging wraps the response, so it has a generated `X-Request-ID` and one hardened completion record. PR1D11 records a 429 as an existing bounded 4xx HTTP metric; no limiter metric is added. `/metrics` remains excluded from HTTP metric self-observation.

Allowed-origin preflight is also limited. A preflight 429 retains the CORS response headers needed by the frozen CORS policy. API authority never fails open: only an internal limiter bookkeeping failure fails open, without exposing details. Body, header, URL, multipart, connection, and timeout limits are deferred. Caddy is unchanged.
