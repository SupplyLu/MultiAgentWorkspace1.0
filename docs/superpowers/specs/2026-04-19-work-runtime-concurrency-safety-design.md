# Work Runtime 并发安全与终态收敛架构设计

> **设计日期**: 2026-04-19
> **设计目标**: 在现有 Work Runtime 闭环基础上，增加线程安全保护与终态收敛统一出口，消除风险审查报告中的 6 个并发/幂等/时序问题
> **设计原则**: 最小侵入式加固，不推翻现有主链路，为后续复制到其他四池提供稳定模板

---

## 1. 背景与问题

### 1.1 当前状态
- Work Runtime 功能闭环已验证成功（64/64 tests passed，真实 Worker 闭环两次通过）
- Signal-only 单一状态真相源已落地
- done/timeout 后槽位目录即时清理已实现

### 1.2 风险审查发现的 6 个问题（已按开发负责人校准）

| ID | 级别 | 文件 | 问题 | 影响 |
|----|------|------|------|------|
| R1 | 🔴 P0 | `work_runtime.py` | `WorkerSlot` 数据竞争（无锁） | 主线程 dispatch 与 HTTP 线程 handle_signal 并发修改 slot 状态，可能导致任务黑洞、误杀新进程 |
| R2 | 🔴 P0 | `launch_manager.py` | Job Handle 双重释放（无幂等） | timeout 与 done 并发到达时，同一 job_handle 被 CloseHandle 两次，可能造成未定义行为 / 资源误释放，在 Windows handle 复用场景下后果可能严重 |
| R3 | 🟡 P2 | `work_runtime.py` | Outbox 时序倒置（先收集后杀进程） | Worker 进程仍在写文件时就开始收集产物，可能导致文件截断 |
| R4 | 🟡 P2 | `work_runtime.py` | `check_timeouts` 不写 LifecycleEvent | 超时强制清理跳过 EventStore，破坏状态机追踪闭环 |
| R5 | 🟡 P2 | `pool_state_templates.py` | 缺少 timeout 终态 | 状态机模板未定义 timeout 转换，无法追踪超时路径 |
| R6 | 🟠 扩展期风险 | `json_store.py` | 文件并发写 Lost Update（无锁） | 设计上存在隐患。当前 HTTPServer 为单线程，实际并发路径仅来自 main thread × signal thread 对 runtime slot 的竞争，JSONStore 层面暂无直接并发写入。但未来如改用 ThreadingHTTPServer，此问题会暴露 |

**风险定级说明（开发负责人校准）：**
- R1、R2 为当前生产环境实际风险，立即处理
- R3-R5 为当前功能缺陷，影响可诊断性和健壮性，立即处理
- R6 为架构扩展期风险，当前 blast radius 低，但应同步加固（改动极小）

### 1.3 设计目标
1. **消除数据竞争**：用 `threading.RLock` 保护所有 slot 状态读写
2. **阻断旧 signal 误伤新任务**：终态处理前强制校验 `task_id` 与 slot 当前任务一致
3. **统一终态收敛**：done/failed/blocked/timeout 走同一个内部方法
4. **幂等清理**：cleanup_launch 可重入，防止双重释放
5. **线程安全存储**：JSONStore 加锁保护 read-modify-write（当前为低优先级但低成本加固）
6. **正确时序**：先杀进程，再收集产物
7. **完整追踪**：timeout 写入 EventStore 并纳入状态机

---

## 2. 架构设计

### 2.1 核心原则

#### 原则 1：Slot 状态单一真相源
- `WorkerSlot` 的所有字段（`busy`, `assigned_task_id`, `launch_result`, `assigned_at_epoch`, `timeout_seconds`）只能在 `WorkRuntime._lock` 保护下读写
- 任何外部线程（HTTP signal thread）不得直接修改 slot 字段

#### 原则 2：终态收敛统一出口
- 所有导致 slot 释放的路径（done/failed/blocked/timeout）必须经过统一内部方法 `_finalize_slot_terminal(...)`
- 进入终态收敛前必须先做 task-slot 一致性校验：
  - `slot.busy is True`
  - `slot.assigned_task_id == signal_result["task_id"]`
- 若校验失败，则判定为迟到 / 过期 / 错配 signal：
  - 不释放当前 slot
  - 不 cleanup 当前 `launch_result`
  - 返回 ignored 结果，供日志或测试诊断
- 该方法内部顺序固定：
  1. 校验 task-slot 一致性
  2. 写 terminal event（timeout 必写）
  3. cleanup_launch（杀进程）
  4. collect_artifacts（done 时）
  5. clean_slot_dir
  6. reset slot fields

#### 原则 3：资源清理幂等性
- `cleanup_launch()` 必须可重入：第一次执行清理，第二次 no-op
- `job_handle` 取走后立即置 `None`，防止重复释放

#### 原则 4：事件存储线程安全
- `JSONStore` 的 read/write/update 必须在同一把锁内执行
- 保证本进程内不丢事件

### 2.2 架构调整

#### 调整 1：WorkRuntime 增加全局锁

```python
class WorkRuntime:
    def __init__(self, root_dir: Path | str, signal_port: int = 18765):
        # ... existing fields ...
        self._lock = threading.RLock()  # 新增全局锁
```

#### 调整 2：所有 slot 操作加锁

```python
def dispatch_next(self, dry_run: bool = True) -> dict[str, Any]:
    with self._lock:  # 包裹整个派发逻辑
        slot = self.get_next_idle_slot()
        # ... 所有 slot 状态修改都在锁内 ...
        slot.busy = True
        slot.assigned_task_id = task_id
        slot.launch_result = launch_result
        # ...

def handle_signal(self, signal_result: dict[str, Any]) -> None:
    with self._lock:  # 包裹整个信号处理逻辑
        agent_id = signal_result.get("agent_id", "")
        task_id = signal_result.get("task_id", "")
        signal = signal_result.get("signal", "")

        slot = self._slots.get(agent_id)
        if slot is None:
            return

        # 必须校验 task_id 一致性，防止旧 signal 误伤新任务
        if not slot.busy or slot.assigned_task_id != task_id:
            return  # stale / mismatched signal, ignore

        # 终态处理
        terminal_signals = {"done", "failed", "blocked"}
        if signal in terminal_signals:
            self._finalize_slot_terminal(
                slot,
                signal=signal,
                task_id=task_id,
                collect_artifacts=(signal == "done"),
            )

def check_timeouts(self) -> list[dict[str, Any]]:
    with self._lock:  # 包裹整个超时检查逻辑
        # ... 超时检测与终态处理 ...
```

#### 调整 3：统一终态收敛方法

```python
def _finalize_slot_terminal(
    self,
    slot: WorkerSlot,
    *,
    signal: str,
    task_id: str,
    is_timeout: bool = False,
    collect_artifacts: bool = False,
) -> dict[str, Any]:
    """
    统一终态收敛方法，处理 done/failed/blocked/timeout。

    必须在 self._lock 内调用，且 caller 已完成 task_id 一致性校验。

    执行顺序：
    1. 写 terminal event（timeout 必写）
    2. cleanup_launch（杀进程）
    3. collect_artifacts（done 时，进程已死，安全收集）
    4. clean_slot_dir
    5. reset slot fields
    """
    result = {"finalized": True, "slot_id": slot.slot_id, "task_id": task_id, "signal": signal}

    # Step 1: 写 terminal event（timeout 必写，done/failed/blocked 由 signal server 已写）
    if is_timeout:
        from app.services.event_store import LifecycleEvent
        from datetime import datetime
        # 读取当前状态作为 from_state
        current_state = self._signal_server.event_store.get_current_state(
            slot.slot_id, task_id
        ) or "state_2"
        self._signal_server.event_store.append(LifecycleEvent(
            timestamp=datetime.now().isoformat() + "Z",
            agent_id=slot.slot_id,
            task_id=task_id,
            signal="timeout",
            pool="work",
            from_state=current_state,
            to_state="state_timeout",
            is_terminal=True,
        ))

    # Step 2: cleanup_launch（先杀进程）
    if slot.launch_result is not None:
        cleanup_result = self._launch_manager.cleanup_launch(slot.launch_result)
        result["cleanup"] = cleanup_result

    # Step 3: collect_artifacts（done 时，进程已死，安全收集）
    if collect_artifacts:
        artifact_result = self.collect_artifacts_to_outbox(slot.slot_id, task_id)
        result["artifacts"] = artifact_result

    # Step 4: clean_slot_dir
    self._clean_slot_dir(slot)

    # Step 5: reset slot fields
    slot.busy = False
    slot.assigned_task_id = ""
    slot.launch_result = None
    slot.assigned_at_epoch = 0.0
    slot.timeout_seconds = 300

    return result
```

#### 调整 4：LaunchManager 幂等清理

```python
# runtime/app/shared/launch_manager.py
def cleanup_launch(self, launch_result: dict[str, Any]) -> dict[str, Any]:
    job_handle = launch_result.get("job_handle")
    if job_handle is None:
        return {"cleaned": False, "reason": "missing_or_already_cleaned"}

    # 关键：取走后立即置空，防止重入
    launch_result["job_handle"] = None

    return {
        "cleaned": terminate_job(job_handle),
        "job_handle": job_handle,
    }
```

#### 调整 5：JSONStore 线程安全

```python
# runtime/app/shared/json_store.py
import threading

class JSONStore:
    def __init__(self, file_path: Path | str, default_factory: Callable[[], Any]):
        self._file_path = Path(file_path)
        self._default_factory = default_factory
        self._lock = threading.RLock()  # 新增文件锁

    def read(self) -> Any:
        with self._lock:  # 读操作也需要锁
            self.ensure_initialized()
            with open(self._file_path, encoding="utf-8") as f:
                return json.load(f)

    def write(self, data: Any) -> None:
        with self._lock:  # 写操作加锁
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def update(self, updater: Callable[[Any], Any]) -> Any:
        with self._lock:  # Read-Modify-Write 原子化
            current = self.read()
            updated = updater(current)
            self.write(updated)
            return updated
```

#### 调整 6：状态机增加 timeout 终态

```python
# runtime/app/services/pool_state_templates.py
work_template = PoolStateTemplate(
    pool_id="work",
    initial_state="state_0",
    terminal_states={"state_3", "state_timeout"},  # 新增 timeout 终态
    transitions=[
        StateTransition("state_0", "state_1", ["online"], "idle -> online"),
        StateTransition("state_1", "state_2", ["start_writing"], "online -> writing"),
        StateTransition("state_2", "state_3", ["done"], "writing -> done"),
        StateTransition("state_1", "state_timeout", ["timeout"], "online -> timeout"),  # 新增
        StateTransition("state_2", "state_timeout", ["timeout"], "writing -> timeout"),  # 新增
        StateTransition("state_1", "state_0", ["blocked"], "online -> blocked, reset"),
        StateTransition("state_2", "state_0", ["blocked"], "writing -> blocked, reset"),
        StateTransition("state_0", "state_0", ["failed"], "any -> failed"),
        StateTransition("state_1", "state_0", ["failed"], "any -> failed"),
        StateTransition("state_2", "state_0", ["failed"], "any -> failed"),
    ],
)
```

---

## 3. 关键设计决策

### 决策 1：为什么用 RLock 而不是 Lock？
- `RLock` 允许同一线程重入，避免死锁
- 例如：`dispatch_next()` 内部可能调用其他需要锁的方法

### 决策 2：为什么不用事件队列/消息队列？
- 当前 Work Runtime 已验证可用，不应大翻修
- 事件队列会导致 main loop、server callback、测试模型一起重写
- RLock 方案改动最小，风险最低

### 决策 3：为什么 timeout 要写 LifecycleEvent？
- 保持状态机追踪闭环完整
- 后续诊断任务失败时，可以区分"done 后正常退出"和"timeout 强制杀死"

### 决策 4：为什么 cleanup 必须在 collect_artifacts 之前？
- Worker 进程可能仍在写文件
- 先杀进程，确保文件系统状态静态后再收集
- 避免文件截断或锁冲突

### 决策 5：为什么必须增加 task-slot 一致性校验？
- `RLock` 只能保证 slot 状态修改串行化，不能证明到达的 signal 仍然属于 slot 当前任务
- 同一个 `agent_id` / `slot_id` 会被连续复用给不同 `task_id`
- 因此真正的风险不是只有“并发写”，还包括“旧 signal 迟到后误伤新任务”
- 所以 `handle_signal()` 进入终态收敛前，必须校验：
  ```python
  if not slot.busy or slot.assigned_task_id != signal_result.get("task_id"):
      return  # stale / mismatched signal, must not release current slot
  ```
- 这是本次架构加固的必要条件，不再作为未来增强点

---

## 4. 影响范围

### 4.1 核心代码修改
- `runtime/app/runtimes/work_runtime.py`
  - 增加 `self._lock`
  - `dispatch_next()` / `handle_signal()` / `check_timeouts()` 加锁
  - 新增 `_finalize_slot_terminal()`
  - `handle_signal()` 增加 task_id 一致性校验，调用 `_finalize_slot_terminal()`
  - `check_timeouts()` 调用 `_finalize_slot_terminal()`
- `runtime/app/shared/launch_manager.py`
  - `cleanup_launch()` 幂等改造
- `runtime/app/shared/json_store.py`
  - 增加 `self._lock`
  - `read()` / `write()` / `update()` 加锁
- `runtime/app/services/pool_state_templates.py`
  - work 模板增加 `state_timeout` 终态
  - 增加 `state_1/state_2 --timeout--> state_timeout` 转换

### 4.2 测试修改与新增
- `runtime/tests/test_work_runtime.py`
  - 回归测试全部通过
- `runtime/tests/test_work_runtime_lifecycle_ownership.py`
  - 回归测试全部通过
- `runtime/tests/test_work_runtime_integration.py`
  - 回归测试全部通过
- 新增测试文件：
  - `runtime/tests/test_work_runtime_concurrency.py`
    - 测试 done 与 timeout 并发时只清理一次
    - 测试 cleanup_launch 幂等性
    - 测试 JSONStore 并发写入不丢事件
  - `runtime/tests/test_work_runtime_timeout_event.py`
    - 测试 timeout 写入 LifecycleEvent
    - 测试 timeout 状态机转换

### 4.3 文档更新
- `MultiAgentWorkspace1.0开发手册.md`
  - 第2节开发日志增加本次架构加固记录
  - 明确 Work Runtime 已完成线程安全加固
- `pools/work/WORKPOOL_HANDOVER.md`
  - 更新当前状态为"线程安全已加固，可作为其他池参考模板"

---

## 5. 验收标准

### 5.1 功能验收
- [ ] 所有现有测试通过（64/64）
- [ ] 新增并发测试通过
- [ ] 真实 Worker 闭环验证通过

### 5.2 并发安全验收
- [ ] done 与 timeout 并发到达时，只执行一次 cleanup
- [ ] cleanup_launch 可重入，第二次调用 no-op
- [ ] JSONStore 并发写入不丢事件

### 5.3 状态机验收
- [ ] timeout 事件写入 EventStore
- [ ] timeout 状态机转换合法
- [ ] EventStore 可查询 timeout 事件

### 5.4 时序验收
- [ ] done 信号处理顺序：cleanup → collect_artifacts → clean_slot_dir → reset
- [ ] timeout 处理顺序：write_event → cleanup → clean_slot_dir → reset

---

## 6. 风险与缓解

### 风险 1：锁粒度过粗导致性能下降
- **缓解**：当前 Work Pool 只有 2 个 slot，并发压力不大
- **后续优化**：如需提升性能，可改为 per-slot 锁

### 风险 2：持锁期间执行 I/O 可能阻塞
- **缓解**：当前 I/O 操作（文件拷贝、bat 生成）耗时极短
- **后续优化**：如需优化，可将 I/O 移到锁外

### 风险 3：RLock 可能隐藏死锁问题
- **缓解**：严格遵守"不在持锁期间调用外部回调"原则
- **验证**：增加并发压力测试

---

## 7. 后续演进

### 7.1 短期（本次实施后）
- 复制 Work Runtime 模板到 Thinking/Gate/Task/Packaging Pool
- 每个池复用相同的线程安全模式

### 7.2 中期（多池运行后）
- 如发现锁竞争，改为 per-slot 锁
- 如发现 I/O 阻塞，改为锁外执行

### 7.3 长期（系统稳定后）
- 考虑改为事件队列/消息队列模型
- 彻底消除锁竞争

---

## 8. 设计批准

- **设计者**: Claude Opus 4.6
- **审查者**: （待用户确认）
- **批准日期**: 2026-04-19
- **实施计划**: `docs/superpowers/plans/2026-04-19-work-runtime-concurrency-safety-implementation.md`
