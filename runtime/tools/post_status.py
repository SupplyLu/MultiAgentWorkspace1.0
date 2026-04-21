#!/usr/bin/env python3
"""CLI tool to query batch status."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.post_common import add_root_dir_argument, build_registry_from_args, print_json


def main():
    parser = argparse.ArgumentParser(description="Query POST batch status.")
    add_root_dir_argument(parser)
    parser.add_argument("--batch-id", required=True, help="ID of the batch")
    args = parser.parse_args()

    registry = build_registry_from_args(args)
    batch = registry.get_batch(args.batch_id)

    if batch is None:
        raise SystemExit(1)

    print_json(batch)


if __name__ == "__main__":
    main()
