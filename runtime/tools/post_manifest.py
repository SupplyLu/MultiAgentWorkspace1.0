#!/usr/bin/env python3
"""CLI tool to render current manifest view for a batch."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.post_common import add_root_dir_argument, build_registry_from_args, print_json


def main():
    parser = argparse.ArgumentParser(description="Render manifest view for a POST batch.")
    add_root_dir_argument(parser)
    parser.add_argument("--batch-id", required=True, help="ID of the batch")
    args = parser.parse_args()

    registry = build_registry_from_args(args)

    batch = registry.get_batch(args.batch_id)
    if batch is None:
        raise SystemExit(1)

    branches = registry.get_branches(args.batch_id)
    dependencies = registry.get_dependencies(args.batch_id)

    manifest = {
        "batch_id": batch["batch_id"],
        "name": batch["name"],
        "from_pool": batch["from_pool"],
        "to_pool": batch["to_pool"],
        "status": batch["status"],
        "branches": branches,
        "dependencies": dependencies,
    }

    print_json(manifest)


if __name__ == "__main__":
    main()
