#!/usr/bin/env python3
"""CLI tool to register a batch and its branches."""

import argparse
import sys
from pathlib import Path

# Add runtime root to path so we can import app
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.post_common import add_root_dir_argument, build_registry_from_args, print_json


def main():
    parser = argparse.ArgumentParser(description="Register a new POST batch and branches.")
    add_root_dir_argument(parser)
    parser.add_argument("--batch-id", required=True, help="ID of the batch")
    parser.add_argument("--name", required=True, help="Name of the batch")
    parser.add_argument("--from-pool", required=True, help="Source pool")
    parser.add_argument("--to-pool", required=True, help="Target pool")

    # Simple parsing for one branch in Phase 1 tests.
    parser.add_argument("--branch-id", required=True, help="ID of the branch")
    parser.add_argument("--feature-id", required=True, help="Feature ID")
    parser.add_argument("--task-body", required=True, help="Task body")
    parser.add_argument("--outbox-path", required=True, help="Outbox path")

    args = parser.parse_args()

    registry = build_registry_from_args(args)

    branches = [
        {
            "branch_id": args.branch_id,
            "feature_id": args.feature_id,
            "task_body": args.task_body,
            "outbox_path": args.outbox_path,
        }
    ]

    result = registry.register_batch(
        batch_id=args.batch_id,
        name=args.name,
        from_pool=args.from_pool,
        to_pool=args.to_pool,
        branches=branches,
    )

    print_json(result)


if __name__ == "__main__":
    main()
