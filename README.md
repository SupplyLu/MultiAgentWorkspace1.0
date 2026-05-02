# MultiAgentWorkspace1.0

> **仅需 Claude Code，无需任何插件，无广告，原生 Python 语言搭建 Agent 协作流水线。**
> 
> 目前已支持：自定义池加入、超时时间配置、可视化桌面 UI 管理。
> 
> **所有需求都可定制成流水线。**

[中文介绍](#中文) | [English](#english)

---

## 中文

### 项目简介

MultiAgentWorkspace1.0 是一个面向多 Agent 协作的池化运行时框架。它的目标不是简单“多开几个 Agent”，而是把复杂任务拆解为可治理、可追踪、可恢复的流水线执行系统。

在长链路任务里，常见问题是：上下文持续膨胀、角色职责混杂、状态不可观测、返工成本高。MultiAgentWorkspace1.0 通过六池分层架构 + 项目级 POST 跨池编排系统来降低这些问题，让协作流程更稳定。

### 为什么选择这个项目

| 特性 | 说明 |
|------|------|
| **零依赖启动** | 仅需 Claude Code CLI + Python，无需 Docker、无需 K8s、无需云服务 |
| **一键启动 UI** | `python -m app.desktop_ui.app` 启动桌面控制面板，所有 Runtime 自动纳管 |
| **原生 Python** | 无广告、无捆绑、代码完全透明可审计 |
| **高度可定制** | 六池架构可扩展，支持自定义 Pool 加入流水线 |
| **离线可用** | 完全本地运行，数据不出境，适合敏感场景 |

### 快速开始（3 步上手）

```bash
# 1. 安装依赖（仅需 psutil、PySide6 等常用库）
pip install -r requirements.txt

# 2. 进入 runtime 目录
cd runtime

# 3. 启动桌面 UI，一键管理所有 Pool
python -m app.desktop_ui.app
```

桌面 UI 启动后，你可以：
- 查看所有 Runtime 的实时状态
- 注册新项目并自动触发流水线
- 自定义 Pool 超时时间
- 创建自定义 Pool 加入流水线

### 这个项目能做什么

- 将任务按职责拆分到不同 Pool（Thinking / Construct / Gate / Work）
- 用 Runtime 驱动生命周期，通过信号（online / done / timeout 等）推进状态机
- POST 统一跨池投递，支持项目级路由、依赖检查、退回重排、原子工单识别
- 支持多槽位并行执行与超时治理
- 提供可审计的事件轨迹与投递记录

### 核心优势

1. **仅需 Claude Code，无需任何插件**
   不依赖额外 IDE 插件、不要求云端编排平台，直接基于 Claude Code CLI 即可搭建多 Agent 协作流水线。

2. **原生 Python 搭建，无广告、可审计**
   全部核心逻辑基于 Python 实现，目录清晰、依赖简单、改造成本低，适合继续二开和定制。

3. **简易上手，启动 UI 就可以使用**
   通过桌面 UI 作为统一入口，用户不需要分别理解每个 Runtime 的启动细节，开箱即可注册项目、观察状态、控制运行。

4. **支持自定义池加入流水线**
   现在已经支持 Create Pool，可以按你的业务定义新 Pool、槽位前缀、Bootstrap、状态机和动作步骤。

5. **支持超时时间配置**
   Work / Thinking / Construct / Gate / Package 五个执行池都支持默认超时持久化配置，适配不同复杂度任务。

6. **所有需求都可以定制成流水线**
   无论是代码开发、审查、构造、测试、打包，还是你自己的特殊环节，都可以拆成独立 Pool 并接入统一编排。

7. **降低上下文负担，减少注意力陷阱**
   通过多池分层和清晰职责边界，把任务切成更小的上下文单元，减少“一个 Agent 同时背负规划、构造、审查、执行”导致的注意力漂移。

8. **信号驱动生命周期，状态可观测**
   Runtime 通过 `online / start_* / done / timeout` 等信号推进状态机，问题定位更直接，不再依赖 `status/progress/outbox` 的间接猜测。

9. **POST 项目级编排，完整治理**
   以 `project_key`（格式 `XXX-(Vision)-(Mode)`）为唯一标识，统一管理项目注册、路由、依赖、投递、退回、人工干预（hold / resume / replay / skip）。

10. **Gate 原子工单拆分，灵活投递**
    Gate 审查通过后，Runtime 将项目拆分为原子工单（`project_key-NNN` 格式），POST 识别后逐个投递到 Work Pool，实现细粒度调度。

11. **职责边界明确，扩展更稳**
    各 Runtime 专注池内生命周期，POST 统一治理跨池流转，拒绝 / 退回逻辑清晰，降低模块耦合。

### 架构总览

当前架构围绕以下六层组织：

```text
Task Pool → Thinking Pool → Construct Pool → Gate Pool → Work Pool → Packaging Pool
                                      ↓              ↓
                              Rejectbox（退回）   POST System（投递编排）
```

- **Task Pool**：任务入口（外部驱动）
- **Thinking Pool**：需求拆解为子任务规格
- **Construct Pool**：架构处理与工单生成
- **Gate Pool**：代码质量与规范审查，支持 `accepted` / `denied`
- **Work Pool**：执行代码编写
- **Packaging Pool**：打包与交付
- **POST System**：跨池编排与投递层，处理项目路由、依赖、退回、原子工单

### v1.2.1 更新内容（基于 v1.2）

#### Gate Runtime dispatch rollback 补全
- 新增 `_rollback_dispatch()` 方法，与 Work/Thinking/Construct 保持一致
- 修复 dispatch 失败时 `.processing` 文件残留导致的任务死锁问题

#### 全池 txt-only 收口统一
- Thinking/Construct/Gate 只从 `workspace/` 根目录收集 `.txt` 文件
- 避免 Outbox 产生 `task_id/task_id` 双层嵌套
- Work Runtime 保持 legacy 模式向后兼容

#### 桌面 UI Create Pool 功能
- 新增 `pool_creation_service.py`、`pool_registry_service.py`、`create_pool_dialog.py`
- 支持自定义 Pool 创建：池名称、槽位前缀、槽位数量、流程模板、Bootstrap 编辑
- 运行时入口优先从 PoolRegistryService 读取，支持运行时动态注册

#### runtime_template/ 模版目录
- 提供 Runtime 模版骨架用于新池初始化
- 包含核心共享组件、BAT 模版、状态机示例
- 配合 Create Pool 功能实现自定义池快速创建

### v1.2 更新内容（基于 v1.1）

#### 执行池默认超时可配置

- **新增持久化超时配置**：五个执行池（Work / Thinking / Construct / Gate / Package）的默认超时统一持久化到 `runtime/state/pool_timeout_config.json`
- **桌面 UI 可直接调整**：Dashboard 为每个执行池新增 `Timeout` 按钮，可直接修改后续新任务使用的默认超时
- **运行态展示更直观**：Runtime 卡片显示当前池默认超时，便于观察不同池的治理参数
- **任务头优先级保留**：若任务头显式声明 `TIMEOUT`，仍优先覆盖池默认值
- **本地状态排除发布**：超时配置文件与 Dashboard 列顺序文件作为本地运行态数据默认忽略，不进入发布仓库

### v1.1 更新内容（相比 v1.0）

#### POST 全面落地

- **项目级注册模型**：统一使用 `project_key` 格式 `XXX-(Vision)-(Mode)`，支持跨池全生命周期追踪
- **依赖检查与阻塞**：支持 `after_delivered` 依赖规则，依赖未满足时项目进入 `waiting` 状态
- **Gate Rejectbox 退回**：被拒绝的项目退回上一池，cursor 回退，支持重审重投
- **原子工单识别**：Gate Outbox 中的 `project_key-NNN` 目录被识别为原子工单，逐个投递
- **人工治理动作**：支持 `hold / resume / replay / skip / modify-route` 等 CLI 工具

#### Thinking Pool 独立化

- 新增 `THINKING_BOOTSTRAP.txt`：专属生命周期与输出语义约束
- 规范项目目录创建：`workspace/XXX-(Vision)-(Mode)/` 由 Agent 按 bootstrap 创建
- 完善测试覆盖：单元测试、并发测试、安全测试、集成测试

#### Construct / Work / Gate Pool 优化

- 各池使用专属 `BOOTSTRAP.txt`（`WORK_BOOTSTRAP.txt`、`GATE_BOOTSTRAP.txt`）
- 移除通用 `BOOTSTRAP.txt` 的污染，避免池间规则混杂
- Gate Runtime 支持通过 / 拒绝双路径收口

#### 测试基线扩充

| 模块 | 测试文件 |
|------|----------|
| POST Runtime | `test_post_runtime.py` |
| POST Registry | `test_post_registry.py` |
| POST CLI 工具 | `test_post_cli_tools.py` |
| POST 命名规则 | `test_post_naming.py` |
| Thinking Runtime | `test_thinking_runtime.py` |
| Thinking Bootstrap | `test_thinking_bootstrap_constraints.py` |
| Gate Runtime | `test_gate_runtime.py` |
| Work Runtime | `test_work_runtime.py` |
| Construct Runtime | `test_construct_runtime.py` |

### 快速开始

安装依赖：

```bash
pip install -r requirements.txt
```

启动桌面 UI：

```bash
cd runtime
python -m app.desktop_ui.app
```

桌面 UI 会作为统一入口，负责连接和管理各 Runtime；发布版不再要求用户分别手动启动每个 Runtime。

### 测试

```bash
cd runtime
pytest tests/ -v
```

单测示例：

```bash
pytest tests/test_post_runtime.py -v
pytest tests/test_thinking_runtime.py -v
pytest tests/test_gate_runtime.py -v
```

---

## English

### Overview

> **Claude Code only, no plugins, no ads — pure Python multi-agent collaboration pipeline.**
> 
> Now supports: custom pool integration, configurable timeout, visual desktop UI.
> 
> **Any requirement can be turned into a pipeline.**

MultiAgentWorkspace1.0 is a pool-based multi-agent runtime framework for structured orchestration. It is designed to turn long, fragile agent workflows into a governable, observable, and recoverable execution pipeline.

In real-world long-chain tasks, common failure modes include context bloat, mixed responsibilities, weak observability, and high rework cost. This project addresses those issues with six-layered runtime architecture plus project-level POST-based cross-pool orchestration.

### Why this project

| Feature | Description |
|---------|-------------|
| **Zero dependencies to start** | Only Claude Code CLI + Python needed, no Docker, no K8s, no cloud |
| **One-click UI launch** | `python -m app.desktop_ui.app` starts the desktop control panel, all Runtimes auto-managed |
| **Pure Python, no ads, auditable** | Full transparency, clean code, easy to audit and extend |
| **Highly customizable** | Six-pool architecture extensible, supports custom Pool integration |
| **Offline capable** | Runs entirely locally, no data leaves your machine, great for sensitive scenarios |

### Quick start (3 steps)

```bash
# 1. Install dependencies (psutil, PySide6, and other common libraries)
pip install -r requirements.txt

# 2. Enter runtime directory
cd runtime

# 3. Launch desktop UI to manage all Pools
python -m app.desktop_ui.app
```

After the desktop UI starts, you can:
- View real-time status of all Runtimes
- Register new projects and auto-trigger the pipeline
- Configure default timeout per Pool
- Create custom Pools to integrate into the pipeline

### What this project is for

- Split responsibilities across dedicated pools (Thinking / Construct / Gate / Work)
- Drive lifecycle transitions through runtime signals (online / done / timeout)
- POST unified cross-pool delivery with project routing, dependency checks, reject-replay, and atomic ticket recognition
- Support parallel slot execution and timeout governance
- Keep auditable event trails and delivery records

### Key advantages

1. **Claude Code only, no plugins required**
   No IDE plugin dependency, no cloud orchestration platform required. You can build a multi-agent collaboration pipeline directly with Claude Code CLI.

2. **Pure Python, no ads, fully auditable**
   Core logic is implemented in Python with simple dependencies and transparent structure, making it easy to audit, extend, and customize.

3. **Easy to start, launch the UI and use it**
   The desktop UI acts as the unified entry point, so users do not need to manually understand or launch each Runtime separately.

4. **Supports custom pool integration**
   Create Pool is now supported, allowing you to define new Pools, slot prefixes, bootstrap rules, state machines, and action steps.

5. **Supports configurable timeout defaults**
   All five execution pools — Work, Thinking, Construct, Gate, and Package — support persistent default timeout configuration.

6. **Any requirement can become a pipeline**
   Code generation, review, architecture, testing, packaging, or your own custom business stage can all be turned into dedicated Pools under one orchestration system.

7. **Lower context burden, fewer attention traps**
   Pool boundaries keep each execution unit smaller and role-focused, reducing context overload and attention drift in long tasks.

8. **Signal-driven lifecycle with strong observability**
   Runtime state transitions are driven by explicit signals (`online / start_* / done / timeout`), making failure localization more direct.

9. **POST project-level orchestration with full governance**
   Unified management using `project_key` format `XXX-(Vision)-(Mode)`, covering registration, routing, dependencies, delivery, rejection, and manual actions (hold / resume / replay / skip).

10. **Gate atomic ticket splitting for flexible delivery**
    After Gate review passes, Runtime splits projects into atomic tickets (`project_key-NNN` format), which POST recognizes and delivers individually to Work Pool for fine-grained scheduling.

11. **Clear boundaries, safer evolution**
    Each runtime focuses on in-pool lifecycle management, while POST governs cross-pool transfer. Rejection / replay logic is explicit, reducing module coupling.

### Architecture overview

```text
Task Pool → Thinking Pool → Construct Pool → Gate Pool → Work Pool → Packaging Pool
                                      ↓              ↓
                              Rejectbox (replay)   POST System (delivery orchestration)
```

- **Task Pool**: Task entry (externally driven)
- **Thinking Pool**: Break down requirements into sub-task specifications
- **Construct Pool**: Architecture processing and ticket generation
- **Gate Pool**: Code quality and standards review, supports `accepted` / `denied`
- **Work Pool**: Execute code writing
- **Packaging Pool**: Packaging and delivery
- **POST System**: Cross-pool orchestration layer, handles project routing, dependencies, rejection replay, and atomic ticket recognition

### What's new in v1.1 (compared to v1.0)

#### POST fully implemented

- **Project-level registration model**: Unified `project_key` format `XXX-(Vision)-(Mode)`, supporting full lifecycle tracking across pools
- **Dependency checks and blocking**: Supports `after_delivered` dependency rules; projects enter `waiting` state when dependencies not satisfied
- **Gate Rejectbox replay**: Rejected projects return to previous pool with cursor rollback, supporting re-review and re-delivery
- **Atomic ticket recognition**: `project_key-NNN` directories in Gate Outbox recognized as atomic tickets, delivered individually
- **Manual governance actions**: Supports `hold / resume / replay / skip / modify-route` CLI tools

#### Thinking Pool independent

- New `THINKING_BOOTSTRAP.txt`: Dedicated lifecycle and output semantics constraints
- Standardized project directory creation: `workspace/XXX-(Vision)-(Mode)/` created by Agent per bootstrap
- Complete test coverage: unit tests, concurrency tests, security tests, integration tests

#### Construct / Work / Gate Pool improvements

- Each pool uses dedicated `BOOTSTRAP.txt` (`WORK_BOOTSTRAP.txt`, `GATE_BOOTSTRAP.txt`)
- Removed generic `BOOTSTRAP.txt` pollution, preventing cross-pool rule mixing
- Gate Runtime supports both pass and reject path closure

#### Expanded test baseline

| Module | Test files |
|--------|------------|
| POST Runtime | `test_post_runtime.py` |
| POST Registry | `test_post_registry.py` |
| POST CLI tools | `test_post_cli_tools.py` |
| POST naming | `test_post_naming.py` |
| Thinking Runtime | `test_thinking_runtime.py` |
| Thinking Bootstrap | `test_thinking_bootstrap_constraints.py` |
| Gate Runtime | `test_gate_runtime.py` |
| Work Runtime | `test_work_runtime.py` |
| Construct Runtime | `test_construct_runtime.py` |

### Quick start

Install dependencies:

```bash
pip install -r requirements.txt
```

Launch the desktop UI:

```bash
cd runtime
python -m app.desktop_ui.app
```

The desktop UI is the unified entry point and is responsible for connecting to and managing the runtimes. The release build no longer requires users to manually start each runtime one by one.

### GitHub Topics / Keywords

- `claude-code`
- `multi-agent`
- `agent-workflow`
- `agent-pipeline`
- `python`
- `desktop-ui`
- `runtime-orchestration`
- `workflow-automation`
- `local-first`
- `llm-orchestration`
- `ai-agents`
- `task-pipeline`

> Recommended GitHub topics: `claude-code`, `multi-agent`, `agent-pipeline`, `python`, `desktop-ui`, `llm-orchestration`

### Test

```bash
cd runtime
pytest tests/ -v
```

Single module examples:

```bash
pytest tests/test_post_runtime.py -v
pytest tests/test_thinking_runtime.py -v
pytest tests/test_gate_runtime.py -v
```

### Release notes

This is a clean publish export for v1.1. The following are intentionally excluded:

- Development manuals
- Handover/handoff documents
- Planning documents (plans/specs)
- Runtime logs and events
- Queue / Outbox / Rejectbox runtime data
- Cache and dirty artifacts
