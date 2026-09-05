"""Static contract for the PR1D7 production deployment runbook."""

from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = REPOSITORY_ROOT / "docs" / "DEPLOYMENT.md"
CADDYFILE = REPOSITORY_ROOT / "deployment" / "Caddyfile"
SERVICE_UNIT = REPOSITORY_ROOT / "deployment" / "etm-affiliate-os.service"
CADDY_DROP_IN = (
    REPOSITORY_ROOT / "deployment" / "caddy.service.d" / "etm-affiliate-os.conf"
)
LAUNCHER = REPOSITORY_ROOT / "deployment" / "start-production.sh"
READINESS_TESTS = REPOSITORY_ROOT / "backend" / "tests" / "test_production_readiness.py"
CI_RUNNER = REPOSITORY_ROOT / "backend" / "scripts" / "qualify_pr1d6_ci.py"
CONFIG = REPOSITORY_ROOT / "backend" / "app" / "core" / "config.py"
DATABASE_SESSION = REPOSITORY_ROOT / "backend" / "app" / "database" / "session.py"
APP_MAIN = REPOSITORY_ROOT / "backend" / "app" / "main.py"
API_SECURITY = REPOSITORY_ROOT / "backend" / "app" / "core" / "api_security.py"
CI_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "pr1d6-production-qualification.yml"


def _section(document: str, heading: str) -> str:
    marker = f"## {heading}\n"
    assert marker in document, f"missing runbook section: {heading}"
    return document.split(marker, 1)[1].split("\n## ", 1)[0]


def _unit_values(text: str) -> dict[str, str]:
    return {
        key: value
        for line in text.splitlines()
        if "=" in line and not line.startswith("[")
        for key, value in [line.split("=", 1)]
    }


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _deployment_steps(document: str) -> dict[int, str]:
    section = _section(document, "Deployment sequence")
    matches = list(re.finditer(r"(?m)^(\d+)\.\s+(.+?)(?=\n\d+\.\s|\Z)", section, re.S))
    return {int(match.group(1)): _normalise(match.group(2)) for match in matches}


def _step_number(steps: dict[int, str], required_text: str) -> int:
    matches = [number for number, text in steps.items() if required_text in text]
    assert len(matches) == 1, f"expected one deployment step containing {required_text!r}"
    return matches[0]


def test_runbook_matches_frozen_topology_service_and_environment_contracts():
    assert RUNBOOK.is_file()
    document = RUNBOOK.read_text(encoding="utf-8")
    caddy = CADDYFILE.read_text(encoding="utf-8")
    unit_text = SERVICE_UNIT.read_text(encoding="utf-8")
    unit = _unit_values(unit_text)
    launcher = LAUNCHER.read_text(encoding="utf-8")
    config = CONFIG.read_text(encoding="utf-8")
    topology = _section(document, "Frozen topology")
    paths = _section(document, "Filesystem and service layout")
    environment = _section(document, "Production environment and secrets")

    assert "authoritative production deployment and operations runbook" in document
    assert "Internet\n→ Caddy HTTPS\n→ 127.0.0.1:8000\n→ one Uvicorn worker\n→ app.main:app\n→ PostgreSQL" in topology
    assert "not an externally reachable Uvicorn service" in topology
    for path in ("/opt/etm-affiliate-os", "/opt/etm-affiliate-os/backend", "/opt/etm-affiliate-os/backend/.venv", "/etc/etm-affiliate-os/etm-affiliate-os.env", "/etc/etm-affiliate-os/caddy.env"):
        assert path in paths
    for key in ("User", "Group", "WorkingDirectory", "EnvironmentFile", "ExecStart", "Restart", "RestartSec", "KillSignal", "NoNewPrivileges", "PrivateTmp"):
        assert unit[key] in paths
    assert "/etc/etm-affiliate-os/caddy.env" in CADDY_DROP_IN.read_text(encoding="utf-8")
    assert "/opt/etm-affiliate-os/backend/.venv/bin/python" in paths
    for flag in ("--host 127.0.0.1", "--workers 1", "--proxy-headers", "--forwarded-allow-ips 127.0.0.1"):
        assert flag in launcher and flag in document
    assert "app.main:app" in launcher and "app.main:app" in topology

    for name in ("DATABASE_URL", "OPERATOR_API_TOKEN", "SERVICE_API_TOKEN", "APP_NAME", "ENV=production"):
        assert name in environment
    assert "distinct" in environment
    assert "ETM_AFFILIATE_OS_DOMAIN" in environment
    assert "only in" in environment and "caddy.env" in environment
    assert "DATABASE_ECHO=false" in environment
    assert "OPERATOR_SESSION_COOKIE_SECURE=true" in environment
    timeout = re.search(r"DATABASE_CONNECTION_TIMEOUT_SECONDS:\s*int\s*=\s*Field\(default=(\d+), ge=(\d+), le=(\d+)\)", config)
    assert timeout
    default, minimum, maximum = timeout.groups()
    for required in ("DATABASE_CONNECTION_TIMEOUT_SECONDS", f"default is {default}", f"range is {minimum}", f"through {maximum}", "connection and pool-acquisition"):
        assert required in environment


def test_deployment_sequence_is_ordered_and_rejects_early_caddy_activation():
    document = RUNBOOK.read_text(encoding="utf-8")
    steps = _deployment_steps(document)
    assert list(steps) == list(range(1, 30))
    application_start = _step_number(steps, "enable and start the application service")
    health = _step_number(steps, "localhost `get /health` returns http 200")
    ready = _step_number(steps, "localhost `get /ready` returns http 200")
    caddy_validation = _step_number(steps, "validate native caddy configuration")
    caddy_activation = _step_number(steps, "enable, start, or reload caddy")
    public_https = _step_number(steps, "verify public https/tls")
    assert application_start < health < ready < caddy_validation < caddy_activation < public_https
    activation_steps = [number for number, text in steps.items() if "caddy" in text and re.search(r"\b(enable|start|reload|restart)\b", text)]
    assert activation_steps == [caddy_activation]
    assert "only after both localhost liveness and readiness pass" in steps[caddy_validation]
    normal_sequence = " ".join(steps.values())
    assert "alembic" not in normal_sequence
    assert "create_all" not in normal_sequence
    assert "schema initialization" not in normal_sequence


def test_runbook_protects_migration_health_caddy_and_rollback_contracts():
    document = RUNBOOK.read_text(encoding="utf-8")
    migration = _section(document, "Migration policy")
    health = _normalise(_section(document, "Health and readiness"))
    caddy_contract = _normalise(_section(document, "Caddy operational contract"))
    rollback = _normalise(_section(document, "Rollback"))
    caddy = CADDYFILE.read_text(encoding="utf-8")
    app_main = APP_MAIN.read_text(encoding="utf-8")
    session = DATABASE_SESSION.read_text(encoding="utf-8")
    security = API_SECURITY.read_text(encoding="utf-8")

    assert "AUTOMATIC MIGRATIONS ARE NOT AUTHORIZED." in migration
    assert "MANUAL MIGRATION — DO NOT RUN WITHOUT EXPLICIT AUTHORIZATION" in migration
    assert not re.search(r"\balembic\s+(?:upgrade|downgrade|stamp|current)\b", document, re.I)
    assert "database_is_ready" in app_main and "SELECT 1" in session
    assert "OPERATOR_API_TOKEN" in security and "SERVICE_API_TOKEN" in security
    for required in ("process liveness only", "not database readiness", '"status": "healthy"', "postgresql", "not a retry-manager gate", '"status": "ready"', '"status": "not_ready"', "http 503", "cache-control: no-store"):
        assert required in health
    assert "health is database readiness" not in health

    assert "{$ETM_AFFILIATE_OS_DOMAIN}" in caddy
    assert "reverse_proxy 127.0.0.1:8000" in caddy
    for caddy_directive, documented_header in (
        ('Strict-Transport-Security "max-age=31536000"', "strict-transport-security: max-age=31536000"),
        ('X-Content-Type-Options "nosniff"', "x-content-type-options: nosniff"),
        ('Referrer-Policy "strict-origin-when-cross-origin"', "referrer-policy: strict-origin-when-cross-origin"),
        ('Permissions-Policy "camera=(), microphone=(), geolocation=()"', "permissions-policy: camera=(), microphone=(), geolocation=()"),
        ('X-Frame-Options "DENY"', "x-frame-options: deny"),
    ):
        assert caddy_directive in caddy and documented_header in caddy_contract
    for prohibited in ("do not add csp", "csp is not currently enforced", "no cors headers", "no proxy caching", "no explicit access-log directive"):
        assert prohibited in caddy_contract
    assert "csp currently enforced" not in _normalise(document)
    assert "caddy is cors authority" not in _normalise(document)

    for required in ("known-good prior release or commit", "restart or reload the application service", "rerun localhost `/health`", "rerun localhost `/ready`", "known-good external application environment configuration", "never recover secrets from git history", "validate caddy configuration **before** any reload or restart", "public https", "reverse-proxy behavior", "security headers", "dns, tls, and firewall correction", "loopback service remains available", "do not unnecessarily roll back healthy application code", "do not blindly roll back database schema"):
        assert required in rollback
    assert "routine database schema rollback" not in rollback
    assert "automatic database schema rollback" not in rollback


def test_troubleshooting_validation_boundary_and_secret_contracts():
    document = RUNBOOK.read_text(encoding="utf-8")
    troubleshooting = _normalise(_section(document, "Basic troubleshooting"))
    validation = _normalise(_section(document, "Deployment validation checklist"))
    local_vs_live = _normalise(_section(document, "Repository-qualified and deployment-host validation"))

    for required in ("application service fails to start", "systemd status", "`/ready` returns 503", "postgresql availability", "https or certificate failure", "domain dns", "public proxy failure with healthy loopback endpoint", "firewall/dns policy", "public https succeeds but authenticated operation fails", "api authentication configuration", "operator_api_token", "service_api_token", "session/cookie configuration", "cors configuration", "route authority expectations"):
        assert required in troubleshooting
    assert "do not reset a database" in troubleshooting
    assert "pr1d6 ci baseline" in validation and CI_RUNNER.is_file() and CI_WORKFLOW.is_file()
    for phrase in ("windows-safe", "linux systemd behavior", "caddy", "dns", "tls", "postgresql", "migrations"):
        assert phrase in local_vs_live

    assert "<PRODUCTION_DOMAIN>" in document
    assert "ETM_AFFILIATE_OS_DOMAIN" in document
    assert not re.search(r"postgres(?:ql)?://[^\s<>]+", document, re.I)
    assert not re.search(r"(?:operator|service)_api_token\s*=\s*(?!<)[^\s`]+", document, re.I)
    assert not re.search(r"(?:database_url|password)\s*=\s*(?!<)[^\s`]+", document, re.I)
    assert not re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", document)
    assert not re.search(r"https?://[^\s<>`]+", document, re.I)
