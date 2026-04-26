"""Thinking Runtime 守护进程入口

负责：
  - 启动 ThinkingRuntime + Signal Server
  - 轮询 Queue 目录，自动派发任务
  - 超时检测（基于任务 TIMEOUT 字段）
  - 日志输出到文件和 stdout
  - 优雅关闭（SIGINT/SIGTERM）
  - 动态扫描 sub_brain_* 槽位目录
"""

from __future__ import annotations

import argparse
import fnmatch
import logging
import os
import signal
import socket
import sys
import time
from pathlib import Path

from app.runtimes.thinking_runtime import ThinkingRuntime
from app.services.runtime_registry import RuntimeRegistry


def find_free_port(start: int = 18910, end: int = 19010) -> int:
    """查找可用端口（与 Work Runtime 端口范围不重叠）"""
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

    logger = logging.getLogger("thinking_runtime")
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
    """确保必要的目录结构存在，动态识别所有 sub_brain_* 槽位"""
    pools_dir = root_dir / "pools" / "thinking"
    (pools_dir / "Queue").mkdir(parents=True, exist_ok=True)
    (pools_dir / "Outbox").mkdir(parents=True, exist_ok=True)

    # 动态扫描所有 sub_brain_* 目录并创建 workspace
    if pools_dir.exists():
        for sub_dir in pools_dir.iterdir():
            if sub_dir.is_dir() and fnmatch.fnmatch(sub_dir.name, "sub_brain_*"):
                (sub_dir / "workspace").mkdir(parents=True, exist_ok=True)


def main() -> None:
    """主函数"""
    parser = argparse.ArgumentParser(description="Thinking Runtime 守护进程")
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
        help="信号服务端口（默认动态分配 18910-19010）",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Queue 轮询间隔（秒），默认 2.0",
    )
    args = parser.parse_args()

    root_dir = args.root_dir.resolve()
    log_file = root_dir / "logs" / "thinking_runtime.log"

    # 初始化日志
    logger = setup_logging(log_file)
    logger.info("=" * 50)
    logger.info("Thinking Runtime 守护进程启动")
    logger.info(f"工作区: {root_dir}")
    logger.info(f"日志文件: {log_file}")

    # 查找空闲端口（与 Work Runtime 端口范围不重叠）
    signal_port = args.port or find_free_port()
    logger.info(f"信号服务端口: {signal_port}")

    # 确保目录结构
    ensure_directory_structure(root_dir)
    logger.info("目录结构已确认")

    # 初始化 RuntimeRegistry
    registry = RuntimeRegistry(root_dir=root_dir)

    # 初始化 ThinkingRuntime
    runtime = ThinkingRuntime(root_dir=root_dir, signal_port=signal_port)
    runtime.start()
    logger.info("Signal Server 已启动")

    # 注册到 registry
    registry.register(
        pool="thinking",
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
            registry.register(
                pool="thinking",
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

    while True:
        current_time = time.time()

        # 轮询间隔控制
        if current_time - last_check_time >= poll_interval:
            last_check_time = current_time

            # 更新 registry 心跳
            registry.heartbeat("thinking")

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

        # 短暂休眠，避免 CPU 占用过高
        time.sleep(0.1)


if __name__ == "__main__":
    main()
