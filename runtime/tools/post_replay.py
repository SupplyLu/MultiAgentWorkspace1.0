#!/usr/bin/env python3
"""CLI tool to replay a project delivery."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.post_common import add_root_dir_argument, build_registry_from_args, print_json


def main():
    parser = argparse.ArgumentParser(
        description="Replay delivery for a POST project."
    )
    add_root_dir_argument(parser)
    parser.add_argument("--project-key", required=True, help="Key of the project to replay")
    args = parser.parse_args()

    registry = build_registry_from_args(args)

    # Get project to verify it exists
    project = registry.get_project(args.project_key)
    if project is None:
        print(f"Error: Project {args.project_key} not found", file=sys.stderr)
        sys.exit(1)

    # Reset project to registered status and reset cursor to beginning
    route = project.get("route", [project["from_pool"], project["to_pool"]])
    cursor = 0
    current_pool = route[cursor]
    next_pool = route[cursor + 1] if cursor + 1 < len(route) else None

    registry.update_project(
        args.project_key,
        {
            "status": "registered",
            "cursor": cursor,
            "current_pool": current_pool,
            "next_pool": next_pool,
        }
    )

    # Record manager action
    action = registry.record_manager_action(
        project_key=args.project_key,
        action_type="replay",
        detail=f"Replayed project {args.project_key}",
    )

    result = {
        "project_key": args.project_key,
        "action": action,
    }

    print_json(result)


if __name__ == "__main__":
    main()
