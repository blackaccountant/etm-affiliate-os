"""
Filesystem utilities for ETM CLI.
"""

from pathlib import Path


def ensure_directory(path: Path):

    path.mkdir(
        parents=True,
        exist_ok=True,
    )


def file_exists(path: Path):

    return path.exists()


def write_file(
    path: Path,
    content: str,
    overwrite: bool = False,
):

    ensure_directory(
        path.parent
    )

    if path.exists() and not overwrite:

        raise FileExistsError(
            f"{path} already exists."
        )

    path.write_text(
        content,
        encoding="utf-8",
    )