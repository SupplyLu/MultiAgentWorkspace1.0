#!/usr/bin/env python3
"""CLI tool to hold/resume a batch."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.post_common import add_root_dir_argument, build_registry_from_args, print_json


def main():
    parser = argparse.ArgumentParser(description="Hold or resume a POST batch.")
    add_root_dir_argument(parser)
    parser.add_argument("--batch-id", required=True, help="ID of the batch")
    parser.add_argument(
        "--action",
        required=True,
        choices=["hold", "resume"],
        help="Action to perform",
    )
    parser.add_argument("--reason", default="", help="Reason for the action")
    args = parser.parse_args()

    registry = build_registry_from_args(args)

    if args.action == "hold":
        registry.update_batch(args.batch_id, {"status": "blocked"})
        action = registry.record_manager_action(
            batch_id=args.batch_id,
            action_type="hold",
            detail=args.reason or "User manually held batch",
        )
    else:  # resume
        registry.update_batch(args.batch_id, {"status": "registered"})
        action = registry.record_manager_action(
            batch_id=args.batch_id,
            action_type="resume",
            detail=args.reason or "User manually resumed batch",
        )

    print_json(action)


if __name__ == "__main__":
    main()
