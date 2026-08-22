"""
ETM Doctor

Checks the development environment.
"""

from pathlib import Path


def run_doctor():

    print()
    print("ETM Affiliate OS Doctor")
    print("-----------------------")

    backend = Path(__file__).resolve().parents[2]

    checks = {
        "Backend": backend.exists(),
        "App": (backend / "app").exists(),
        "Tests": (backend / "tests").exists(),
        "Templates": (backend / "tools" / "templates").exists(),
    }

    for name, status in checks.items():

        icon = "✓" if status else "✗"

        print(f"{icon} {name}")

    print()
    print("Doctor complete.")