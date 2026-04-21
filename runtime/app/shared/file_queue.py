from __future__ import annotations

from pathlib import Path

HEADER_BODY_SEPARATOR = "\n\n"


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



def parse_task_file(file_path: str | Path) -> dict[str, object]:
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")
    header_text, body = split_task_file_content(content)
    headers = parse_task_header(header_text)
    return {
        "file_path": str(path),
        "headers": headers,
        "body": body,
        "raw": content,
    }
