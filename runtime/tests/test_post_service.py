from pathlib import Path

from app.services.post_service import PostService


def test_post_service_deliver(tmp_path):
    service = PostService(transfers_dir=tmp_path)

    delivery_dir = tmp_path / "work" / "pending"
    result = service.deliver(
        task_id="t_001",
        from_actor="brain_01",
        from_pool="task",
        to_pool="work",
        to_slot="worker_01",
        delivery_address=delivery_dir / "task_t_001.txt",
        artifact_root=str(tmp_path / "artifacts" / "t_001"),
        task_body="TASK_ID: t_001\n---\n这是一段任务正文\n",
    )

    assert result["status"] == "delivered"
    assert result["transfer_id"].startswith("xfer_t_001")
    assert Path(result["delivery_address"]).exists()

    content = Path(result["delivery_address"]).read_text(encoding="utf-8")
    assert "TASK_ID: t_001" in content


def test_post_service_query_by_task_id(tmp_path):
    service = PostService(transfers_dir=tmp_path)

    for i in range(3):
        service.deliver(
            task_id=f"t_{i:03d}",
            from_actor="brain_01",
            from_pool="task",
            to_pool="work",
            to_slot="worker_01",
            delivery_address=tmp_path / "work" / f"task_{i}.txt",
            task_body=f"body {i}",
        )

    transfers = service.get_transfers(task_id="t_001")
    assert len(transfers) == 1
    assert transfers[0]["task_id"] == "t_001"


def test_post_service_query_by_pool(tmp_path):
    service = PostService(transfers_dir=tmp_path)

    service.deliver("t_001", "b", "task", "thinking", "sb_01", tmp_path / "s1.txt", "")
    service.deliver("t_002", "b", "task", "work", "w_01", tmp_path / "w1.txt", "")

    task_transfers = service.get_transfers(from_pool="task")
    assert len(task_transfers) == 2

    work_transfers = service.get_transfers(to_pool="work")
    assert len(work_transfers) == 1


def test_post_service_get_pool_status(tmp_path):
    service = PostService(transfers_dir=tmp_path)

    service.deliver("t_001", "b", "task", "work", "w_01", tmp_path / "w1.txt", "")
    service.deliver("t_002", "b", "task", "work", "w_02", tmp_path / "w2.txt", "")

    status = service.get_pool_status("work")
    assert status["pool"] == "work"
    assert status["total"] == 2
    assert status["delivered"] == 2


def test_post_service_failed_delivery(tmp_path):
    service = PostService(transfers_dir=tmp_path)

    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")

    result = service.deliver(
        task_id="t_fail",
        from_actor="b",
        from_pool="task",
        to_pool="work",
        to_slot="w_01",
        delivery_address=blocker / "task.txt",
        task_body="should fail",
    )

    assert result["status"] == "failed"
    assert result["error"] != ""
