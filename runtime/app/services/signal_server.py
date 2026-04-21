"""Runtime Signal Server - 接收 CLI 发来的生命周期信号"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
from pathlib import Path
import threading
from typing import Any, Callable, cast

from app.services.event_store import EventStore, LifecycleEvent
from app.services.pool_state_templates import PoolStateTemplateRegistry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SignalHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args):
        logger.info("%s - %s", self.address_string(), format % args)

    def do_POST(self):
        if self.path != "/signal":
            self.send_error(404)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400)
            return

        server = cast("SignalHTTPServer", self.server)
        result = server.runtime_server.process_signal(payload)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))


class SignalHTTPServer(HTTPServer):
    def __init__(self, server_address: tuple[str, int], runtime_server: "RuntimeSignalServer"):
        self.runtime_server = runtime_server
        # [Fix P1] Set allow_reuse_address before calling super().__init__ which calls bind()
        self.allow_reuse_address = True
        super().__init__(server_address, SignalHandler)


class RuntimeSignalServer:
    """Runtime 信号接收与状态推进服务器"""

    def __init__(
        self,
        port: int = 18765,
        event_store_dir: Path | str | None = None,
    ):
        self.port = port
        if event_store_dir is None:
            # Resolves to MultiAgentWorkspace1.0/runtime/events
            event_store_dir = Path(__file__).parent.parent.parent / "events"
        self.event_store = EventStore(event_store_dir)
        self.template_registry = PoolStateTemplateRegistry()
        self._running = False
        self._httpd: SignalHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.on_signal: Callable[[dict[str, Any]], None] | None = None

    def process_signal(self, payload: dict[str, Any]) -> dict[str, Any]:
        """处理信号，返回结果"""
        agent_id = payload.get("agent_id", "")
        task_id = payload.get("task_id", "")
        signal = payload.get("signal", "")
        pool = payload.get("pool", "work")

        if not agent_id or not task_id or not signal:
            return {"accepted": False, "reason": "missing required fields"}

        template = self.template_registry.get_template(pool)
        if template is None:
            return {"accepted": False, "reason": f"unknown pool: {pool}"}

        current_state = self.event_store.get_current_state(agent_id, task_id) or template.initial_state
        next_state = template.get_next_state(current_state, signal)

        if next_state is None:
            return {
                "accepted": False,
                "reason": f"illegal transition: signal={signal} from state={current_state} in pool={pool}",
                "current_state": current_state,
            }

        is_terminal = template.is_terminal(next_state)
        event = LifecycleEvent(
            timestamp=payload.get("timestamp", ""),
            agent_id=agent_id,
            task_id=task_id,
            signal=signal,
            feature_id=payload.get("feature_id", ""),
            role=payload.get("role", ""),
            pool=pool,
            message=payload.get("message", ""),
            artifact_root=payload.get("artifact_root", ""),
            source=payload.get("source", ""),
            pid=payload.get("pid", 0),
            from_state=current_state,
            to_state=next_state,
            is_terminal=is_terminal,
        )

        self.event_store.append(event)

        result = {
            "accepted": True,
            "agent_id": agent_id,
            "task_id": task_id,
            "signal": signal,
            "from_state": current_state,
            "to_state": next_state,
            "is_terminal": is_terminal,
        }

        if self.on_signal:
            try:
                self.on_signal(result)
            except Exception as e:
                logger.error("on_signal hook error: %s", e)

        return result

    def start(self):
        """启动 HTTP 服务器"""
        if self._running:
            return
        self._httpd = SignalHTTPServer(("localhost", self.port), self)
        self._running = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        logger.info("Signal server started on port %s", self.port)

    def stop(self):
        """停止服务器"""
        self._running = False
        if self._httpd:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("Signal server stopped")

    @property
    def is_running(self) -> bool:
        return self._running
