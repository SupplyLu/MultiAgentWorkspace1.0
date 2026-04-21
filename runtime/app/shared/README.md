# Runtime 共享控件使用手册

> 维护日期：2026-04-18
> 用途：所有池通用的底层执行控件

## 快速导入

```python
from app.shared import JSONStore, EventBus, AgentRecord
from app.shared.launch_manager import LaunchManager
from app.shared.shutdown_manager import ShutdownManager
```

## 控件清单

| 控件 | 文件 | 用途 |
|------|------|------|
| JSONStore | json_store.py | 原子 JSON 存储 |
| WindowsProcess | windows_process.py | Windows 进程/Job Object 原语 |
| FileQueue | file_queue.py | TXT 任务头解析 |
| EventBus | event_bus.py | 进程内事件总线 |
| Constants | constants.py | 常量定义 |
| AgentRecord | agent_record.py | Agent 记录模型 |
| HeartbeatMonitor | heartbeat_monitor.py | 心跳超时检测 |
| LaunchManager | launch_manager.py | CLI 进程拉起 |
| ShutdownManager | shutdown_manager.py | 进程关停 |

## LaunchManager 使用示例

```python
from pathlib import Path
from app.shared.launch_manager import LaunchManager, LaunchRequest

manager = LaunchManager(workspace_root=Path("C:/Users/lenovo/Desktop/MultiAgentWorkspace1.0"))

request = LaunchRequest(
    bat_path=Path("agents/worker_01/launch_worker_01.bat"),
    working_dir=Path("agents/worker_01"),
    bootstrap_path=Path("agents/worker_01/BOOTSTRAP.txt"),
)

result = manager.launch(request, dry_run=False)
# result: {"pid": ..., "job_handle": ..., "success": True}
```

## ShutdownManager 使用示例

```python
from app.shared.shutdown_manager import ShutdownManager, ShutdownRequest

manager = ShutdownManager(workspace_root=Path("..."))

request = ShutdownRequest(
    worker_id="worker_01",
    pid=12345,
    job_handle=67890,
    reason="task_completed",
    timeout_seconds=5.0
)

result = manager.request_shutdown(request)
```

## 注意事项

1. 所有 shared 控件不依赖池运行时
2. 新代码禁止直接修改 shared 内文件
3. LaunchManager 自动清除 CLAUDE* 环境变量
4. Job Object 关闭即全杀进程树
