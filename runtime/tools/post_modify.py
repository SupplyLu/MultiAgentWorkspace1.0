#!/usr/bin/env python3
"""CLI tool to modify batch or branch fields."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.post_common import add_root_dir_argument, build_registry_from_args, print_json


def main():
    parser = argparse.ArgumentParser(description="Modify a POST batch or branch field.")
    add_root_dir_argument(parser)
    parser.add_argument("--batch-id", required=True, help="ID of the batch")
    parser.add_argument("--branch-id", help="ID of the branch to modify")
    parser.add_argument("--field", required=True, help="Field to update")
    parser.add_argument("--value", required=True, help="New value")
    args = parser.parse_args()

    registry = build_registry_from_args(args)

    if args.branch_id:
        result = registry.update_branch(args.batch_id, args.branch_id, {args.field: args.value})
    else:
        result = registry.update_batch(args.batch_id, {args.field: args.value})

    if result is None:
        raise SystemExit(1)

    print_json(result)


if __name__ == "__main__":
    main()
