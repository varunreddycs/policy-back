from __future__ import annotations

from pathlib import Path

from packages.governance.prompts import PromptRegistry, PromptTemplate


def default_registry() -> PromptRegistry:
    registry = PromptRegistry()

    prompts_dir = Path(__file__).resolve().parent / "prompts"
    v1 = (prompts_dir / "strict_citation_v1.txt").read_text(encoding="utf-8")
    v2 = (prompts_dir / "strict_citation_v2.txt").read_text(encoding="utf-8")

    registry.register(PromptTemplate(name="strict_citation", version="v1", template=v1))
    registry.register(PromptTemplate(name="strict_citation", version="v2", template=v2))
    return registry
