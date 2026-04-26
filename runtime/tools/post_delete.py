#!/usr/bin/env python3
"""CLI tool to skip a project."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.post_common import add_root_dir_argument, build_registry_from_args, print_json


def main():
    parser = argparse.ArgumentParser(description="Mark a POST project as skipped.")
    add_root_dir_argument(parser)
    parser.add_argument("--project-key", required=True, help="Key of the project to skip")
    parser.add_argument("--reason", default="Project skipped by operator", help="Reason for skipping")
    args = parser.parse_args()

    registry = build_registry_from_args(args)

    result = registry.update_project(
        args.project_key,
        {"status": "skipped", "skipped_reason": args.reason},
    )

    if result is None:
        raise SystemExit(1)

    registry.record_manager_action(
        project_key=args.project_key,
        action_type="skip",
        detail=args.reason,
    )

    print_json(result)


if __name__ == "__main__":
    main()
