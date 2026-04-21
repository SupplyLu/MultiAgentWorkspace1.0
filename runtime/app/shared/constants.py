# -*- coding: utf-8 -*-
"""
Runtime 基础常量定义
包含路径常量、超时默认值、角色常量、状态常量
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# 基础路径
# ---------------------------------------------------------------------------

# runtime 根目录（此文件位于 runtime/app/core/constants.py）
RUNTIME_ROOT = Path(__file__).parent.parent.parent.resolve()

# workspace 根目录（runtime 的上一级）
WORKSPACE_ROOT = RUNTIME_ROOT.parent.resolve()

# 各功能子目录
RUNTIME_APP_DIR = RUNTIME_ROOT / "app"
RUNTIME_CONFIG_DIR = RUNTIME_ROOT / "config"
RUNTIME_LOGS_DIR = RUNTIME_ROOT / "logs"
RUNTIME_STATE_DIR = RUNTIME_ROOT / "state"
RUNTIME_SCRIPTS_DIR = RUNTIME_ROOT / "scripts"
RUNTIME_TESTS_DIR = RUNTIME_ROOT / "tests"

# 默认配置文件路径
DEFAULT_CONFIG_PATH = RUNTIME_CONFIG_DIR / "runtime.yaml"

# ---------------------------------------------------------------------------
# 超时默认值（单位：秒）
# ---------------------------------------------------------------------------

# Agent 空闲超时：超过此时间无活动则标记为 idle
DEFAULT_IDLE_TIMEOUT = 300  # 5 分钟

# Agent 强制超时：超过此时间不管活动与否强制终止
DEFAULT_HARD_TIMEOUT = 3600  # 60 分钟

# 轮询回退间隔：事件驱动失败时的降级轮询间隔
DEFAULT_POLL_FALLBACK_SECONDS = 5

# 进程启动等待超时
DEFAULT_STARTUP_TIMEOUT = 30

# 进程优雅停止等待时间
DEFAULT_GRACEFUL_STOP_TIMEOUT = 10

# ---------------------------------------------------------------------------
# Agent 角色常量
# ---------------------------------------------------------------------------

ROLE_BRAIN = "brain"          # 总大脑
ROLE_SUB_BRAIN = "sub_brain"  # 子大脑
ROLE_WORKER = "worker"        # 工作者

ALL_ROLES = (ROLE_BRAIN, ROLE_SUB_BRAIN, ROLE_WORKER)

# ---------------------------------------------------------------------------
# Agent 生命周期状态常量
# ---------------------------------------------------------------------------

STATE_IDLE = "idle"           # 空闲，等待任务
STATE_RUNNING = "running"     # 正在执行任务
STATE_WAITING = "waiting"     # 等待外部依赖（如子 Agent 完成）
STATE_DONE = "done"           # 任务完成，可被回收
STATE_ERROR = "error"         # 发生错误
STATE_STOPPED = "stopped"     # 已被停止

ALL_STATES = (
    STATE_IDLE,
    STATE_RUNNING,
    STATE_WAITING,
    STATE_DONE,
    STATE_ERROR,
    STATE_STOPPED,
)

# 终态集合：处于这些状态的 Agent 不需要继续监控
TERMINAL_STATES = (STATE_DONE, STATE_ERROR, STATE_STOPPED)

# ---------------------------------------------------------------------------
# 队列与文件名常量
# ---------------------------------------------------------------------------

QUEUE_DIR_NAME = "queue"         # 任务队列目录名
OUTBOX_FILE_NAME = "outbox.txt"  # 输出消息文件名
STATUS_FILE_NAME = "status.txt"  # 状态文件名
PROGRESS_FILE_NAME = "progress.txt"  # 进度文件名

# ---------------------------------------------------------------------------
# 日志常量
# ---------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_LOG_LEVEL = "INFO"
