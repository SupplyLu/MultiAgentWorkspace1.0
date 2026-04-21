"""POST Runtime 守护进程入口

负责：
  - 启动 POST Runtime + 扫描循环
  - 定期扫描 registry 和 filesystem
  - 日志输出到文件和 stdout
  - 优雅关闭（SIGINT/SIGTERM）
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from app.runtimes.post_runtime import PostRuntime


def setup_logging(log_file: Path) -> logging.Logger:
    """配置日志系统，同时输出到 stdout 和文件"""
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("post_runtime")
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def build_runtime(root_dir: str, scan_interval_seconds: int = 60) -> PostRuntime:
    """Build a POST Runtime instance."""
    return PostRuntime(root_dir=Path(root_dir), scan_interval_seconds=scan_interval_seconds)


def main():
    parser = argparse.ArgumentParser(description="POST Runtime daemon - scan-based cross-pool delivery orchestrator.")
    parser.add_argument(
        "--root-dir",
        type=str,
        default=None,
        help="Root directory for workspace (default: current directory)",
    )
    parser.add_argument(
        "--scan-interval",
        type=int,
        default=60,
        help="Scan interval in seconds (default: 60)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan cycle and exit (useful for testing)",
    )
    args = parser.parse_args()

    root_dir = Path(args.root_dir) if args.root_dir else Path.cwd()

    log_file = root_dir / "logs" / "post_runtime.log"
    logger = setup_logging(log_file)

    logger.info(f"Starting POST Runtime (root_dir={root_dir}, scan_interval={args.scan_interval})")

    runtime = build_runtime(str(root_dir), args.scan_interval)

    def shutdown_handler(signum, frame):
        logger.info("Received shutdown signal, stopping POST Runtime...")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    if args.once:
        runtime.scan_once()
        logger.info("Single scan completed.")
        return

    while True:
        try:
            runtime.scan_once()
            logger.info(f"Scan cycle complete. Sleeping {args.scan_interval}s...")
            time.sleep(args.scan_interval)
        except Exception as e:
            logger.error(f"Scan cycle failed: {e}")


if __name__ == "__main__":
    main()
