#!/usr/bin/env python3
"""CLI tool to query project status."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.post_common import add_root_dir_argument, build_registry_from_args, print_json


def main():
    parser = argparse.ArgumentParser(description="Query POST project status.")
    add_root_dir_argument(parser)
    parser.add_argument("--project-key", required=True, help="Key of the project")
    args = parser.parse_args()

    registry = build_registry_from_args(args)
    project = registry.get_project(args.project_key)

    if project is None:
        raise SystemExit(1)

    print_json(project)


if __name__ == "__main__":
    main()
