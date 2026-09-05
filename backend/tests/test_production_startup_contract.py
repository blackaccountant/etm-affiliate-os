import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
START_SCRIPT = REPOSITORY_ROOT / "deployment" / "start-production.sh"
SYSTEMD_UNIT = REPOSITORY_ROOT / "deployment" / "etm-affiliate-os.service"
PRODUCTION_WORKERS = 1
PRODUCTION_REPLICAS = 1


def _artifact_text(path: Path) -> str:
    assert path.is_file(), f"missing deployment artifact: {path}"
    return path.read_text(encoding="utf-8")


def test_start_script_is_single_worker_loopback_uvicorn_launcher():
    script = _artifact_text(START_SCRIPT)
    port_defaulting = script.split('if [ "${PORT+x}" = "x" ]; then', 1)[1].split('case "$PORT" in', 1)[0]
    explicit_port_branch, unset_port_branch = port_defaulting.split("else", 1)

    assert script.startswith("#!/bin/sh\nset -eu\n")
    assert 'cd "$REPOSITORY_ROOT/backend"' in script
    assert 'exec "$PYTHON" -m uvicorn app.main:app' in script
    assert "--host 127.0.0.1" in script
    assert '--port "$PORT"' in script
    assert "--workers 1" in script
    assert "PORT must be an integer between 1 and 65535" in script
    assert "backend/.venv/bin/python" in script
    assert "PORT=${PORT:-8000}" not in script
    assert 'if [ "${PORT+x}" = "x" ]; then' in script
    assert 'if [ -z "$PORT" ]; then' in explicit_port_branch
    assert "PORT must not be empty" in explicit_port_branch
    assert "exit 1" in explicit_port_branch
    assert unset_port_branch.count("PORT=8000") == 1
    assert "''|*[!0-9]*)" in script
    assert '[ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]' in script


def test_start_script_excludes_development_network_and_migration_behavior():
    script = _artifact_text(START_SCRIPT).lower()

    for forbidden in (
        "--reload",
        "0.0.0.0",
        "gunicorn",
        "watchfiles",
        "watchgod",
        "alembic",
        " upgrade",
        " downgrade",
        " stamp",
        " current",
        "create_all",
    ):
        assert forbidden not in script
    assert not re.search(r"(?<![>&])&(?![&>])", script)


def test_start_script_uses_exec_without_restart_or_background_supervision():
    script = _artifact_text(START_SCRIPT)

    assert re.search(r'^exec "\$PYTHON" -m uvicorn app\.main:app', script, flags=re.MULTILINE)
    assert "while " not in script
    assert "until " not in script
    assert "trap " not in script


def test_systemd_unit_is_single_dedicated_service_with_external_environment():
    unit = _artifact_text(SYSTEMD_UNIT)

    assert "Description=ETM Affiliate OS" in unit
    assert "User=etm-affiliate" in unit
    assert "Group=etm-affiliate" in unit
    assert "WorkingDirectory=/opt/etm-affiliate-os" in unit
    assert "EnvironmentFile=/etc/etm-affiliate-os/etm-affiliate-os.env" in unit
    assert "EnvironmentFile=-" not in unit
    assert "ExecStart=/opt/etm-affiliate-os/deployment/start-production.sh" in unit
    assert "Restart=on-failure" in unit
    assert "KillSignal=SIGTERM" in unit
    assert "NoNewPrivileges=true" in unit
    assert "PrivateTmp=true" in unit
    assert "@.service" not in SYSTEMD_UNIT.name
    assert "gunicorn" not in unit.lower()


def test_deployment_artifacts_contain_no_embedded_credentials_or_secret_assignments():
    artifacts = _artifact_text(START_SCRIPT) + "\n" + _artifact_text(SYSTEMD_UNIT)

    forbidden_patterns = (
        r"postgres(?:ql)?(?:\+[a-z0-9_]+)?://",
        r"bearer\s+[a-z0-9._-]{16,}",
        r"(?:database_url|operator_api_token|service_api_token|openai_api_key|resend_api_key)\s*=",
        r"password\s*=",
    )
    assert all(not re.search(pattern, artifacts, flags=re.IGNORECASE) for pattern in forbidden_patterns)


def test_single_process_replica_contract_is_explicit():
    script = _artifact_text(START_SCRIPT)
    unit = _artifact_text(SYSTEMD_UNIT)

    assert PRODUCTION_WORKERS == 1
    assert PRODUCTION_REPLICAS == 1
    assert script.count("--workers 1") == 1
    assert unit.count("ExecStart=") == 1
