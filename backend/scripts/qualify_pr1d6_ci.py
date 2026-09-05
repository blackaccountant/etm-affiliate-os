"""Run the explicit PR1D6 no-service production qualification baseline."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
import xml.etree.ElementTree as element_tree
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
EVIDENCE_ROOT = BACKEND_ROOT / ".qualification-evidence" / "pr1d6"
EXPECTED_TEST_COUNT = 82
SAFE_TEST_FILES = (
    "backend/tests/test_production_readiness.py",
    "backend/tests/test_api_security_boundary.py",
    "backend/tests/test_operator_console_session_security.py",
    "backend/tests/test_production_runtime_configuration.py",
    "backend/tests/test_production_startup_contract.py",
    "backend/tests/test_production_reverse_proxy_contract.py",
    "backend/tests/test_pr1d6_ci_qualification_contract.py",
)


def _run(name: str, command: list[str], *, cwd: Path, environment: dict[str, str] | None = None) -> dict:
    print(f"[PR1D6] {name}: {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.stderr:
        print(completed.stderr, end="" if completed.stderr.endswith("\n") else "\n", file=sys.stderr)
    result = {"name": name, "command": command, "returncode": completed.returncode}
    print(f"[PR1D6] {name}: {'PASS' if completed.returncode == 0 else 'FAIL'}")
    return result


def _git_status() -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError("could not inspect git status")
    return completed.stdout.splitlines()


def _junit_test_count(path: Path) -> int:
    root = element_tree.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    return sum(int(suite.attrib.get("tests", "0")) for suite in suites)


def _test_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "APP_NAME": "ETM CI qualification",
            "ENV": "development",
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "OPERATOR_API_TOKEN": "",
            "SERVICE_API_TOKEN": "",
            "OPENAI_API_KEY": "",
            "RESEND_API_KEY": "",
            "RESEND_FROM_EMAIL": "",
            "RESEND_FROM_NAME": "",
        }
    )
    return environment


def main() -> int:
    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex}"
    evidence_dir = EVIDENCE_ROOT / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    junit_path = evidence_dir / "junit.xml"
    basetemp = evidence_dir / "basetemp"
    initial_status = _git_status()
    results: list[dict] = []

    results.append(
        _run(
            "py_compile",
            [
                sys.executable,
                "-m",
                "py_compile",
                "backend/scripts/qualify_pr1d6_ci.py",
                "backend/tests/test_pr1d6_ci_qualification_contract.py",
            ],
            cwd=REPOSITORY_ROOT,
        )
    )
    results.append(_run("git diff --check", ["git", "diff", "--check"], cwd=REPOSITORY_ROOT))
    pytest_command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        *SAFE_TEST_FILES,
        f"--junitxml={junit_path}",
        f"--basetemp={basetemp}",
    ]
    results.append(_run("safe suite", pytest_command, cwd=REPOSITORY_ROOT, environment=_test_environment()))

    final_status = _git_status()
    status_unchanged = initial_status == final_status
    if not status_unchanged:
        print("[PR1D6] repository status changed during qualification", file=sys.stderr)

    test_count = None
    if junit_path.is_file():
        try:
            test_count = _junit_test_count(junit_path)
        except (OSError, element_tree.ParseError, ValueError) as exc:
            print(f"[PR1D6] JUnit evidence is invalid: {exc}", file=sys.stderr)

    passed = all(result["returncode"] == 0 for result in results)
    passed = passed and status_unchanged and test_count == EXPECTED_TEST_COUNT
    evidence = {
        "phase": "PR1D6",
        "run_id": run_id,
        "safe_test_files": list(SAFE_TEST_FILES),
        "expected_test_count": EXPECTED_TEST_COUNT,
        "observed_test_count": test_count,
        "initial_status": initial_status,
        "final_status": final_status,
        "results": results,
        "passed": passed,
    }
    (evidence_dir / "summary.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(f"[PR1D6] evidence: {evidence_dir}")
    print(f"[PR1D6] qualification: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
