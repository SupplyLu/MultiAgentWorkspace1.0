from pathlib import Path

from app.services.post_registry import PostRegistry


def test_registry_initializes_required_directories(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)

    assert (tmp_path / "transfers" / "batches").exists()
    assert (tmp_path / "transfers" / "dependencies").exists()
    assert (tmp_path / "transfers" / "transfers").exists()
    assert (tmp_path / "transfers" / "manager_actions").exists()
    assert (tmp_path / "transfers" / "post_index.json").exists()


def test_register_batch_persists_batch_and_branches(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)

    result = registry.register_batch(
        batch_id="feat_001",
        name="login feature",
        from_pool="task",
        to_pool="thinking",
        branches=[
            {
                "branch_id": "feat_001_b1",
                "feature_id": "login_ui",
                "task_body": "task one",
                "outbox_path": "pools/thinking/Outbox/feat_001_b1",
            },
            {
                "branch_id": "feat_001_b2",
                "feature_id": "login_api",
                "task_body": "task two",
                "outbox_path": "pools/thinking/Outbox/feat_001_b2",
            },
        ],
    )

    assert result["batch_id"] == "feat_001"
    assert len(registry.get_branches("feat_001")) == 2
    assert registry.get_batch("feat_001")["status"] == "registered"


def test_register_batch_is_idempotent(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    payload = {
        "batch_id": "feat_001",
        "name": "login feature",
        "from_pool": "task",
        "to_pool": "thinking",
        "branches": [
            {
                "branch_id": "feat_001_b1",
                "feature_id": "login_ui",
                "task_body": "task one",
                "outbox_path": "pools/thinking/Outbox/feat_001_b1",
            }
        ],
    }

    first = registry.register_batch(**payload)
    second = registry.register_batch(**payload)

    assert first["batch_id"] == second["batch_id"]
    assert registry.list_batches() == ["feat_001"]


def test_add_dependency_persists_record(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    dependency = registry.add_dependency(
        source_batch_id="feat_001",
        target_batch_id="feat_002",
        rule="after_delivered",
    )

    assert dependency["rule"] == "after_delivered"
    assert registry.get_dependencies("feat_002")[0]["source_batch_id"] == "feat_001"


def test_record_transfer_persists_delivery_event(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    transfer = registry.record_transfer(
        batch_id="feat_001",
        branch_id="feat_001_b1",
        from_pool="thinking",
        to_pool="construct",
        delivery_address="pools/construct/Queue/task_feat_001_b1.txt",
        status="delivered",
    )

    assert transfer["batch_id"] == "feat_001"
    assert transfer["status"] == "delivered"
    transfers = registry.list_transfers(batch_id="feat_001")
    assert len(transfers) == 1
    assert transfers[0]["branch_id"] == "feat_001_b1"


def test_record_manager_action_persists_audit_log(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    action = registry.record_manager_action(
        batch_id="feat_001",
        action_type="hold",
        detail="User manually held batch due to bug",
    )

    assert action["action_type"] == "hold"
    assert action["batch_id"] == "feat_001"
    actions = registry.list_manager_actions(batch_id="feat_001")
    assert len(actions) == 1
    assert actions[0]["detail"] == "User manually held batch due to bug"


