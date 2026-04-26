#!/usr/bin/env python3
"""CLI tool to register a project."""

import argparse
import sys
from pathlib import Path

# Add runtime root to path so we can import app
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.post_naming import is_valid_project_key
from tools.post_common import add_root_dir_argument, build_registry_from_args, print_json


def main():
    parser = argparse.ArgumentParser(description="Register a new POST project.")
    add_root_dir_argument(parser)
    parser.add_argument("--project-key", required=True, help="Key of the project")
    parser.add_argument("--from-pool", required=True, help="Source pool")
    parser.add_argument("--to-pool", required=True, help="Target pool")
    parser.add_argument("--route", help="Optional comma-separated route, e.g. thinking,construct,work")

    args = parser.parse_args()

    # Validate project_key format
    if not is_valid_project_key(args.project_key):
        print_json(
            {
                "error": (
                    "Invalid project_key format: "
                    f"{args.project_key}. Expected format: XXX-(Vision)-(Mode), "
                    "e.g., SignalOfBridge-v1-Build"
                )
            }
        )
        sys.exit(1)

    registry = build_registry_from_args(args)

    route = [p.strip() for p in args.route.split(",")] if args.route else None

    result = registry.register_project(
        project_key=args.project_key,
        from_pool=args.from_pool,
        to_pool=args.to_pool,
        route=route,
    )

    print_json(result)


if __name__ == "__main__":
    main()
