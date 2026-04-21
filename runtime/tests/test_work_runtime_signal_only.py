"""测试 WorkRuntime 状态仅由 Signal 推进，TXT 文件不得推进状态"""

import pytest
from pathlib import Path
from app.runtimes.work_runtime import WorkRuntime


@pytest.fixture
def work_runtime(tmp_path: Path) -> WorkRuntime:
    """创建测试用 WorkRuntime 实例"""
    # 创建必要的目录结构
    pools_dir = tmp_path / "pools" / "work"
    pools_dir.mkdir(parents=True, exist_ok=True)
    (pools_dir / "Queue").mkdir(exist_ok=True)
    (pools_dir / "Outbox").mkdir(exist_ok=True)

    for worker_id in ["worker_01", "worker_02"]:
        worker_dir = pools_dir / worker_id
        worker_dir.mkdir(exist_ok=True)
        (worker_dir / "workspace").mkdir(exist_ok=True)

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18765)
    return runtime


def test_status_or_outbox_changes_do_not_change_slot_state(work_runtime: WorkRuntime):
    """测试：写入 status.txt 或 outbox.txt 不应改变 slot 状态"""
    slot = work_runtime.get_slot("worker_01")
    assert slot is not None

    # 模拟派发后的状态
    slot.busy = True
    slot.assigned_task_id = "t_001"

    # 模拟旧路径：写入 status.txt（不应改变状态）
    status_file = slot.slot_dir / "status.txt"
    status_file.write_text("AGENT_ID: worker_01\nSTATUS: IDLE\n", encoding="utf-8")

    # 模拟旧路径：写入 outbox.txt（不应改变状态）
    outbox_file = slot.slot_dir / "outbox.txt"
    outbox_file.write_text("[2026-04-18] TASK_ID: t_001 | STATUS: done | RESULT: completed\n", encoding="utf-8")

    # 验证：slot 状态不应被 TXT 文件改变
    assert slot.busy is True, "TXT 文件不应改变 slot.busy 状态"
    assert slot.assigned_task_id == "t_001", "TXT 文件不应改变 slot.assigned_task_id"


def test_only_signal_can_change_slot_state(work_runtime: WorkRuntime):
    """测试：只有 Signal 能改变 slot 状态"""
    slot = work_runtime.get_slot("worker_01")
    assert slot is not None

    # 初始状态
    slot.busy = True
    slot.assigned_task_id = "t_002"

    # 通过 Signal 改变状态
    work_runtime.handle_signal({
        "agent_id": "worker_01",
        "task_id": "t_002",
        "signal": "done",
        "is_terminal": True,
    })

    # 验证：Signal 成功改变了状态
    assert slot.busy is False, "Signal 应该能改变 slot.busy"
    assert slot.assigned_task_id == "", "Signal 应该能清空 slot.assigned_task_id"


def test_work_runtime_has_no_txt_state_recovery_method(work_runtime: WorkRuntime):
    """测试：WorkRuntime 不应有从 TXT 恢复状态的方法"""
    # 检查 WorkRuntime 不应有这些方法
    forbidden_methods = [
        "recover_from_status_txt",
        "recover_from_outbox_txt",
        "scan_status_files",
        "scan_outbox_files",
        "apply_legacy_text_status",
    ]

    for method_name in forbidden_methods:
        assert not hasattr(work_runtime, method_name), \
            f"WorkRuntime 不应有 {method_name} 方法（TXT 状态恢复路径）"
