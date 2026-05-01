import json
import threading
from pathlib import Path

import pytest

from app.services.post_registry import PostRegistry


def _register_project(registry: PostRegistry) -> dict:
    return registry.register_project(
        project_key="proj_001",
        from_pool="task",
        to_pool="thinking",
        route=["task", "thinking", "construct"],
    )


def test_registry_initializes_required_directories(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)

    assert (tmp_path / "transfers" / "projects").exists()
    assert (tmp_path / "transfers" / "dependencies").exists()
    assert (tmp_path / "transfers" / "deliveries").exists()
    assert (tmp_path / "transfers" / "manager_actions").exists()
    assert (tmp_path / "transfers" / "post_index.json").exists()


def test_register_project_persists_project_record(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)

    result = registry.register_project(
        project_key="proj_001",
        from_pool="task",
        to_pool="thinking",
        route=["task", "thinking", "construct"],
    )

    assert result["project_key"] == "proj_001"
    assert result["status"] == "registered"
    assert result["route"] == ["task", "thinking", "construct"]
    assert result["cursor"] == 0
    assert result["current_pool"] == "task"
    assert result["next_pool"] == "thinking"
    assert result["route_version"] == 1
    assert registry.get_project("proj_001") == result


def test_register_project_is_idempotent(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)

    first = _register_project(registry)
    second = _register_project(registry)

    assert first["project_key"] == second["project_key"]
    assert registry.list_projects() == ["proj_001"]


def test_get_project_returns_none_when_missing(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)

    assert registry.get_project("missing") is None


def test_update_project_persists_updates(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    _register_project(registry)

    updated = registry.update_project(
        "proj_001",
        {"status": "in_progress", "cursor": 1, "current_pool": "thinking", "next_pool": "construct"},
    )

    assert updated is not None
    assert updated["status"] == "in_progress"
    assert updated["cursor"] == 1
    assert updated["current_pool"] == "thinking"
    assert registry.get_project("proj_001")["next_pool"] == "construct"


def test_list_projects_returns_all_registered_project_keys(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_project("proj_001", "task", "thinking", ["task", "thinking"])
    registry.register_project("proj_002", "thinking", "construct", ["thinking", "construct"])

    assert registry.list_projects() == ["proj_001", "proj_002"]


def test_add_dependency_uses_project_key_fields(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)

    dependency = registry.add_dependency(
        source_project_key="proj_001",
        target_project_key="proj_002",
        rule="after_delivered",
    )

    assert dependency["source_project_key"] == "proj_001"
    assert dependency["target_project_key"] == "proj_002"
    assert dependency["rule"] == "after_delivered"
    assert registry.get_dependencies("proj_002") == [dependency]


def test_add_dependency_is_atomic_under_concurrent_writes(tmp_path: Path):
    """Test that concurrent add_dependency calls don't lose updates due to read-modify-write race."""
    registry = PostRegistry(root_dir=tmp_path)

    # Simulate race condition: both threads read empty list, both append, one overwrites the other
    # This test verifies the fix uses JSONStore.update() for atomic read-modify-write

    errors: list[Exception] = []
    results: list[dict] = []

    def add_dep(source_key: str):
        try:
            result = registry.add_dependency(
                source_project_key=source_key,
                target_project_key="proj_target",
                rule="after_delivered",
            )
            results.append(result)
        except Exception as exc:  # pragma: no cover - defensive thread capture
            errors.append(exc)

    # Launch 10 concurrent dependency additions to increase race probability
    threads = [
        threading.Thread(target=add_dep, args=(f"proj_{i:03d}",))
        for i in range(10)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert errors == []
    assert len(results) == 10

    # Verify all 10 dependencies were persisted (not lost due to race)
    deps = registry.get_dependencies("proj_target")
    assert len(deps) == 10
    assert {d["source_project_key"] for d in deps} == {f"proj_{i:03d}" for i in range(10)}


def test_record_delivery_persists_delivery_event(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    _register_project(registry)

    delivery = registry.record_delivery(
        project_key="proj_001",
        payload_name="task_proj_001.txt",
        from_pool="thinking",
        to_pool="construct",
        delivery_address="pools/construct/Queue/task_proj_001.txt",
        status="delivered",
        reason="normal routing",
    )

    assert delivery["project_key"] == "proj_001"
    assert delivery["payload_name"] == "task_proj_001.txt"
    assert delivery["status"] == "delivered"
    deliveries = registry.list_deliveries(project_key="proj_001")
    assert len(deliveries) == 1
    assert deliveries[0]["delivery_address"] == "pools/construct/Queue/task_proj_001.txt"
    assert deliveries[0]["reason"] == "normal routing"


def test_list_deliveries_returns_all_and_can_filter_by_project_key(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_project("proj_001", "task", "thinking", ["task", "thinking"])
    registry.register_project("proj_002", "thinking", "construct", ["thinking", "construct"])

    first = registry.record_delivery(
        project_key="proj_001",
        payload_name="task_proj_001.txt",
        from_pool="task",
        to_pool="thinking",
        delivery_address="pools/thinking/Queue/task_proj_001.txt",
        status="delivered",
        reason="initial send",
    )
    second = registry.record_delivery(
        project_key="proj_002",
        payload_name="task_proj_002.txt",
        from_pool="thinking",
        to_pool="construct",
        delivery_address="pools/construct/Queue/task_proj_002.txt",
        status="failed",
        reason="address missing",
    )

    assert registry.list_deliveries() == [first, second]
    assert registry.list_deliveries(project_key="proj_002") == [second]


def test_record_manager_action_uses_project_key(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)

    action = registry.record_manager_action(
        project_key="proj_001",
        action_type="hold",
        detail="User manually held project due to bug",
    )

    assert action["project_key"] == "proj_001"
    assert action["action_type"] == "hold"
    assert registry.list_manager_actions(project_key="proj_001") == [action]


def test_register_project_fallback_route_when_route_omitted(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)

    result = registry.register_project(
        project_key="proj_fallback_001",
        from_pool="thinking",
        to_pool="construct",
    )

    assert result["route"] == ["thinking", "construct"]
    assert result["current_pool"] == "thinking"
    assert result["next_pool"] == "construct"


def test_register_project_rejects_empty_route(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)

    with pytest.raises(ValueError, match="route cannot be empty"):
        registry.register_project(
            project_key="proj_empty_route_001",
            from_pool="thinking",
            to_pool="construct",
            route=[],
        )


def test_update_remaining_route_updates_project_and_records_audit(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_project(
        project_key="proj_route_001",
        from_pool="thinking",
        to_pool="work",
        route=["thinking", "construct", "gate", "work"],
    )
    registry.update_project(
        "proj_route_001",
        {"cursor": 1, "current_pool": "construct", "next_pool": "gate"},
    )

    updated = registry.update_remaining_route(
        project_key="proj_route_001",
        remaining_route=["construct", "work"],
        operator="admin",
        reason="skip gate",
    )

    assert updated["route"] == ["thinking", "construct", "work"]
    assert updated["next_pool"] == "work"
    assert updated["route_version"] == 2
    actions = registry.list_manager_actions(project_key="proj_route_001")
    assert any(a["action_type"] == "route_update" for a in actions)


def test_update_remaining_route_rejects_empty_list(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    _register_project(registry)

    with pytest.raises(ValueError, match="remaining_route cannot be empty"):
        registry.update_remaining_route(
            project_key="proj_001",
            remaining_route=[],
            operator="admin",
            reason="test",
        )


def test_update_remaining_route_rejects_wrong_current_pool(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    _register_project(registry)

    with pytest.raises(ValueError, match="remaining_route must start with current_pool"):
        registry.update_remaining_route(
            project_key="proj_001",
            remaining_route=["wrong_pool", "construct"],
            operator="admin",
            reason="test",
        )


def test_update_remaining_route_audit_detail_contains_required_fields(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_project(
        project_key="proj_audit_001",
        from_pool="thinking",
        to_pool="work",
        route=["thinking", "construct", "work"],
    )
    registry.update_project(
        "proj_audit_001",
        {"cursor": 1, "current_pool": "construct", "next_pool": "work"},
    )

    registry.update_remaining_route(
        project_key="proj_audit_001",
        remaining_route=["construct", "work"],
        operator="admin",
        reason="skip gate for faster delivery",
    )

    actions = registry.list_manager_actions(project_key="proj_audit_001")
    route_action = next(a for a in actions if a["action_type"] == "route_update")

    detail = json.loads(route_action["detail"])
    assert detail["operator"] == "admin"
    assert detail["reason"] == "skip gate for faster delivery"
    assert detail["before"]["route"] == ["thinking", "construct", "work"]
    assert detail["after"]["route"] == ["thinking", "construct", "work"]


def test_get_project_returns_none_for_corrupted_project_file(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    project_file = tmp_path / "transfers" / "projects" / "broken.json"
    project_file.write_text("{broken", encoding="utf-8")

    assert registry.get_project("broken") is None


def test_get_dependencies_returns_empty_for_corrupted_file(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    dep_file = tmp_path / "transfers" / "dependencies" / "proj_002.json"
    dep_file.write_text("{broken", encoding="utf-8")

    assert registry.get_dependencies("proj_002") == []


def test_list_deliveries_skips_corrupted_delivery_files(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    _register_project(registry)
    delivery = registry.record_delivery(
        project_key="proj_001",
        payload_name="task_proj_001.txt",
        from_pool="task",
        to_pool="thinking",
        delivery_address="pools/thinking/Queue/task_proj_001.txt",
        status="delivered",
        reason="initial send",
    )
    delivery_file = tmp_path / "transfers" / "deliveries" / f"{delivery['delivery_id']}.json"
    delivery_file.write_text("{broken", encoding="utf-8")

    assert registry.list_deliveries(project_key="proj_001") == []


def test_list_manager_actions_skips_corrupted_action_files(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    action = registry.record_manager_action(
        project_key="proj_001",
        action_type="hold",
        detail="manual",
    )
    action_file = tmp_path / "transfers" / "manager_actions" / f"{action['action_id']}.json"
    action_file.write_text("{broken", encoding="utf-8")

    assert registry.list_manager_actions(project_key="proj_001") == []
