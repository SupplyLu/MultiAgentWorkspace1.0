#!/usr/bin/env python3
"""CLI tool to modify project route."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.post_common import add_root_dir_argument, build_registry_from_args, print_json


def main():
    parser = argparse.ArgumentParser(description="Modify a POST project route.")
    add_root_dir_argument(parser)
    parser.add_argument("--project-key", required=True, help="Key of the project")
    parser.add_argument("--remaining-route", required=True, help="Comma-separated remaining route for governed mutation")
    parser.add_argument("--operator", required=True, help="Operator name for route mutation audit")
    parser.add_argument("--reason", required=True, help="Reason for route mutation audit")

    args = parser.parse_args()

    registry = build_registry_from_args(args)

    remaining_route = [p.strip() for p in args.remaining_route.split(",")]
    result = registry.update_remaining_route(
        project_key=args.project_key,
        remaining_route=remaining_route,
        operator=args.operator,
        reason=args.reason,
    )

    if result is None:
        raise SystemExit(1)

    print_json(result)


if __name__ == "__main__":
    main()
