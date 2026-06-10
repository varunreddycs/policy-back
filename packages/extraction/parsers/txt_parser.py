from __future__ import annotations


def parse_txt(content: bytes) -> str:
    try:
        return content.decode("utf-8", errors="replace")
    except Exception:
        return ""
