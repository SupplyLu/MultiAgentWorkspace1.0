#!/usr/bin/env python3
"""CLI tool to delete (skip) a branch."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.post_common import add_root_dir_argument, build_registry_from_args, print_json


def main():
    parser = argparse.ArgumentParser(description="Mark a POST branch as skipped.")
    add_root_dir_argument(parser)
    parser.add_argument("--batch-id", required=True, help="ID of the batch")
    parser.add_argument("--branch-id", required=True, help="ID of the branch to delete/skip")
    args = parser.parse_args()

    registry = build_registry_from_args(args)

    result = registry.update_branch(args.batch_id, args.branch_id, {"status": "skipped"})

    if result is None:
        raise SystemExit(1)

    # Optional: could record manager action here

    print_json(result)


if __name__ == "__main__":
    main()
