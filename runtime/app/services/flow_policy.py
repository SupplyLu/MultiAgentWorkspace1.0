"""Configurable flow policy for POST routing decisions."""

import json
from pathlib import Path


class FlowPolicy:
    def __init__(self, policy_file: Path | str | None = None):
        if policy_file is None:
            self._policies = {}
            self._active = "default_route"
            return

        policy_file = Path(policy_file)
        if not policy_file.exists():
            self._policies = {}
            self._active = "default_route"
            return

        data = json.loads(policy_file.read_text(encoding="utf-8"))
        self._policies = data.get("policies", {})
        self._active = data.get("active_policy", "default_route")

    def get_active_route(self) -> list[str]:
        """Return the route for the currently active policy."""
        return self._policies.get(self._active, ["post", "gate"])

    def list_policies(self) -> list[str]:
        """Return all available policy names."""
        return list(self._policies.keys())
