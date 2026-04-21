#!/usr/bin/env python3
"""CLI tool to replay a batch or specific branch delivery."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.post_common import add_root_dir_argument, build_registry_from_args, print_json


def main():
    parser = argparse.ArgumentParser(
        description="Replay delivery for a POST batch or specific branch."
    )
    add_root_dir_argument(parser)
    parser.add_argument("--batch-id", required=True, help="ID of the batch to replay")
    parser.add_argument(
        "--branch-id",
        help="ID of specific branch to replay (if omitted, replays all branches)",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Reason for replay",
    )
    args = parser.parse_args()

    registry = build_registry_from_args(args)

    # Get batch to verify it exists
    batch = registry.get_batch(args.batch_id)
    if batch is None:
        print(f"Error: Batch {args.batch_id} not found", file=sys.stderr)
        sys.exit(1)

    # Get branches
    branches = registry.get_branches(args.batch_id)
    if not branches:
        print(f"Error: No branches found for batch {args.batch_id}", file=sys.stderr)
        sys.exit(1)

    # Filter to specific branch if requested
    if args.branch_id:
        branches = [b for b in branches if b["branch_id"] == args.branch_id]
        if not branches:
            print(
                f"Error: Branch {args.branch_id} not found in batch {args.batch_id}",
                file=sys.stderr,
            )
            sys.exit(1)

    # Reset branch statuses to pending to trigger re-delivery
    replayed_branches = []
    for branch in branches:
        updated = registry.update_branch(
            batch_id=args.batch_id,
            branch_id=branch["branch_id"],
            updates={"status": "pending", "completed_at": None},
        )
        if updated:
            replayed_branches.append(updated)

    # Reset batch status to registered (from delivered)
    registry.update_batch(args.batch_id, {"status": "registered"})

    # Record manager action
    action = registry.record_manager_action(
        batch_id=args.batch_id,
        action_type="replay",
        detail=args.reason
        or f"Replayed {len(replayed_branches)} branch(es) for batch {args.batch_id}",
    )

    result = {
        "batch_id": args.batch_id,
        "replayed_branches": [b["branch_id"] for b in replayed_branches],
        "action": action,
    }

    print_json(result)


if __name__ == "__main__":
    main()
