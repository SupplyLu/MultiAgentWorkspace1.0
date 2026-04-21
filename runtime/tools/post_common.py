"""Shared helpers for POST CLI tools."""

import argparse
import json
import sys
from pathlib import Path

from app.services.post_registry import PostRegistry


def build_registry_from_args(args) -> PostRegistry:
    """Build PostRegistry from parsed CLI arguments."""
    root_dir = Path(args.root_dir) if args.root_dir else Path.cwd()
    return PostRegistry(root_dir=root_dir)


def print_json(payload: dict):
    """Print JSON payload to stdout."""
    print(json.dumps(payload, indent=2))


def add_root_dir_argument(parser: argparse.ArgumentParser):
    """Add --root-dir argument to parser."""
    parser.add_argument(
        "--root-dir",
        type=str,
        default=None,
        help="Root directory for POST registry (default: current directory)",
    )
