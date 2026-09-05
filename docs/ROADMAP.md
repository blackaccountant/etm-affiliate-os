# PR1 Production-Readiness Roadmap

## Authority and governance

`docs/ROADMAP.md` is the single living authority for the PR1
production-readiness roadmap. `docs/ROADMAP_v1.0.md` is not authoritative
unless a future explicit decision designates it as such.

A milestone may not enter implementation until reconnaissance has defined its
exact candidate manifest and its frozen-boundary implications. The required
workflow is:

1. reconnaissance
2. exact candidate manifest
3. implementation and qualification
4. closure audit
5. explicit freeze, commit, and push authorization

Frozen milestone files must not be modified unless a later milestone explicitly
authorizes a boundary exception. Database mutations and migration execution
require explicit authorization. Deployment-only validation must be reported
separately from repository qualification.

## Completed and frozen baseline

### PR1D1R — Alembic credential remediation

- Status: FROZEN / COMPLETED.
- Scope: remediation of Alembic credential sourcing without embedding real
  credentials.

### PR1D2 — Production runtime configuration

- Status: FROZEN / COMPLETED.
- Scope: fail-closed production runtime configuration validation and safe
  production defaults.

### PR1D3 — Single-process production startup

- Status: FROZEN / COMPLETED.
- Scope: one-worker, loopback-bound production launcher and service contract
  while operator-session and retry-manager state remain process-local.

### PR1D4 — Production Caddy reverse-proxy contract

- Status: FROZEN / COMPLETED.
- Frozen commit: `78290799a1be3f1b85556de54aa7642730d22a50`.
- Scope: production Caddy HTTPS/reverse-proxy contract and bounded loopback
  proxy trust.
- Frozen artifacts: `deployment/Caddyfile`,
  `deployment/caddy.service.d/etm-affiliate-os.conf`,
  `deployment/start-production.sh`, and
  `backend/tests/test_production_reverse_proxy_contract.py`.

### PR1D4 deferred deployment validations

These checks are non-blocking repository-deployment validations and remain
deferred until a suitable deployment environment is available:

- native Caddy parser and runtime validation;
- production real-domain and TLS certificate validation; and
- Linux systemd activation and Caddy drop-in validation.

## Remaining milestones

### PR1D5 — Production Liveness and Database Readiness

- Status: PLANNED — RECON_REQUIRED.
- Objective: separate process liveness from dependency-aware production
  readiness, beginning with PostgreSQL.
- Key scope:
  - `/health` remains lightweight process liveness;
  - introduce a separate `/ready` readiness route for infrastructure,
    load-balancer, and service checks;
  - readiness PostgreSQL probing is read-only;
  - readiness success returns HTTP 200 and database failure or timeout returns
    HTTP 503;
  - readiness responses do not expose internal database, driver, or connection
    details; and
  - application startup remains independent of transient PostgreSQL
    availability.
- Explicit exclusions:
  - retry-manager ongoing state is excluded from D5 readiness unless a later
    milestone explicitly changes that policy;
  - backup, restore, monitoring, metrics, and request limiting are not D5
    scope.
- Dependencies: PR1D1R through PR1D4.
- Frozen-boundary risk: expected overlap with the API authority policy requires
  explicit authorization before implementation.
- Database access: expected at runtime only for a read-only readiness probe;
  qualification should avoid a live database where practical.
- Migrations: not expected.
- Qualification and freeze intent: define the exact route, probe seam, timeout
  behavior, public authority treatment, and candidate manifest during
  reconnaissance before implementation approval.

### PR1D6 — Production Qualification and CI Baseline

- Status: PLANNED — RECON_REQUIRED.
- Objective: make the existing guarded production qualification process
  repeatable and CI-safe.
- Key scope: select safe contract/regression suites, preserve guarded
  PostgreSQL qualification behavior, and establish reproducible qualification
  evidence in an authorized CI system.
- Explicit exclusions: no production deployment, database provisioning, or
  broad test-suite rewrite.
- Dependencies: PR1D5 contracts must be frozen first.
- Frozen-boundary risk: frozen tests are regression inputs; no frozen
  application or deployment modification is expected.
- Database access: CI-safe suites should not require database access; guarded
  PostgreSQL suites remain explicitly opt-in.
- Migrations: not expected.
- Qualification and freeze intent: CI provider, suite selection, evidence
  retention, and candidate manifest are RECON_REQUIRED.

### PR1D7 — Production Operations and Deployment Runbook

- Status: PLANNED — RECON_REQUIRED.
- Objective: define service management, secrets provisioning, production
  environment setup, domain/DNS/TLS cutover, deployment steps, and operational
  ownership.
- Key scope: operational runbooks and validation instructions for the frozen
  service, launcher, and reverse-proxy contracts.
- Explicit exclusions: no unapproved Caddy feature expansion and no embedded
  credentials or production domain values.
- Dependencies: PR1D4 and PR1D6.
- Frozen-boundary risk: PR1D3 and PR1D4 artifacts are expected to be referenced
  rather than modified; any modification requires a boundary exception.
- Database access: not expected for repository documentation work.
- Migrations: not expected.
- Qualification and freeze intent: deployment topology, secret owner, domain,
  certificate, and Linux-host validation details are RECON_REQUIRED.

### PR1D8 — Backup and Restore Procedure

- Status: PLANNED — RECON_REQUIRED.
- Objective: define and prove backup and restore procedures for the selected
  production PostgreSQL topology.
- Key scope: backup ownership, retention, encryption, restore procedure, and
  non-production restore verification.
- Explicit exclusions: no production database mutation or schema change as part
  of repository reconnaissance.
- Dependencies: PR1D7 must establish the production database operating model.
- Frozen-boundary risk: no frozen application/deployment artifact change is
  expected.
- Database access: required later only in an explicitly authorized dedicated
  backup/restore qualification environment.
- Migrations: not expected as part of backup/restore procedure qualification.
- Qualification and freeze intent: topology, recovery-point objective,
  recovery-time objective, storage, and verification environment are
  RECON_REQUIRED.

### PR1D9 — Disaster Recovery Runbook

- Status: PLANNED — RECON_REQUIRED.
- Objective: define recovery objectives, ownership, restore verification,
  failure handling, and incident recovery procedure.
- Key scope: incident roles, recovery sequence, decision points, and evidence
  requirements based on the approved backup/restore procedure.
- Explicit exclusions: no new application recovery behavior without a separate
  authorized milestone.
- Dependencies: PR1D8.
- Frozen-boundary risk: no frozen code change is expected.
- Database access: no repository-time access; later drills depend on explicitly
  authorized non-production recovery infrastructure.
- Migrations: not expected.
- Qualification and freeze intent: recovery objectives, incident ownership, and
  drill requirements are RECON_REQUIRED.

### PR1D10 — Production Logging Hardening

- Status: PLANNED — RECON_REQUIRED.
- Objective: define safe and useful production logging, including operational
  fields, redaction, correlation, and retention responsibilities.
- Key scope: logging contract, sensitive-data redaction, correlation policy,
  and operational ownership of retention.
- Explicit exclusions: no monitoring platform selection or alert policy.
- Dependencies: PR1D6 and PR1D7.
- Frozen-boundary risk: logging integration may overlap application startup;
  exact boundaries are RECON_REQUIRED.
- Database access: not expected.
- Migrations: not expected.
- Qualification and freeze intent: required fields, prohibited values, log sink,
  and candidate manifest are RECON_REQUIRED.

### PR1D11 — Metrics, Monitoring, and Alerting

- Status: PLANNED — RECON_REQUIRED.
- Objective: provide measurable production health and operational signals with
  alert policy.
- Key scope: metrics contract, monitoring integration, dashboards, alert
  thresholds, and ownership.
- Explicit exclusions: no unapproved public operational endpoint or dashboard
  feature expansion.
- Dependencies: PR1D5, PR1D7, and PR1D10.
- Frozen-boundary risk: a metrics endpoint may overlap API authority policy and
  application routing; explicit boundary analysis is required.
- Database access: not expected by default; any database-derived metric requires
  separate justification.
- Migrations: not expected.
- Qualification and freeze intent: monitoring stack, metric cardinality,
  authorization, alert destination, and candidate manifest are RECON_REQUIRED.

### PR1D12 — Inbound Request Protection

- Status: PLANNED — RECON_REQUIRED.
- Objective: define and implement bounded inbound HTTP request protection with
  awareness of public, operator, service, and reverse-proxy authority
  boundaries.
- Key scope: request-limit policy, client identity/trust model, response
  behavior, and authority-aware qualification.
- Explicit exclusions: no blanket bypass, no weakening of PR1C authority, and
  no unreviewed Caddy feature change.
- Dependencies: PR1D4, PR1D5, and PR1D7.
- Frozen-boundary risk: likely overlap with PR1C API authority policy and may
  overlap PR1D4 if edge enforcement is selected.
- Database access: not expected by default.
- Migrations: not expected.
- Qualification and freeze intent: enforcement layer, policy values, trusted
  client identity, and candidate manifest are RECON_REQUIRED.

### PR1D13 — Final Production Readiness Audit and Cutover

- Status: PLANNED — RECON_REQUIRED.
- Objective: reconcile all frozen contracts, operational runbooks, automated
  qualification, backup/restore/DR evidence, observability, request protection,
  and deferred live deployment validations before production cutover.
- Key scope: evidence review, final audit, deferred Caddy/TLS/systemd checks,
  and explicit cutover approval.
- Explicit exclusions: no corrective implementation without a separately
  authorized candidate manifest.
- Dependencies: PR1D5 through PR1D12.
- Frozen-boundary risk: no modification is expected; any discovered defect
  requires a new authorized boundary exception.
- Database access: only as explicitly authorized for final live validation.
- Migrations: not expected.
- Qualification and freeze intent: all predecessor evidence, deployment-owner
  approvals, and live-validation prerequisites must be complete before cutover.
