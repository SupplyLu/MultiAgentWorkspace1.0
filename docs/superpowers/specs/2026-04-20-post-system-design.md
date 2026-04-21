# POST System 设计文档

> 设计日期：2026-04-20
> 状态：已批准
> 版本：v1.0

---

## 1. 概述

### 1.1 背景

MultiAgentWorkspace 1.0 采用五池架构（Task / Thinking / Gate / Work / Packaging），各池由独立 Runtime 推进池内状态。当前缺少一个统一的跨池编排与投递系统，导致：

- 跨池流转缺乏全局追踪
- 无法保证批次完整性（散装任务可能部分完成就被投递）
- 人工协调困难（合并、顺序依赖、暂停、重投等操作无统一入口）
- Runtime 局部瘫痪时无法自动恢复投递

### 1.2 目标

构建 **POST 系统**（Pool Orchestration & Scheduling Transfer），作为跨池编排中枢，实现：

1. **所有跨池流转必须先经过 POST 注册**
2. **完整性优先**：等待批次所有分支完成后统一投递，而非"看到一个发一个"
3. **人工可治理**：支持合并、顺序依赖、暂停、恢复、删除、重投等操作
4. **Runtime 独立性**：各池 Agent 无需理解全局分支关系，只专注局部任务
5. **抗故障**：采用定期扫描机制，不依赖 Runtime 主动通知

### 1.3 核心原则

- **POST 只负责传递，不负责业务决策**
- **注册表是唯一全局账本**
- **文件系统现状优先于注册表旧状态**
- **CLI skill 幂等、原子、可组合**

---

## 2. 架构设计

### 2.1 三层架构

```
┌─────────────────────────────────────────────────────┐
│              POST Manager (CLI Skill)               │
│  注册、增删改、依赖管理、人工治理                      │
└─────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────┐
│              POST Registry (注册表)                  │
│  Batch / Branch / Dependency / Transfer / Actions   │
└─────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────┐
│              POST Runtime (守护进程)                 │
│  每60秒扫描、完整性检查、依赖检查、执行投递            │
└─────────────────────────────────────────────────────┘
```

### 2.2 职责边界

| 组件 | 职责 | 不负责 |
|------|------|--------|
| POST Manager | 注册批次、修改注册表、人工治理 | 不执行投递、不监听信号 |
| POST Registry | 存储批次/分支/依赖/投递记录 | 不做业务逻辑判断 |
| POST Runtime | 扫描注册表、检查完整性、执行投递 | 不修改注册表（只更新状态） |

---

## 3. 数据模型

### 3.1 核心实体

#### Batch（批次）
表示一个完整的跨池工作单元。

```json
{
  "batch_id": "feat_001",
  "name": "用户登录功能",
  "from_pool": "task",
  "to_pool": "construct",
  "status": "registered | running | waiting | ready | delivered | blocked",
  "branches": ["feat_001_b1", "feat_001_b2"],
  "created_at": "2026-04-20T10:00:00Z",
  "updated_at": "2026-04-20T10:05:00Z"
}
```

#### Branch（子任务支线）
批次下的单条执行路径。

```json
{
  "branch_id": "feat_001_b1",
  "batch_id": "feat_001",
  "feature_id": "login_ui",
  "from_pool": "task",
  "to_pool": "thinking",
  "task_body": "FROM: task\nTO: thinker\n...",
  "status": "pending | in_progress | done | failed | skipped",
  "outbox_path": "pools/thinking/Outbox/feat_001_b1/",
  "outbox_checked_at": "2026-04-20T10:05:00Z",
  "created_at": "2026-04-20T10:00:00Z",
  "completed_at": "2026-04-20T10:05:00Z"
}
```

#### Dependency（依赖关系）
定义批次或支线之间的先后顺序。

```json
{
  "dep_id": "dep_001",
  "source_batch_id": "feat_001",
  "source_branch_id": null,
  "target_batch_id": "feat_002",
  "target_branch_id": null,
  "rule": "after_done | after_delivered",
  "satisfied": false,
  "satisfied_at": null
}
```

#### Transfer（投递记录）
一次真实的跨池投递事件。

```json
{
  "transfer_id": "xfer_feat_001_b1_20260420",
  "batch_id": "feat_001",
  "branch_id": "feat_001_b1",
  "from_pool": "thinking",
  "to_pool": "construct",
  "to_slot": "construct_01",
  "delivery_address": "pools/construct/Queue/task_feat_001_b1.txt",
  "status": "pending | delivered | failed",
  "created_at": "2026-04-20T10:05:00Z",
  "delivered_at": "2026-04-20T10:05:10Z",
  "error": ""
}
```

#### ManagerAction（人工干预记录）
记录 POST Manager 的所有手动操作。

```json
{
  "action_id": "act_001",
  "batch_id": "feat_001",
  "branch_id": "feat_001_b1",
  "action_type": "merge | hold | resume | modify | delete | replay",
  "detail": {"reason": "手动合并两个分支"},
  "operator": "manual",
  "created_at": "2026-04-20T10:10:00Z"
}
```

### 3.2 注册表文件结构

```
transfers/
├── batches/
│   ├── {batch_id}.json           # Batch 主体信息
│   └── {batch_id}_branches.json  # 所有 Branch 信息
├── dependencies/
│   └── {dep_id}.json             # 依赖关系
├── transfers/
│   └── {transfer_id}.json        # 投递记录
├── manager_actions/
│   └── {action_id}.json          # 人工操作记录
└── post_index.json               # 全局索引
```

### 3.3 状态机

#### Branch 状态流转

```
pending
  → in_progress  [Transfer 已投递到目标池]
  → skipped      [Manager 删除]

in_progress
  → done         [Outbox 产物存在且完整]
  → failed       [超时或 Runtime 报错]
  → skipped      [Manager 跳过]

done
  → (终态)
```

#### Batch 状态流转

```
registered
  → running      [至少一个 Branch 进入 in_progress]
  → blocked      [Manager 暂停]

running
  → waiting      [所有 Branch done，但依赖未满足]
  → ready        [所有 Branch done，且依赖满足]

waiting
  → ready        [依赖条件满足]

ready
  → delivered    [POST 执行了跨池投递]
  → blocked      [Manager 暂停]

delivered
  → (终态)
```

---

## 4. POST Manager（CLI Skill）

### 4.1 定位

POST Manager 是一个**纯工具型 CLI skill**，不运行守护进程，作为 Skill 被各 Agent 或 Runtime 调用。

### 4.2 文件结构

```
runtime/tools/
├── post_register.py          # 注册批次
├── post_dep.py               # 添加依赖
├── post_merge.py             # 合并支线
├── post_hold.py              # 暂停/恢复
├── post_modify.py            # 修改支线
├── post_delete.py            # 删除支线
├── post_replay.py            # 重投
├── post_status.py            # 查询状态
└── post_manifest.py          # 生成 manifest
```

### 4.3 命令清单

| 命令 | 用途 | 示例 |
|------|------|------|
| `post_register` | 注册批次和支线 | `python post_register.py --batch feat_001 --branches b1,b2 --from task --to thinking` |
| `post_dep` | 添加依赖 | `python post_dep.py --after feat_001 --before feat_002` |
| `post_merge` | 合并支线 | `python post_merge.py --batch feat_001 --branches b1,b2` |
| `post_hold` | 暂停/恢复 | `python post_hold.py --batch feat_001 --action hold` |
| `post_modify` | 修改支线 | `python post_modify.py --branch feat_001_b1 --to_pool construct` |
| `post_delete` | 删除支线 | `python post_delete.py --branch feat_001_b1` |
| `post_replay` | 重投 | `python post_replay.py --transfer xfer_xxx` |
| `post_status` | 查询状态 | `python post_status.py --batch feat_001` |
| `post_manifest` | 生成 manifest | `python post_manifest.py --batch feat_001` |

### 4.4 核心原则

1. **不污染调用者上下文**：所有参数通过命令行传入，输出只返回结构化结果
2. **幂等性**：重复注册同一批次返回已有信息，不报错
3. **原子性**：每个命令操作单一注册表文件，使用 JSONStore 保证读写原子
4. **可组合**：Runtime 可以在任意时机调用任意命令

---

## 5. POST Runtime（守护进程）

### 5.1 核心职责

周期扫描 + 完整性判断 + 执行投递，不做业务决策。

### 5.2 扫描逻辑

```python
def scan():
    for batch in get_all_batches():
        # 跳过暂停的批次
        if batch.status == "blocked":
            continue

        # 检查所有分支是否完成
        branches = get_branches(batch.batch_id)
        all_done = all(b.status == "done" for b in branches)

        if not all_done:
            continue

        # 检查依赖是否满足
        deps = get_dependencies(batch.batch_id)
        deps_ok = all(d.satisfied for d in deps)

        if not deps_ok:
            update_batch_status(batch, "waiting")
            continue

        # 检查产物是否存在
        if not all_outbox_exist(branches):
            continue

        # 一切就绪，执行投递
        for branch in branches:
            deliver(branch)

        update_batch_status(batch, "delivered")
```

### 5.3 触发条件

| 条件 | 说明 |
|------|------|
| 所有分支 `done` | Runtime 已确认完成 |
| 依赖 `satisfied` | 前置批次已送达 |
| `status != blocked` | Manager 未暂停 |
| Outbox 产物存在 | 文件完整性验证 |

### 5.4 产物检查规则

第一阶段最简版：
- Outbox 目录下存在 `*.txt` 文件即视为有效产物
- 未来可扩展为检查 manifest 中列出的具体文件列表

### 5.5 扫描周期

- 默认：60 秒
- 可配置：通过 `runtime/app/main_post.py` 启动参数调整

---

## 6. 完整数据流

```
[Task] → 发起任务描述
    ↓
[POST Manager] → post_register 注册批次
    ↓
[POST Registry] → 存储 batch + branches
    ↓
[POST Runtime] → 每60秒扫描
    ↓ (分支1: Task → Thinking)
[Transfer] → 投递到 pools/thinking/Queue/
    ↓
[Thinking Runtime] → 处理任务，产出 Outbox
    ↓
[POST Runtime] → 检测 Outbox，更新分支状态
    ↓ (所有分支 done + 依赖满足)
[POST Runtime] → 投递到 pools/construct/Queue/
    ↓
[Construct Runtime] → 继续处理...
    ↓
[POST Manager] → 人工编排后续流程（如需要）
```

---

## 7. 第一阶段落地范围

### 7.1 目标

先落地一个**最小可用但方向正确**的 POST 系统，只覆盖：

1. **Task → Thinking 必须先经过 POST 注册**
2. **Thinking Outbox → Construct Queue 由 POST Runtime 扫描后统一投递**
3. **POST Manager 用原生 CLI skill 做注册表增删改**
4. **POST Runtime 每 60 秒扫描一次**
5. **完整性优先，不做"看到一个文件就发一个"**

### 7.2 包含的能力

- Batch / Branch 注册
- Task → Thinking 首跳规范化
- Thinking → Construct 第二跳自动化
- 手工治理能力（register / status / hold / resume / modify / delete / replay / add dependency）
- 最小审计链（batch / branch / transfer / manager action 记录）

### 7.3 不做的内容

为了避免过度设计，第一阶段**不做**：

- UI 面板
- 复杂工作流语言
- 多级嵌套 branch 图谱
- 实时事件总线
- 跨机器/网络 POST
- 自动冲突解决
- Construct 之后全链自动推进
- 过于复杂的产物校验规则

---

## 8. 风险与约束

### 8.1 风险 1：注册表和真实目录状态不一致

**例如**：
- branch 显示 done，但 Outbox 文件丢了
- transfer 显示 delivered，但目标 Queue 被清空了

**处理方式**：
POST Runtime 每次扫描都以**文件系统现状优先**，注册表只是事实账本，不盲目信任旧状态。

### 8.2 风险 2：某些 branch 永远不完成

会导致 batch 一直卡住。

**处理方式**：
由 POST Manager 人工执行：
- `hold`
- `delete branch`
- `modify`
- `force merge`
- `replay`

也就是说：**POST Runtime 不替你做主，POST Manager 才负责例外治理。**

### 8.3 风险 3：Runtime 局部瘫痪导致状态滞后

**处理方式**：
POST Runtime 的扫描依据：
- 注册表
- Queue
- Outbox
- 真实文件是否存在

而不是依赖某个 Runtime 主动通知。

### 8.4 风险 4：CLI skill 被不同 Agent 用出不同格式

**处理方式**：
POST Manager CLI 必须收紧为：
- 参数固定
- 输出固定
- 注册文件格式固定
- 重复调用幂等

这样 Runtime 和人都能用，不会越用越乱。

---

## 9. 测试策略

### 9.1 单元测试

- POST Manager CLI 各命令的幂等性、原子性测试
- POST Registry 读写一致性测试
- POST Runtime 扫描逻辑测试

### 9.2 集成测试

- Task → Thinking → Construct 完整链路测试
- 多分支批次完整性测试
- 依赖关系满足后自动投递测试
- Manager 暂停/恢复/删除/重投测试

### 9.3 真实闭环验证

- 手动投放一个包含 3 个分支的批次
- 观察 POST Runtime 是否等待所有分支完成后统一投递
- 验证 Outbox 产物是否完整复制到 Construct Queue

---

## 10. 后续扩展方向

第一阶段稳定后，可考虑：

- 支持 Construct → Gate → Work → Packaging 全链自动推进
- 支持更复杂的依赖规则（any_of / all_of / conditional）
- 支持产物 manifest 校验（而非简单的 *.txt 存在性检查）
- 支持 POST 状态查询 Web UI
- 支持跨机器 POST（通过网络 API）
- 支持自动冲突检测与建议

---

## 11. 总结

POST 系统将 MultiAgentWorkspace 1.0 从"各池独立推进"升级为"全局编排与投递"，核心价值在于：

1. **完整性优先**：不再"看到一个发一个"，而是等待批次完整后统一投递
2. **全局追踪**：所有跨池流转都有注册、有记录、可审计
3. **人工可治理**：支持合并、顺序依赖、暂停、恢复、删除、重投等操作
4. **Runtime 独立性**：各池 Agent 无需理解全局分支关系，只专注局部任务
5. **抗故障**：采用定期扫描机制，不依赖 Runtime 主动通知

第一阶段先落地 Task → Thinking → Construct 两跳，验证架构可行性，后续逐步扩展到全链。
