"""Work Runtime 守护进程入口

负责：
  - 启动 WorkRuntime + Signal Server
  - 轮询 Queue 目录，自动派发任务
  - 超时检测（基于任务 TIMEOUT 字段）
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

from app.runtimes.work_runtime import WorkRuntime
from app.services.runtime_registry import RuntimeRegistry
from app.shared.single_instance_guard import SingleInstanceGuard


def find_free_port(start: int = 18800, end: int = 18900) -> int:
    """查找可用端口"""
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
    """配置日志系统，同时输出到 stdout 和文件"""
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("work_runtime")
    logger.setLevel(logging.INFO)

    # 同时输出到 stdout 和文件
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def ensure_directory_structure(root_dir: Path) -> None:
    """确保必要的目录结构存在"""
    pools_dir = root_dir / "pools" / "work"
    (pools_dir / "Queue").mkdir(parents=True, exist_ok=True)
    (pools_dir / "Outbox").mkdir(parents=True, exist_ok=True)

    for worker_id in ["worker_01", "worker_02", "worker_03", "worker_04", "worker_05"]:
        worker_dir = pools_dir / worker_id
        worker_dir.mkdir(parents=True, exist_ok=True)
        (worker_dir / "workspace").mkdir(parents=True, exist_ok=True)


def main() -> None:
    """主函数"""
    parser = argparse.ArgumentParser(description="Work Runtime 守护进程")
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
        help="信号服务端口（默认动态分配 18800-18900）",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Queue 轮询间隔（秒），默认 2.0",
    )
    args = parser.parse_args()

    root_dir = args.root_dir.resolve()
    log_file = root_dir / "logs" / "work_runtime.log"

    # 初始化日志
    logger = setup_logging(log_file)
    logger.info("=" * 50)
    logger.info("Work Runtime 守护进程启动")
    logger.info(f"工作区: {root_dir}")
    logger.info(f"日志文件: {log_file}")

    guard = SingleInstanceGuard(root_dir=root_dir, instance_key="work")
    success, message = guard.try_acquire(timeout=0.1)
    if not success:
        logger.warning(f"Work Runtime 启动被拒绝: {message}")
        print(f"[Work Runtime] {message}")
        print("提示：如需重启，请先停止现有进程或使用 UI 控制面的 restart 功能")
        sys.exit(1)
    logger.info("单实例守护锁已获取")

    # 查找空闲端口
    signal_port = args.port or find_free_port()
    logger.info(f"信号服务端口: {signal_port}")

    # 确保目录结构
    ensure_directory_structure(root_dir)
    logger.info("目录结构已确认")

    # 初始化 RuntimeRegistry
    registry = RuntimeRegistry(root_dir=root_dir)

    # 初始化 WorkRuntime
    runtime = WorkRuntime(root_dir=root_dir, signal_port=signal_port)
    runtime.start()
    logger.info("Signal Server 已启动")

    # 注册到 registry
    registry.register(
        pool="work",
        pid=os.getpid(),
        port=signal_port,
        status="running"
    )
    logger.info("已注册到 RuntimeRegistry")

    # 信号处理（优雅关闭）
    shutdown_flag = False

    def signal_handler(sig, frame):
        nonlocal shutdown_flag
        if not shutdown_flag:
            shutdown_flag = True
            logger.info("收到关闭信号，正在停止...")
            runtime.stop()
            logger.info("Signal Server 已停止")
            guard.release()
            # 更新 registry 状态为 stopped
            registry.register(
                pool="work",
                pid=os.getpid(),
                port=signal_port,
                status="stopped"
            )
            logger.info("已更新 RuntimeRegistry 状态为 stopped")
            sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal_handler)

    # 主循环：轮询 Queue 目录
    logger.info("开始监控 Queue 目录...")
    poll_interval = args.poll_interval
    last_check_time = 0
    consecutive_failures = 0
    max_backoff = 60.0

    while True:
        current_time = time.time()

        # 轮询间隔控制
        if current_time - last_check_time >= poll_interval:
            last_check_time = current_time

            try:
                # 更新 registry 心跳
                registry.heartbeat("work")

                # 先检查超时任务
                timed_out = runtime.check_timeouts()
                for item in timed_out:
                    logger.warning(
                        f"任务超时: {item['task_id']} @ {item['slot_id']} after {item['timeout_seconds']}s"
                    )

                # 列出 Queue 中的任务
                tasks = runtime.list_queue_tasks()

                if tasks:
                    logger.info(f"检测到 {len(tasks)} 个任务")

                    # 尝试派发任务
                    result = runtime.dispatch_next(dry_run=False)

                    if result["dispatched"]:
                        logger.info(
                            f"派发成功: {result['task_id']} -> {result['slot_id']}"
                        )
                        launch_result = result.get("launch", {})
                        if launch_result.get("launched"):
                            logger.info(
                                f"Worker 进程已启动: PID={launch_result.get('pid')}"
                            )
                    else:
                        error = result.get("error", "未知错误")
                        logger.warning(f"派发失败: {error}")

                consecutive_failures = 0

            except Exception as e:
                consecutive_failures += 1
                backoff = min(2 ** consecutive_failures, max_backoff)
                logger.error(f"Cycle failed (attempt {consecutive_failures}): {e}", exc_info=True)
                time.sleep(backoff)

        # 短暂休眠，避免 CPU 占用过高
        time.sleep(0.1)


if __name__ == "__main__":
    main()
