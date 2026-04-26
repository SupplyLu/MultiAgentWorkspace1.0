#!/usr/bin/env python3
"""CLI tool to render current manifest view for a project."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.post_common import add_root_dir_argument, build_registry_from_args, print_json


def main():
    parser = argparse.ArgumentParser(description="Render manifest view for a POST project.")
    add_root_dir_argument(parser)
    parser.add_argument("--project-key", required=True, help="Key of the project")
    args = parser.parse_args()

    registry = build_registry_from_args(args)

    project = registry.get_project(args.project_key)
    if project is None:
        raise SystemExit(1)

    dependencies = registry.get_dependencies(args.project_key)

    manifest = {
        "project_key": project["project_key"],
        "from_pool": project["from_pool"],
        "to_pool": project["to_pool"],
        "status": project["status"],
        "route": project.get("route", [project["from_pool"], project["to_pool"]]),
        "cursor": project.get("cursor", 0),
        "current_pool": project.get("current_pool"),
        "next_pool": project.get("next_pool"),
        "route_version": project.get("route_version", 1),
        "dependencies": dependencies,
    }

    print_json(manifest)


if __name__ == "__main__":
    main()
