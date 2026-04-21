"""Signal Bridge - CLI 通过 bat 调用此模块向 Runtime 发送生命周期信号"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

DEFAULT_SIGNAL_SERVER_URL = "http://localhost:18765"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_server_url(server_url_arg: str | None) -> str:
    """解析 Signal Server URL，优先级：--server-url > SIGNAL_SERVER_PORT > 默认值"""
    if server_url_arg:
        return server_url_arg

    port = os.environ.get("SIGNAL_SERVER_PORT")
    if port:
        return f"http://localhost:{port}"

    return DEFAULT_SIGNAL_SERVER_URL


def send_signal(
    agent_id: str,
    task_id: str,
    signal: str,
    feature_id: str = "",
    role: str = "",
    pool: str = "",
    message: str = "",
    artifact_root: str = "",
    source: str = "",
    pid: int = 0,
    server_url: str = DEFAULT_SIGNAL_SERVER_URL,
    dry_run: bool = False,
) -> dict[str, Any]:
    """构造并发送信号到 Runtime 信号服务器"""
    payload = {
        "timestamp": utc_now(),
        "agent_id": agent_id,
        "task_id": task_id,
        "signal": signal,
        "feature_id": feature_id,
        "role": role,
        "pool": pool,
        "message": message,
        "artifact_root": artifact_root,
        "source": source,
        "pid": pid,
    }

    if dry_run:
        print(f"[DRY_RUN] Signal payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
        return {"status": "dry_run", "payload": payload}

    try:
        req = urllib.request.Request(
            f"{server_url}/signal",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return {"status": "ok", "response": result}
    except urllib.error.URLError as e:
        return {"status": "error", "message": str(e), "payload": payload}


def main():
    parser = argparse.ArgumentParser(description="Signal Bridge - Send lifecycle signals to Runtime")
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument(
        "--signal",
        required=True,
        choices=[
            "online",
            "start_thinking",
            "start_summarizing",
            "start_architecting",
            "start_finalizing",
            "start_writing",
            "start_review",
            "blocked",
            "failed",
            "done",
            "approved",
            "rejected",
        ],
    )
    parser.add_argument("--feature-id", default="")
    parser.add_argument("--role", default="")
    parser.add_argument("--pool", default="work")
    parser.add_argument("--message", default="")
    parser.add_argument("--artifact-root", default="")
    parser.add_argument("--source", default="")
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--server-url", default=None)
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    server_url = resolve_server_url(args.server_url)

    result = send_signal(
        agent_id=args.agent_id,
        task_id=args.task_id,
        signal=args.signal,
        feature_id=args.feature_id,
        role=args.role,
        pool=args.pool,
        message=args.message,
        artifact_root=args.artifact_root,
        source=args.source,
        pid=args.pid,
        server_url=server_url,
        dry_run=args.dry_run,
    )

    if result["status"] == "ok":
        print(f"OK: {json.dumps(result['response'], ensure_ascii=False)}")
        sys.exit(0)
    if result["status"] == "dry_run":
        print(f"DRY_RUN: {json.dumps(result['payload'], ensure_ascii=False)}")
        sys.exit(0)

    print(f"ERROR: {result.get('message', 'unknown')}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
