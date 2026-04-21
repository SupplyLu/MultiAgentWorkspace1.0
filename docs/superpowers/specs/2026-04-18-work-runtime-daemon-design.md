# Work Runtime 后台守护进程设计

**日期**: 2026-04-18
**目标**: 为 Work Pool 创建后台守护进程入口，实现 Queue 自动监听与派发
**架构**: 轮询式文件系统监控 + WorkRuntime 调度 + 信号驱动生命周期

---

## 1. 背景与目标

### 当前状态
- `WorkRuntime` 已实现完整调度能力：
  - `dispatch_next()` 派发任务到空闲槽位
  - `_deploy_lifecycle_bats()` 部署生命周期 bats
  - `handle_signal()` 接收 worker 信号并释放槽位
  - `RuntimePromptBuilder` 注入启动词和生命周期协议
- 缺少主程序入口，无法持续运行

### 目标
创建 `runtime/app/main.py` 作为后台守护进程，实现：
1. 启动时初始化 WorkRuntime + Signal Server
2. 持续监听 `Queue/` 目录，检测新任务文件
3. 自动派发任务到空闲 worker 槽位
4. 日志输出到文件和 stdout
5. 优雅关闭（Ctrl+C / SIGTERM）

---

## 2. 核心架构

```
main.py (入口)
├── 初始化 WorkRuntime(root_dir, signal_port)
├── 启动 Signal Server (runtime.start())
├── 创建必要目录（Queue/Outbox/worker_*/workspace）
├── 主循环：轮询 Queue 目录
│   ├── 检测 *.txt 文件
│   ├── 调用 runtime.dispatch_next(dry_run=False)
│   └── 等待 poll_interval 秒
└── 信号处理：SIGINT/SIGTERM → runtime.stop() → 退出
```

### 职责边界

| 组件 | 职责 |
|------|------|
| **main.py** | 守护进程入口、Queue 监控、派发触发、日志配置、信号处理 |
| **WorkRuntime** | 任务派发、槽位管理、lifecycle bats 部署、worker 信号处理 |
| **RuntimePromptBuilder** | 启动词注入、生命周期协议注入（Runtime 携带，不是 task.txt） |
| **LaunchManager** | 进程拉起、Job Object 管理、进程清理 |
| **SignalServer** | HTTP 信号接收、状态机推进、事件持久化 |

---

## 3. 技术选择

### 文件系统监控：轮询模式

| 方案 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| **轮询（推荐）** | 零外部依赖、跨平台、Debug 直观 | 有延迟（轮询间隔内） | ✅ 采用 |
| watchdog 库 | 事件驱动、低延迟 | Windows 不稳定、增加依赖 | ❌ 不采用 |
| inotify (Linux) | 原生高效 | 仅 Linux，Windows 不可用 | ❌ 不适用 |

**决策理由**：
- 本场景允许秒级延迟（2 秒轮询间隔）
- 避免 watchdog 在 Windows 上的稳定性问题
- 代码简单，易于调试和维护

### 日志系统

- **双输出**：同时输出到 stdout 和 `logs/work_runtime.log`
- **格式**：`[TIMESTAMP] [LEVEL] message`
- **级别**：INFO（正常运行）、ERROR（派发失败、信号异常）

### 信号端口

- **动态分配**：使用 `find_free_port()` 避免端口冲突
- **默认范围**：18800-18900
- **可配置**：通过 `--port` 参数指定

---

## 4. 目录结构

```
runtime/
├── app/
│   ├── __init__.py          # 空文件
│   ├── main.py              # 守护进程入口（新增）
│   ├── runtimes/
│   │   └── work_runtime.py  # WorkRuntime 实现（已有）
│   ├── services/
│   │   ├── signal_server.py
│   │   └── runtime_prompt_builder.py
│   └── shared/
│       └── launch_manager.py
├── logs/                     # 日志目录（新增）
│   └── work_runtime.log
├── runtime/
│   └── tools/               # lifecycle bats 源文件（已有）
│       ├── Online.bat
│       ├── StartWriting.bat
│       └── Done.bat
└── pools/
    └── work/
        ├── Queue/           # 任务队列目录
        ├── Outbox/          # 输出目录
        ├── worker_01/
        │   └── workspace/
        └── worker_02/
            └── workspace/
```

---

## 5. 启动参数

```bash
python -m app.main [root_dir] [--port PORT] [--poll-interval SECONDS]
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `root_dir` | 工作区根目录 | 当前目录的父目录 |
| `--port` | 信号服务端口 | 动态分配（18800-18900） |
| `--poll-interval` | 轮询间隔（秒） | 2 |

**示例**：
```bash
# 使用默认配置
python -m app.main

# 指定工作区和端口
python -m app.main C:\MultiAgentWorkspace1.0\runtime --port 18850

# 指定轮询间隔
python -m app.main --poll-interval 5
```

---

## 6. 核心行为

### 6.1 启动流程

1. **解析参数**：root_dir、port、poll_interval
2. **初始化日志**：配置双输出（stdout + file）
3. **查找空闲端口**：如果未指定 port，调用 `find_free_port()`
4. **创建 WorkRuntime**：`WorkRuntime(root_dir, signal_port)`
5. **启动 Signal Server**：`runtime.start()`
6. **创建目录结构**：Queue、Outbox、worker_*/workspace（如不存在）
7. **进入主循环**：开始轮询 Queue 目录

### 6.2 主循环逻辑

```python
while True:
    tasks = runtime.list_queue_tasks()  # 返回 Queue/*.txt 文件列表
    if tasks:
        result = runtime.dispatch_next(dry_run=False)
        if result["dispatched"]:
            log.info(f"Dispatched {result['task_id']} to {result['slot_id']}")
        else:
            log.info(f"No idle slot: {result.get('error')}")
    time.sleep(poll_interval)
```

**关键点**：
- `list_queue_tasks()` 已有实现，返回排序后的任务文件列表
- `dispatch_next()` 已有实现，自动处理：
  - 任务文件解析
  - 槽位分配
  - lifecycle bats 部署
  - 启动词注入（RuntimePromptBuilder）
  - worker 进程拉起
  - 任务文件从 Queue 移除（防重复派发）

### 6.3 并发派发

- **两个槽位**：worker_01 和 worker_02
- **自动并发**：Queue 有任务 + 有空闲槽位 → 立即派发
- **槽位释放**：worker 发送 Done/Failed/Blocked 信号 → `handle_signal()` 释放槽位

### 6.4 优雅关闭

```python
def signal_handler(sig, frame):
    log.info("Received shutdown signal, stopping...")
    runtime.stop()  # 停止 Signal Server
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
```

---

## 7. 错误处理

| 场景 | 处理策略 |
|------|----------|
| Queue 为空 | 静默等待，继续轮询 |
| 无空闲槽位 | 记录 INFO 日志，继续轮询 |
| dispatch 失败 | 记录 ERROR 日志，继续轮询（不 crash） |
| worker 信号异常 | 记录 ERROR 日志，继续运行（不 crash） |
| 端口占用 | 自动查找下一个空闲端口 |

**原则**：守护进程不应因单个任务失败而崩溃，记录错误后继续运行。

---

## 8. 日志示例

```
[2026-04-18 10:30:15] [INFO] WorkRuntime daemon starting...
[2026-04-18 10:30:15] [INFO] Signal server started on port 18801
[2026-04-18 10:30:15] [INFO] Watching queue: C:\...\pools\work\Queue
[2026-04-18 10:30:17] [INFO] Dispatched t_001 to worker_01
[2026-04-18 10:30:17] [INFO] Launch: pid=12345, command=['cmd.exe', '/c', '...']
[2026-04-18 10:30:25] [INFO] Signal received: worker_01 | online | state_0 -> state_1
[2026-04-18 10:30:30] [INFO] Signal received: worker_01 | start_writing | state_1 -> state_2
[2026-04-18 10:30:45] [INFO] Signal received: worker_01 | done | state_2 -> state_3 (terminal)
[2026-04-18 10:30:45] [INFO] Slot released: worker_01
[2026-04-18 10:30:47] [INFO] Dispatched t_002 to worker_01
[2026-04-18 10:31:00] [INFO] Received shutdown signal, stopping...
[2026-04-18 10:31:00] [INFO] Signal server stopped
```

---

## 9. 与现有组件集成

### WorkRuntime（已有）
- `dispatch_next(dry_run=False)` → 派发任务，返回结果字典
- `list_queue_tasks()` → 返回 Queue 中的任务文件列表
- `start()` → 启动 Signal Server
- `stop()` → 停止 Signal Server
- `handle_signal()` → 处理 worker 信号，释放槽位

### RuntimePromptBuilder（已有）
- `build_agent_launch_bat_content(ctx)` → 生成 launch bat 内容
- 注入启动词：`"You are worker_01, execute task t_001..."`
- 注入生命周期协议：`"Run Online.bat when ready, StartWriting.bat when writing, Done.bat when complete"`

### LaunchManager（已有）
- `launch(request, dry_run=False)` → 拉起 worker 进程
- `cleanup_launch(launch_result)` → 清理 worker 进程（Job Object）

### SignalServer（已有）
- HTTP POST `/signal` 接收 worker 信号
- 状态机验证：检查当前状态，拒绝非法转换
- 事件持久化：写入 `events/` 目录

---

## 10. 测试策略

### 单元测试（不需要新增）
- WorkRuntime 已有完整测试覆盖（44/44 tests passing）

### 集成测试（E2E）
- `tests/e2e_work_runtime_demo.py` 已验证完整链路：
  - Queue 派发 → worker 拉起 → 信号流转 → 槽位释放
  - 动态端口分配
  - lifecycle bats 部署

### 手动验证（main.py 启动后）
1. 启动守护进程：`python -m app.main`
2. 放入任务文件到 `Queue/task_001.txt`
3. 观察日志：派发成功、worker 窗口弹出
4. 观察 worker 窗口：执行 Online.bat → StartWriting.bat → Done.bat
5. 观察日志：信号接收、槽位释放
6. Ctrl+C 关闭：优雅退出

---

## 11. 未来扩展

### Phase 2（可选）
- **多池支持**：main.py 同时管理 Work/Think/Review 三个池
- **Web UI**：实时查看槽位状态、任务队列、事件日志
- **任务优先级**：Queue 中的任务按优先级排序
- **槽位动态扩展**：根据负载自动增加 worker 槽位

### Phase 3（可选）
- **分布式部署**：多台机器运行 Runtime，共享 Queue（需要文件锁）
- **任务依赖**：支持任务间依赖关系（DAG）

---

## 12. 交付清单

- [ ] `runtime/app/main.py` 实现
- [ ] `runtime/logs/` 目录创建
- [ ] 手动验证：启动守护进程 + 派发真实任务
- [ ] 更新 `MultiAgentWorkspace1.0开发手册.md`：记录 main.py 启动方式
- [ ] 清理旧文件：`pools/work/worker_01/launch_worker_01.bat`（旧静态文件）
- [ ] 更新任务文件格式：`pools/work/Queue/.example_task.txt`（已正确）

---

## 13. 风险与限制

| 风险 | 缓解措施 |
|------|----------|
| 轮询延迟（2 秒） | 可接受，通过 `--poll-interval` 调整 |
| 端口冲突 | 动态端口分配 + 可配置 |
| 守护进程崩溃 | 错误处理 + 日志记录，不因单个任务失败而退出 |
| worker 卡住不发信号 | 未来可增加超时检测（Phase 2） |

---

## 14. 总结

本设计为 Work Pool 提供了一个简单、可靠的后台守护进程入口。核心原则：

1. **Runtime 携带启动词和生命周期协议**，不是 task.txt
2. **轮询式监控**，零外部依赖，跨平台兼容
3. **复用现有能力**，main.py 只做调度和监控
4. **优雅降级**，单个任务失败不影响整体运行
5. **可观测性**，完整日志记录所有关键事件

设计完成，准备进入实现阶段。
