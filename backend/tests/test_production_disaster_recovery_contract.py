from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]

RUNBOOK_PATH = ROOT / "docs" / "DISASTER_RECOVERY.md"
DEPLOYMENT_PATH = ROOT / "docs" / "DEPLOYMENT.md"
BACKUP_RESTORE_PATH = ROOT / "docs" / "BACKUP_RESTORE.md"

LAUNCHER_PATH = ROOT / "deployment" / "start-production.sh"
SERVICE_PATH = ROOT / "deployment" / "etm-affiliate-os.service"
CADDY_PATH = ROOT / "deployment" / "Caddyfile"


REQUIRED_SECTIONS = (
    "Classification and severity",
    "Recovery objectives",
    "Roles and authorization",
    "Decision tree",
    "Replacement-host preparation",
    "Database disaster path",
    "Full environment loss sequence",
    "One-writer fencing",
    "DNS and edge reconstruction",
    "Secrets and configuration",
    "Containment and trust",
    "Provider reconciliation",
    "Acceptance gates",
    "Abort and fallback",
    "Evidence and communications",
    "Drills and validation boundary",
    "Unresolved deployment decisions",
)


def _read(path: Path) -> str:
    assert path.exists(), f"required file missing: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _sections(text: str) -> dict[str, str]:
    lines = text.splitlines()
    found: dict[str, list[str]] = {}
    current: str | None = None

    for line in lines:
        match = re.match(r"^##\s+(.+?)\s*$", line)

        if match:
            current = match.group(1).strip()
            assert current not in found, f"duplicate section: {current}"
            found[current] = []
            continue

        if current is not None:
            found[current].append(line)

    return {name: "\n".join(body).strip() for name, body in found.items()}


def _steps(section: str) -> dict[int, str]:
    result: dict[int, str] = {}

    for line in section.splitlines():
        match = re.match(r"^\s*(\d+)\.\s+(.+?)\s*$", line)

        if not match:
            continue

        number = int(match.group(1))
        assert number not in result, f"duplicate recovery step: {number}"
        result[number] = match.group(2).strip()

    return result


def _clauses(text: str) -> list[str]:
    # Split strongly enough that:
    #
    #   "Do not wait, allow real provider access ..."
    #
    # becomes two independent instructions.  This prevents negation leakage
    # from an unrelated earlier clause.
    pieces = re.split(
        r"(?:[.!?;]\s+|\n+|,\s+(?=[A-Za-z]))",
        text,
    )
    return [_norm(piece) for piece in pieces if piece.strip()]


def _has_local_negation(clause: str, action_match: re.Match[str]) -> bool:
    before = clause[: action_match.start()]

    return bool(
        re.search(
            r"\b(?:do not|don't|never|must not|cannot|can't|"
            r"prohibit(?:ed)?|reject(?:ed)?|blocked|not authorized|"
            r"not permitted|not allowed)\b",
            before,
        )
    )


def _contradictions(text: str) -> list[str]:
    errors: list[str] = []

    for clause in _clauses(text):

        # Direct restore into current/live/production DB.
        restore_action = re.search(
            r"\b(?:restore|pg_restore|replace)\b",
            clause,
        )

        production_target = re.search(
            r"\b(?:current\s+production|existing\s+production|"
            r"production|live|primary)\s+(?:database|db|target)\b",
            clause,
        )

        if restore_action and production_target:
            if not _has_local_negation(clause, restore_action):
                if re.search(
                    r"\b(?:into|over|against|directly|first|immediately|replace)\b",
                    clause,
                ):
                    errors.append(
                        f"unsafe direct-production restore instruction: {clause}"
                    )

        # Provider access during isolated/private validation.
        provider_action = re.search(
            r"\b(?:allow|enable|permit|use|resume)\b",
            clause,
        )

        provider_resource = re.search(
            r"\b(?:real provider (?:access|egress)|"
            r"outbound provider egress|"
            r"(?:production|live) provider credentials|"
            r"real publishing|live payment|live email)\b",
            clause,
        )

        isolated_context = re.search(
            r"\b(?:isolated|private)\s+(?:validation|recovery|environment)\b",
            clause,
        )

        if provider_action and provider_resource and isolated_context:
            if not _has_local_negation(clause, provider_action):
                errors.append(
                    f"unsafe provider access during isolated validation: {clause}"
                )

        # Public Uvicorn emergency exposure.
        uvicorn_action = re.search(
            r"\b(?:bind|expose|run|allow)\b",
            clause,
        )

        if (
            uvicorn_action
            and "uvicorn" in clause
            and "0.0.0.0" in clause
            and not _has_local_negation(clause, uvicorn_action)
        ):
            errors.append(f"unsafe public uvicorn exposure: {clause}")

        # Caddy bypass.
        caddy_action = re.search(
            r"\b(?:bypass|skip|avoid)\b",
            clause,
        )

        if (
            caddy_action
            and "caddy" in clause
            and re.search(r"\b(?:public|expose|production)\b", clause)
            and not _has_local_negation(clause, caddy_action)
        ):
            errors.append(f"unsafe caddy bypass: {clause}")

        # Automatic migration.
        migration_action = re.search(
            r"\b(?:run|execute|apply)\b",
            clause,
        )

        if (
            migration_action
            and re.search(r"\balembic\s+upgrade\s+head\b", clause)
            and not _has_local_negation(clause, migration_action)
        ):
            errors.append(f"automatic alembic upgrade permitted: {clause}")

        downgrade_action = re.search(
            r"\b(?:run|execute|apply)\b",
            clause,
        )

        if (
            downgrade_action
            and re.search(r"\balembic\s+downgrade\b", clause)
            and not _has_local_negation(clause, downgrade_action)
        ):
            errors.append(f"automatic alembic downgrade permitted: {clause}")

        create_action = re.search(
            r"\b(?:run|execute|use)\b",
            clause,
        )

        if (
            create_action
            and re.search(r"\bcreate_all\b", clause)
            and not _has_local_negation(clause, create_action)
        ):
            errors.append(f"create_all recovery permitted: {clause}")

        init_action = re.search(
            r"\b(?:run|execute|use)\b",
            clause,
        )

        if (
            init_action
            and re.search(r"\binit_db\b", clause)
            and not _has_local_negation(clause, init_action)
        ):
            errors.append(f"init_db recovery permitted: {clause}")

        # Secrets recovered from Git.
        secret_action = re.search(
            r"\b(?:recover|retrieve|obtain|restore)\b",
            clause,
        )

        if (
            secret_action
            and "git" in clause
            and re.search(
                r"\b(?:secret|secrets|credential|credentials|token|tokens)\b",
                clause,
            )
            and not _has_local_negation(clause, secret_action)
        ):
            errors.append(f"unsafe secret recovery from git: {clause}")

        # Demonstrated/guaranteed RPO/RTO claims.
        if "rpo" in clause and "rto" in clause:
            objective_claim = re.search(
                r"\b(?:targets?|objectives?)\b.*"
                r"\b(?:demonstrated|proven|guaranteed|already achieved|validated)\b",
                clause,
            )

            if objective_claim and not re.search(
                r"\b(?:not|never|have not|has not)\b",
                clause[: objective_claim.end()],
            ):
                errors.append(
                    f"recovery objectives falsely claimed demonstrated: {clause}"
                )

        # DNS/process state alone must not be described as fencing.
        if re.search(
            r"\b(?:dns (?:change|changed|cutover)|"
            r"process (?:stop|stopped)|host (?:offline|unreachable))\b",
            clause,
        ) and re.search(
            r"\b(?:is|are|proves?|provides?)\s+(?:sufficient|enough|complete)\s+fencing\b",
            clause,
        ):
            if not re.search(r"\b(?:not|never)\b", clause):
                errors.append(f"weak fencing falsely accepted: {clause}")

        # Recovery cannot be accepted while readiness fails.
        accept_action = re.search(
            r"\b(?:accept|approve|complete)\s+(?:the\s+)?recovery\b",
            clause,
        )

        if (
            accept_action
            and re.search(r"/ready\s+(?:fails|failed|is failing)", clause)
            and not _has_local_negation(clause, accept_action)
        ):
            errors.append(f"recovery accepted with failed readiness: {clause}")

    return errors


def _validate_runbook(text: str) -> list[str]:
    errors: list[str] = []

    sections = _sections(text)

    for required in REQUIRED_SECTIONS:
        if required not in sections:
            errors.append(f"missing required section: {required}")

    if errors:
        return errors

    normalized = _norm(text)

    required_authorities = (
        "docs/deployment.md",
        "docs/backup_restore.md",
    )

    for authority in required_authorities:
        if authority not in normalized:
            errors.append(f"missing frozen authority reference: {authority}")

    for tier in ("dr-0", "dr-1", "dr-2", "dr-3"):
        if tier not in normalized:
            errors.append(f"missing severity tier: {tier}")

    objectives = _norm(sections["Recovery objectives"])

    if "<= 24 hours" not in objectives and "≤ 24 hours" not in objectives:
        errors.append("missing provisional RPO <=24 hours")

    if "<= 8 hours" not in objectives and "≤ 8 hours" not in objectives:
        errors.append("missing provisional RTO <=8 hours")

    if "provisional" not in objectives:
        errors.append("RPO/RTO are not marked provisional")

    if "business approval required" not in objectives:
        errors.append("RPO/RTO business approval requirement missing")

    if "rto starts at actual service disruption" not in objectives:
        errors.append("RTO does not start at actual service disruption")

    roles = _norm(sections["Roles and authorization"])

    for marker in (
        "incident lead",
        "infrastructure/network/dns operator",
        "database recovery operator",
        "application operator",
        "business/provider reconciliation approver",
        "database_url",
        "dns",
        "provider",
    ):
        if marker not in roles:
            errors.append(f"missing role/authorization marker: {marker}")

    sequence = _steps(sections["Full environment loss sequence"])

    expected_numbers = list(range(1, 51))

    if sorted(sequence) != expected_numbers:
        errors.append(
            "full-loss sequence must contain exactly consecutive steps 1..50"
        )
        return errors + _contradictions(text)

    required_step_fragments = {
        1: "service disruption time",
        4: "rto",
        8: "approved verified recovery point",
        14: "target identities",
        15: "pr1d8 isolated restore",
        16: "schema/alembic",
        17: "provider egress block",
        18: "isolated/test credentials",
        19: "private validation ingress",
        20: "start replacement application privately",
        21: "/health",
        22: "/ready",
        26: "reconcile",
        28: "validate native caddy",
        30: "dns target",
        32: "cutover approval",
        33: "old-writer fencing",
        34: "old provider workers/egress",
        35: "database_url target identity",
        36: "dns/tls transition",
        37: "production writes",
        38: "provider work",
        39: "public traffic",
        44: "one intended production writer",
        46: "recovery point age",
        47: "achieved rto",
        49: "acceptance/sign-off",
        50: "after acceptance",
    }

    for number, fragment in required_step_fragments.items():
        if fragment not in _norm(sequence[number]):
            errors.append(
                f"step {number} does not preserve required action: {fragment}"
            )

    # Explicit ordering gates.
    ordered = (
        14, 15, 16,
        17, 18, 19, 20,
        21, 22, 23, 24, 25,
        26,
        27, 28, 29, 30, 31,
        32,
        33, 34, 35,
        36,
        37, 38, 39,
        40, 41, 42, 43, 44,
        49, 50,
    )

    if list(ordered) != sorted(ordered):
        errors.append("internal recovery ordering contract invalid")

    fencing = _norm(sections["One-writer fencing"])

    for marker in (
        "sole intended production writer",
        "changing dns is not fencing",
        "cutover blocked",
        "do not enable replacement production writes before fencing",
        "do not change database_url before target identity verification",
    ):
        if marker not in fencing:
            errors.append(f"missing one-writer safeguard: {marker}")

    provider = _norm(sections["Provider reconciliation"])

    for marker in (
        "provider egress blocked",
        "isolated/test",
        "before replacement startup",
        "retry",
        "external systems",
    ):
        if marker not in provider:
            errors.append(f"missing provider safeguard: {marker}")

    acceptance = _norm(sections["Acceptance gates"])

    for marker in (
        "/health",
        "/ready",
        "one intended production writer",
        "schema/alembic",
        "authentication",
        "security",
    ):
        if marker not in acceptance:
            errors.append(f"missing acceptance gate: {marker}")

    abort = _norm(sections["Abort and fallback"])

    for marker in (
        "checksum",
        "secret",
        "restore",
        "old writer",
        "replay",
        "dns",
        "/ready",
    ):
        if marker not in abort:
            errors.append(f"missing abort/fallback gate: {marker}")

    live = _norm(sections["Drills and validation boundary"])

    for marker in (
        "repository freeze does not equal demonstrated disaster recoverability",
        "real dns",
        "real certificate",
        "durable one-writer fencing",
        "achieved rpo",
        "achieved rto",
        "full isolated recovery drill",
    ):
        if marker not in live:
            errors.append(f"missing deferred-live-validation marker: {marker}")

    errors.extend(_contradictions(text))

    return errors


def _replace_required(text: str, old: str, new: str) -> str:
    assert old in text, f"mutation source missing: {old}"
    return text.replace(old, new, 1)


def test_pr1d9_runbook_contract() -> None:
    text = _read(RUNBOOK_PATH)
    errors = _validate_runbook(text)
    assert not errors, "\n".join(errors)


def test_pr1d9_frozen_authorities_remain_distinct() -> None:
    runbook = _norm(_read(RUNBOOK_PATH))
    deployment = _read(DEPLOYMENT_PATH)
    backup = _read(BACKUP_RESTORE_PATH)

    assert deployment.strip()
    assert backup.strip()

    assert "docs/deployment.md" in runbook
    assert "docs/backup_restore.md" in runbook

    assert "pr1d7" in runbook
    assert "pr1d8" in runbook

    assert "normal deployment" in runbook
    assert "isolated restore" in runbook


def test_pr1d9_matches_frozen_runtime_topology() -> None:
    runbook = _norm(_read(RUNBOOK_PATH))

    launcher = _norm(_read(LAUNCHER_PATH))
    service = _norm(_read(SERVICE_PATH))
    caddy = _norm(_read(CADDY_PATH))

    assert "127.0.0.1" in launcher
    assert "--workers 1" in launcher or "--workers=1" in launcher
    assert "127.0.0.1:8000" in caddy

    assert "user=etm-affiliate" in service
    assert "group=etm-affiliate" in service
    assert "workingdirectory=/opt/etm-affiliate-os" in service

    assert "0.0.0.0" in runbook
    assert "do not bind uvicorn publicly to 0.0.0.0" in runbook
    assert "do not bypass caddy" in runbook


NEGATIVE_MUTATIONS = (
    (
        "provider block removed before startup",
        lambda t: _replace_required(
            t,
            "17. Establish provider egress block.",
            "17. Record provider configuration.",
        ),
    ),
    (
        "isolated credentials removed before startup",
        lambda t: _replace_required(
            t,
            "18. Establish isolated/test credentials.",
            "18. Record credentials.",
        ),
    ),
    (
        "old-writer fencing delayed",
        lambda t: _replace_required(
            t,
            "33. Prove old-writer fencing.",
            "33. Record old-writer status.",
        ),
    ),
    (
        "public traffic before approval",
        lambda t: _replace_required(
            t,
            "32. Obtain explicit cutover approval.",
            "32. Enable public traffic.",
        ),
    ),
    (
        "database target verification removed",
        lambda t: _replace_required(
            t,
            "35. Verify replacement DATABASE_URL target identity.",
            "35. Record replacement configuration.",
        ),
    ),
    (
        "direct production restore first",
        lambda t: t
        + "\nRun pg_restore directly into the current production database as the first recovery action.\n",
    ),
    (
        "automatic restore latest",
        lambda t: t
        + "\nRestore the latest backup over the live database immediately.\n",
    ),
    (
        "provider access allowed",
        lambda t: t
        + "\nAllow real provider access during isolated validation.\n",
    ),
    (
        "negation leakage provider access",
        lambda t: t
        + "\nDo not wait, allow real provider access during isolated validation.\n",
    ),
    (
        "live credentials during isolation",
        lambda t: t
        + "\nUse production provider credentials during isolated validation.\n",
    ),
    (
        "automatic alembic head",
        lambda t: t
        + "\nRun alembic upgrade head automatically during disaster recovery.\n",
    ),
    (
        "automatic downgrade",
        lambda t: t
        + "\nRun alembic downgrade during disaster recovery.\n",
    ),
    (
        "create_all recovery",
        lambda t: t + "\nRun create_all for recovery.\n",
    ),
    (
        "init_db recovery",
        lambda t: t + "\nRun init_db for recovery.\n",
    ),
    (
        "public uvicorn",
        lambda t: t
        + "\nBind Uvicorn publicly to 0.0.0.0 as an emergency shortcut.\n",
    ),
    (
        "caddy bypass",
        lambda t: t
        + "\nBypass Caddy and expose the application publicly.\n",
    ),
    (
        "git secret recovery",
        lambda t: t
        + "\nRecover production secrets from Git before startup.\n",
    ),
    (
        "objectives demonstrated",
        lambda t: t
        + "\nThe RPO and RTO targets have already been demonstrated.\n",
    ),
    (
        "objectives guaranteed",
        lambda t: t
        + "\nThe RPO and RTO objectives are guaranteed.\n",
    ),
    (
        "dns alone is fencing",
        lambda t: t
        + "\nDNS changed is sufficient fencing for the old environment.\n",
    ),
    (
        "stopped process alone is fencing",
        lambda t: t
        + "\nProcess stopped is sufficient fencing for the old writer.\n",
    ),
    (
        "accept with failed readiness",
        lambda t: t
        + "\nAccept recovery while /ready fails.\n",
    ),
)


@pytest.mark.parametrize(
    ("name", "mutate"),
    NEGATIVE_MUTATIONS,
    ids=[name for name, _ in NEGATIVE_MUTATIONS],
)
def test_pr1d9_rejects_unsafe_mutations(name, mutate) -> None:
    text = _read(RUNBOOK_PATH)
    mutated = mutate(text)

    errors = _validate_runbook(mutated)

    assert errors, f"unsafe mutation was incorrectly accepted: {name}"


POSITIVE_CONTROLS = (
    "Never restore directly into production as the first recovery action.",
    "Do not allow real provider access during isolated validation.",
    "The RPO and RTO targets have not been demonstrated.",
    "Do not bind Uvicorn publicly to 0.0.0.0.",
    "Do not bypass Caddy to expose the application publicly.",
)


@pytest.mark.parametrize("safe_text", POSITIVE_CONTROLS)
def test_pr1d9_accepts_explicit_prohibitions(safe_text: str) -> None:
    text = _read(RUNBOOK_PATH)
    candidate = text + "\n" + safe_text + "\n"

    errors = _validate_runbook(candidate)

    assert not errors, "\n".join(errors)
