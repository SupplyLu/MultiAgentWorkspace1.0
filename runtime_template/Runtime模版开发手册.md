# Runtime 模版开发手册

**版本**: v1.0.0  
**最后更新**: 2026-05-02

---

## 1. 库/依赖清单

| 库名称 | 版本 | 官方 URL | 接口类型 | 使用部分 | 环境要求 | 项目中的作用 |
|--------|------|----------|----------|----------|----------|--------------|
| filelock | 3.13+ | https://pypi.org/project/filelock/ | Python SDK | FileLock | Python 3.10+ | 跨进程文件锁，保证 JSON 状态文件原子读写 |
| dataclasses | stdlib | - | Python stdlib | @dataclass | Python 3.10+ | 状态机模板、配置对象的结构化定义 |
| pathlib | stdlib | - | Python stdlib | Path | Python 3.10+ | 跨平台路径操作 |
| subprocess | stdlib | - | Python stdlib | Popen | Python 3.10+ | 启动 Claude CLI 子进程 |
| json | stdlib | - | Python stdlib | json.load/dump | Python 3.10+ | 任务文件、状态文件序列化 |
| re | stdlib | - | Python stdlib | re.compile | Python 3.10+ | 任务头部字段安全校验 |

**可移除部分**: 无  
**推荐保留**: 全部依赖均为核心功能必需

---

## 2. 开发日志

### [v1.0.0] - 2026-05-02
#### 已完成
- 从现有 Runtime 抽取核心机制：file_queue、json_store、pool_state_templates、launch_manager、windows_process
- 定义标准目录结构：Queue/Outbox/fields/槽位 workspace
- 定义 BAT 信号协议：Online/Done/Start*/Accepted/Denied
- 定义 BOOTSTRAP 注入协议：用户提供专属 BOOTSTRAP.txt
- 创建模版生成器框架：`runtime_template_generator.py`
- 添加完整测试套件：`runtime_template/tests/`
- 与现有 Runtime 核心组件完全对齐，不做功能裁剪

#### 注意事项
- 本模版是"框架"，不是"实例"——不包含具体业务池（work/thinking/construct/gate）
- 用户使用时需提供：池类型、槽位数量、专属 BOOTSTRAP、状态机定义
- **核心组件与现有 Runtime 完全一致**：file_queue、json_store、pool_state_templates、launch_manager、windows_process
- 生成的 Pool 与现有 Pool（Queue/slots/fields/Outbox）结构一致
- 内部流转的项目主键（PROJECT_KEY、BATCH_ID）遵循现有 Runtime 格式规范
- 仅通过名字、Bootstrap、中间信号 bat 名称、职能四个维度与现有 Runtime 区分

---

## 3. 目录

1. 库/依赖清单 ........................ 第 1 节
2. 开发日志 ............................ 第 2 节
3. 目录 ................................ 第 3 节
4. 修改纪律 ............................ 第 4 节
5. 核心组件说明 ........................ 第 5 节
6. 标准目录结构 ........................ 第 6 节
7. BAT 信号协议 ........................ 第 7 节
8. BOOTSTRAP 注入协议 .................. 第 8 节
9. 状态机模板协议 ...................... 第 9 节
10. 工程文件清单 ....................... 第 10 节
11. 手册维护规则 ....................... 第 11 节

---

## 4. 修改纪律

**铁律：只修改指定的业务区域。除非存在兼容性或逻辑依赖，否则禁止改动无关部分。**

具体规则：
- 严格只修改分配的业务区域
- 如果没有兼容性/逻辑问题，**绝不**改动其他业务区域
- 如果必须跨区域修改，必须记录**为什么**
- 跨区域修改前必须获得明确批准

---

## 5. 核心组件说明

### 5.1 file_queue.py - 任务文件解析器

**作用**: 解析 TXT 格式任务文件头部（key: value 格式），提取任务元数据

**核心函数**:
- `parse_task_file(file_path)` - 解析任务文件，返回 headers + body
- `validate_id_field(value, field_name)` - 校验关键字段（TASK_ID/FEATURE_ID/BATCH_ID/PROJECT_NAME），防止注入和路径穿越

**安全机制**:
- 只允许 `[a-zA-Z0-9_-]` 字符
- 最大长度 128 字符
- 防止路径穿越（`../`）和命令注入

**使用示例**:
```python
from runtime_template.core.file_queue import parse_task_file

task = parse_task_file("Queue/task_001.txt")
if task:
    task_id = task["headers"]["TASK_ID"]
    body = task["body"]
```

### 5.2 json_store.py - 原子 JSON 存储

**作用**: 跨进程安全的 JSON 文件读写，使用 filelock + 原子写入（temp file + os.replace）

**核心类**:
- `JSONStore(file_path, default_factory)` - JSON 文件存储对象
- `read()` - 读取 JSON 数据
- `write(data)` - 原子写入 JSON 数据
- `update(updater)` - 原子读-改-写操作

**线程安全**: 使用 threading.RLock（进程内）+ FileLock（跨进程）双重锁

**使用示例**:
```python
from runtime_template.core.json_store import JSONStore

store = JSONStore("state/pool_state.json", default_factory=dict)
store.ensure_initialized()

# 原子更新
store.update(lambda data: {**data, "status": "running"})
```

### 5.3 pool_state_templates.py - 状态机模板

**作用**: 定义池的状态转换规则（状态机）

**核心类**:
- `StateTransition` - 状态转换定义（from_state, to_state, allowed_signals）
- `PoolStateTemplate` - 池状态机模板（initial_state, terminal_states, transitions）
- `PoolStateTemplateRegistry` - 全局状态机注册表

**状态机示例**（简化的 work 池）:
```
state_0 (idle) --[online]--> state_1 (online)
state_1 (online) --[start_writing]--> state_2 (writing)
state_2 (writing) --[done]--> state_3 (done, terminal)
```

**使用示例**:
```python
from runtime_template.core.pool_state_templates import PoolStateTemplate, StateTransition

template = PoolStateTemplate(
    pool_id="custom_pool",
    initial_state="state_0",
    terminal_states={"state_2"},
    transitions=[
        StateTransition("state_0", "state_1", ["start"], "idle -> working"),
        StateTransition("state_1", "state_2", ["done"], "working -> done"),
    ]
)

next_state = template.get_next_state("state_0", "start")  # "state_1"
```

### 5.4 launch_manager.py - CLI 进程启动器

**作用**: 启动 Claude CLI 子进程，注入 BOOTSTRAP 和 RUNTIME_CONTEXT

**核心类**:
- `LaunchRequest` - 启动请求配置（bat_path, working_dir, bootstrap_path, runtime_context_path）
- `LaunchManager` - 进程启动管理器

**启动流程**:
1. 生成 launch.bat，内容包含 `claude` 命令 + BOOTSTRAP 提示词
2. 使用 `subprocess.Popen` 启动 bat
3. 在 Windows 上使用 Job Object 管理进程生命周期

**使用示例**:
```python
from runtime_template.core.launch_manager import LaunchManager, LaunchRequest
from pathlib import Path

manager = LaunchManager()
request = LaunchRequest(
    bat_path=Path("worker_01/launch_worker_01.bat"),
    working_dir=Path("worker_01/workspace"),
    bootstrap_path=Path("tools/BOOTSTRAP.txt"),
)

result = manager.launch(request, dry_run=False)
print(f"Launched PID: {result['pid']}")
```

### 5.5 signal_bridge.py - 信号桥接器

**作用**: BAT 文件通过此脚本向 Runtime 发送生命周期信号

**信号类型**:
- `online` - Agent 上线
- `start_*` - 开始某阶段（如 start_writing, start_thinking）
- `done` - 任务完成
- `approved/rejected/denied` - 审批结果
- `blocked/failed/timeout` - 异常状态

**调用格式**:
```bash
python signal_bridge.py --agent-id worker_01 --task-id task_001 --signal online --pool work
```

---

## 6. 标准目录结构

每个池实例必须包含以下标准目录：

```
pools/{pool_name}/
├── Queue/              # 任务队列（待处理任务文件）
├── Outbox/             # 输出箱（已完成任务的最终交付物）
├── fields/             # 字段区（长期保留的项目产物，如代码仓库）
├── Rejectbox/          # 拒绝箱（可选，用于审批类池）
└── {slot_prefix}_*/    # 槽位目录（如 worker_01, worker_02）
    └── workspace/      # 槽位工作区（Agent 执行任务的临时空间）
```

**目录语义**:
- **Queue**: Runtime 将任务文件放入此处，槽位从此处取任务
- **Outbox**: 槽位完成任务后，Runtime 将最终产物从 workspace 复制到此处
- **fields**: 长期保留的项目产物（如 `fields/ProjectA-v1/src/`），不会被清理
- **Rejectbox**: 审批类池（如 gate）拒绝的任务放入此处
- **workspace**: 槽位的临时工作区，任务完成后可能被清理

**强制规则**:
- Agent **只能**在 `workspace/` 中工作
- Agent **禁止**直接写入 `Outbox/` 或 `fields/`
- Runtime 在槽位进入终态后，负责将 `workspace/` 中的最终产物复制到 `Outbox/`

---

## 7. BAT 信号协议

### 7.1 标准信号 BAT 文件

所有池必须提供以下标准 BAT 文件（位于 `tools/` 目录）：

| BAT 文件 | 信号 | 触发时机 | 参数 |
|----------|------|----------|------|
| `Online.bat` | `online` | Agent 启动后立即调用 | `AGENT_ID TASK_ID POOL MESSAGE` |
| `Done.bat` | `done` | 任务完成 | `AGENT_ID TASK_ID POOL RESULT` |
| `Blocked.bat` | `blocked` | 遇到阻塞 | `AGENT_ID TASK_ID POOL REASON` |
| `Failed.bat` | `failed` | 任务失败 | `AGENT_ID TASK_ID POOL ERROR` |

### 7.2 池特定信号 BAT 文件

根据池的状态机定义，可添加池特定的信号 BAT：

**示例**（work 池）:
- `StartWriting.bat` → 信号 `start_writing`

**示例**（thinking 池）:
- `StartThinking.bat` → 信号 `start_thinking`
- `StartSummarizing.bat` → 信号 `start_summarizing`

**示例**（gate 池）:
- `StartReview.bat` → 信号 `start_review`
- `Accepted.bat` → 信号 `approved`
- `Denied.bat` → 信号 `rejected`

### 7.3 BAT 文件标准格式

所有 BAT 文件必须遵循以下格式：

```batch
@echo off
setlocal enabledelayedexpansion

set AGENT_ID=%1
set TASK_ID=%2
set SIGNAL={signal_name}
set POOL=%3
set MESSAGE=%4

python "%~dp0signal_bridge.py" --agent-id %AGENT_ID% --task-id %TASK_ID% --signal %SIGNAL% --pool %POOL% --message %MESSAGE%

endlocal
```

**参数说明**:
- `%1` (AGENT_ID) - 槽位 ID（如 `worker_01`）
- `%2` (TASK_ID) - 任务 ID（如 `task_001`）
- `%3` (POOL) - 池名称（如 `work`）
- `%4` (MESSAGE) - 可选消息

---

## 8. BOOTSTRAP 注入协议

### 8.1 BOOTSTRAP 文件作用

BOOTSTRAP.txt 是 Agent 启动后第一个读取的指令文件，定义：
- Agent 的身份和职责
- 生命周期 BAT 的调用时机和格式
- 执行流程和强制规则
- 输入/输出位置

### 8.2 BOOTSTRAP 标准结构

每个 BOOTSTRAP.txt 必须包含以下章节：

```
1. 身份定义
   - 你是谁（Agent 角色）
   - 你的职责是什么
   - 禁止事项（如禁止调用 Skill）

2. 生命周期 BAT 用法
   - 列出所有可用的 BAT 文件
   - 每个 BAT 的调用格式和参数
   - 调用时机

3. 执行流程
   - 步骤 1: 读取任务文件
   - 步骤 2: 提取 TASK_ID
   - 步骤 3: 调用 Online.bat
   - 步骤 4: 执行任务（根据池类型）
   - 步骤 5: 调用 Done.bat
   - 步骤 6: 退出

4. 强制规则
   - 禁止以 end_turn 或空回复结束对话
   - 调用终态 bat 后直接结束
   - 禁止调用任何 Skill
   - 最终产物必须写入 workspace/
   - 环境变量说明（AGENT_ID, TASK_ID, POOL, SIGNAL_SERVER_PORT）
```

### 8.3 用户自定义 BOOTSTRAP

用户在初始化 Runtime 时，必须提供专属 BOOTSTRAP.txt，包含：
- 池特定的执行流程（如 thinking 池的"思考 → 总结"两阶段）
- 池特定的 BAT 调用顺序（如 `StartThinking.bat → StartSummarizing.bat → Done.bat`）
- 池特定的输入/输出约定（如 construct 池需要创建 PROJECT_ROOT）

**模版不提供默认 BOOTSTRAP**，避免业务逻辑写死。

---

## 9. 状态机模板协议

### 9.1 状态机定义规范

每个池必须定义状态机，包含：
- `pool_id` - 池唯一标识
- `initial_state` - 初始状态（通常是 `state_0`）
- `terminal_states` - 终态集合（任务完成或失败的状态）
- `transitions` - 状态转换列表

### 9.2 状态命名约定

- 初始状态: `state_0`
- 中间状态: `state_1`, `state_2`, ...
- 终态: `state_N` 或 `state_N_{suffix}`（如 `state_3_approved`, `state_3_rejected`）
- 异常终态: `state_timeout`, `state_failed`

### 9.3 信号命名约定

- 生命周期信号: `online`, `done`, `blocked`, `failed`, `timeout`
- 阶段开始信号: `start_{phase}`（如 `start_writing`, `start_thinking`）
- 审批信号: `approved`, `rejected`, `denied`
- 阶段完成信号: `{phase}_passed`（如 `cut_passed`, `test_passed`）

### 9.4 状态机示例

**简单两阶段池**（如 work 池）:
```
state_0 (idle) --[online]--> state_1 (online)
state_1 (online) --[start_writing]--> state_2 (writing)
state_2 (writing) --[done]--> state_3 (done, terminal)
```

**复杂多阶段池**（如 thinking 池）:
```
state_0 (idle) --[online]--> state_1 (online)
state_1 (online) --[start_thinking]--> state_2 (thinking)
state_2 (thinking) --[start_summarizing]--> state_3 (summarizing)
state_3 (summarizing) --[done]--> state_4 (done, terminal)
```

**审批池**（如 gate 池）:
```
state_0 (idle) --[online]--> state_1 (online)
state_1 (online) --[start_review]--> state_2 (reviewing)
state_2 (reviewing) --[approved]--> state_3_approved (terminal)
state_2 (reviewing) --[rejected]--> state_3_rejected (terminal)
```

---

## 10. 工程文件清单

### 10.1 核心组件

| 文件 | 路径 | 作用 | 必需 |
|------|------|------|------|
| file_queue.py | core/ | 任务文件解析器 | 是 |
| json_store.py | core/ | 原子 JSON 存储 | 是 |
| pool_state_templates.py | core/ | 状态机模板 | 是 |
| launch_manager.py | core/ | CLI 进程启动器 | 是 |
| signal_bridge.py | tools/ | 信号桥接器 | 是 |

### 10.2 工具文件

| 文件 | 路径 | 作用 | 必需 |
|------|------|------|------|
| Online.bat | tools/ | 上线信号 | 是 |
| Done.bat | tools/ | 完成信号 | 是 |
| Blocked.bat | tools/ | 阻塞信号 | 是 |
| Failed.bat | tools/ | 失败信号 | 是 |
| {池特定}.bat | tools/ | 池特定信号 | 根据池定义 |

### 10.3 模版生成器

| 文件 | 路径 | 作用 | 必需 |
|------|------|------|------|
| runtime_template_generator.py | / | 模版生成器脚本 | 是 |
| README.md | / | 使用说明 | 是 |

### 10.4 编译/构建方式

**无需编译**，纯 Python 脚本。

**使用方式**:
```bash
python runtime_template_generator.py \
  --pool-name my_pool \
  --slot-prefix worker \
  --slot-count 3 \
  --bootstrap-path /path/to/BOOTSTRAP.txt \
  --state-machine-path /path/to/state_machine.json \
  --output-dir /path/to/output
```

---

## 11. 手册维护规则

- **一个项目，一份手册** - 所有开发日志和注意事项统一记录在此
- **禁止未授权编辑** - 手册内容变更必须经过复核
- **修改后复核** - 更新手册后，必须经过至少 **2 轮无项目背景的 Agent 复核**（验证新人能否理解全部内容）
- **复核标准**: 一个零背景的 Agent 或人员应能够：
  - 描述所有业务功能
  - 理解源码结构
  - 复现构建过程
  - 知道在哪里做特定修改

---

## 附录 A: 与现有 Runtime 的差异

| 特性 | 现有 Runtime | Runtime 模版 |
|------|--------------|--------------|
| 池定义 | 硬编码 work/thinking/construct/gate/task/package | 用户自定义，模版不包含具体池 |
| BOOTSTRAP | 每个池有固定 BOOTSTRAP.txt | 用户提供专属 BOOTSTRAP.txt |
| 状态机 | 硬编码在 pool_state_templates.py | 用户提供 JSON 定义，动态注册 |
| BAT 文件 | 所有池的 BAT 都在 tools/ | 用户根据状态机生成对应 BAT |
| 目录结构 | 固定 pools/work/, pools/thinking/ 等 | 用户指定池名称和槽位前缀 |

**核心理念**: 模版是"框架"，不是"实例"。用户使用模版生成器创建自己的 Runtime 实例。

---

## 附录 B: 快速开始示例

假设用户要创建一个简单的 "review" 池，包含 2 个 reviewer 槽位：

**步骤 1**: 编写 BOOTSTRAP.txt
```
你是 Reviewer Agent，负责审查代码。

生命周期 BAT:
- Online.bat - 上线时调用
- StartReview.bat - 开始审查时调用
- Done.bat - 审查完成时调用

执行流程:
1. 读取 Queue/ 中的任务文件
2. 调用 Online.bat
3. 调用 StartReview.bat
4. 在 workspace/ 中完成审查，生成 review_report.md
5. 调用 Done.bat
6. 退出
```

**步骤 2**: 编写状态机定义 state_machine.json
```json
{
  "pool_id": "review",
  "initial_state": "state_0",
  "terminal_states": ["state_3"],
  "transitions": [
    {"from_state": "state_0", "to_state": "state_1", "allowed_signals": ["online"]},
    {"from_state": "state_1", "to_state": "state_2", "allowed_signals": ["start_review"]},
    {"from_state": "state_2", "to_state": "state_3", "allowed_signals": ["done"]}
  ]
}
```

**步骤 3**: 运行生成器
```bash
python runtime_template_generator.py \
  --pool-name review \
  --slot-prefix reviewer \
  --slot-count 2 \
  --bootstrap-path BOOTSTRAP.txt \
  --state-machine-path state_machine.json \
  --output-dir ./my_review_runtime
```

**步骤 4**: 生成的目录结构
```
my_review_runtime/
├── pools/
│   └── review/
│       ├── Queue/
│       ├── Outbox/
│       ├── fields/
│       ├── reviewer_01/
│       │   └── workspace/
│       └── reviewer_02/
│           └── workspace/
├── tools/
│   ├── Online.bat
│   ├── Done.bat
│   ├── StartReview.bat
│   ├── signal_bridge.py
│   └── BOOTSTRAP.txt
└── core/
    ├── file_queue.py
    ├── json_store.py
    ├── pool_state_templates.py
    └── launch_manager.py
```

---

**手册结束**
