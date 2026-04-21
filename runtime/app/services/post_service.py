"""POST Service - 跨池任务投递服务"""

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import json
import uuid
from datetime import datetime, timezone

from app.shared.json_store import JSONStore


@dataclass
class TransferRecord:
    """投递记录"""

    transfer_id: str
    task_id: str
    from_actor: str
    from_pool: str
    to_pool: str
    to_slot: str
    delivery_address: str
    artifact_root: str
    status: str = "pending"
    created_at: str = ""
    delivered_at: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "TransferRecord":
        return TransferRecord(**data)


class PostService:
    """POST 投递服务 - 池间唯一合法通信通道"""

    def __init__(self, transfers_dir: Path | str | None = None):
        if transfers_dir is None:
            # Resolves to MultiAgentWorkspace1.0/transfers
            transfers_dir = Path(__file__).parent.parent.parent.parent / "transfers"
        self._transfers_dir = Path(transfers_dir)
        self._transfers_dir.mkdir(parents=True, exist_ok=True)

        self._index_store = JSONStore(
            self._transfers_dir / "transfers_index.json",
            default_factory=lambda: {"transfers": []},
        )
        self._ensure_index()

    def _ensure_index(self) -> None:
        self._index_store.ensure_initialized()

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def deliver(
        self,
        task_id: str,
        from_actor: str,
        from_pool: str,
        to_pool: str,
        to_slot: str,
        delivery_address: Path | str,
        artifact_root: Path | str = "",
        task_body: str = "",
        extra_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行一次投递，返回投递记录"""
        del extra_meta

        transfer_id = f"xfer_{task_id}_{uuid.uuid4().hex[:8]}"
        created_at = self._utc_now()
        delivery_path = Path(delivery_address)

        record = TransferRecord(
            transfer_id=transfer_id,
            task_id=task_id,
            from_actor=from_actor,
            from_pool=from_pool,
            to_pool=to_pool,
            to_slot=to_slot,
            delivery_address=str(delivery_path),
            artifact_root=str(artifact_root),
            status="pending",
            created_at=created_at,
        )

        try:
            delivery_path.parent.mkdir(parents=True, exist_ok=True)
            with open(delivery_path, "w", encoding="utf-8") as f:
                f.write(task_body)
            record.status = "delivered"
            record.delivered_at = self._utc_now()
        except Exception as e:
            record.status = "failed"
            record.error = str(e)

        xfer_file = self._transfers_dir / f"{transfer_id}.json"
        with open(xfer_file, "w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, ensure_ascii=False, indent=2)

        self._index_store.update(
            lambda idx: {**idx, "transfers": idx.get("transfers", []) + [record.to_dict()]}
        )

        return {
            "status": record.status,
            "transfer_id": transfer_id,
            "delivery_address": str(delivery_path),
            "error": record.error if record.status == "failed" else "",
        }

    def get_transfer(self, transfer_id: str) -> dict[str, Any] | None:
        """查询投递记录"""
        xfer_file = self._transfers_dir / f"{transfer_id}.json"
        if not xfer_file.exists():
            return None
        with open(xfer_file, encoding="utf-8") as f:
            return json.load(f)

    def get_transfers(
        self,
        task_id: str | None = None,
        from_pool: str | None = None,
        to_pool: str | None = None,
        to_slot: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """查询投递记录列表"""
        index = self._index_store.read()
        transfers = index.get("transfers", [])

        if task_id:
            transfers = [t for t in transfers if t.get("task_id") == task_id]
        if from_pool:
            transfers = [t for t in transfers if t.get("from_pool") == from_pool]
        if to_pool:
            transfers = [t for t in transfers if t.get("to_pool") == to_pool]
        if to_slot:
            transfers = [t for t in transfers if t.get("to_slot") == to_slot]
        if status:
            transfers = [t for t in transfers if t.get("status") == status]

        return transfers[-limit:]

    def get_pool_status(self, pool_id: str) -> dict[str, Any]:
        """获取指定池的投递状态概览"""
        all_transfers = self._index_store.read().get("transfers", [])
        pool_transfers = [
            t
            for t in all_transfers
            if t.get("from_pool") == pool_id or t.get("to_pool") == pool_id
        ]

        return {
            "pool": pool_id,
            "total": len(pool_transfers),
            "pending": len([t for t in pool_transfers if t.get("status") == "pending"]),
            "delivered": len([t for t in pool_transfers if t.get("status") == "delivered"]),
            "failed": len([t for t in pool_transfers if t.get("status") == "failed"]),
        }
