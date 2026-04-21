# Construct Runtime 文件夹任务接收设计

> 日期：2026-04-20
> 状态：设计稿，待复核

## 背景

Thinking Pool Outbox 的产物天然是**文件夹**，里面包含多个相关的 thinking task txt、summary 等文件。
Work / Thinking Runtime 只处理单文件，无法原生接收文件夹任务。
因此 Construct Runtime 需要支持文件夹作为 task 单元。

## 设计目标

1. Construct Queue 同时支持：
   - 单个 `.txt` 文件 → 按现有逻辑处理
   - 单个目录 → 识别后移入 field，生成路径引用 txt，再按现有逻辑处理
2. 完全兼容旧链路，不破坏现有单文件 dispatch 逻辑
3. 统一在 `Done` 信号后清理 field

## 核心流程

```
Queue/
  pid_simulink_001/          ← 文件夹 task 进来了
    summary.txt               (内有 BATCH_ID=pid_simulink_001)
    task_*.txt

Runtime.list_queue_tasks()    ← 扫描时发现是目录
  → 读取 summary.txt，取 BATCH_ID
  → 在 fields/ 下创建 pid_simulink_001/
  → 将整个文件夹移入 fields/pid_simulink_001/
  → 在 Queue/ 中生成 task_batch_pid_simulink_001.txt
  → 返回 txt 列表（此时只有生成的引用文件）

Runtime.dispatch_next()        ← 现有逻辑不变，照常派发
  → 派发 task_batch_pid_simulink_001.txt
  → Constructor 读取 BATCH_FIELD 路径
  → Constructor 处理整个 batch，生成 work task

Constructor 调用 Done.bat
Runtime.handle_signal(done)
  → collect_artifacts_to_outbox()
  → 清理 fields/pid_simulink_001/
  → slot 复位
```

## 详细设计

### 1. 新增目录结构

```
pools/construct/
  fields/
    <batch_id>/
      input/           ← 原始 Thinking 产物（移入的文件夹内容）
      output/          ← Constructor 产出（work task 工单等）
      meta/
        batch_info.json  ← batch 元信息：source, created_at, task_ids
```

### 2. `list_queue_tasks()` 改造

```python
def list_queue_tasks(self) -> list[Path]:
    """Scan Queue, convert folder batches to reference txt, return txt tasks."""
    if not self._queue_dir.exists():
        return []

    self._preprocess_queue_folders()  # 新增：文件夹预处理

    tasks = []
    for f in self._queue_dir.iterdir():
        if f.is_file() and f.suffix == ".txt" and not f.name.startswith("."):
            tasks.append(f)
    return sorted(tasks)

def _preprocess_queue_folders(self) -> None:
    """Convert each folder in Queue to a reference txt."""
    for item in self._queue_dir.iterdir():
        if not item.is_dir():
            continue
        if item.name.startswith("."):
            continue

        batch_id = self._extract_batch_id(item)
        if not batch_id:
            continue

        field_dir = self._construct_fields_dir / batch_id
        input_dir = field_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        # 移动文件夹内容到 input/
        for sub_item in item.iterdir():
            dst = input_dir / sub_item.name
            if sub_item.is_dir():
                shutil.move(str(sub_item), str(dst))
            else:
                shutil.move(str(sub_item), str(dst))

        # 删除空原文件夹
        if not any(item.iterdir()):
            item.rmdir()

        # 生成引用 txt
        ref_txt = self._queue_dir / f"task_batch_{batch_id}.txt"
        if not ref_txt.exists():
            ref_txt.write_text(self._build_batch_task_txt(batch_id, field_dir), encoding="utf-8")

        # 写 batch meta
        meta_dir = field_dir / "meta"
        meta_dir.mkdir(parents=True, exist_ok=True)
        (meta_dir / "batch_info.json").write_text(json.dumps({
            "batch_id": batch_id,
            "field_dir": str(field_dir),
            "created_at": datetime.now().isoformat(),
        }, indent=2), encoding="utf-8")
```

### 3. `BATCH_ID` 提取规则

从 `summary.txt` 读取：

```
BATCH_ID: pid_simulink_001
```

如果没有 `summary.txt` 或没有 `BATCH_ID` 字段，降级为使用文件夹名。

### 4. 路径引用 txt 格式

```txt
FROM: thinking_pool
TO: constructor_01
TASK_ID: batch_pid_simulink_001
FEATURE_ID: pid_simulink_001
TIMEOUT: 600
INPUT_MODE: batch_dir
BATCH_FIELD: C:/Users/lenovo/Desktop/MultiAgentWorkspace1.0/pools/construct/fields/pid_simulink_001/
PROJECT_ROOT: C:/Users/lenovo/Desktop/MultiAgentWorkspace1.0/pools/work/fields/pid_tuner/
---

[Construct Task: Process Thinking batch from field directory]

Read all thinking task files from:
  BATCH_FIELD/input/

Analyze and generate strong-constrained work tasks for Work Pool:
  1. Read summary.txt for overall architecture
  2. Read each task_*.txt for individual components
  3. Identify dependencies between tasks
  4. Create work tasks with:
     - TARGET_FILE paths
     - class and method signatures
     - exact test targets
     - acceptance checklists
  5. Output work tasks to BATCH_FIELD/output/
  6. Call Done.bat when complete
```

### 5. `handle_signal(done)` 清理 field

```python
def handle_signal(self, signal_result):
    # 现有逻辑...
    if signal in terminal_signals or is_terminal:
        # 清理 field
        self._cleanup_batch_field(slot, task_id)
        self._finalize_slot_terminal(...)

def _cleanup_batch_field(self, slot: ConstructorSlot, task_id: str) -> None:
    """Remove batch field directory on task completion."""
    if not task_id.startswith("batch_"):
        return  # 单文件 task 无 field

    batch_id = task_id.replace("batch_", "")
    field_dir = self._construct_fields_dir / batch_id

    if field_dir.exists():
        shutil.rmtree(field_dir)
```

### 6. Constructor BOOTSTRAP.txt 改造

Constructor 的 `BOOTSTRAP.txt` 需要识别 `INPUT_MODE`：

- `INPUT_MODE=batch_dir`：读取 `BATCH_FIELD/input/` 下的所有文件
- `INPUT_MODE` 不存在：按现有逻辑，读取 `task_*.txt` 从 slot workspace

## 兼容性

| 场景 | 行为 |
|------|------|
| Queue 中只有 `.txt` | 走现有单文件逻辑，不变 |
| Queue 中有 `.txt` 和目录 | 目录先预处理，txt 正常处理，并行调度 |
| Queue 中只有目录 | 全部预处理后生成引用 txt，再调度 |
| 同一 batch 多次投递 | field 已存在则跳过（幂等） |

## 改动清单

1. `construct_runtime.py`
   - 新增 `fields/` 目录管理
   - `_preprocess_queue_folders()` 方法
   - `_extract_batch_id()` 方法
   - `_build_batch_task_txt()` 方法
   - `_cleanup_batch_field()` 方法
   - `list_queue_tasks()` 调用预处理
   - `handle_signal(done)` 调用清理

2. `pools/construct/` 下新增：
   - `fields/` 目录（初始为空）

3. 测试用例：
   - 文件夹预处理：文件夹 → field + 引用 txt
   - BATCH_ID 提取
   - 重复预处理幂等性
   - Done 后 field 清理
   - 混合 txt + 文件夹场景
