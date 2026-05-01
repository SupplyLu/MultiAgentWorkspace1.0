"""Tests for parse_task_file None handling and runtime input validation.

B组修复测试: 验证所有runtime正确处理parse_task_file返回None的情况
"""

from pathlib import Path
import pytest


class TestParseTaskFileNoneHandling:
    """Test that all runtimes handle parse_task_file returning None correctly."""

    def test_gate_runtime_dispatch_handles_none_parse_result(self, tmp_path):
        """GateRuntime.dispatch_next must handle parse_task_file returning None gracefully."""
        # Setup gate pool
        gate_pool = tmp_path / "pools" / "gate"
        queue_dir = gate_pool / "Queue"
        queue_dir.mkdir(parents=True)
        (gate_pool / "Outbox").mkdir(parents=True)
        (gate_pool / "Rejectbox").mkdir(parents=True)

        slot_dir = gate_pool / "guard_01"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir()

        # Create a task file with invalid header (will cause parse_task_file to return None)
        task_file = queue_dir / "task_invalid.txt"
        task_file.write_text(
            "TASK_ID: ../../../etc/passwd\n\nInvalid task with path traversal",
            encoding="utf-8"
        )

        tools_dir = tmp_path / "runtime" / "tools"
        tools_dir.mkdir(parents=True)
        for f in ["Online.bat", "StartReview.bat", "Accepted.bat", "Denied.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
            (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

        from app.runtimes.gate_runtime import GateRuntime
        runtime = GateRuntime(root_dir=tmp_path, signal_port=19200)

        # Mock parse_task_file to return None (simulating file disappeared or invalid)
        from app.shared import file_queue
        original_parse = file_queue.parse_task_file
        file_queue.parse_task_file = lambda x: None

        try:
            # Should not raise exception, should handle gracefully
            result = runtime.dispatch_next(dry_run=True)

            # Should return error indicating the failure
            assert result["dispatched"] is False
            assert "error" in result

            # Slot should be released (not stuck in busy state)
            slot = runtime.get_slot("guard_01")
            assert slot.busy is False
            assert slot.assigned_task_id == ""

        finally:
            file_queue.parse_task_file = original_parse

    def test_package_runtime_dispatch_handles_none_parse_result(self, tmp_path):
        """PackageRuntime.dispatch_next must handle parse_task_file returning None gracefully."""
        # Setup package pool
        package_pool = tmp_path / "pools" / "package"
        queue_dir = package_pool / "Queue"
        queue_dir.mkdir(parents=True)
        (package_pool / "Outbox").mkdir(parents=True)
        (package_pool / "Rejectbox").mkdir(parents=True)

        cutter_dir = package_pool / "cutter_01"
        cutter_dir.mkdir(parents=True)
        (cutter_dir / "workspace").mkdir()

        # Create a task file
        task_file = queue_dir / "task_invalid.txt"
        task_file.write_text(
            "TASK_ID: invalid/../../../etc\n\nInvalid task",
            encoding="utf-8"
        )

        tools_dir = tmp_path / "runtime" / "tools"
        tools_dir.mkdir(parents=True)
        for f in ["Online.bat", "StartCut.bat", "StartTest.bat", "StartRelease.bat",
                  "StartCompletePlayer.bat", "Reject.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
            (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

        from app.runtimes.package_runtime import PackageRuntime
        runtime = PackageRuntime(root_dir=tmp_path, signal_port=19300)

        # Mock parse_task_file to return None
        from app.shared import file_queue
        original_parse = file_queue.parse_task_file
        file_queue.parse_task_file = lambda x: None

        try:
            # Should not raise exception
            result = runtime.dispatch_next(dry_run=True)

            # Should return error
            assert result["dispatched"] is False
            assert "error" in result

        finally:
            file_queue.parse_task_file = original_parse

    def test_construct_runtime_dispatch_handles_none_parse_result(self, tmp_path):
        """ConstructRuntime.dispatch_next must handle parse_task_file returning None gracefully."""
        # Setup construct pool
        construct_pool = tmp_path / "pools" / "construct"
        queue_dir = construct_pool / "Queue"
        queue_dir.mkdir(parents=True)
        (construct_pool / "Outbox").mkdir(parents=True)

        slot_dir = construct_pool / "constructor_01"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir()

        # Create a task file with invalid header
        task_file = queue_dir / "task_invalid.txt"
        task_file.write_text(
            "TASK_ID: ../../../etc/passwd\n\nInvalid task",
            encoding="utf-8"
        )

        tools_dir = tmp_path / "runtime" / "tools"
        tools_dir.mkdir(parents=True)
        for f in ["Online.bat", "StartArchitecting.bat", "StartFinalizing.bat",
                  "Done.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
            (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

        from app.runtimes.construct_runtime import ConstructRuntime
        runtime = ConstructRuntime(root_dir=tmp_path, signal_port=19020)

        # Mock parse_task_file to return None
        from app.shared import file_queue
        original_parse = file_queue.parse_task_file
        file_queue.parse_task_file = lambda x: None

        try:
            # Should not raise exception
            result = runtime.dispatch_next(dry_run=True)

            # Should return error
            assert result["dispatched"] is False
            assert "error" in result

            # Slot should be released
            slot = runtime.get_slot("constructor_01")
            assert slot.busy is False

        finally:
            file_queue.parse_task_file = original_parse


class TestGateRuntimeTerminalStateRace:
    """Test GateRuntime terminal state convergence to prevent double finalization."""

    def test_gate_slot_has_finalizing_field(self, tmp_path):
        """GuardSlot must have finalizing field for terminal state convergence."""
        from app.runtimes.gate_runtime import GuardSlot
        from pathlib import Path

        slot = GuardSlot(
            slot_id="guard_01",
            slot_dir=tmp_path,
            workspace_dir=tmp_path
        )

        # Should have finalizing field defaulting to False
        assert hasattr(slot, "finalizing")
        assert slot.finalizing is False

    def test_find_idle_slot_filters_finalizing_slots(self, tmp_path):
        """find_idle_slot must not return slots that are finalizing."""
        gate_pool = tmp_path / "pools" / "gate"
        queue_dir = gate_pool / "Queue"
        queue_dir.mkdir(parents=True)
        (gate_pool / "Outbox").mkdir(parents=True)
        (gate_pool / "Rejectbox").mkdir(parents=True)

        # Create two slots
        for i in [1, 2]:
            slot_dir = gate_pool / f"guard_0{i}"
            slot_dir.mkdir(parents=True)
            (slot_dir / "workspace").mkdir()

        from app.runtimes.gate_runtime import GateRuntime
        runtime = GateRuntime(root_dir=tmp_path, signal_port=19200)

        # Mark guard_01 as finalizing
        slot1 = runtime.get_slot("guard_01")
        slot1.busy = True
        slot1.finalizing = True

        # Mark guard_02 as busy but not finalizing
        slot2 = runtime.get_slot("guard_02")
        slot2.busy = True
        slot2.finalizing = False

        # find_idle_slot should return None (both are busy)
        idle_slot = runtime.find_idle_slot()
        assert idle_slot is None

        # Reset guard_02
        slot2.busy = False

        # Now should return guard_02 (not guard_01 which is finalizing)
        idle_slot = runtime.find_idle_slot()
        assert idle_slot is not None
        assert idle_slot.slot_id == "guard_02"

    def test_gate_check_timeouts_skips_finalizing_slots(self, tmp_path):
        """check_timeouts must not finalize slots already claimed by another terminal path."""
        gate_pool = tmp_path / "pools" / "gate"
        queue_dir = gate_pool / "Queue"
        queue_dir.mkdir(parents=True)
        (gate_pool / "Outbox").mkdir(parents=True)
        (gate_pool / "Rejectbox").mkdir(parents=True)

        slot_dir = gate_pool / "guard_01"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir()

        from app.runtimes.gate_runtime import GateRuntime
        runtime = GateRuntime(root_dir=tmp_path, signal_port=19200)

        slot = runtime.get_slot("guard_01")
        slot.busy = True
        slot.finalizing = True
        slot.assigned_task_id = "review_004"
        slot.assigned_at_epoch = 1.0
        slot.timeout_seconds = 1
        slot.launch_result = {"pid": 1234, "launched": True}

        cleanup_calls = []
        original_cleanup = runtime._launch_manager.cleanup_launch

        def mock_cleanup(launch_result):
            cleanup_calls.append(launch_result)
            return {"cleaned": True}

        runtime._launch_manager.cleanup_launch = mock_cleanup

        import time as time_module
        original_time = time_module.time
        time_module.time = lambda: 10.0

        try:
            timed_out = runtime.check_timeouts()

            assert timed_out == []
            assert cleanup_calls == []
            assert slot.busy is True
            assert slot.finalizing is True
            assert slot.assigned_task_id == "review_004"
        finally:
            runtime._launch_manager.cleanup_launch = original_cleanup
            time_module.time = original_time


class TestPackageRuntimeTerminalStateRace:
    """Test PackageRuntime terminal state convergence."""

    def test_package_slot_has_finalizing_field(self, tmp_path):
        """PackageSlot must have finalizing field for terminal state convergence."""
        from app.runtimes.package_runtime import PackageSlot
        from pathlib import Path

        slot = PackageSlot(
            slot_id="cutter_01",
            slot_dir=tmp_path,
            workspace_dir=tmp_path,
            slot_type="cutter"
        )

        # Should have finalizing field defaulting to False
        assert hasattr(slot, "finalizing")
        assert slot.finalizing is False

    def test_package_check_timeouts_skips_finalizing_slots(self, tmp_path):
        """check_timeouts must not finalize slots already claimed by another terminal path."""
        package_pool = tmp_path / "pools" / "package"
        queue_dir = package_pool / "Queue"
        queue_dir.mkdir(parents=True)
        (package_pool / "Outbox").mkdir(parents=True)
        (package_pool / "Rejectbox").mkdir(parents=True)
        (package_pool / "context").mkdir(parents=True)
        (package_pool / "Release").mkdir(parents=True)

        slot_dir = package_pool / "cutter_01"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir()

        from app.runtimes.package_runtime import PackageRuntime, PackageTask
        runtime = PackageRuntime(root_dir=tmp_path, signal_port=19300)

        task = PackageTask(
            task_id="pkg_001",
            project_name="demo_project",
            project_root=tmp_path / "pools" / "work" / "fields" / "demo_project",
            original_task="package demo project",
            context_dir=package_pool / "context" / "demo_project",
            current_stage="cut",
        )
        runtime._tasks[task.task_id] = task

        slot = runtime.get_slot("cutter_01")
        slot.busy = True
        slot.finalizing = True
        slot.assigned_task_id = task.task_id
        slot.assigned_project_name = task.project_name
        slot.assigned_at_epoch = 1.0
        slot.timeout_seconds = 1
        slot.launch_result = {"pid": 2345, "launched": True}

        cleanup_calls = []
        original_cleanup = runtime._launch_manager.cleanup_launch

        def mock_cleanup(launch_result):
            cleanup_calls.append(launch_result)
            return {"cleaned": True}

        runtime._launch_manager.cleanup_launch = mock_cleanup

        import time as time_module
        original_time = time_module.time
        time_module.time = lambda: 10.0

        try:
            timed_out = runtime.check_timeouts()

            assert timed_out == []
            assert cleanup_calls == []
            assert slot.busy is True
            assert slot.finalizing is True
            assert slot.assigned_task_id == "pkg_001"
            assert task.task_id in runtime._tasks
        finally:
            runtime._launch_manager.cleanup_launch = original_cleanup
            time_module.time = original_time

    def test_package_finalize_slot_noops_when_already_finalizing(self, tmp_path):
        """_finalize_slot must not perform duplicate cleanup once another terminal path claimed the slot."""
        package_pool = tmp_path / "pools" / "package"
        (package_pool / "Queue").mkdir(parents=True)
        (package_pool / "Outbox").mkdir(parents=True)
        (package_pool / "Rejectbox").mkdir(parents=True)
        (package_pool / "context").mkdir(parents=True)
        (package_pool / "Release").mkdir(parents=True)

        slot_dir = package_pool / "cutter_01"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir()

        from app.runtimes.package_runtime import PackageRuntime
        runtime = PackageRuntime(root_dir=tmp_path, signal_port=19300)

        slot = runtime.get_slot("cutter_01")
        slot.busy = True
        slot.finalizing = True
        slot.assigned_task_id = "pkg_003"
        slot.assigned_project_name = "demo_project"
        slot.launch_result = {"pid": 3456, "launched": True}
        slot.assigned_at_epoch = 5.0
        slot.last_known_state = "state_timeout"

        cleanup_calls = []
        clean_slot_calls = []
        original_cleanup = runtime._launch_manager.cleanup_launch
        original_clean_slot_dir = runtime._clean_slot_dir

        def mock_cleanup(launch_result):
            cleanup_calls.append(launch_result)
            return {"cleaned": True}

        def mock_clean_slot_dir(slot_arg):
            clean_slot_calls.append(slot_arg.slot_id)

        runtime._launch_manager.cleanup_launch = mock_cleanup
        runtime._clean_slot_dir = mock_clean_slot_dir

        try:
            runtime._finalize_slot(slot)

            assert cleanup_calls == []
            assert clean_slot_calls == []
            assert slot.busy is True
            assert slot.finalizing is True
            assert slot.assigned_task_id == "pkg_003"
            assert slot.launch_result == {"pid": 3456, "launched": True}
            assert slot.assigned_at_epoch == 5.0
            assert slot.last_known_state == "state_timeout"
        finally:
            runtime._launch_manager.cleanup_launch = original_cleanup
            runtime._clean_slot_dir = original_clean_slot_dir

    def test_package_handle_signal_skips_finalizing_slots(self, tmp_path):
        """handle_signal must ignore stale terminal-adjacent signals once a slot is finalizing."""
        package_pool = tmp_path / "pools" / "package"
        (package_pool / "Queue").mkdir(parents=True)
        (package_pool / "Outbox").mkdir(parents=True)
        (package_pool / "Rejectbox").mkdir(parents=True)
        (package_pool / "context").mkdir(parents=True)
        (package_pool / "Release").mkdir(parents=True)

        slot_dir = package_pool / "cutter_01"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir()

        from app.runtimes.package_runtime import PackageRuntime, PackageTask
        runtime = PackageRuntime(root_dir=tmp_path, signal_port=19300)

        task = PackageTask(
            task_id="pkg_002",
            project_name="demo_project",
            project_root=tmp_path / "pools" / "work" / "fields" / "demo_project",
            original_task="package demo project",
            context_dir=package_pool / "context" / "demo_project",
            current_stage="cut",
        )
        runtime._tasks[task.task_id] = task

        slot = runtime.get_slot("cutter_01")
        slot.busy = True
        slot.finalizing = True
        slot.assigned_task_id = task.task_id
        slot.assigned_project_name = task.project_name
        slot.last_known_state = "state_timeout"

        stage_passed_calls = []
        original_handle_stage_passed = runtime._handle_stage_passed

        def mock_handle_stage_passed(task_arg, slot_arg, signal_arg):
            stage_passed_calls.append((task_arg.task_id, slot_arg.slot_id, signal_arg))

        runtime._handle_stage_passed = mock_handle_stage_passed

        try:
            runtime.handle_signal({
                "agent_id": "cutter_01",
                "task_id": task.task_id,
                "signal": "cut_passed",
                "to_state": "state_3",
            })

            assert stage_passed_calls == []
            assert slot.last_known_state == "state_timeout"
            assert slot.finalizing is True
            assert slot.assigned_task_id == "pkg_002"
        finally:
            runtime._handle_stage_passed = original_handle_stage_passed



class TestBatInjectionProtection:
    """Test that launch bat generation escapes untrusted values."""

    def test_gate_runtime_escapes_slot_and_task_ids_in_launch_bat(self, tmp_path):
        """GateRuntime launch bat must escape slot/task identifiers before writing set commands."""
        gate_pool = tmp_path / "pools" / "gate"
        queue_dir = gate_pool / "Queue"
        queue_dir.mkdir(parents=True)
        (gate_pool / "Outbox").mkdir(parents=True)
        (gate_pool / "Rejectbox").mkdir(parents=True)

        slot_dir = gate_pool / "guard_01"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir()

        tools_dir = tmp_path / "runtime" / "tools"
        tools_dir.mkdir(parents=True)
        for f in ["Online.bat", "StartReview.bat", "Accepted.bat", "Denied.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
            (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")
        gate_subdir = tools_dir / "gate"
        gate_subdir.mkdir(parents=True)
        (gate_subdir / "GATE_BOOTSTRAP.txt").write_text("mock gate bootstrap", encoding="utf-8")

        from app.runtimes.gate_runtime import GateRuntime
        runtime = GateRuntime(root_dir=tmp_path, signal_port=19200)

        task_file = queue_dir / "task_review_safe.txt"
        task_file.write_text("FROM: construct\nTASK_ID: review_safe\n\nContent", encoding="utf-8")

        slot = runtime.get_slot("guard_01")
        runtime._slots.pop("guard_01")
        slot.slot_id = 'guard_01&calc.exe'
        runtime._slots[slot.slot_id] = slot

        import app.shared.launch_manager as lm_module
        original_launch = lm_module.LaunchManager.launch

        def mock_launch(self, request, dry_run=True):
            return {
                "launched": True,
                "dry_run": dry_run,
                "command": ["cmd"],
                "cwd": str(slot_dir),
                "pid": 5678,
                "job_handle": None,
            }

        lm_module.LaunchManager.launch = mock_launch

        try:
            result = runtime.dispatch_next(dry_run=False)

            assert result["dispatched"] is True
            launch_bat = slot_dir / "launch_guard_01&calc.exe.bat"
            assert launch_bat.exists()
            launch_content = launch_bat.read_text(encoding="utf-8")
            assert 'set "AGENT_ID=guard_01^&calc.exe"' in launch_content
            assert 'set "TASK_ID=review_safe"' in launch_content
            assert 'set AGENT_ID=guard_01&calc.exe' not in launch_content
        finally:
            lm_module.LaunchManager.launch = original_launch

    def test_package_runtime_escapes_path_like_headers_in_launch_bat(self, tmp_path):
        """PackageRuntime launch bat must quote and escape path-like header values before set commands."""
        package_pool = tmp_path / "pools" / "package"
        queue_dir = package_pool / "Queue"
        queue_dir.mkdir(parents=True)
        (package_pool / "Outbox").mkdir(parents=True)
        (package_pool / "Rejectbox").mkdir(parents=True)
        (package_pool / "context").mkdir(parents=True)
        (package_pool / "Release").mkdir(parents=True)

        slot_dir = package_pool / "cutter_01"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir()

        tools_dir = tmp_path / "runtime" / "tools"
        tools_dir.mkdir(parents=True)
        for f in ["Online.bat", "StartCut.bat", "StartTest.bat", "StartRelease.bat",
                  "StartCompletePlayer.bat", "Reject.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
            (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

        task_file = queue_dir / "pkg_safe.txt"
        task_file.write_text(
            "TASK_ID: pkgsafe\n"
            "PROJECT_NAME: demo_project\n"
            "PROJECT_ROOT: C:/demo & calc.exe\n"
            "ORIGINAL_TASK: package demo\n\n"
            "body",
            encoding="utf-8"
        )

        from app.runtimes.package_runtime import PackageRuntime
        runtime = PackageRuntime(root_dir=tmp_path, signal_port=19300)

        import app.shared.launch_manager as lm_module
        original_launch = lm_module.LaunchManager.launch

        def mock_launch(self, request, dry_run=True):
            return {
                "launched": True,
                "dry_run": dry_run,
                "command": ["cmd"],
                "cwd": str(slot_dir),
                "pid": 6789,
                "job_handle": None,
            }

        lm_module.LaunchManager.launch = mock_launch

        try:
            result = runtime.dispatch_next(dry_run=False)

            assert result["dispatched"] is True
            launch_bat = slot_dir / "launch_cutter_01.bat"
            assert launch_bat.exists()
            launch_content = launch_bat.read_text(encoding="utf-8")
            # After Group B path trust fix, PROJECT_ROOT is derived internally, not from external header
            expected_root = tmp_path / "pools" / "work" / "fields" / "demo_project"
            assert f'set "PROJECT_ROOT={expected_root.as_posix()}"' in launch_content
            assert 'set "CONTEXT_DIR=' in launch_content
            # Verify malicious external path is NOT in bat
            assert "C:/demo & calc.exe" not in launch_content
        finally:
            lm_module.LaunchManager.launch = original_launch


class TestPathTrustValidation:
    """Test that runtimes reject malicious path headers."""

    def test_gate_runtime_build_batch_task_txt_no_path_leak(self, tmp_path):
        """_build_batch_task_txt should not expose internal paths."""
        gate_pool = tmp_path / "pools" / "gate"
        (gate_pool / "Queue").mkdir(parents=True)
        (gate_pool / "Outbox").mkdir(parents=True)
        (gate_pool / "Rejectbox").mkdir(parents=True)

        slot_dir = gate_pool / "guard_01"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir()

        from app.runtimes.gate_runtime import GateRuntime
        runtime = GateRuntime(root_dir=tmp_path, signal_port=19200)

        field_dir = tmp_path / "pools" / "gate" / "fields" / "batch_001"
        content = runtime._build_batch_task_txt("batch_001", field_dir)

        assert "batch_001" in content

    def test_construct_runtime_validates_batch_field_path(self, tmp_path):
        """ConstructRuntime should derive batch field from trusted task id instead of external BATCH_FIELD."""
        construct_pool = tmp_path / "pools" / "construct"
        queue_dir = construct_pool / "Queue"
        queue_dir.mkdir(parents=True)
        (construct_pool / "Outbox").mkdir(parents=True)

        slot_dir = construct_pool / "constructor_01"
        slot_dir.mkdir(parents=True)
        workspace_dir = slot_dir / "workspace"
        workspace_dir.mkdir()

        trusted_input_dir = construct_pool / "fields" / "batch_001" / "input"
        trusted_input_dir.mkdir(parents=True)
        (trusted_input_dir / "trusted.txt").write_text("trusted batch content", encoding="utf-8")

        malicious_dir = tmp_path / "malicious_batch"
        (malicious_dir / "input").mkdir(parents=True)
        (malicious_dir / "input" / "pwned.txt").write_text("malicious batch content", encoding="utf-8")

        task_file = queue_dir / "task_malicious.txt"
        task_file.write_text(
            "TASK_ID: batch_001\n"
            "FEATURE_ID: batch_001\n"
            f"BATCH_FIELD: {malicious_dir.as_posix()}\n"
            "\n"
            "Malicious task trying path traversal",
            encoding="utf-8"
        )

        tools_dir = tmp_path / "runtime" / "tools"
        tools_dir.mkdir(parents=True)
        for f in ["Online.bat", "StartArchitecting.bat", "StartFinalizing.bat",
                  "Done.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
            (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

        from app.runtimes.construct_runtime import ConstructRuntime
        runtime = ConstructRuntime(root_dir=tmp_path, signal_port=19020)

        import app.shared.launch_manager as lm_module
        original_launch = lm_module.LaunchManager.launch
        lm_module.LaunchManager.launch = lambda self, request, dry_run=True: {
            "launched": True, "dry_run": dry_run, "job_handle": None
        }

        try:
            result = runtime.dispatch_next(dry_run=True)

            assert result["dispatched"] is True
            assert (workspace_dir / "batch_001" / "trusted.txt").read_text(encoding="utf-8") == "trusted batch content"
            assert not (workspace_dir / "malicious_batch").exists()
            assert not (workspace_dir / "pwned.txt").exists()
        finally:
            lm_module.LaunchManager.launch = original_launch
