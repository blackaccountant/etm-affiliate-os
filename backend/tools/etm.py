"""
ETM Developer CLI

Entry point for ETM Affiliate OS developer tools.
"""

import sys

from commands.worker import create_worker
from commands.mission import create_mission
from commands.workflow import create_workflow
from commands.doctor import run_doctor


def show_help():

    print()
    print("ETM Affiliate OS Developer CLI")
    print("--------------------------------")
    print("Usage:")
    print("  python etm.py new worker <Name>")
    print("  python etm.py new mission <Name>")
    print("  python etm.py new workflow <Name>")
    print("  python etm.py doctor")
    print()


def main():

    if len(sys.argv) < 2:

        show_help()
        return

    command = sys.argv[1].lower()

    if command == "doctor":

        run_doctor()
        return

    if command != "new":

        show_help()
        return

    if len(sys.argv) < 4:

        show_help()
        return

    component = sys.argv[2].lower()

    name = sys.argv[3]

    if component == "worker":

        create_worker(name)

    elif component == "mission":

        create_mission(name)

    elif component == "workflow":

        create_workflow(name)

    else:

        print(f"Unknown component: {component}")


if __name__ == "__main__":

    main()