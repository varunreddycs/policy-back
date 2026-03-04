from __future__ import annotations

from packages.core.errors import NotImplementedFeature


class LlmClient:
    def complete(self, prompt: str) -> str:
        raise NotImplementedFeature("LLM integration not wired yet")
