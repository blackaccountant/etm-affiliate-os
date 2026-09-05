import ast
import copy
import importlib.util
import re
from pathlib import Path

import yaml
from yaml.constructor import ConstructorError
from yaml.resolver import BaseResolver


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "pr1d6-production-qualification.yml"
RUNNER = REPOSITORY_ROOT / "backend" / "scripts" / "qualify_pr1d6_ci.py"
CI_REQUIREMENTS = REPOSITORY_ROOT / "backend" / "Requirements-ci.txt"
RUNTIME_REQUIREMENTS = REPOSITORY_ROOT / "backend" / "Requirements.txt"
BASELINE_BRANCH = "pr1-production-readiness-baseline"
SAFE_TEST_FILES = (
    "backend/tests/test_production_readiness.py",
    "backend/tests/test_api_security_boundary.py",
    "backend/tests/test_operator_console_session_security.py",
    "backend/tests/test_production_runtime_configuration.py",
    "backend/tests/test_production_startup_contract.py",
    "backend/tests/test_production_reverse_proxy_contract.py",
    "backend/tests/test_pr1d6_ci_qualification_contract.py",
)


class StrictWorkflowLoader(yaml.SafeLoader):
    pass


StrictWorkflowLoader.yaml_implicit_resolvers = {
    key: [entry for entry in values if entry[0] != "tag:yaml.org,2002:bool"]
    for key, values in copy.deepcopy(yaml.SafeLoader.yaml_implicit_resolvers).items()
}
StrictWorkflowLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def _construct_mapping_no_duplicates(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


StrictWorkflowLoader.add_constructor(BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping_no_duplicates)


def _workflow():
    assert WORKFLOW.is_file(), f"missing PR1D6 artifact: {WORKFLOW}"
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=StrictWorkflowLoader)


def _runner_module():
    specification = importlib.util.spec_from_file_location("qualify_pr1d6_ci", RUNNER)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _function(tree, name):
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _string(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _list_strings(node):
    assert isinstance(node, ast.List)
    return [_string(item) for item in node.elts]


def test_pr1d6_ci_workflow_and_runner_preserve_the_no_service_contract():
    assert CI_REQUIREMENTS.is_file(), f"missing PR1D6 artifact: {CI_REQUIREMENTS}"
    ci_requirements = [
        line.strip()
        for line in CI_REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert ci_requirements == ["-r Requirements.txt", "PyYAML==6.0.3"]
    assert all("pyyaml" not in line.lower() for line in RUNTIME_REQUIREMENTS.read_text(encoding="utf-8").splitlines())

    workflow = _workflow()
    assert isinstance(workflow, dict)
    assert workflow["name"] == "PR1D6 Production Qualification"
    assert set(workflow["on"]) == {"push", "pull_request"}
    assert workflow["on"] == {
        "push": {"branches": [BASELINE_BRANCH]},
        "pull_request": {"branches": [BASELINE_BRANCH]},
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "pr1d6-production-qualification-${{ github.workflow }}-${{ github.ref }}",
        "cancel-in-progress": True,
    }
    assert set(workflow["jobs"]) == {"qualify"}
    job = workflow["jobs"]["qualify"]
    assert set(job) == {"runs-on", "timeout-minutes", "steps"}
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == 15
    assert "permissions" not in job and "services" not in job and "env" not in job and "environment" not in job
    assert "matrix" not in job

    steps = job["steps"]
    assert steps == [
        {"uses": "actions/checkout@v4"},
        {"uses": "actions/setup-python@v5", "with": {"python-version": "3.11"}},
        {"run": "python -m pip install --upgrade pip"},
        {"run": "python -m pip install -r backend/Requirements-ci.txt"},
        {"run": "python backend/scripts/qualify_pr1d6_ci.py"},
        {
            "if": "always()",
            "uses": "actions/upload-artifact@v4",
            "with": {
                "name": "pr1d6-qualification-evidence",
                "path": "backend/.qualification-evidence/pr1d6/",
                "if-no-files-found": "error",
            },
        },
    ]

    runner = _runner_module()
    assert runner.EXPECTED_TEST_COUNT == 82
    assert runner.SAFE_TEST_FILES == SAFE_TEST_FILES

    tree = ast.parse(RUNNER.read_text(encoding="utf-8"), filename=str(RUNNER))
    main = _function(tree, "main")
    assignments = {
        target.id: node.value
        for node in ast.walk(main)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    pytest_command = assignments["pytest_command"]
    assert isinstance(pytest_command, ast.List)
    assert _list_strings(pytest_command)[:5] == [None, "-m", "pytest", "-p", "no:cacheprovider"]
    assert isinstance(pytest_command.elts[5], ast.Starred)
    assert isinstance(pytest_command.elts[5].value, ast.Name)
    assert pytest_command.elts[5].value.id == "SAFE_TEST_FILES"
    assert isinstance(pytest_command.elts[6], ast.JoinedStr)
    assert isinstance(pytest_command.elts[7], ast.JoinedStr)
    assert "--junitxml=" in ast.unparse(pytest_command.elts[6])
    assert "--basetemp=" in ast.unparse(pytest_command.elts[7])

    run_calls = [
        node
        for node in ast.walk(main)
        if isinstance(node, ast.Call) and _call_name(node.func) == "_run"
    ]
    run_names = [_string(call.args[0]) for call in run_calls]
    assert run_names == ["py_compile", "git diff --check", "safe suite"]
    py_compile_command = run_calls[0].args[1]
    assert _list_strings(py_compile_command) == [
        None,
        "-m",
        "py_compile",
        "backend/scripts/qualify_pr1d6_ci.py",
        "backend/tests/test_pr1d6_ci_qualification_contract.py",
    ]
    assert _list_strings(run_calls[1].args[1]) == ["git", "diff", "--check"]
    assert isinstance(run_calls[2].args[1], ast.Name) and run_calls[2].args[1].id == "pytest_command"
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "pytest_command"
        and node.func.attr in {"append", "extend", "insert"}
        for node in ast.walk(main)
    )
    status_calls = [
        node for node in ast.walk(main) if isinstance(node, ast.Call) and _call_name(node.func) == "_git_status"
    ]
    assert len(status_calls) == 2

    subprocess_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr == "run"
    ]
    assert subprocess_calls
    subprocess_call_functions = {
        function.name
        for function in (node for node in tree.body if isinstance(node, ast.FunctionDef))
        if any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "subprocess"
            and call.func.attr == "run"
            for call in ast.walk(function)
        )
    }
    assert subprocess_call_functions == {"_run", "_git_status"}
    assert all(
        not any(keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True for keyword in call.keywords)
        for call in subprocess_calls
    )
    executable_tokens = set()
    for call in run_calls:
        if isinstance(call.args[1], ast.List):
            executable_tokens.update(value for value in _list_strings(call.args[1]) if value)
    executable_tokens.update(value for value in _list_strings(pytest_command) if value)
    assert executable_tokens.isdisjoint(
        {
            "alembic",
            "docker",
            "psql",
            "createdb",
            "dropdb",
            "curl",
            "wget",
            "add",
            "commit",
            "push",
            "reset",
            "restore",
            "clean",
            "checkout",
            "merge",
            "rebase",
        }
    )
