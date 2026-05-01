"""
POST naming validation rules.

Enforces strict naming conventions for POST registration:
- Project key format: ProjectName-Version-Mode (e.g., SignalBridge-v1-Build, SignalBridge-2.0.1-Demo)
- Atomic workorder format: {ProjectKey}-{SubTaskName}{Seq} (e.g., SignalBridge-v1-Build-UIupgrade001)
"""

import re

_VERSION_PATTERN = r"[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*"
_PROJECT_KEY_PATTERN = re.compile(rf"^[A-Za-z][A-Za-z0-9]*-{_VERSION_PATTERN}-[A-Za-z][A-Za-z0-9]*$")
_ATOMIC_WORKORDER_PATTERN = re.compile(rf"^([A-Za-z][A-Za-z0-9]*-{_VERSION_PATTERN}-[A-Za-z][A-Za-z0-9]*)-([A-Za-z][A-Za-z0-9]*)(\d+)$")


def is_valid_project_key(name: str) -> bool:
    """
    Validate project key format: ProjectName-Version-Mode.

    Args:
        name: The project key to validate

    Returns:
        True if valid project key format, False otherwise
    """
    return bool(_PROJECT_KEY_PATTERN.fullmatch(name))


def is_valid_atomic_workorder(name: str) -> bool:
    """
    Validate atomic workorder format: {ProjectKey}-{SubTaskName}{Seq}.

    Args:
        name: The atomic workorder to validate

    Returns:
        True if valid atomic workorder format, False otherwise
    """
    return bool(_ATOMIC_WORKORDER_PATTERN.fullmatch(name))


def extract_project_key(name: str) -> str | None:
    """
    Extract project key from atomic workorder or validate project key.

    Args:
        name: Either an atomic workorder or project key

    Returns:
        The project key if valid format, None otherwise
    """
    if is_valid_project_key(name):
        return name

    match = _ATOMIC_WORKORDER_PATTERN.fullmatch(name)
    if match:
        return match.group(1)

    return None
