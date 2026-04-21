"""Runtime 持久层最小数据结构定义。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class TaskRecord:
    task_id: str = ""
    feature_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AgentRecord:
    agent_id: str
    role: str
    parent_agent_id: str | None = None
    status: str = "created"
    task_id: str = ""
    feature_id: str = ""
    pid: int | None = None
    window_title: str = ""
    last_heartbeat: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    def update_heartbeat(self, heartbeat_at: str | None = None) -> None:
        timestamp = heartbeat_at or utc_now_iso()
        self.last_heartbeat = timestamp
        self.updated_at = timestamp

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentRecord":
        return cls(
            agent_id=data.get("agent_id", ""),
            role=data.get("role", ""),
            parent_agent_id=data.get("parent_agent_id"),
            status=data.get("status", "created"),
            task_id=data.get("task_id", ""),
            feature_id=data.get("feature_id", ""),
            pid=data.get("pid"),
            window_title=data.get("window_title", ""),
            last_heartbeat=data.get("last_heartbeat", ""),
            created_at=data.get("created_at", utc_now_iso()),
            updated_at=data.get("updated_at", utc_now_iso()),
        )


@dataclass(slots=True)
class OwnershipRecord:
    parent_agent_id: str
    child_agent_ids: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_registry_state() -> dict[str, Any]:
    return {
        "agents": {},
        "updated_at": utc_now_iso(),
    }


def default_ownership_state() -> dict[str, Any]:
    return {
        "ownership": {},
        "updated_at": utc_now_iso(),
    }


@dataclass(slots=True)
class CoordinatorSnapshot:
    """子脑/大脑运行时快照，用于退出时持久化、复活时恢复。"""
    agent_id: str
    role: str
    generation: int
    parent_agent_id: str | None = None
    task_id: str = ""
    feature_id: str = ""
    children_ids: list[str] = field(default_factory=list)
    waiting_for: list[str] = field(default_factory=list)
    dispatch_child_id: str | None = None
    dispatch_task_id: str | None = None
    dispatch_feature_id: str | None = None
    revival_token: str | None = None
    revival_target_role: str | None = None
    resume_action: str | None = None
    report_to: str = ""
    snapshot_reason: str = ""
    snapshot_path: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CoordinatorSnapshot":
        return cls(
            agent_id=data.get("agent_id", ""),
            role=data.get("role", ""),
            generation=data.get("generation", 1),
            parent_agent_id=data.get("parent_agent_id"),
            task_id=data.get("task_id", ""),
            feature_id=data.get("feature_id", ""),
            children_ids=data.get("children_ids", []),
            waiting_for=data.get("waiting_for", []),
            dispatch_child_id=data.get("dispatch_child_id"),
            dispatch_task_id=data.get("dispatch_task_id"),
            dispatch_feature_id=data.get("dispatch_feature_id"),
            revival_token=data.get("revival_token"),
            revival_target_role=data.get("revival_target_role"),
            resume_action=data.get("resume_action"),
            report_to=data.get("report_to", ""),
            snapshot_reason=data.get("snapshot_reason", ""),
            snapshot_path=data.get("snapshot_path", ""),
            created_at=data.get("created_at", utc_now_iso()),
        )


def default_coordinator_snapshot_state() -> dict[str, Any]:
    return {
        "coordinators": {},
        "updated_at": utc_now_iso(),
    }


def default_worker_lifecycle_state() -> dict[str, Any]:
    return {
        "workers": {},
        "updated_at": utc_now_iso(),
    }


def default_runtime_status_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "updated_at": utc_now_iso(),
    }


def default_guardianship_state() -> dict[str, Any]:
    return {
        "guardian": {},
        "coordinator": {},
        "wards": {},
        "updated_at": utc_now_iso(),
    }
