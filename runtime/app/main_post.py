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
import os
import signal
import socket
import sys
import time
from pathlib import Path

from app.runtimes.post_runtime import PostRuntime
from app.services.runtime_registry import RuntimeRegistry
from app.services.signal_server import RuntimeSignalServer
from app.shared.single_instance_guard import SingleInstanceGuard


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


def find_free_port(start: int = 19120, end: int = 19200) -> int:
    for port in range(start, end):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("localhost", port))
            sock.close()
            return port
        except OSError:
            pass
    raise RuntimeError(f"No free port found in range {start}-{end}")


def main():
    parser = argparse.ArgumentParser(description="POST Runtime daemon - scan-based cross-pool delivery orchestrator.")
    parser.add_argument(
        "--root-dir",
        type=str,
        default=None,
        help="Root directory for workspace (default: project root)",
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

    root_dir = Path(args.root_dir) if args.root_dir else Path(__file__).resolve().parents[2]

    log_file = root_dir / "logs" / "post_runtime.log"
    logger = setup_logging(log_file)

    guard = SingleInstanceGuard(root_dir=root_dir, instance_key="post")
    success, guard_msg = guard.try_acquire(timeout=0.1)
    if not success:
        logger.warning(f"POST Runtime 启动被拒绝: {guard_msg}")
        print(f"[POST Runtime] {guard_msg}")
        print("提示：如需重启，请先停止现有进程或使用 UI 控制面的 restart 功能")
        sys.exit(1)
    logger.info("单实例守护锁已获取")

    logger.info(f"Starting POST Runtime (root_dir={root_dir}, scan_interval={args.scan_interval})")

    signal_port = find_free_port()
    logger.info(f"POST Signal Server 端口: {signal_port}")

    runtime = build_runtime(str(root_dir), args.scan_interval)
    signal_server = RuntimeSignalServer(
        port=signal_port,
        event_store_dir=root_dir / "events" / "post",
    )
    signal_server.on_api_request = runtime.handle_api_request
    signal_server.start()
    registry = RuntimeRegistry(root_dir=root_dir)
    registry.register(
        pool="post",
        pid=os.getpid(),
        port=signal_port,
        status="running"
    )

    def shutdown_handler(signum, frame):
        logger.info("Received shutdown signal, stopping POST Runtime...")
        signal_server.stop()
        guard.release()
        registry.register(
            pool="post",
            pid=os.getpid(),
            port=signal_port,
            status="stopped"
        )
        logger.info("已更新 RuntimeRegistry 状态为 stopped")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, shutdown_handler)

    if args.once:
        runtime.scan_once()
        logger.info("Single scan completed.")
        return

    consecutive_failures = 0
    max_backoff = 60.0

    while True:
        try:
            runtime.scan_once()
            registry.heartbeat("post")
            consecutive_failures = 0
            logger.info(f"Scan cycle complete. Sleeping {args.scan_interval}s...")
            time.sleep(args.scan_interval)
        except Exception as e:
            consecutive_failures += 1
            backoff = min(2 ** consecutive_failures, max_backoff)
            logger.error(f"Scan cycle failed (attempt {consecutive_failures}): {e}", exc_info=True)
            time.sleep(backoff)


if __name__ == "__main__":
    main()
