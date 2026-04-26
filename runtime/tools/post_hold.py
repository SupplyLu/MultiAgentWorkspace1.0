#!/usr/bin/env python3
"""CLI tool to hold/resume a project."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.post_common import add_root_dir_argument, build_registry_from_args, print_json


def main():
    parser = argparse.ArgumentParser(description="Hold or resume a POST project.")
    add_root_dir_argument(parser)
    parser.add_argument("--project-key", required=True, help="Key of the project")
    parser.add_argument(
        "--action",
        required=True,
        choices=["hold", "resume"],
        help="Action to perform",
    )
    parser.add_argument("--reason", default="", help="Reason for the action")
    args = parser.parse_args()

    registry = build_registry_from_args(args)

    if args.action == "hold":
        registry.update_project(args.project_key, {"status": "blocked"})
        action = registry.record_manager_action(
            project_key=args.project_key,
            action_type="hold",
            detail=args.reason or "User manually held project",
        )
    else:  # resume
        registry.update_project(args.project_key, {"status": "registered"})
        action = registry.record_manager_action(
            project_key=args.project_key,
            action_type="resume",
            detail=args.reason or "User manually resumed project",
        )

    print_json(action)


if __name__ == "__main__":
    main()
