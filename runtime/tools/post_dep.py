#!/usr/bin/env python3
"""CLI tool to add dependency records."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.post_common import add_root_dir_argument, build_registry_from_args, print_json


def main():
    parser = argparse.ArgumentParser(description="Add a POST dependency record.")
    add_root_dir_argument(parser)
    parser.add_argument("--source-project-key", required=True, help="Source project that must happen first")
    parser.add_argument("--target-project-key", required=True, help="Target project that depends on the source")
    parser.add_argument("--rule", default="after_delivered", help="Dependency rule")
    args = parser.parse_args()

    registry = build_registry_from_args(args)

    result = registry.add_dependency(
        source_project_key=args.source_project_key,
        target_project_key=args.target_project_key,
        rule=args.rule,
    )

    print_json(result)


if __name__ == "__main__":
    main()
