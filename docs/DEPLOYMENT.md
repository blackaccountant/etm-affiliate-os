# ETM Affiliate OS Production Deployment and Operations Runbook

This is the authoritative production deployment and operations runbook for ETM
Affiliate OS. It describes how to operate the frozen production contracts; it
does not authorize a change to them or replace host-specific change control.

## Authoritative scope

This runbook is the sole operational deployment reference for the current PR1
baseline. The service, launcher, reverse-proxy, readiness, and CI contracts
remain authoritative in their respective repository artifacts. Follow this
runbook together with the approved production change record; do not treat a
development README command as a production procedure.

## Frozen topology

```text
Internet
→ Caddy HTTPS
→ 127.0.0.1:8000
→ one Uvicorn worker
→ app.main:app
→ PostgreSQL
```

Caddy is the public HTTPS endpoint. The application is deliberately loopback
only: it is not an externally reachable Uvicorn service. The frozen launcher
starts exactly one worker for `app.main:app`, bound to `127.0.0.1:8000`.
PostgreSQL is the application data dependency, reached only through the
configured `DATABASE_URL`.

Its frozen Uvicorn contract includes `--host 127.0.0.1`, `--workers 1`,
`--proxy-headers`, and `--forwarded-allow-ips 127.0.0.1`.

## Host prerequisites

Provision a supported Linux host with systemd, a Caddy installation, a Python
runtime compatible with the repository, Git or another approved release/source
delivery method, a Python virtual environment, network reachability to
PostgreSQL, DNS control for `<PRODUCTION_DOMAIN>`, inbound TCP 80/443, a
service account, appropriate filesystem ownership/permissions, and the ability
to inspect journald. Confirm outbound network requirements for approved package
installation and certificate issuance where applicable.

The Linux distribution, package manager, Caddy installation method, service
account provisioning, filesystem ownership, and firewall commands are
`DEPLOYMENT_DECISION_REQUIRED`. Do not substitute a guessed distribution or
cloud-provider command. Windows, WSL, Docker, Hyper-V, and other
virtualization are not prerequisites for repository qualification; final Caddy,
TLS, and systemd validation occurs on the approved Linux deployment host.

## Filesystem and service layout

The approved paths are:

```text
/opt/etm-affiliate-os
/opt/etm-affiliate-os/backend
/opt/etm-affiliate-os/backend/.venv
/etc/etm-affiliate-os/etm-affiliate-os.env
/etc/etm-affiliate-os/caddy.env
```

`deployment/etm-affiliate-os.service` runs as `etm-affiliate` group
`etm-affiliate`, uses working directory `/opt/etm-affiliate-os`, loads
`/etc/etm-affiliate-os/etm-affiliate-os.env`, and executes
`/opt/etm-affiliate-os/deployment/start-production.sh`. Its contract is
`Restart=on-failure`, `RestartSec=5s`, `KillSignal=SIGTERM`,
`NoNewPrivileges=true`, and `PrivateTmp=true`.

The launcher source is `deployment/start-production.sh`; its default Python is
`/opt/etm-affiliate-os/backend/.venv/bin/python`. The Caddy sources are
`deployment/Caddyfile` and
`deployment/caddy.service.d/etm-affiliate-os.conf`.

`deployment/caddy.service.d/etm-affiliate-os.conf` separately loads
`/etc/etm-affiliate-os/caddy.env`. Caddy does not inherit the application
service environment.

## Production environment and secrets

Before starting the application service, provision these required secrets in
`/etc/etm-affiliate-os/etm-affiliate-os.env`: `DATABASE_URL`,
`OPERATOR_API_TOKEN`, and `SERVICE_API_TOKEN`. Generate operator and service
tokens independently. Production validation requires them to be distinct and
does not permit either to be short. Never put credential values in Git,
documentation, shell history, tickets, logs, or command output.

Set the non-secret application identity and mode there: `APP_NAME` and
`ENV=production`. Set `ETM_AFFILIATE_OS_DOMAIN` only in
`/etc/etm-affiliate-os/caddy.env`; it is the Caddy site address and is not an
application service setting.

Recommended production settings are `DATABASE_ECHO=false`,
`OPERATOR_SESSION_COOKIE_SECURE=true`, and CORS enabled only for a specific,
valid operator origin when needed; CORS remains application-owned.
`DATABASE_CONNECTION_TIMEOUT_SECONDS` belongs to application environment
configuration. Its frozen default is 5 seconds and its validated range is 1
through 30 seconds; it bounds database connection and pool-acquisition
behavior. Operators may override it only within that range and must not invent
a separate readiness-timeout variable. Provider and email configuration are
optional and must be explicitly approved for the deployment.

## Environment-file security

Keep both environment files outside the repository and restrict their exposure
to the approved host operators and service context. Confirm the actual host's
ownership, ACL, backup, rotation, and secret-management policy before placing
values in either file. Do not copy example credentials, and do not infer a
universal chmod, user, group, or secret-store command from this runbook.

## Deployment sequence

1. Provision the approved host prerequisites.
2. Create or verify the service account and filesystem ownership.
3. Deploy the approved source or release and record its immutable revision.
4. Create the Python environment at `/opt/etm-affiliate-os/backend/.venv`.
5. Install runtime dependencies from `backend/Requirements.txt` using the
   host's reviewed procedure.
6. Provision `/etc/etm-affiliate-os/etm-affiliate-os.env` outside the checkout.
7. Provision `/etc/etm-affiliate-os/caddy.env` outside the checkout.
8. Validate production configuration without printing secrets: `ENV=production`,
   token distinction, cookie security, and intended application CORS settings.
9. Perform a separately authorized PostgreSQL reachability check where
   applicable; this is configuration validation, not a migration authorization.
10. Handle a schema migration only if it is separately and explicitly
    authorized under **Migration policy**.
11. Install or verify the frozen application systemd unit.
12. Have the systemd operator perform daemon-reload where required.
13. Enable and start the application service using the approved host procedure.
14. Verify the localhost application process and `127.0.0.1:8000` listener.
15. Verify localhost `GET /health` returns HTTP 200.
16. Verify localhost `GET /ready` returns HTTP 200.
17. Only after both localhost liveness and readiness pass, have the Caddy/domain
    owner validate native Caddy configuration on the Linux host.
18. Install or verify the Caddy service and its drop-in.
19. Verify production DNS points `<PRODUCTION_DOMAIN>` to the intended host.
20. Verify inbound TCP ports 80/443 prerequisites.
21. Enable, start, or reload Caddy only after step 17 validation passes.
22. Verify public HTTPS/TLS.
23. Verify public reverse-proxy behavior.
24. Verify required production security headers.
25. Verify public authentication boundaries and route authority expectations.
26. Verify no-store behavior on readiness and session-sensitive responses where
    applicable.
27. Inspect application and system logs without exposing secrets.
28. Confirm the latest PR1D6 CI baseline passed for the deployed commit.
29. Record deployment evidence and operator sign-off.

No single automatic command is authorized to perform this sequence.

## Migration policy

**AUTOMATIC MIGRATIONS ARE NOT AUTHORIZED.** The application, Caddy, systemd
unit, and launcher do not execute migrations automatically.

**MANUAL MIGRATION — DO NOT RUN WITHOUT EXPLICIT AUTHORIZATION.** A separately
approved database change must identify its command, database target, backup
state, validation, rollback approach, and responsible database operator. Do
not perform a schema action merely because an application release is deployed.

## Health and readiness

`GET /health` is **PROCESS LIVENESS ONLY** and **NOT DATABASE READINESS**. It
does not probe PostgreSQL. A healthy response is HTTP 200 with:

```json
{"success": true, "status": "healthy"}
```

`GET /ready` is a database-readiness endpoint. It performs a lightweight
database availability probe; it is not a retry-manager gate. When available it
returns HTTP 200 with:

```json
{"success": true, "status": "ready"}
```

When the probe cannot establish availability, `/ready` returns HTTP 503 with:

```json
{"success": false, "status": "not_ready"}
```

Both endpoint response paths preserve `Cache-Control: no-store`. Validate
these endpoints first over loopback and then through Caddy after HTTPS is live.

## Caddy operational contract

The Caddy site address is exactly `{$ETM_AFFILIATE_OS_DOMAIN}` and the only
application upstream is exactly `127.0.0.1:8000`. Caddy supplies these headers:
`Strict-Transport-Security: max-age=31536000`,
`X-Content-Type-Options: nosniff`,
`Referrer-Policy: strict-origin-when-cross-origin`,
`Permissions-Policy: camera=(), microphone=(), geolocation=()`, and
`X-Frame-Options: DENY`.

Do not add CSP; CSP is not currently enforced. Caddy has no CORS headers, no
proxy caching, and no explicit access-log directive. Do not add an alternate
upstream or a configurable application upstream port. Caddy must not overwrite
application `Cache-Control` responses. Caddy configuration
syntax, service operation, certificate issuance, and TLS behavior are
deployment-host validation responsibilities, not Windows repository tests.

## Systemd operational contract

Use systemd operations appropriate to the approved Linux host to inspect
status, journal output, enable/start/restart state, and to run daemon-reload
after unit changes. Confirm the service starts the frozen launcher rather than
an ad-hoc Uvicorn command. The launcher contains no reload mode, no external
binding, no widened proxy trust, no database setup, and no automatic migration
execution. Application startup does not wait for PostgreSQL; `/ready`
determines whether database traffic should be accepted.

## DNS and TLS cutover

The DNS/TLS owner must provision and validate `<PRODUCTION_DOMAIN>` before
public cutover. The domain value remains a placeholder in this runbook and is
provided only through the Caddy environment file. Verify that Caddy can obtain
and serve the required certificate on the approved Linux host, then validate
the public HTTPS route and security headers. Do not hard-code a production
hostname in repository artifacts.

## Deployment validation checklist

Repository-qualified checks: PR1D6 CI baseline is the shared qualification
baseline; confirm its approved test result and the release revision. The PR1D7
contract test verifies this runbook against frozen repository service,
launcher, Caddy, readiness, and CI facts without accessing a host or database.

Deployment-host-only checks: validate systemd unit installation and lifecycle,
Caddy native syntax, Caddy service health, certificate issuance and TLS,
DNS for `<PRODUCTION_DOMAIN>`, firewall policy, loopback and proxied endpoint
responses, PostgreSQL reachability, and secure environment-file handling.

## Rollback

Use the approved host change process and preserve logs and deployment evidence
before replacing a release.

For application code rollback, select a known-good prior release or commit,
redeploy it, then restart or reload the application service as appropriate.
Rerun localhost `/health` and rerun localhost `/ready`; treat the rollback as
successful only when the required checks pass.

For environment/configuration rollback, restore the known-good external
application environment configuration. Never recover secrets from Git history.
Preserve correct file ownership and access, restart the affected service, and
rerun localhost `/health` and localhost `/ready`.

For Caddy rollback, restore the known-good Caddyfile, drop-in, and environment
configuration. Validate Caddy configuration **before** any reload or restart;
reload or restart only after validation passes, then verify public HTTPS,
reverse-proxy behavior, and security headers.

DNS, TLS, and firewall correction should be handled independently where
possible while the application loopback service remains available. Do not
unnecessarily roll back healthy application code merely because DNS/TLS is
broken.

Coordinate application rollback with the database owner whenever data or
schema compatibility is uncertain. **DO NOT BLINDLY ROLL BACK DATABASE
SCHEMA.** Database rollback needs its own explicit authorization and plan.

## Basic troubleshooting

| Symptom | Safe first checks | Owner / escalation |
| --- | --- | --- |
| Application service fails to start | Inspect systemd status and journal; verify required environment variable names without showing values. | Application/service owner; escalate secret or database issues to their owners. |
| `/ready` returns 503 | Check PostgreSQL availability and approved `DATABASE_URL` handling; `/health` may remain 200. | Database owner and application owner. |
| HTTPS or certificate failure | Inspect Caddy service status, domain DNS, and host TLS validation. | Caddy/domain/TLS owner. |
| Public proxy failure with healthy loopback endpoint | Confirm Caddy route targets `127.0.0.1:8000` and review host firewall/DNS policy. | Caddy/network owner. |
| Public HTTPS succeeds but authenticated operation fails | Investigate API authentication configuration, applicable `OPERATOR_API_TOKEN`/`SERVICE_API_TOKEN`, operator session/cookie configuration, application CORS configuration for browser access, and route authority expectations. Do not reset a database or change Caddy without edge evidence. | Application/security owner. |

## Unresolved deployment decisions

The following remain `DEPLOYMENT_DECISION_REQUIRED`: Linux distribution and
package method, host/service-account provisioning, filesystem and secret
ownership policy, firewall policy, DNS ownership, certificate policy,
PostgreSQL backup/restore ownership, provider/email activation, and monitoring
ownership. PR1D8 defines backup and restore work; PR1D9 defines disaster
recovery work. Neither is authorized by this deployment runbook.

## Repository-qualified and deployment-host validation

This runbook and its static contract are repository-qualified and Windows-safe.
They do not run Caddy, systemd, DNS, TLS, PostgreSQL, migrations, or deployment
commands. Native Caddy syntax/TLS, Linux systemd behavior, public DNS cutover,
and live database reachability remain deployment-host-only validation.
