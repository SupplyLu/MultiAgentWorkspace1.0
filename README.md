# MultiAgentWorkspace1.0

[中文介绍](#中文) | [English](#english)

---

## 中文

### 项目简介

MultiAgentWorkspace1.0 是一个面向多 Agent 协作的池化运行时框架。它的目标不是简单“多开几个 Agent”，而是把复杂任务拆解为可治理、可追踪、可恢复的流水线执行系统。

在长链路任务里，常见问题是：上下文持续膨胀、角色职责混杂、状态不可观测、返工成本高。MultiAgentWorkspace1.0 通过分层 Runtime + 跨池编排账本（POST）来降低这些问题，让协作流程更稳定。

### 这个项目能做什么

- 将任务按职责拆分到不同 Pool（如 Thinking / Construct / Gate / Work）
- 用 Runtime 驱动生命周期，而不是依赖零散文本推断状态
- 在跨池流转前做批次完整性检查，避免半成品提前投递
- 支持多槽位并行执行与超时治理
- 提供可审计的事件轨迹与跨池投递记录

### 核心优势

1. **降低上下文负担，减少注意力陷阱**
   通过多池分层和清晰职责边界，把任务切成更小的上下文单元，减少“一个 Agent 同时背负规划、构造、审查、执行”导致的注意力漂移。

2. **信号驱动生命周期，状态可观测**
   Runtime 通过 `online / start_* / done / timeout` 等信号推进状态机，问题定位更直接，不再依赖 `status/progress/outbox` 的间接猜测。

3. **POST 统一跨池编排，完整性优先**
   以注册表为跨池账本，遵循“批次完整后再投递”，避免局部完成就提前流转引发下游返工。

4. **职责边界明确，扩展更稳**
   各 Runtime 专注池内生命周期，跨池交付由 POST 统一治理，降低模块耦合。

### 架构总览

当前架构围绕以下运行层组织：

- Task Pool
- Thinking Pool
- Construct Pool
- Gate Pool
- Work Pool
- POST System（跨池编排与投递层）

### v1.0 已实现能力

- Gate Runtime 已实现
  - Entry: `runtime/app/main_gate.py`
  - Runtime: `runtime/app/runtimes/gate_runtime.py`
  - Tests: `runtime/tests/test_gate_runtime.py`
  - Gate lifecycle tools:
    - `runtime/tools/StartReview.bat`
    - `runtime/tools/Accepted.bat`
    - `runtime/tools/Denied.bat`
- Work / Thinking / Construct / POST 关键 Runtime 与测试基线已在 1.0 工作线上落地

### 快速开始

安装依赖：

```bash
pip install -r requirements.txt
```

启动 Runtime（示例）：

```bash
cd runtime
python -m app.main
python -m app.main_thinking
python -m app.main_construct
python -m app.main_gate
python -m app.main_post
```

### 测试

```bash
cd runtime
pytest tests/test_gate_runtime.py -v
```

### Release 说明

这是 1.0 的 clean publish export。以下内容被有意排除：

- 开发手册
- 交接文档
- 规划文档
- Runtime 日志
- 缓存与脏产物

---

## English

### Overview

MultiAgentWorkspace1.0 is a pool-based multi-agent runtime framework for structured orchestration. It is designed to turn long, fragile agent workflows into a governable, observable, and recoverable execution pipeline.

In real-world long-chain tasks, common failure modes include context bloat, mixed responsibilities, weak observability, and high rework cost. This project addresses those issues with layered runtimes plus POST-based cross-pool orchestration.

### What this project is for

- Split responsibilities across dedicated pools (Thinking / Construct / Gate / Work)
- Drive lifecycle transitions through runtime signals instead of text-file guessing
- Enforce batch completeness before cross-pool delivery
- Support parallel slot execution and timeout governance
- Keep auditable event trails and transfer records

### Key advantages

1. **Lower context burden, fewer attention traps**
   Pool boundaries keep each execution unit smaller and role-focused, reducing context overload and attention drift in long tasks.

2. **Signal-driven lifecycle with strong observability**
   Runtime state transitions are driven by explicit signals (`online / start_* / done / timeout`), making failure localization more direct.

3. **POST as a unified cross-pool ledger**
   Cross-pool delivery is registry-governed and completeness-first, reducing premature downstream handoff and rework.

4. **Clear boundaries, safer evolution**
   Each runtime focuses on in-pool lifecycle management, while POST governs cross-pool transfer as a separate responsibility.

### Runtime layers

- Task Pool
- Thinking Pool
- Construct Pool
- Gate Pool
- Work Pool
- POST System

### Implemented in v1.0

- Gate Runtime is implemented in this release:
  - Entry: `runtime/app/main_gate.py`
  - Runtime: `runtime/app/runtimes/gate_runtime.py`
  - Tests: `runtime/tests/test_gate_runtime.py`
  - Gate lifecycle tools:
    - `runtime/tools/StartReview.bat`
    - `runtime/tools/Accepted.bat`
    - `runtime/tools/Denied.bat`
- Core runtime baseline for Work / Thinking / Construct / POST is included in the 1.0 line

### Quick start

Install dependencies:

```bash
pip install -r requirements.txt
```

Run runtimes (example):

```bash
cd runtime
python -m app.main
python -m app.main_thinking
python -m app.main_construct
python -m app.main_gate
python -m app.main_post
```

### Test

```bash
cd runtime
pytest tests/test_gate_runtime.py -v
```

### Release notes

This is a clean publish export for 1.0.
The following are intentionally excluded:

- Development manuals
- Handover/handoff documents
- Planning documents
- Runtime logs
- Cache/dirty artifacts
