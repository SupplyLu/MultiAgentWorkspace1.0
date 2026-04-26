import json
import urllib.error
import urllib.request

from app.services.signal_server import RuntimeSignalServer


def test_get_api_status_routes_to_callback(tmp_path):
    server = RuntimeSignalServer(port=18820, event_store_dir=tmp_path)
    captured: dict[str, object] = {}

    def on_api_request(method: str, path: str, payload: dict | None):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = payload
        return {"ok": True, "path": path}

    server.on_api_request = on_api_request
    server.start()

    try:
        with urllib.request.urlopen("http://localhost:18820/api/status", timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            content_type = resp.headers["Content-Type"]

        assert result == {"ok": True, "path": "/api/status"}
        assert "application/json" in content_type
        assert captured == {
            "method": "GET",
            "path": "/api/status",
            "payload": None,
        }

    finally:
        server.stop()


def test_get_api_returns_404_json_when_handler_missing(tmp_path):
    server = RuntimeSignalServer(port=18821, event_store_dir=tmp_path)
    server.start()

    try:
        try:
            urllib.request.urlopen("http://localhost:18821/api/status", timeout=5)
            assert False, "Expected HTTPError for missing API handler"
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
            content_type = exc.headers["Content-Type"]
            result = json.loads(exc.read().decode("utf-8"))

        assert result == {"reason": "no API handler registered"}
        assert "application/json" in content_type

    finally:
        server.stop()


def test_post_api_dispatches_json_payload_to_callback(tmp_path):
    server = RuntimeSignalServer(port=18822, event_store_dir=tmp_path)
    captured: dict[str, object] = {}

    def on_api_request(method: str, path: str, payload: dict | None):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = payload
        return {"received": payload}

    server.on_api_request = on_api_request
    server.start()

    try:
        body = {"query": "status"}
        req = urllib.request.Request(
            "http://localhost:18822/api/status",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            content_type = resp.headers["Content-Type"]

        assert result == {"received": body}
        assert "application/json" in content_type
        assert captured == {
            "method": "POST",
            "path": "/api/status",
            "payload": body,
        }

    finally:
        server.stop()


def test_post_api_returns_400_for_malformed_json(tmp_path):
    server = RuntimeSignalServer(port=18823, event_store_dir=tmp_path)
    called = {"value": False}

    def on_api_request(method: str, path: str, payload: dict | None):
        called["value"] = True
        return {"ok": True}

    server.on_api_request = on_api_request
    server.start()

    try:
        req = urllib.request.Request(
            "http://localhost:18823/api/status",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "Expected HTTPError for malformed JSON"
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            content_type = exc.headers["Content-Type"]
            result = json.loads(exc.read().decode("utf-8"))

        assert result == {"reason": "malformed JSON"}
        assert "application/json" in content_type
        assert called["value"] is False

    finally:
        server.stop()


def test_unknown_post_route_returns_404_without_json_parse(tmp_path):
    server = RuntimeSignalServer(port=18824, event_store_dir=tmp_path)
    server.start()

    try:
        req = urllib.request.Request(
            "http://localhost:18824/unknown/route",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "Expected HTTPError for unknown route"
        except urllib.error.HTTPError as exc:
            assert exc.code == 404

    finally:
        server.stop()


def test_callback_exception_returns_json_500(tmp_path):
    server = RuntimeSignalServer(port=18825, event_store_dir=tmp_path)

    def on_api_request(method: str, path: str, payload: dict | None):
        raise RuntimeError("handler failure")

    server.on_api_request = on_api_request
    server.start()

    try:
        try:
            urllib.request.urlopen("http://localhost:18825/api/status", timeout=5)
            assert False, "Expected HTTPError for callback exception"
        except urllib.error.HTTPError as exc:
            assert exc.code == 500
            content_type = exc.headers["Content-Type"]
            result = json.loads(exc.read().decode("utf-8"))

        assert result["reason"] == "internal server error"
        assert result["error"] == "handler failure"
        assert "application/json" in content_type

    finally:
        server.stop()


def test_signal_endpoint_backward_compatibility(tmp_path):
    server = RuntimeSignalServer(port=18826, event_store_dir=tmp_path)
    server.start()

    try:
        payload = {
            "timestamp": "2026-04-23T10:00:00Z",
            "agent_id": "worker_99",
            "task_id": "t_099",
            "signal": "online",
            "pool": "work",
        }
        req = urllib.request.Request(
            "http://localhost:18826/signal",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            content_type = resp.headers["Content-Type"]

        assert result["accepted"] is True
        assert result["from_state"] == "state_0"
        assert result["to_state"] == "state_1"
        assert "application/json" in content_type

    finally:
        server.stop()
