from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DomainError(Exception):
	code: str
	message: str
	detail: Optional[dict] = None

	def __str__(self) -> str:  # pragma: no cover
		return f"{self.code}: {self.message}"


class NotImplementedFeature(DomainError):
	def __init__(self, message: str = "Feature not implemented") -> None:
		super().__init__(code="NOT_IMPLEMENTED", message=message)
