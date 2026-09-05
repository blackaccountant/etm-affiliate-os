# PR1D10 Production Logging Contract

This is the authoritative PR1D10 production logging contract. It hardens
application process logging only. It does not select a monitoring platform,
define alert policy, add Caddy access logging, or change API response handling.
Monitoring and alert policy belong to PR1D11. The production topology and normal
service operations remain governed by docs/DEPLOYMENT.md.

## Output and ownership

Application logs use Python standard-library logging and one process stdout
handler. Launcher validation errors may use process stderr. Under production
systemd, these process streams are expected to be collected by journald. The
application creates no log files and owns no rotation, retention, export, archive
or deletion policy. The deployment/host owner controls journald retention, log
access, export/archive and deletion. No external logging or monitoring platform
is selected by PR1D10. Caddy access logging is not added by PR1D10.

Repository qualification does not prove Linux journald collection, retention or
access policy. These require live host validation by the deployment/host owner.

## Record contract

The PR1D10 application formatter emits plain text with stable timestamp, severity,
logger/component name, request_id and message/event fields. Fixed INFO is the
root and application handler level. No LOG_LEVEL setting is introduced. The
sqlalchemy.engine logger remains WARNING; production SQL echo remains disabled.

Every application record formatted by this handler includes request_id. Background
or non-request work uses the exact sentinel request_id=-. No separate trace ID,
client address, raw URL, raw path parameter, query string, request header, cookie,
request body, host, referrer or user agent is added as logging metadata.

## Request correlation and completion

For every HTTP application request, middleware generates a server-side lowercase
UUID hex request ID of exactly 32 hexadecimal characters before downstream work.
It ignores inbound X-Request-ID and X-Correlation-ID, including valid-looking,
oversized, control-character or newline-bearing values. It returns the generated
value in X-Request-ID for application responses and resets request context after
completion, including exception paths.

Uvicorn access logging is explicitly disabled by the frozen launcher. The
application instead emits one request_completed record for normal and handled-error
responses. It contains method, resolved application route template when available
(otherwise route=-), status and formatter-provided request_id. It never uses the
raw inbound path or other request data named above. Logging failure must not fail a
request or suppress its original exception.

## Redaction and exceptions

The exact replacement token is [REDACTED]. Central logging redaction is
deterministic and idempotent. It sanitizes strings, supported primitive values,
dict/list/tuple/set containers, %-format arguments, preformatted messages,
exception text and rendered traceback text without mutating caller-owned
containers. It does not introspect arbitrary request, provider or database
objects; those objects must not be logged.

Never log Authorization/Bearer credentials, OPERATOR_API_TOKEN, SERVICE_API_TOKEN,
provider API keys/secrets/tokens, password/passwd values, session/CSRF tokens,
Cookie/Set-Cookie values, DATABASE_URL credentials, PostgreSQL or other URLs with
userinfo, token-bearing URL query values, request bodies, outreach recipients or
email addresses, message bodies/content, affiliate/provider secrets, or raw
environment values. Redaction recognizes sensitive mapped keys and common URL,
header and Bearer forms. It is a defense for known forms, not permission to log
unbounded arbitrary values.
Do not recover production secrets from Git.

Exception logs preserve exception class/traceback structure only after final
formatter redaction. Do not assume str(exc) is safe or interpolate it into event
messages. The existing API endpoints that return str(exc) are observed security
debt outside PR1D10; this logging contract does not alter their HTTP responses.

## Validation boundary

Repository tests are Windows-safe and perform no database, network, provider,
DNS, systemd, Caddy, migration or production-host filesystem operation. Deferred
live validation includes journald stream collection, retention/access/export
policy, systemd/Uvicorn interaction and safe production incident diagnostics.
