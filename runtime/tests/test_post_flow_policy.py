"""Test configurable POST flow policies."""

import json

from app.runtimes.post_runtime import PostRuntime
from app.services.flow_policy import FlowPolicy


def test_post_runtime_skips_gate_when_policy_disables_gate(tmp_path):
    """lightweight_route should skip gate."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "flow_policy.json").write_text(
        json.dumps(
            {
                "active_policy": "lightweight_route",
                "policies": {
                    "default_route": ["post", "gate"],
                    "lightweight_route": ["post", "package"],
                    "post_package_review_route": ["post", "package", "gate"],
                },
            }
        ),
        encoding="utf-8",
    )

    runtime = PostRuntime(root_dir=tmp_path)

    assert runtime.get_policy_route() == ["post", "package"]
    assert "gate" not in runtime.get_policy_route()


def test_post_runtime_follows_default_route(tmp_path):
    """default_route should keep the default downstream order."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "flow_policy.json").write_text(
        json.dumps(
            {
                "active_policy": "default_route",
                "policies": {
                    "default_route": ["post", "gate"],
                    "lightweight_route": ["post", "package"],
                    "post_package_review_route": ["post", "package", "gate"],
                },
            }
        ),
        encoding="utf-8",
    )

    runtime = PostRuntime(root_dir=tmp_path)

    assert runtime.get_policy_route() == ["post", "gate"]


def test_flow_policy_supports_package_review_route(tmp_path):
    """post_package_review_route should flow to package and then back to gate."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    policy_file = config_dir / "flow_policy.json"
    policy_file.write_text(
        json.dumps(
            {
                "active_policy": "post_package_review_route",
                "policies": {
                    "default_route": ["post", "gate"],
                    "lightweight_route": ["post", "package"],
                    "post_package_review_route": ["post", "package", "gate"],
                },
            }
        ),
        encoding="utf-8",
    )

    policy = FlowPolicy(policy_file)

    assert policy.get_active_route() == ["post", "package", "gate"]
