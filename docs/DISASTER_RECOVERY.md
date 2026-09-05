# PR1D9 Disaster Recovery Runbook

This is the single authoritative disaster recovery procedure for ETM Affiliate
OS. docs/ROADMAP.md governs milestone scope. docs/DEPLOYMENT.md (PR1D7) remains
the authority for normal deployment/service operations. docs/BACKUP_RESTORE.md
(PR1D8) remains the authority for detailed backup and isolated restore. Invoke
those authorities at the gates below; this document does not reproduce their
complete procedures or authorize their execution in an unidentified environment.

PR1D9 owns disaster declaration/classification, recovery roles, reconstruction
sequencing, fencing, provider isolation/reconciliation, DNS/TLS disaster
coordination, production traffic cutover, acceptance/abort gates, evidence,
fallback and DR drills. It adds no runtime behavior or operational automation.

## Classification and severity

| Tier | Meaning | Initial authority |
| --- | --- | --- |
| DR-0 | Routine operational incident | PR1D7 troubleshooting |
| DR-1 | Significant interruption where existing infrastructure remains recoverable | PR1D7 troubleshooting, escalate on confirmed loss |
| DR-2 | Major component loss requiring rebuild and/or restore | PR1D9 coordination with PR1D7/PR1D8 |
| DR-3 | Complete environment/control-plane loss | Canonical full-loss sequence below |

Routine process restart or ordinary service failure is not automatically a full
DR event. Suspected compromise is an additional recovery condition, not
automatically DR-3. Record classification and reclassify when evidence changes.

| Incident category | Safe initial decision |
| --- | --- |
| Routine application/process incident | PR1D7 diagnosis; avoid unnecessary restore |
| Application host/filesystem loss | DR-2 reconstruction; inventory lost deployment-specific mounts |
| PostgreSQL unavailable with host otherwise intact | Diagnose connectivity/service before declaring host loss |
| Suspected database corruption | Preserve state; approved PR1D8 isolated restore |
| PostgreSQL host/provider loss | DR-2 replacement database infrastructure and PR1D8 |
| Caddy/TLS failure | Targeted PR1D7 edge repair; escalate on infrastructure/control loss |
| DNS failure/bad cutover | Correct intended routing with DNS owner; keep old endpoint fenced |
| Firewall/network failure | Contain unintended exposure; repair approved network controls |
| External provider outage | Contain/defer affected work; do not restore a healthy DB solely for provider outage |
| Secret/config loss | Recover secure records or authorized reissue; stop activation if unavailable |
| Full production-environment loss | DR-3 reconstruction |
| Suspected compromise | Containment and trust branch before reconstruction |
| Partial recovery with uncertain data freshness | Withhold acceptance; verify recovery point and reconcile missing writes |

## Recovery objectives

| Objective | Target | Status |
| --- | --- | --- |
| RPO | <= 24 hours | PROVISIONAL — BUSINESS APPROVAL REQUIRED |
| RTO | <= 8 hours | PROVISIONAL — BUSINESS APPROVAL REQUIRED |

RPO and RTO are not demonstrated. RPO and RTO are not guaranteed. These preserve
PR1D8's provisional objectives; operational approval and measurement remain
required. A successful exercise proves only that exercise's measured result.
Do not describe an exercise result as a guarantee of future recoverability.

Measure recovery-point age from the selected recovery point snapshot timestamp
against the incident/data-loss reference time. Use conservative backup start
time when true snapshot time is unavailable, and record that timing basis.
Account separately for writes after the chosen recovery point, including writes
on surviving systems during recovery. Record lost/uncertain intervals and the
explicit business acceptance or reconciliation plan; elapsed time alone does
not establish the exact lost transaction set.

RTO starts at actual service disruption, not later disaster declaration. Record
detection/declaration timestamps separately. Disclose uncertain disruption onset
and use the recorded actual/estimated onset throughout; do not reset the clock
when roles are assigned or another restore attempt starts. RTO ends only after
the approved service scope passes recovery acceptance. Record provisional
elapsed time at sequence step 47, then finalize achieved RTO using the acceptance
timestamp at step 49. Evidence includes trusted timestamps, selected backup ID,
verified recovered data, accepted missing-write accounting and signed acceptance.

Missing a provisional RPO/RTO target requires escalation and an explicit business
decision. A target miss must not authorize bypassing technical safety gates.

## Roles and authorization

| Function | Responsibility |
| --- | --- |
| Incident Lead | Approve declaration/escalation, coordinate gates and communication, obtain final acceptance |
| Infrastructure/Network/DNS Operator | Administrative access, trusted host, network/fencing, DNS and Caddy/TLS |
| Database Recovery Operator | Recovery point, target identity, restore verification and schema compatibility |
| Application Operator | Trusted release, secure configuration, private validation and controlled activation |
| Business/Provider Reconciliation Approver | Accept data-loss exposure, reconcile external effects and approve resumption |

One person may hold multiple roles; record responsibility and approvals explicitly.
Use protected operational contact/escalation records; no personnel are prescribed.
Explicit approval is required for disaster declaration/escalation, selected
recovery point, restore target, backup restoration, production DATABASE_URL
change, DNS cutover/change, public traffic enablement, provider-work
resumption/replay, separate schema migration and eventual disposal of old state.
Each approval identifies action, environment/target, responsible operator,
evidence and timestamp. Cutover approval includes accepted post-snapshot loss,
reconciliation, intended service scope and the planned DNS/TLS transition.
Approval is conditional on subsequent fencing and target proofs remaining valid.

## Decision tree

Evaluate in priority order; diagnose surviving components before selecting a path:

1. If compromise is suspected, invoke Containment and trust before normal reconstruction.
2. If the complete production environment is lost, invoke Full environment loss sequence.
3. If database corruption is suspected, preserve state and invoke the approved PR1D8 isolated restore path.
4. If the DB host/provider is lost, reconstruct the DB target and invoke PR1D8.
5. If the application host is permanently lost, rebuild through PR1D7 preparation plus DR isolation/fencing gates; retain a verified healthy surviving DB rather than restoring unnecessarily.
6. If /health = 200 and /ready = 503, investigate PostgreSQL connectivity/readiness before declaring host disaster.
7. If loopback works and public access fails, repair Caddy, DNS, firewall and TLS through PR1D7.
8. If host intact + app unhealthy, use PR1D7 troubleshooting first.
9. Otherwise preserve evidence, classify remaining provider/config/freshness issues and escalate to the responsible role.

Every branch stops before production cutover if trust, isolation, old-writer
fencing or recovery target identity is unresolved, or acceptance gates fail.
Pre-cutover gates must pass before activation; public verification and final
acceptance follow activation. No branch may skip these gates.

## Replacement-host preparation

Invoke PR1D7 host preparation, not its entire normal activation blindly. Recreate
an approved Linux/systemd host, etm-affiliate service account/group,
/opt/etm-affiliate-os, /opt/etm-affiliate-os/backend/.venv, reviewed runtime
dependencies from backend/Requirements.txt, and immutable approved release/commit.
Recover protected application env at /etc/etm-affiliate-os/etm-affiliate-os.env
and protected Caddy env at /etc/etm-affiliate-os/caddy.env. Install/verify the
frozen systemd service/launcher, frozen Caddyfile/drop-in, permissions/ownership,
PostgreSQL connectivity, observable logs/journald and health/readiness.

Do not execute PR1D7 normal activation blindly against an unidentified or live
production database during DR. DR isolation/target verification gates take
precedence. Prevent installation, service enablement or host reboot from starting
the application before those gates pass. Private validation uses isolated target
state; background retries can modify that state even without incoming traffic.
Preserve recovery evidence and account for validation changes before promotion.
Do not describe private app startup as read-only database validation.

## Database disaster path

Preserve surviving DB/state where possible. Select an explicit acceptable recovery
point and verified backup under the recorded approvals. Invoke PR1D8 for the
detailed restore into a new isolated empty target, never a production destination.
Verify schema/object/data, required functions/triggers/constraints, ownership and
Alembic/release compatibility. PR1D8 restore operations and PR1D9 orchestration
refer to the same identified recovery attempt; do not execute a second restore
or a nested production cutover simply because a referenced procedure includes it.
At DR-3 step 15 invoke PR1D8's restore and database-verification portion only;
hold application startup and cutover at the explicit PR1D9 gates below.

Provider isolation precedes app startup; provider reconciliation, accepted
post-snapshot data loss and explicit cutover approval precede activation.
Do not restore directly into production as the first action.
Do not restore latest automatically.
Do not automatically run alembic upgrade head.
Do not automatically downgrade.
Do not automatically stamp.
Do not run create_all for recovery.
Do not run init_db for recovery.
No automatic migrations are authorized. A separately approved migration requires
its own target, verified recovery point, operator, validation and fallback plan;
it is not an implicit part of restoration or application startup.

## Full environment loss sequence

This is the sole canonical numbered DR-3 sequence. Each action inherits the
authorization, target-binding, stop conditions and evidence requirements above.

1. Record actual/estimated service disruption time.
2. Declare/classify disaster.
3. Assign recovery roles.
4. Start/record RTO measurement.
5. Contain affected systems and preserve surviving evidence.
6. Verify administrative/control access.
7. Select trusted matching application release.
8. Select explicitly approved verified recovery point.
9. Establish replacement infrastructure.
10. Establish restrictive network controls.
11. Recreate service account/filesystem/runtime.
12. Recover protected application configuration.
13. Recover protected Caddy configuration.
14. Verify target identities before restore/startup.
15. Invoke PR1D8 isolated restore workflow.
16. Verify restored DB/schema/Alembic/object state.
17. Establish provider egress block.
18. Establish isolated/test credentials.
19. Establish private validation ingress.
20. Start replacement application privately.
21. Verify /health.
22. Verify /ready.
23. Verify authentication.
24. Verify representative data/application behavior.
25. Verify required functions/triggers/constraints.
26. Inventory/reconcile retry-eligible and external-provider work.
27. Prepare frozen Caddy configuration.
28. Validate native Caddy configuration.
29. Verify firewall/80/443 prerequisites.
30. Verify DNS target plan and replacement endpoint identity.
31. Prepare certificate/TLS bootstrap path.
32. Obtain explicit cutover approval.
33. Prove old-writer fencing.
34. Prove old provider workers/egress cannot replay production work.
35. Verify replacement DATABASE_URL target identity.
36. Complete approved DNS/TLS transition.
37. Enable approved replacement production writes.
38. Enable provider work only after reconciliation approval.
39. Enable public traffic.
40. Verify public HTTPS.
41. Verify authentication and session behavior.
42. Verify security headers.
43. Verify /health and /ready through intended operational paths.
44. Verify only one intended production writer.
45. Monitor for recovery regression.
46. Record selected recovery point age.
47. Record achieved RTO.
48. Record exceptions/residual risk.
49. Obtain final acceptance/sign-off.
50. Only after acceptance, downgrade/close disaster state.

Step 4 measures from step 1's disruption time. Steps 14-20 bind the restore and
private application to the explicitly approved isolated target only. Step 35
positively verifies the intended replacement production DB identity before any
authorized production DATABASE_URL change, service restart with production
configuration or step 37 activation. Keep writes, public traffic and provider
actions blocked during this transition. Recheck target, health/readiness and
reconciliation after any restart/configuration change before enabling production.
The frozen runtime has no read-only DR mode: if environment controls cannot keep
production writes blocked during bootstrap, stop; do not improvise runtime changes.
Step 36 requires the prepared edge and approved certificate-bootstrap method;
DNS routing alone is not authorization to enable application traffic or writes.
Step 38 requires explicit approval for each provider capability. Steps 40-45
are post-activation acceptance gates; failure invokes Abort and fallback.

## One-writer fencing

Require positive proof of the sole intended production writer before replacement
production activation. The old environment must be fenced from production
writes/replay, and replacement target identity must be verified. Replacement may
validate privately only against isolated target/state until production activation
approval. Retain old state isolated/read-only until acceptance and authorized disposal.

None of these alone is sufficient fencing: process appears stopped; host appears
offline; DNS changed; network temporarily unreachable. Fencing must survive an
old host restarting or old database becoming reachable. It must cover old
application process, old background/retry workers, old database credentials/access,
old provider credentials, replacement provider egress and DNS propagation overlap.
Use deployment-approved durable infrastructure/network/credential controls and
record positive verification. No universal fencing command is prescribed.
If the old writer cannot be fenced, CUTOVER BLOCKED. Changing DNS is not fencing.
Do not enable replacement production writes before fencing.
Do not change DATABASE_URL before target identity verification.
Do not change DNS while the old writer remains active.

## DNS and edge reconstruction

Positively identify replacement IP/endpoint and inspect all relevant DNS records,
including stale IPv6/AAAA or alternate targets. Prepare replacement edge before
routing change, with native configuration validation and a safe TLS bootstrap
plan. Do not assume TTL was previously lowered. Lowering TTL during an incident
does not immediately expire old caches. Verify authoritative DNS after change,
account for propagation/caches and keep old endpoint fenced throughout.
Separate DNS routing from production-write enablement and public traffic gates.
Verify HTTPS after transition and observed propagation; record remaining cache risk.

Invoke PR1D7's Caddy contract: recover ETM_AFFILIATE_OS_DOMAIN, frozen Caddyfile,
frozen Caddy drop-in and loopback upstream 127.0.0.1:8000. Require native Caddy
validation before activation, ports 80/443/firewall prerequisites, certificate
issuance/renewal connectivity, TLS verification, proxy verification and frozen
security-header verification. Do not add provider-specific DNS commands or
unapproved Caddy features. Keep Uvicorn at one worker and loopback proxy trust.
Do not bind Uvicorn publicly to 0.0.0.0 as an emergency shortcut.
Do not bypass Caddy to expose the application publicly.

If certificate issuance requires temporary public routing, use only an explicitly
approved certificate-bootstrap method; keep application traffic/writes/provider
actions blocked until DR gates pass. Certificate/bootstrap reachability is not
application traffic enablement. Do not assume certificates can always be obtained
privately. If no safe certificate-bootstrap method exists, CUTOVER BLOCKED.

## Secrets and configuration

Recover DATABASE_URL, OPERATOR_API_TOKEN, SERVICE_API_TOKEN, enabled provider
credentials, APP_NAME, ENV=production, approved application settings and
ETM_AFFILIATE_OS_DOMAIN. Operator/service tokens remain distinct. Git contains
only variable names/contracts; actual values require protected secure records
or secret-management access. Never print secrets during validation. Verify target
identity without exposing credentials. Preserve file ownership/access controls.
Do not recover production secrets from Git.
If compromise is suspected, affected credentials must be rotated/reissued;
obsolete credentials must be revoked where applicable. Recover encryption keys
through approved custody, not alongside exposed backup data. Missing secure
records stop activation until authorized recovery/reissue succeeds.

## Containment and trust

Preserve evidence where possible and quarantine/fence affected infrastructure.
Do not blindly reuse compromised host.
Do not blindly reuse compromised configuration.
Verify trusted source/release and backup provenance/trust, then rebuild on clean
infrastructure. Rotate/reissue affected credentials and revoke obsolete credentials
through trusted administrative access. Reconcile provider activity before
resumption and keep old compromised environment fenced. An untrusted latest
backup is not an acceptable default. Escalate security investigation separately;
this is a bounded recovery branch, not a full cybersecurity IR manual.

## Provider reconciliation

Current runtime starts retries during application lifespan. No deployment-wide
provider kill switch is established by frozen contracts. Retry start/stop methods
are not a deployment-wide isolation guarantee. Use environment/network/credential
controls: before replacement startup, provider egress blocked and isolated/test
credentials established, verified rather than inferred from a private DB.

Inventory retry-eligible work, email, publishing, payment/commission/payout
workflows where enabled, external jobs and uncertain side effects. Compare
against external systems of record, including completed actions absent from the
snapshot and provider-specific replay windows. Record reconcile/defer/cancel
decisions under approved procedures without inventing SQL repair instructions.
Require explicit approval before each production provider capability resumes.
Do not assume operation-level idempotency/fencing alone protects two restored
environments. Private validation can change retry state; preserve evidence and
reconcile those changes before promotion. Unresolved replay risk blocks acceptance.
Do not allow real provider access during private validation.
Do not ignore unresolved provider replay risk.

## Acceptance gates

All pre-activation gates are mandatory before their corresponding activation;
public checks and signed acceptance follow controlled activation. Verify safely
authorized representative read/write behavior without unapproved external effects.

| Area | Required evidence |
| --- | --- |
| Infrastructure | Replacement host healthy; services lifecycle correct; permissions/ownership verified; logs observable |
| Database | Recovery point verified; schema/Alembic compatibility understood; required objects present; representative data verified; /ready succeeds |
| Application | /health succeeds; authentication succeeds; representative behavior verified; no unauthorized migration occurred |
| Edge | Caddy config valid; DNS correct; HTTPS/TLS valid; frozen security headers present |
| Operations | One intended production writer proven; provider reconciliation approved; provider resumption controlled; residual risks recorded; recovery point/time recorded; acceptance timestamp/sign-off recorded |

/health is process liveness only. /ready proves PostgreSQL connectivity only
through SELECT 1; it does not prove full schema/data/provider correctness.
Readiness success is 200 and failure is 503, with Cache-Control: no-store on both
readiness outcomes. No-store belongs to readiness, not /health; there is no frozen
no-store guarantee on /health. Authentication/session-sensitive cache behavior
remains as defined by PR1D7 and the frozen application, not a new DR header policy.
Do not accept recovery while /ready fails.

## Abort and fallback

Recovery must fail closed for any unresolved condition below:

- Backup checksum invalid.
- Backup source untrusted.
- Encryption key unavailable.
- Required secret unavailable.
- Restore errors.
- Required trigger/function/object missing.
- Incompatible release/schema.
- Old writer cannot be fenced.
- Provider replay risk unresolved.
- DNS target uncertain.
- DB target uncertain.
- Authentication fails.
- /ready fails.
- Safe TLS/Caddy exposure unavailable.
- Compromise trust boundary unresolved.

Keep public traffic blocked or block it again after an activation failure.
Stop/keep blocked writes/provider work, including background retries. Preserve
replacement evidence/state and surviving old state. Select another verified
recovery point only with authorization; use known-good release/config only.
Do not oscillate DNS repeatedly without approval.
Do not blindly switch DBs after new writes.
Reconcile any new writes before fallback. Do not discard previous DB/state before
acceptance and authorized disposal. Missing a provisional target is an escalation/
business decision, never authorization to bypass technical safety gates.

## Evidence and communications

Record disruption time, detection time, declaration time, severity/classification,
assigned roles, release SHA, backup/recovery-point ID, snapshot timestamp and timing
basis, restore outcome, object/schema/Alembic checks, fencing evidence, DNS changes,
secret rotation identifiers (not values), provider reconciliation decisions,
cutover time, achieved recovery-point age, achieved RTO, exceptions, residual risks
and final acceptance/sign-off. Retain protected incident evidence and operator
approvals. Do not record secret values or sensitive application payloads.

Incident Lead owns communication updates at declaration, material state change,
target miss, cutover and acceptance. Use deployment-approved contact/escalation
records and communication channels; no platform or personnel is prescribed.

## Drills and validation boundary

Recommend quarterly tabletop exercises and periodic full isolated recovery
exercises coordinated with PR1D8. Cadence remains recommendation/operational
decision, with assigned ownership, not a guarantee. Repeat after material changes.
Measure recovery point identification time, replacement provisioning time, restore
duration, application validation duration, edge readiness, total recovery duration,
achieved RPO, achieved RTO, operator ambiguity and provider reconciliation issues.
Simulated DNS/fencing evidence must be clearly labeled as simulated.

Repository qualification does NOT prove the following deferred live validations:

- Real replacement-host provisioning and infrastructure/control-account permissions.
- Real Linux ownership/permissions and service lifecycle.
- Actual DB restore, privilege/object coverage and release/schema/data compatibility.
- Actual provider isolation and external reconciliation/resumption behavior.
- Real DNS propagation/cutover.
- Real firewall reconstruction and private ingress enforcement.
- Real certificate issuance/renewal, Caddy parsing/runtime and HTTPS/TLS.
- Real secret recovery/rotation/revocation and encryption-key recovery.
- Durable one-writer fencing, including old-host return and DNS overlap.
- Real production traffic cutover and post-cutover acceptance/fallback.
- Achieved RPO and achieved RTO.
- End-to-end DR capability through a full isolated recovery drill.

These require separately authorized deployment environment drills/live validation.
They do not block repository freeze when explicitly deferred. Repository freeze
does not equal demonstrated disaster recoverability. Static qualification is
Windows-safe: no DB, network, DNS changes, Caddy/systemd, backup/restore or migration
execution. No operational automation is added by PR1D9.

## Unresolved deployment decisions

DEPLOYMENT_DECISION_REQUIRED: host/provider/topology/version/size and replacement
capacity; infrastructure/control-account recovery; service/filesystem permissions;
trusted release delivery; backup storage/encryption/key custody; PostgreSQL roles,
grants/extensions and compatible target; approved recovery point and data-loss
exceptions; secret-store access and credential rotation/revocation; durable fencing
method; provider inventory/replay windows and reconciliation owners; DNS ownership,
records/endpoints, firewall/private ingress and certificate-bootstrap method;
approved RPO/RTO, service acceptance scope/observation period; role assignments,
communications/escalation contacts and drill environment/cadence. None is resolved
by choosing a guessed provider command or by changing frozen runtime behavior.
