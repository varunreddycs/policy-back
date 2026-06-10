from __future__ import annotations

import hashlib


def stable_section_key(path: str) -> str:
    return hashlib.sha256((path or "").encode("utf-8")).hexdigest()[:16]
