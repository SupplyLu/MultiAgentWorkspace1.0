"""Configurable flow policy for POST routing decisions."""

import json
from pathlib import Path


class FlowPolicy:
    def __init__(self, policy_file: Path | str | None = None):
        if policy_file is None:
            self._policies = {}
            self._active = "default_route"
            self._modes = []
            self._default_mode = ""
            self._pool_descriptions = {}
            return

        policy_file = Path(policy_file)
        if not policy_file.exists():
            self._policies = {}
            self._active = "default_route"
            self._modes = []
            self._default_mode = ""
            self._pool_descriptions = {}
            return

        data = json.loads(policy_file.read_text(encoding="utf-8"))
        self._policies = data.get("policies", {})
        self._active = data.get("active_policy", "default_route")
        self._modes = data.get("modes", [])
        self._default_mode = data.get("default_mode", "")
        self._pool_descriptions = data.get("pool_descriptions", {})

    def get_active_route(self) -> list[str]:
        """Return the route for the currently active policy."""
        return self._policies.get(self._active, ["post", "gate"])

    def list_policies(self) -> list[str]:
        """Return all available policy names."""
        return list(self._policies.keys())

    def list_modes(self) -> list[str]:
        """Return available registration modes."""
        return list(self._modes)

    def get_default_mode(self) -> str:
        """Return default registration mode."""
        return self._default_mode

    def get_pool_description(self, pool_name: str) -> str:
        """Return a one-line description for the given pool."""
        return self._pool_descriptions.get(pool_name, "")
