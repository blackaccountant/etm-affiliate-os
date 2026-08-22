"""
ETM Scaffold Engine

Central generation engine.
"""

from pathlib import Path

from core.renderer import render
from core.filesystem import write_file
from core.logger import success, error


TOOLS_ROOT = Path(__file__).resolve().parents[1]

BACKEND_ROOT = TOOLS_ROOT.parent



def generate_worker(
    name: str,
    overwrite: bool = False,
):

    module = snake_case(name)


    worker_path = (
        BACKEND_ROOT
        /
        "app"
        /
        "ai"
        /
        "workers"
        /
        f"{module}.py"
    )


    test_path = (
        BACKEND_ROOT
        /
        "tests"
        /
        f"test_{module}.py"
    )


    try:

        worker_content = render(
            "worker.py.template",
            class_name=name,
            name=name,
        )


        test_content = render(
            "test_worker.py.template",
            module=module,
            class_name=name,
            name=name,
        )


        write_file(
            worker_path,
            worker_content,
            overwrite,
        )


        write_file(
            test_path,
            test_content,
            overwrite,
        )


        success(
            f"Worker created: {worker_path}"
        )


        success(
            f"Test created: {test_path}"
        )


    except FileExistsError as exc:

        error(
            str(exc)
        )



def snake_case(name: str):

    import re

    name = re.sub(
        r"([a-z0-9])([A-Z])",
        r"\1_\2",
        name,
    )

    return name.lower()



def generate_mission(
    name: str,
    workflow: str = "default_workflow",
    overwrite: bool = False,
):

    module = snake_case(name)


    mission_path = (
        BACKEND_ROOT
        /
        "app"
        /
        "mission"
        /
        f"{module}.py"
    )


    test_path = (
        BACKEND_ROOT
        /
        "tests"
        /
        "mission"
        /
        f"test_{module}.py"
    )


    mission_content = render(
        "mission.py.template",
        class_name=name,
        name=name,
        workflow=workflow,
    )


    test_content = render(
        "test_mission.py.template",
        module=module,
        class_name=name,
        name=name,
    )


    write_file(
        mission_path,
        mission_content,
        overwrite,
    )


    write_file(
        test_path,
        test_content,
        overwrite,
    )


    success(
        f"Mission created: {mission_path}"
    )

    success(
        f"Test created: {test_path}"
    )