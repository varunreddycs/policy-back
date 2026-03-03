from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class PromptTemplate:
	name: str
	version: str
	template: str


class PromptRegistry:
	"""Prompt template registry + versioning (Phase 2 scaffold)."""

	def __init__(self) -> None:
		self._prompts: Dict[str, PromptTemplate] = {}

	def register(self, prompt: PromptTemplate) -> None:
		self._prompts[f"{prompt.name}:{prompt.version}"] = prompt

	def get(self, name: str, version: str) -> PromptTemplate:
		return self._prompts[f"{name}:{version}"]
