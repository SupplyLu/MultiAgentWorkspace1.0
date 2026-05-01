from __future__ import annotations

import logging
from pathlib import Path
import re

logger = logging.getLogger(__name__)

HEADER_BODY_SEPARATOR = "\n\n"

# Pattern for safe ID values
_SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")

def validate_id_field(value: str, field_name: str) -> str:
    """Validate critical headers against a safe whitelist pattern to prevent injection and traversal."""
    if not value:
        raise ValueError(f"{field_name} cannot be empty")
    if len(value) > 128:
        raise ValueError(f"{field_name} is too long (max 128 chars)")
    if not _SAFE_ID_PATTERN.match(value):
        raise ValueError(f"{field_name} contains invalid characters (only alphanumeric, underscores, and hyphens allowed)")
    return value

def normalize_header_key(key: str) -> str:
    return key.strip().upper().replace("-", "_")

def parse_task_header(header_text: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw_line in header_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[normalize_header_key(key)] = value.strip()
    return headers

def split_task_file_content(content: str) -> tuple[str, str]:
    if "\r\n\r\n" in content:
        header_text, body = content.split("\r\n\r\n", 1)
        return header_text, body
    if HEADER_BODY_SEPARATOR in content:
        header_text, body = content.split(HEADER_BODY_SEPARATOR, 1)
        return header_text, body
    return content, ""

def parse_task_file(file_path: str | Path) -> dict[str, object] | None:
    path = Path(file_path)
    try:
        content = path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError) as e:
        logger.warning(f"无法读取任务文件 {path}，可能已被移走或没有权限: {e}")
        return None

    header_text, body = split_task_file_content(content)
    headers = parse_task_header(header_text)
    
    # Validate critical identity fields
    critical_fields = ["TASK_ID", "FEATURE_ID", "BATCH_ID", "PROJECT_NAME"]
    for field in critical_fields:
        if field in headers:
            try:
                headers[field] = validate_id_field(headers[field], field)
            except ValueError as e:
                # We log warning and return None as if the file was unreadable/invalid, letting the caller handle it (usually skips)
                logger.warning(f"Invalid task file {path} skipped due to header violation: {e}")
                return None

    return {
        "file_path": str(path),
        "headers": headers,
        "body": body,
        "raw": content,
    }
