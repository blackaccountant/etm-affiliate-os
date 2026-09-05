# PR1D8 Backup and Restore Procedure

This is the single authoritative PR1D8 backup/restore procedure for ETM Affiliate
OS. PostgreSQL is the production database authority. Use the matching release
and the frozen production operations runbook, `docs/DEPLOYMENT.md`, together
with this procedure. Execution requires explicit operator authorization for the
identified environment. Repository qualification does not authorize database access.

## Recovery scope

| Recovery class | Contents |
| --- | --- |
| Must be backed up | PostgreSQL schema, table data, sequences, indexes, constraints, functions, triggers, and captured Alembic version state |
| Reproducible from matching Git/release | Application source and Alembic migration scripts |
| Secure operator/secret-management records | Application and Caddy environment configuration, DATABASE_URL credentials, OPERATOR_API_TOKEN, SERVICE_API_TOKEN, enabled provider credentials, and encryption keys |
| Not primary recovery data | Virtualenv, caches, and process-local sessions; rebuild or reauthenticate |
| External systems of record | Provider delivery/publishing/payment state where applicable; reconcile with the restored database |

Generated content is persisted in database Text/JSON fields. No essential
generated filesystem data store was identified from repository evidence;
deployment-specific mounts must still be inventoried on the real host. Logs and
qualification evidence have separate audit/incident retention needs and are not
a substitute for database backups. Retain access to the exact release and its
migration history even if the production host is lost.

## Backup method and compatibility

Use a pg_dump custom-format single-database archive and restore with pg_restore.
Capture complete schema + data with no table/schema filtering by default. Include
functions, triggers, constraints, indexes, sequences and alembic_version rows.
Preserve large-object coverage through normal complete dump behavior. The
repository contains PostgreSQL append-only enforcement functions/triggers;
row-only recovery is insufficient.

A single-database dump does not inherently preserve cluster roles, global
objects or tablespaces. Recreate required definitions through secure operator
records or a separately approved globals procedure. Inventory live extensions,
roles, ownership, ACLs, encoding, locale and tablespaces; repository evidence
does not prove the live inventory. No application-specific large-object or
extension requirement was identified, but this is not proof of live absence.

Prefer compatible/matching source-major tooling. pg_dump must not be older-major
than a newer PostgreSQL server it cannot support. Restoring into an older
PostgreSQL major version is not assumed safe. Live PostgreSQL version remains
DEPLOYMENT_DECISION_REQUIRED; no major version is prescribed here.

This is a provisional logical-backup baseline, subject to measured database size,
restore duration and recovery objectives. It does not provide continuous
point-in-time recovery. Stricter objectives may require a separately approved
managed or physical/WAL backup strategy.

## Consistency and provider replay

Routine pg_dump logical backups can normally run while the application remains
online: PostgreSQL supplies a transaction-consistent snapshot. The recovery
point corresponds to the snapshot, not backup completion time. Ordinary
concurrent writes do not automatically require application shutdown. Coordinate
schema-changing operations to avoid conflicting locks or ambiguous release metadata.

External provider effects are not transactionally included in the PostgreSQL
snapshot. Restored database state may contain work eligible for retry or replay.
Frozen application lifespan starts a background retry manager. Before starting
an isolated validation instance, block real provider egress and use isolated/test
credentials. Do not permit real publishing/payment/email/provider side effects.
Verify isolation, rather than assuming that a test database alone is sufficient.
Reconcile in-flight external operations before production cutover. PR1D8 does
not change frozen retry/provider runtime behavior.

## Security and off-host storage

Treat backup archives as sensitive production data, including contact, financial
and operational payloads that may contain secrets. Require encryption at rest,
encryption in transit, least-privilege access, protected temporary staging,
recoverable encryption-key custody, access auditing where supported, and
separation from application-host compromise. Compression is NOT encryption.

Never commit database dumps to Git. Never commit plaintext environment copies.
Never upload production dumps as CI artifacts. All backup output must reside
outside the Git checkout. Never store encryption keys beside encrypted backup
data without approved separation. Protect logs and archive listings as sensitive
metadata; avoid connection strings or record contents in routine evidence.

Every successful backup must leave the production host for independently durable,
encrypted, access-restricted storage that remains recoverable if that host is
lost. Verify transfer, enforce retention and protect against accidental deletion
where practical. A local-only file is not a completed backup.

Backup storage provider, storage account, region/location, key custody and deletion
protection mechanism are DEPLOYMENT_DECISION_REQUIRED. No storage vendor is selected.

## Retention and recovery objectives

Retain 7 daily recovery points, 4 weekly recovery points and 3 monthly recovery
points. This is a provisional repository baseline recommendation, not an approved
business/legal retention policy. Legal/privacy/financial requirements may require
adjustment. Existing points may be promoted between retention classes. Budget
capacity for full archives, protected staging and isolated restores; do not prune
the last verified point because a new attempt merely started.

No approved numerical RPO/RTO currently exists.

| Objective | Provisional target | Approval |
| --- | --- | --- |
| RPO | <= 24 hours | PROVISIONAL — BUSINESS APPROVAL REQUIRED |
| RTO | <= 8 hours | PROVISIONAL — BUSINESS APPROVAL REQUIRED |

RTO is not yet demonstrated. Recommend backup attempts approximately every 12
hours for operational margin. Monitor the age of the latest verified off-host
recovery point using snapshot time. A daily schedule does not guarantee a
24-hour RPO: failed jobs, transfer delays and backup duration matter. Escalate
missed attempts or an aging recovery point to the named operator; record the
exposure and arrange an authorized replacement attempt. PR1D9 owns disaster
execution of the approved objectives.

## Naming and protected metadata

Use UTC timestamps and a non-sensitive database alias:

```text
etm-affiliate-os_production_<DATABASE_ALIAS>_<YYYYMMDDTHHMMSSZ>_<RELEASE_SHA>.dump.enc
```

Never include usernames, passwords, hostname credential strings, DATABASE_URL
values or tokens in filenames. The suffix describes an actually encrypted
archive, not an instruction to rename plaintext.

Companion protected metadata records backup ID, snapshot/start/completion
timestamps, release SHA, PostgreSQL server/client versions, Alembic revision(s),
archive format, file size, checksum, verification result, secure
configuration-version references and encryption-key identifier only. Never store
encryption key material in metadata. If exact snapshot time cannot be captured,
record the backup start time conservatively and label the timing basis.

## Backup verification

1. Require pg_dump successful exit status.
2. Review warnings and resolve unexplained omissions.
3. Require non-empty output.
4. Require expected protected metadata.
5. Compute and record a SHA-256 checksum for the final encrypted object.
6. Inspect the archive with pg_restore --list in protected local staging after authorized decryption, without a database target.
7. Verify the transferred/off-host object against the recorded checksum and metadata.

Only then mark the backup successful. A checksum mismatch rejects the copy;
quarantine it, preserve the last verified recovery point, investigate the source
and transfer, and repeat the authorized transfer/verification. Do not restore it.
pg_restore --list does not prove a successful full restore. A checksum proves
byte integrity, not semantic correctness; protect the trusted checksum itself.

## Periodic restore qualification

Initially perform a monthly isolated restore test, and repeat after material
schema changes, PostgreSQL tooling changes or backup-format changes. Check
tables/data availability, indexes, constraints, PostgreSQL functions, append-only
enforcement triggers, Alembic state and representative read-only application
queries. Missing triggers/functions or any incomplete object coverage reject
restore acceptance even when readiness is green. Record elapsed time and capacity.

## Restore safety and permissions

PRODUCTION OVERWRITE IS NEVER THE FIRST RESTORE STEP.

The default target is a new isolated database. Require explicit operator
authorization, an exact selected backup ID, verified authenticity/checksum,
positively identified target database, compatible tools, reviewed restore errors,
and application validation before cutover. Do not automatically restore latest.
Do not default to --clean, DROP DATABASE, destructive reset, trigger disabling or
direct overwrite of current production. Restore only trusted archives.

Archive ownership/ACL data must not be ignored blindly. Preserve it in the
archive; for isolated recovery --no-owner and --no-acl may be appropriate with
explicit approved role/grant reconstruction. These flags are not permission
policy by themselves. Validate production ownership/grants before cutover.
Use controlled error-stopping restoration. A single transaction may be suitable
where capacity permits; any partial/error result must be rejected.

## Restore sequence

1. Identify incident.
2. Identify authorized recovery point.
3. Identify responsible operators.
4. Preserve current/failed state where practical.
5. Retrieve archive and protected metadata.
6. Verify authenticity/checksum/readability.
7. Provision and positively identify a new isolated empty target DB.
8. Verify PostgreSQL/client compatibility.
9. Verify required roles/extensions/encoding/locale assumptions.
10. Restore complete archive under approved ownership/ACL policy.
11. Review pg_restore exit status/errors.
12. Reject incomplete restoration.
13. Inspect restored schema.
14. Inspect restored Alembic revision(s).
15. Run authorized read-only database sanity checks.
16. Prepare matching application release in isolation without starting it.
17. Block provider egress.
18. Use isolated/test credentials.
19. Point isolated validation instance to restored DB and start only after isolation is verified.
20. Verify GET /health.
21. Verify GET /ready.
22. Verify representative read queries.
23. Verify authentication.
24. Verify protected schema objects/functions/triggers.
25. Reconcile pending external/provider work.
26. Explicitly account for writes after the chosen snapshot.
27. Approve production cutover.
28. Quiesce the old production writer.
29. Update DATABASE_URL through secure configuration handling.
30. Restart application.
31. DO NOT run migrations automatically.
32. Verify /health.
33. Verify /ready.
34. Verify Cache-Control: no-store on /ready.
35. Verify public HTTPS.
36. Verify authentication.
37. Verify representative application behavior.
38. Verify security headers/session-sensitive responses.
39. Retain pre-cutover DB isolated from writers until recovery acceptance.
40. Record evidence/operator sign-off.

If safe isolated application startup cannot be established, STOP before production
cutover. Approval includes validated ownership/grants, provider reconciliation
and an explicit accepted data-loss or reconciliation plan for post-snapshot writes.
Keep the old writer quiesced; never permit both databases to become active writers.
If post-cutover /ready fails, stop acceptance and further writes/provider work,
inspect configuration and connectivity without exposing secrets, and escalate.
Do not blindly switch back after new writes. A rollback needs a separate approved
reconciliation decision; preserve both states and follow docs/DEPLOYMENT.md.

## Alembic and schema policy

Restore the backup at its captured schema state first. Inspect restored
alembic_version rows using a separately authorized read-only query and compare
against the matching release migration graph in backend/alembic/versions.
backend/alembic.ini points to that migration tree; backend/alembic/env.py loads
DATABASE_URL and its online path connects. Do not treat Alembic current as an
offline check. Do not assume the latest application release matches restored schema.

AUTOMATIC MIGRATIONS ARE NOT AUTHORIZED.
Do not automatically upgrade to head. Do not automatically downgrade. Do not
stamp automatically. Do not run create_all. Do not run init_db.py: the frozen
backend/app/database/init_db.py executes create_all and is not a restore tool.
DO NOT BLINDLY ROLL BACK DATABASE SCHEMA.

A separately authorized forward migration may occur only after restored state
is understood and recovery safety is established. Require a verified recovery
point before separately authorized production migration work. Older restored
schema requires the matching release or a reviewed forward-migration plan,
never an automatic upgrade during startup or restoration.

## Health and readiness

| Endpoint | Meaning | Expected response | Cache contract |
| --- | --- | --- | --- |
| GET /health | Process liveness only | 200: {"success": true, "status": "healthy"} | No frozen no-store header guarantee |
| GET /ready | PostgreSQL connection readiness through SELECT 1 | 200: {"success": true, "status": "ready"}; 503: {"success": false, "status": "not_ready"} | Cache-Control: no-store on both readiness outcomes |

Only /ready has the frozen no-store readiness contract. Neither endpoint proves
restored schema completeness, application-data correctness, trigger/function
integrity or provider reconciliation correctness. Readiness does not depend on
retry-manager/provider/email health. Cross-check backend/app/main.py and
backend/app/database/session.py; the separate read/object checks remain mandatory.

## Configuration and secrets recovery

Actual secrets are NOT recoverable from Git or DEPLOYMENT.md. Recover
/etc/etm-affiliate-os/etm-affiliate-os.env and /etc/etm-affiliate-os/caddy.env
through approved secure records. The application file needs DATABASE_URL,
OPERATOR_API_TOKEN, SERVICE_API_TOKEN, APP_NAME and ENV=production, plus approved
optional provider settings. Operator/service tokens remain distinct; Caddy uses
ETM_AFFILIATE_OS_DOMAIN in its separate file. The deployment runbook supplies
names and validation rules, never actual secret values.

Restore or reissue credentials through the approved mechanism, preserving
ownership/access and recoverable encryption keys. If encrypted configuration
backups use the same storage provider, require appropriate key/access separation.
Never place plaintext env copies beside an unprotected dump. Never recover
secrets from Git history. Record secure version identifiers, not secret values.

## Scheduling and milestone boundary

The operational scheduling contract requires a schedule, named owner, success
criteria, missed-backup detection, retention enforcement and latest verified
recovery-point age monitoring. Actual cron, systemd timer, managed PostgreSQL
backup service or other approved scheduler implementation is a deployment decision.
PR1D8 adds no scheduler, backup/restore scripts or provider-specific configuration.

PR1D8 owns backup creation, storage, retention, encryption expectations, integrity
verification, isolated restore and restore acceptance. PR1D9 owns total host loss,
provider/region outage, infrastructure reconstruction, DNS reconstruction,
broader continuity procedure, operational execution of disaster RPO/RTO, and
disaster roles/escalation/cutover. Its authority remains docs/ROADMAP.md.

## Qualification and unresolved deployment decisions

Repository qualification is Windows-safe and static: read frozen sources,
validate this runbook and its ordering, run in-memory negative contract examples,
and run approved frozen regressions. No database connection or backup/restore
execution is required. Linux, WSL, Docker and virtualization are not repository
qualification prerequisites.

Deferred live validations, each requiring a separately authorized environment:

- Real pg_dump creation and real pg_restore.
- Actual PostgreSQL privilege/object coverage and live PostgreSQL/server-client compatibility.
- Backup encryption implementation and encryption key recovery.
- Real off-host transfer and storage durability/access control.
- Retention enforcement and scheduler behavior.
- Isolated restore duration/capacity and real schema/data verification.
- Provider isolation behavior and observed RPO/RTO.
- Real production cutover.

These do not block repository freeze, but remain required before claiming actual
operational recoverability. The live PostgreSQL topology/version/size, role/grant
mapping, extensions, storage, encryption, named owners, scheduler, retention
approval, business RPO/RTO, isolation environment and cutover reconciliation plan
remain DEPLOYMENT_DECISION_REQUIRED.
