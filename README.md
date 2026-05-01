# MultiAgentWorkspace1.0

[中文介绍](#中文) | [English](#english)

---

## 中文

### 项目简介

MultiAgentWorkspace1.0 是一个面向多 Agent 协作的池化运行时框架。它的目标不是简单“多开几个 Agent”，而是把复杂任务拆解为可治理、可追踪、可恢复的流水线执行系统。

在长链路任务里，常见问题是：上下文持续膨胀、角色职责混杂、状态不可观测、返工成本高。MultiAgentWorkspace1.0 通过六池分层架构 + 项目级 POST 跨池编排系统来降低这些问题，让协作流程更稳定。

### 这个项目能做什么

- 将任务按职责拆分到不同 Pool（Thinking / Construct / Gate / Work）
- 用 Runtime 驱动生命周期，通过信号（online / done / timeout 等）推进状态机
- POST 统一跨池投递，支持项目级路由、依赖检查、退回重排、原子工单识别
- 支持多槽位并行执行与超时治理
- 提供可审计的事件轨迹与投递记录

### 核心优势

1. **降低上下文负担，减少注意力陷阱**
   通过多池分层和清晰职责边界，把任务切成更小的上下文单元，减少“一个 Agent 同时背负规划、构造、审查、执行”导致的注意力漂移。

2. **信号驱动生命周期，状态可观测**
   Runtime 通过 `online / start_* / done / timeout` 等信号推进状态机，问题定位更直接，不再依赖 `status/progress/outbox` 的间接猜测。

3. **POST 项目级编排，完整治理**
   以 `project_key`（格式 `XXX-(Vision)-(Mode)`）为唯一标识，统一管理项目注册、路由、依赖、投递、退回、人工干预（hold / resume / replay / skip）。

4. **Gate 原子工单拆分，灵活投递**
   Gate 审查通过后，Runtime 将项目拆分为原子工单（`project_key-NNN` 格式），POST 识别后逐个投递到 Work Pool，实现细粒度调度。

5. **职责边界明确，扩展更稳**
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

### Release 说明

这是 v1.1 的 clean publish export。以下内容被有意排除：

- 开发手册
- 交接文档
- 规划文档（plans/specs）
- Runtime 日志与事件
- Queue / Outbox / Rejectbox 运行态数据
- 缓存与脏产物

---

## English

### Overview

MultiAgentWorkspace1.0 is a pool-based multi-agent runtime framework for structured orchestration. It is designed to turn long, fragile agent workflows into a governable, observable, and recoverable execution pipeline.

In real-world long-chain tasks, common failure modes include context bloat, mixed responsibilities, weak observability, and high rework cost. This project addresses those issues with six-layered runtime architecture plus project-level POST-based cross-pool orchestration.

### What this project is for

- Split responsibilities across dedicated pools (Thinking / Construct / Gate / Work)
- Drive lifecycle transitions through runtime signals (online / done / timeout)
- POST unified cross-pool delivery with project routing, dependency checks, reject-replay, and atomic ticket recognition
- Support parallel slot execution and timeout governance
- Keep auditable event trails and delivery records

### Key advantages

1. **Lower context burden, fewer attention traps**
   Pool boundaries keep each execution unit smaller and role-focused, reducing context overload and attention drift in long tasks.

2. **Signal-driven lifecycle with strong observability**
   Runtime state transitions are driven by explicit signals (`online / start_* / done / timeout`), making failure localization more direct.

3. **POST project-level orchestration with full governance**
   Unified management using `project_key` format `XXX-(Vision)-(Mode)`, covering registration, routing, dependencies, delivery, rejection, and manual actions (hold / resume / replay / skip).

4. **Gate atomic ticket splitting for flexible delivery**
   After Gate review passes, Runtime splits projects into atomic tickets (`project_key-NNN` format), which POST recognizes and delivers individually to Work Pool for fine-grained scheduling.

5. **Clear boundaries, safer evolution**
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
