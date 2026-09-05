"""PR1D8 static contracts: no application imports, tools, network or databases."""

import ast
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = ROOT / "docs/BACKUP_RESTORE.md"


def _normal(text):
    return re.sub(r"\s+", " ", text.replace("`", "").replace("**", "")).strip().lower()


def _sections(document):
    headings = list(re.finditer(r"(?m)^## (.+)$", document))
    names = [match[1] for match in headings]
    assert len(names) == len(set(names)), "duplicate authority sections"
    return {
        match[1]: document[match.end(): headings[i + 1].start() if i + 1 < len(headings) else len(document)]
        for i, match in enumerate(headings)
    }


def _require(text, *phrases):
    normalized = _normal(text)
    for phrase in phrases:
        assert _normal(phrase) in normalized, f"missing contract: {phrase}"


def _steps(section, count):
    matches = list(re.finditer(r"(?m)^(\d+)\. (.*(?:\n(?!\d+\. |\s*$).*)*)", section))
    numbers = [int(match[1]) for match in matches]
    assert numbers == list(range(1, count + 1)), "steps must be unique and consecutive"
    return [_normal(match[2]) for match in matches]


def _one_step(steps, pattern):
    matches = [index for index, text in enumerate(steps) if re.search(pattern, text)]
    assert len(matches) == 1, f"missing or duplicate action: {pattern}"
    return matches[0]


def _production_target(text):
    """Bounded destination vocabulary, independent of any actual host/name."""
    return bool(re.search(
        r"\b(?:production|live|current|primary|existing)"
        r"(?:\s+(?:production|live|current|primary|existing)){0,3}"
        r"\s+(?:database|db|target)\b|\bproduction\b", text
    ))


def _bind_restore_target(steps):
    provision = _one_step(steps, r"^provision.*new isolated empty target")
    restore = _one_step(steps, r"^restore complete archive")
    assert provision < restore
    # The immutable runbook elides the destination in its canonical action.
    # Resolve that exact approved action to the sole preceding target declaration.
    # Any destination-bearing variant must explicitly name that isolated target.
    assert steps[provision] == "provision and positively identify a new isolated empty target db."
    action = steps[restore]
    assert not _production_target(action), "restore destination is production/live/current"
    assert re.fullmatch(
        r"restore complete archive(?: into (?:the )?(?:new isolated target|"
        r"isolated database|isolated empty target)(?: database| db)?)?"
        r" under approved ownership/acl policy\.", action
    ), "restore must bind to the declared isolated target, without an alternate destination"
    declarations = [i for i, step in enumerate(steps[:restore])
                    if re.search(r"\b(?:provision|create|select|identify)\b.*\b(?:db|database|target)\b", step)]
    assert declarations == [provision], "ambiguous pre-restore target declarations"


def _check_sequence(section):
    steps = _steps(section, 40)
    _bind_restore_target(steps)
    # Identify actions independently of their assigned number, then prove order.
    actions = (
        r"^identify incident", r"^identify authorized recovery point",
        r"^identify responsible operators", r"^preserve current/failed state",
        r"^retrieve archive", r"^verify authenticity/checksum/readability",
        r"^provision.*new isolated empty target", r"^verify postgresql/client compatibility",
        r"^verify required roles/extensions/encoding/locale", r"^restore complete archive",
        r"^review pg_restore exit status/errors", r"^reject incomplete restoration",
        r"^inspect restored schema", r"^inspect restored alembic revision",
        r"^run authorized read-only database sanity", r"^prepare matching application release.*without starting",
        r"^block provider egress", r"^use isolated/test credentials",
        r"^point isolated validation instance.*only after isolation is verified",
        r"^verify get /health", r"^verify get /ready", r"^verify representative read queries",
        r"^verify authentication", r"^verify protected schema objects/functions/triggers",
        r"^reconcile pending external/provider work", r"^explicitly account for writes",
        r"^approve production cutover", r"^quiesce the old production writer",
        r"^update database_url", r"^restart application", r"^do not run migrations automatically",
        r"^verify /health", r"^verify /ready", r"^verify cache-control: no-store on /ready",
        r"^verify public https", r"^verify authentication", r"^verify representative application behavior",
        r"^verify security headers/session-sensitive responses",
        r"^retain pre-cutover db isolated from writers until recovery acceptance",
        r"^record evidence/operator sign-off",
    )
    # Authentication is deliberately checked twice, before and after cutover.
    auth = [i for i, text in enumerate(steps) if re.search(r"^verify authentication", text)]
    assert auth == [22, 35]
    order = [_one_step(steps, pattern) for pattern in actions if pattern != r"^verify authentication"]
    assert order == sorted(order), "unsafe restore/cutover ordering"
    assert len(set(order)) == 38
    _require(section, "STOP before production cutover", "never permit both databases",
             "If post-cutover /ready fails", "stop acceptance", "Do not blindly switch back")


def _clauses(document):
    """Break sentences and coordinate instructions so negation cannot leak."""
    # A comma followed by a new imperative ends the preceding instruction.
    # Do not split noun lists such as 'roles, global objects and tablespaces'.
    text = _normal(re.sub(r"(?m)^#+ .*\n", "", document))
    return re.split(
        r"[.!?;]\s+|\s+(?:but|however|instead|then)\s+|"
        r",\s*(?=(?:allow|permit|enable|use|run|restore|replace|execute|start|"
        r"send|perform|activate|upload|store|copy|save|keep)\b)", text
    )


def _prohibited(clause, action):
    """Only an immediately attached negator protects an imperative."""
    return bool(re.search(
        r"\b(?:do not|must not|should not|never|cannot|must never|should never)\s+(?:(?:a|an|the)\s+)?$",
        clause[:action.start()],
    ))


def _check_restore_claim(clause):
    for action in re.finditer(r"\b(?:restore|pg_restore|overwrite|replace)\b", clause):
        tail = clause[action.start():]
        # A passive prohibition is a safe statement, not an imperative.
        if re.match(r"overwrite is never the first restore step\b", tail):
            continue
        if _production_target(tail):
            # 'Never use pg_restore ...' attaches the negator to 'use'.
            wrapper = re.search(r"\b(?:run|use|execute)\s+$", clause[:action.start()])
            assert _prohibited(clause, wrapper or action), "affirmative production restore destination"


def _check_provider_claim(clause):
    resource = r"(?:real provider (?:access|egress)|outbound provider egress|real publishing|live payment(?: execution)?|live email(?: delivery)?|(?:production|live) provider credentials)"
    for action in re.finditer(r"\b(?:allow|permit|enable|use|activate|send|perform|start)\b", clause):
        if re.search(resource, clause[action.end():]):
            assert _prohibited(clause, action), "affirmative real provider access/side effect"
    # Also reject passive permission: 'Real provider access is allowed'.
    passive = re.search(resource + r"\s+(?:is|are)\s+(?:allowed|permitted|enabled|required)", clause)
    assert not passive, "passive permission for real providers during recovery"


def _check_recovery_objective_claim(clause):
    if not re.search(r"\brpo\b|\brto\b", clause):
        return
    for claim in re.finditer(r"\b(?:demonstrated|proven|achieved|validated|measured successfully|guaranteed|guarantees?|proves?)\b", clause):
        prefix = clause[:claim.start()]
        assert re.search(r"\b(?:not(?: yet)?(?: been)?|never(?: been)?)\s+$", prefix), (
            "recovery objectives asserted as proven/guaranteed"
        )


def _check_unsafe_claims(document):
    # The specialized classifiers handle destinations, provider permission and
    # recovery claims. Remaining imperative prohibitions share local negation.
    unsafe = (
        r"\bautomatically restore (?:the )?latest\b",
        r"\b(?:automatically|automatic)\s+(?:run\s+)?(?:alembic\s+)?(?:upgrade|downgrade|stamp|migrat)",
        r"\b(?:run|execute|use)\s+(?:alembic\s+upgrade\s+head|create_all|init_db\.py)\b",
        r"\b(?:store|save|keep|copy|back up)\s+plaintext\s+(?:env|environment|secret)",
        r"\b(?:upload|store|publish).*\b(?:dump|backup).*\bci artifacts?\b",
        r"/health\s+(?:is|provides|proves|means|confirms)\s+(?:postgresql\s+|database\s+|db\s+)(?:readiness|correctness)",
        r"/ready\s+(?:is|provides|proves|means|confirms)\s+(?:full\s+)?(?:schema|business|data)\s+(?:readiness|correctness|completeness)",
        r"/health\s+(?:has|returns|guarantees).*cache-control:\s*no-store",
        r"\b(?:routine|automatic)\s+(?:database\s+)?schema rollback\b",
        r"\b(?:drop database|disable triggers)\b",
    )
    for sentence in _clauses(document):
        if re.fullmatch(
            r"do not default to --clean, drop database, destructive reset, trigger disabling or direct overwrite of current production", sentence
        ):
            continue
        _check_restore_claim(sentence)
        _check_provider_claim(sentence)
        _check_recovery_objective_claim(sentence)
        if sentence == "automatic migrations are not authorized":
            continue
        for pattern in unsafe:
            for match in re.finditer(pattern, sentence):
                assert _prohibited(sentence, match), (
                    f"affirmative unsafe instruction: {match[0]}"
                )
    # SQL or shell instructions are not runnable fences in this documentation.
    assert re.findall(r"(?m)^```([^\n]*)$", document) == ["text", ""]
    assert not re.search(r"(?:postgres(?:ql)?(?:\+[\w]+)?|https?)://[^\s<>]+", document, re.I)
    assert not re.search(r"\b(?:\w*(?:password|api_token|api_key)|database_url)\s*[:=]\s*[^\s,;]+", document, re.I)
    assert not re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", document)


def _validate(document):
    sections = _sections(document)
    expected = {
        "Recovery scope", "Backup method and compatibility", "Consistency and provider replay",
        "Security and off-host storage", "Retention and recovery objectives",
        "Naming and protected metadata", "Backup verification", "Periodic restore qualification",
        "Restore safety and permissions", "Restore sequence", "Alembic and schema policy",
        "Health and readiness", "Configuration and secrets recovery",
        "Scheduling and milestone boundary", "Qualification and unresolved deployment decisions",
    }
    assert set(sections) == expected
    _require(document.split("##", 1)[0], "single authoritative PR1D8", "PostgreSQL is the production database authority")
    _require(sections["Recovery scope"], "schema", "table data", "sequences", "indexes",
             "constraints", "functions", "triggers", "captured Alembic version state",
             "matching Git/release", "encryption keys", "External systems of record",
             "No essential generated filesystem data store", "mounts must still be inventoried")
    _require(sections["Backup method and compatibility"], "pg_dump custom-format single-database archive",
             "restore with pg_restore", "complete schema + data", "no table/schema filtering",
             "large-object coverage", "alembic_version rows", "does not inherently preserve cluster roles",
             "global objects or tablespaces", "matching source-major", "older-major",
             "older PostgreSQL major version is not assumed safe", "DEPLOYMENT_DECISION_REQUIRED")
    _require(sections["Consistency and provider replay"], "application remains online",
             "transaction-consistent snapshot", "not backup completion time", "Coordinate schema-changing",
             "eligible for retry or replay", "block real provider egress", "isolated/test credentials",
             "Do not permit real publishing/payment/email/provider side effects", "Reconcile in-flight")
    _require(sections["Security and off-host storage"], "sensitive production data", "encryption at rest",
             "encryption in transit", "least-privilege", "Compression is NOT encryption",
             "Never commit database dumps to Git", "Never upload production dumps as CI artifacts",
             "outside the Git checkout", "leave the production host", "independently durable",
             "recoverable if that host is lost", "Verify transfer", "enforce retention",
             "Never store encryption keys beside", "DEPLOYMENT_DECISION_REQUIRED")
    objectives = sections["Retention and recovery objectives"]
    _require(objectives, "7 daily", "4 weekly", "3 monthly", "not an approved business/legal retention policy",
             "No approved numerical RPO/RTO", "RTO is not yet demonstrated", "every 12 hours",
             "latest verified off-host", "daily schedule does not guarantee", "Escalate missed")
    rows = [tuple(cell.strip() for cell in line.strip("|").split("|"))
            for line in objectives.splitlines() if line.startswith("| R")]
    assert rows == [
        ("RPO", "<= 24 hours", "PROVISIONAL — BUSINESS APPROVAL REQUIRED"),
        ("RTO", "<= 8 hours", "PROVISIONAL — BUSINESS APPROVAL REQUIRED"),
    ]
    _require(sections["Naming and protected metadata"], "UTC", "non-sensitive database alias",
             "etm-affiliate-os_production_<DATABASE_ALIAS>_<YYYYMMDDTHHMMSSZ>_<RELEASE_SHA>.dump.enc",
             "Never include usernames", "DATABASE_URL values or tokens", "snapshot/start/completion",
             "PostgreSQL server/client versions", "Alembic revision(s)", "file size", "checksum",
             "verification result", "configuration-version references", "identifier only",
             "Never store encryption key material")
    checks = _steps(sections["Backup verification"], 7)
    for step, phrase in zip(checks, ("pg_dump successful exit status", "warnings", "non-empty",
                                    "metadata", "sha-256", "pg_restore --list", "transferred/off-host")):
        assert phrase in step
    _require(sections["Backup verification"], "checksum mismatch rejects", "Do not restore it",
             "does not prove a successful full restore", "not semantic correctness")
    _require(sections["Periodic restore qualification"], "monthly isolated restore test", "schema changes",
             "tooling changes", "backup-format changes", "append-only enforcement triggers",
             "read-only application queries", "Missing triggers/functions", "reject restore acceptance")
    _require(sections["Restore safety and permissions"], "PRODUCTION OVERWRITE IS NEVER THE FIRST RESTORE STEP",
             "new isolated database", "explicit operator authorization", "exact selected backup ID",
             "Do not automatically restore latest", "Do not default to --clean", "trusted archives",
             "--no-owner", "--no-acl", "role/grant reconstruction", "Validate production ownership/grants")
    _check_sequence(sections["Restore sequence"])
    _require(sections["Alembic and schema policy"], "captured schema state first", "Inspect restored alembic_version",
             "matching release migration graph", "AUTOMATIC MIGRATIONS ARE NOT AUTHORIZED",
             "Do not automatically upgrade to head", "Do not automatically downgrade", "Do not stamp automatically",
             "Do not run create_all", "Do not run init_db.py", "DO NOT BLINDLY ROLL BACK DATABASE SCHEMA",
             "separately authorized forward migration", "Require a verified recovery point")
    health_rows = [line for line in sections["Health and readiness"].splitlines() if line.startswith("| GET")]
    assert len(health_rows) == 2
    assert health_rows[0].split("|")[2].strip() == "Process liveness only"
    assert health_rows[1].split("|")[2].strip() == "PostgreSQL connection readiness through SELECT 1"
    assert health_rows[0].split("|")[4].strip() == "No frozen no-store header guarantee"
    assert health_rows[1].split("|")[4].strip() == "Cache-Control: no-store on both readiness outcomes"
    _require(sections["Health and readiness"], '200: {"success": true, "status": "healthy"}',
             '200: {"success": true, "status": "ready"}', '503: {"success": false, "status": "not_ready"}',
             "Only /ready has the frozen no-store readiness contract",
             "Neither endpoint proves restored schema completeness", "application-data correctness",
             "trigger/function integrity", "provider reconciliation correctness")
    _require(sections["Configuration and secrets recovery"], "Actual secrets are NOT recoverable from Git",
             "/etc/etm-affiliate-os/etm-affiliate-os.env", "/etc/etm-affiliate-os/caddy.env",
             "appropriate key/access separation", "Never place plaintext env copies beside an unprotected dump")
    _require(sections["Scheduling and milestone boundary"], "named owner", "missed-backup detection",
             "recovery-point age monitoring", "implementation is a deployment decision",
             "PR1D8 owns", "PR1D9 owns total host loss", "infrastructure reconstruction",
             "operational execution of disaster RPO/RTO")
    _require(sections["Qualification and unresolved deployment decisions"], "Windows-safe and static",
             "No database connection", "Deferred live validations", "Real pg_dump creation and real pg_restore",
             "privilege/object coverage", "server-client compatibility", "encryption implementation",
             "encryption key recovery", "off-host transfer", "durability/access control", "Retention enforcement",
             "scheduler behavior", "restore duration/capacity", "real schema/data verification",
             "Provider isolation behavior", "observed RPO/RTO", "Real production cutover",
             "do not block repository freeze", "required before claiming actual operational recoverability")
    _check_unsafe_claims(document)


def test_backup_restore_runbook_contract():
    assert RUNBOOK.is_file()
    _validate(RUNBOOK.read_text(encoding="utf-8"))


def test_frozen_sources_support_documented_recovery_contract():
    # AST/source inspection only: never import settings, engine, init_db or Alembic.
    def source(path):
        return (ROOT / path).read_text(encoding="utf-8-sig")

    config = source("backend/app/core/config.py")
    session = source("backend/app/database/session.py")
    main = ast.parse(source("backend/app/main.py"))
    functions = {node.name: node for node in main.body if isinstance(node, ast.FunctionDef)}
    health = ast.unparse(functions["health"])
    ready = ast.unparse(functions["ready"])
    assert "DATABASE_URL: str" in config
    assert '== "postgresql"' in session and 'text("SELECT 1")' in session
    assert "database_is_ready" not in health and "Cache-Control" not in health
    assert "database_is_ready()" in ready and "'Cache-Control': 'no-store'" in ready
    assert "status_code=503" in ready and "status_code=200" in ready
    assert "script_location = %(here)s/alembic" in source("backend/alembic.ini")
    assert (ROOT / "backend/alembic/versions").is_dir()
    assert "settings.DATABASE_URL" in source("backend/alembic/env.py")
    assert "Base.metadata.create_all(bind=engine)" in source("backend/app/database/init_db.py")
    for path in ("/etc/etm-affiliate-os/etm-affiliate-os.env", "/etc/etm-affiliate-os/caddy.env"):
        assert path in source("docs/DEPLOYMENT.md") and path in RUNBOOK.read_text(encoding="utf-8")


@pytest.mark.parametrize("claim", [
    "Restore directly over production first.",
    "Automatically restore latest.",
    "Automatically run alembic upgrade head.",
    "Automatically downgrade after restore.",
    "Run create_all for recovery.",
    "Run init_db.py for recovery.",
    "Store plaintext environment copies beside the dump.",
    "Upload production dumps as CI artifacts.",
    "Enable real provider access during isolated validation.",
    "/health is database readiness.",
    "/ready proves full schema correctness.",
    "/health guarantees Cache-Control: no-store.",
    "Automatic database schema rollback is routine.",
    "DROP DATABASE before restoration.",
    "DATABASE_URL=postgresql://example.invalid/test",
    "PASSWORD=synthetic-negative-fixture",
    "-----BEGIN PRIVATE KEY-----",
])
def test_rejects_appended_unsafe_claim_even_when_required_text_remains(claim):
    # Synthetic strings are in-memory negative fixtures, never commands or secrets.
    document = RUNBOOK.read_text(encoding="utf-8")
    _validate(document)
    with pytest.raises(AssertionError):
        _validate(document + "\n\n" + claim + "\n")


@pytest.mark.parametrize("first,second", [(6, 10), (17, 19), (21, 27), (27, 29), (28, 29), (30, 33)])
def test_rejects_reordered_restore_gates(first, second):
    document = RUNBOOK.read_text(encoding="utf-8")
    _validate(document)
    section = _sections(document)["Restore sequence"]
    lines = section.splitlines()
    a = next(i for i, line in enumerate(lines) if line.startswith(f"{first}. "))
    b = next(i for i, line in enumerate(lines) if line.startswith(f"{second}. "))
    left, right = lines[a].split(". ", 1)[1], lines[b].split(". ", 1)[1]
    lines[a], lines[b] = f"{first}. {right}", f"{second}. {left}"
    with pytest.raises(AssertionError):
        _validate(document.replace(section, "\n".join(lines)))


@pytest.mark.parametrize("text", [
    "Never commit database dumps to Git.",
    "encryption in transit", "leave the production host", "7 daily recovery points",
    "<= 24 hours", "PROVISIONAL — BUSINESS APPROVAL REQUIRED",
    "monthly isolated restore test", "Missing triggers/functions",
    "Do not run init_db.py", "Only /ready has the frozen no-store readiness contract.",
])
def test_rejects_missing_required_safeguard(text):
    document = RUNBOOK.read_text(encoding="utf-8")
    _validate(document)
    assert text in document
    with pytest.raises(AssertionError):
        _validate(document.replace(text, "REMOVED"))


def test_rejects_duplicate_number_that_could_hide_early_restore():
    document = RUNBOOK.read_text(encoding="utf-8")
    _validate(document)
    with pytest.raises(AssertionError):
        _validate(document.replace("6. Verify authenticity", "6. Restore complete archive.\n6. Verify authenticity"))


def _assert_rejected(mutator):
    document = RUNBOOK.read_text(encoding="utf-8")
    _validate(document)
    changed = mutator(document)
    assert changed != document
    with pytest.raises(AssertionError):
        _validate(changed)


@pytest.mark.parametrize("case", ["canonical-target", "direct-first", "demonstrated", "negation-leak"])
def test_original_four_audit_mutations_are_rejected(case):
    if case == "canonical-target":
        _assert_rejected(lambda d: d.replace(
            "10. Restore complete archive under approved ownership/ACL policy.",
            "10. Restore complete archive into the current production database under approved ownership/ACL policy.",
        ))
    else:
        claims = {
            "direct-first": "Run pg_restore into production as the first recovery action.",
            "demonstrated": "The RPO and RTO targets have already been demonstrated.",
            "negation-leak": "Do not wait, allow real provider access during isolated validation.",
        }
        _assert_rejected(lambda d: d + "\n\n" + claims[case])


@pytest.mark.parametrize("modifier", ["production", "current production", "live", "existing production", "primary"])
@pytest.mark.parametrize("noun", ["database", "DB", "target"])
def test_restore_action_cannot_redirect_to_production_state(modifier, noun):
    _assert_rejected(lambda d: d.replace(
        "10. Restore complete archive under approved ownership/ACL policy.",
        f"10. Restore complete archive into the {modifier} {noun} under approved ownership/ACL policy.",
    ))


@pytest.mark.parametrize("claim", [
    "Run pg_restore into production as the first recovery action.",
    "Restore directly into production.",
    "Restore the latest backup over the live database.",
    "Replace the production database immediately from backup.",
    "Use pg_restore against the current production DB before validation.",
    "Automatically restore latest into production.",
    "Do not delay. Restore directly into production.",
    "Do not wait, allow real provider access during isolated validation.",
    "Do not wait, use live provider credentials during isolated validation.",
    "Use production provider credentials during isolated validation.",
    "Allow real publishing during isolated validation.",
    "Permit live payment execution during isolated validation.",
    "Enable live email delivery during isolated validation.",
    "Allow outbound provider egress during isolated validation.",
    "Real provider access is allowed during isolated validation.",
    "Do not allow real provider access but permit real publishing during isolated validation.",
])
def test_rejects_direct_restore_and_provider_paraphrases(claim):
    _assert_rejected(lambda d: d + "\n\n" + claim)


@pytest.mark.parametrize("result", [
    "demonstrated", "proven", "achieved", "validated", "measured successfully", "guaranteed",
])
def test_rejects_asserted_recovery_objectives(result):
    _assert_rejected(lambda d: d + f"\n\nThe RPO and RTO targets have already been {result}.")


@pytest.mark.parametrize("control", [
    "Do not allow real provider access during isolated validation.",
    "Never restore directly into production as the first step.",
    "Never use pg_restore against the current production DB before validation.",
    "Do not use production provider credentials during isolated validation.",
    "Do not permit live payment execution during isolated validation.",
    "Never enable live email delivery during isolated validation.",
    "The RPO and RTO targets have not yet been demonstrated.",
    "The RPO and RTO targets are not guaranteed.",
    "Production overwrite is never the first restore step.",
])
def test_accepts_tightly_attached_prohibitions_and_unproven_objectives(control):
    document = RUNBOOK.read_text(encoding="utf-8")
    _validate(document)
    _validate(document + "\n\n" + control)


@pytest.mark.parametrize("target", ["new isolated target", "isolated database", "isolated empty target"])
def test_accepts_explicit_binding_to_the_isolated_target(target):
    document = RUNBOOK.read_text(encoding="utf-8")
    _validate(document)
    _validate(document.replace(
        "10. Restore complete archive under approved ownership/ACL policy.",
        f"10. Restore complete archive into the {target} under approved ownership/ACL policy.",
    ))


def test_credentials_cannot_be_established_after_isolated_startup():
    # Egress ordering and old-writer ordering are covered above; credentials are
    # an independent prerequisite and must not be inferred from blocked egress.
    test_rejects_reordered_restore_gates(18, 19)
