import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CADDYFILE = REPOSITORY_ROOT / "deployment" / "Caddyfile"
CADDY_DROP_IN = REPOSITORY_ROOT / "deployment" / "caddy.service.d" / "etm-affiliate-os.conf"
START_SCRIPT = REPOSITORY_ROOT / "deployment" / "start-production.sh"
OPERATOR_CONSOLE = REPOSITORY_ROOT / "backend" / "app" / "operator_console.py"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing deployment artifact: {path}"
    return path.read_text(encoding="utf-8")


def _option_values(script: str, option: str) -> list[str]:
    pattern = rf"^\s*{re.escape(option)}\s+([^\s\\]+)\s*\\?\s*$"
    return re.findall(pattern, script, flags=re.MULTILINE)


def _active_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _top_level_site_addresses(caddyfile: str) -> list[str]:
    return [
        line[:-1].strip()
        for line in caddyfile.splitlines()
        if line
        and not line[0].isspace()
        and not line.lstrip().startswith("#")
        and line.rstrip().endswith("{")
    ]


def _header_values(caddyfile: str, header_name: str) -> list[str]:
    pattern = rf"^\s*{re.escape(header_name)}\s+(.+?)\s*$"
    return re.findall(pattern, caddyfile, flags=re.MULTILINE)


def test_caddyfile_uses_exactly_one_external_domain_site_and_frozen_loopback_upstream():
    caddyfile = _active_lines(_read(CADDYFILE))

    assert _top_level_site_addresses(caddyfile) == ["{$ETM_AFFILIATE_OS_DOMAIN}"]
    assert caddyfile.count("reverse_proxy") == 1
    assert re.search(r"^\s*reverse_proxy 127\.0\.0\.1:8000\s*$", caddyfile, flags=re.MULTILINE)
    assert "0.0.0.0" not in caddyfile
    assert "localhost" not in caddyfile.lower()
    assert "http://" not in caddyfile.lower()
    assert "https://" not in caddyfile.lower()


def test_caddyfile_has_compatible_headers_without_csp_cors_cache_or_access_log_directives():
    caddyfile = _active_lines(_read(CADDYFILE))

    for header in (
        'Strict-Transport-Security "max-age=31536000"',
        'X-Content-Type-Options "nosniff"',
        'Referrer-Policy "strict-origin-when-cross-origin"',
        'Permissions-Policy "camera=(), microphone=(), geolocation=()"',
        'X-Frame-Options "DENY"',
    ):
        assert header in caddyfile
    lowered = caddyfile.lower()
    assert _header_values(caddyfile, "Strict-Transport-Security") == ['"max-age=31536000"']
    assert "includesubdomains" not in lowered
    assert "content-security-policy" not in lowered
    assert "access-control-allow" not in lowered
    assert "cache-control" not in lowered
    assert not re.search(r"^\s*(?:log|cache)\b", lowered, flags=re.MULTILINE)


def test_caddy_systemd_drop_in_requires_its_own_external_domain_environment_file():
    drop_in = _read(CADDY_DROP_IN)

    assert [line.strip() for line in drop_in.splitlines() if line.strip()] == [
        "[Service]",
        "EnvironmentFile=/etc/etm-affiliate-os/caddy.env",
    ]


def test_launcher_uses_explicit_loopback_only_forwarded_header_trust():
    script = _active_lines(_read(START_SCRIPT))

    assert re.findall(r"(?<!\S)-m\s+uvicorn\s+([^\s\\]+)", script) == ["app.main:app"]
    assert script.count("app.main:app") == 1
    assert _option_values(script, "--host") == ["127.0.0.1"]
    assert _option_values(script, "--port") == ['"$PORT"']
    assert _option_values(script, "--workers") == ["1"]
    assert _option_values(script, "--forwarded-allow-ips") == ["127.0.0.1"]
    assert len(re.findall(r"^\s*--proxy-headers\s*\\?\s*$", script, flags=re.MULTILINE)) == 1
    assert script.count("PORT=8000") == 1
    assert "--reload" not in script
    assert not re.search(r"alembic\s+(?:upgrade|downgrade|stamp|current)|create_all\(", script, flags=re.IGNORECASE)


def test_operator_session_routes_retain_no_store_responses_for_proxy_passthrough():
    operator_console = _read(OPERATOR_CONSOLE)

    assert 'response.headers["Cache-Control"] = "no-store"' in operator_console
    for route in ("login", "session_status", "logout"):
        route_body = operator_console.split(f"async def {route}", 1)[1]
        assert "_no_store(" in route_body
