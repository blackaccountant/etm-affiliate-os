# PR1D11 Metrics, Monitoring, and Alerting Contract

PR1D11 adds a small process-local metrics contract for the frozen one-process,
one-Uvicorn-worker production topology. It does not select a monitoring
platform, dashboard, alert destination, alert sender, or shared metrics store.

## Metrics contract

`GET /metrics` emits Prometheus-compatible text. It has SERVICE authority only:
anonymous and operator credentials are denied. Caddy returns `404` for public
`/metrics` requests before they reach Uvicorn. A host-local monitor may scrape
`127.0.0.1:8000/metrics` using the service bearer credential.

The exact metric vocabulary is:

- `etm_process_start_time_seconds` gauge: process-local Unix start timestamp.
- `etm_process_uptime_seconds` gauge: nonnegative monotonic uptime.
- `etm_retry_manager_running` gauge: exactly `0` or `1` from existing runtime state.
- `etm_http_requests_total` counter.
- `etm_http_request_duration_seconds_count` counter.
- `etm_http_request_duration_seconds_sum` cumulative seconds.

HTTP metric labels are exactly `method`, `route`, and `status_class`. Methods
are `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `HEAD`, `OPTIONS`, or `OTHER`.
Routes are registered templates only; unresolved routes are `unmatched`.
Status classes are `1xx`, `2xx`, `3xx`, `4xx`, `5xx`, or `other`.

No metric may include request IDs, credentials, cookies, session or CSRF values,
emails, recipients, content, raw URLs, query strings, exception text,
tracebacks, user/lead/content/campaign/program IDs, database identifiers, SQL,
provider payloads, IP addresses, or arbitrary input. `/metrics` is excluded
from HTTP request metrics; PR1D10 request-completion logging remains separate
and continues to log that request normally.

## Health and data boundaries

Metrics scraping has no database, provider, network, file-I/O, or business-state
operation. `/health` remains process liveness only. `/ready` remains the
PostgreSQL availability signal and performs its existing `SELECT 1` probe.
PR1D11 exposes no business or provider metrics.

## Alert policy and ownership

`CRITICAL`: sustained public liveness failure, sustained readiness failure, or
retry manager stopped after expected startup. `WARNING`: elevated HTTP 5xx rate,
metrics scrape failure, or a future approved bounded repeated-retry signal.
These severities are distinct from PR1D9 DR-0 through DR-3.

Alert destination, monitoring platform, scrape cadence, dashboards, retention,
and numeric thresholds are all `DEPLOYMENT_DECISION_REQUIRED`. No alert delivery
daemon is implemented. The host or external monitor owns Caddy and systemd
health, DNS, TLS/certificate expiry, host CPU/memory/disk, journald, PostgreSQL
host health, and public HTTPS reachability.

Repository tests do not prove Linux/Caddy behavior, host-local or external
scrapes, dashboards, alert routing or delivery, threshold effectiveness,
production traffic cardinality, or resource impact under load. Those require
authorized live-host validation.
