"""Package Runtime 守护进程入口

负责：
  - 启动 PackageRuntime + Signal Server
  - 轮询 Queue 目录，自动派发 Package 任务
  - 超时检测（超时后杀进程并重新放回 Queue）
  - 日志输出到文件和 stdout
  - 优雅关闭（SIGINT/SIGTERM）
  - 动态扫描 package 槽位目录
"""

from __future__ import annotations

import argparse
import fnmatch
import logging
import signal
import socket
import sys
import time
from pathlib import Path

from app.runtimes.package_runtime import PackageRuntime, PackageDeniedError


def find_free_port(start: int = 19300, end: int = 19400) -> int:
    """查找可用端口。"""
    for port in range(start, end):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("localhost", port))
            s.close()
            return port
        except OSError:
            pass
    raise RuntimeError(f"No free port found in range {start}-{end}")


def setup_logging(log_file: Path) -> logging.Logger:
    """配置日志系统，同时输出到 stdout 和文件。"""
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("package_runtime")
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def ensure_directory_structure(root_dir: Path) -> None:
    """确保必要目录存在，并为所有 package 槽位创建 workspace。"""
    pools_dir = root_dir / "pools" / "package"
    (pools_dir / "Queue").mkdir(parents=True, exist_ok=True)
    (pools_dir / "Outbox").mkdir(parents=True, exist_ok=True)
    (pools_dir / "Rejectbox").mkdir(parents=True, exist_ok=True)
    (pools_dir / "context").mkdir(parents=True, exist_ok=True)
    (pools_dir / "Release").mkdir(parents=True, exist_ok=True)

    slot_patterns = ["cutter_*", "tester_*", "releaser_*", "complete_player_*"]

    # 扫描已有槽位
    existing_slots = []
    if pools_dir.exists():
        for sub_dir in pools_dir.iterdir():
            if not sub_dir.is_dir():
                continue
            for pattern in slot_patterns:
                if fnmatch.fnmatch(sub_dir.name, pattern):
                    existing_slots.append(sub_dir)
                    break

    # 如果没有槽位，创建默认槽位
    if not existing_slots:
        existing_slots = [
            pools_dir / "cutter_01",
            pools_dir / "tester_01",
            pools_dir / "releaser_01",
            pools_dir / "complete_player_01",
        ]

    for slot_dir in existing_slots:
        slot_dir.mkdir(parents=True, exist_ok=True)
        (slot_dir / "workspace").mkdir(parents=True, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Package Runtime 守护进程")
    parser.add_argument(
        "root_dir",
        nargs="?",
        default=Path(__file__).parent.parent.parent,
        type=Path,
        help="工作区根目录",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="信号服务端口（默认动态分配 19300-19400）",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Queue 轮询间隔（秒），默认 2.0",
    )
    args = parser.parse_args()

    root_dir = args.root_dir.resolve()
    log_file = root_dir / "logs" / "package_runtime.log"

    logger = setup_logging(log_file)
    logger.info("=" * 50)
    logger.info("Package Runtime 守护进程启动")
    logger.info(f"工作区: {root_dir}")
    logger.info(f"日志文件: {log_file}")

    signal_port = args.port or find_free_port()
    logger.info(f"信号服务端口: {signal_port}")

    ensure_directory_structure(root_dir)
    logger.info("目录结构已确认")

    runtime = PackageRuntime(root_dir=root_dir, signal_port=signal_port)
    runtime.start()
    logger.info("Signal Server 已启动")

    shutdown_flag = False

    def signal_handler(sig, frame):
        nonlocal shutdown_flag
        if not shutdown_flag:
            shutdown_flag = True
            logger.info("收到关闭信号，正在停止...")
            runtime.stop()
            logger.info("Signal Server 已停止")
            sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)

    logger.info("开始监控 Queue 目录...")
    poll_interval = args.poll_interval
    last_check_time = 0.0

    while True:
        current_time = time.time()
        if current_time - last_check_time >= poll_interval:
            last_check_time = current_time

            # 检查超时任务
            timed_out = runtime.check_timeouts()
            for item in timed_out:
                logger.warning(
                    f"任务超时并已回队: {item['task_id']} @ {item['slot_id']} after {item['timeout_seconds']}s"
                )

            # 轮询 Queue
            tasks = runtime.list_queue_tasks()
            if tasks:
                logger.info(f"检测到 {len(tasks)} 个任务")

                try:
                    result = runtime.dispatch_next(dry_run=False)
                    if result.get("dispatched"):
                        logger.info(
                            f"派发成功: {result['task_id']} -> {result['slot_id']} ({result['stage']})"
                        )
                        launch_result = result.get("launch", {})
                        if launch_result.get("launched"):
                            logger.info(f"Package 进程已启动: PID={launch_result.get('pid')}")
                    else:
                        logger.warning(f"派发失败: {result.get('error', '未知错误')}")
                except PackageDeniedError as e:
                    logger.error(f"Package task denied: {e}")
                except Exception as e:
                    logger.error(f"派发异常: {e}", exc_info=True)

        time.sleep(0.1)


if __name__ == "__main__":
    main()
