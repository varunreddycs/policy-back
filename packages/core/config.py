from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class FeatureFlags:
	use_pgvector: bool = False
	use_azure_search: bool = False

	@staticmethod
	def from_env() -> "FeatureFlags":
		return FeatureFlags(
			use_pgvector=os.getenv("FEATURE_PGVECTOR", "0") == "1",
			use_azure_search=os.getenv("FEATURE_AZURE_SEARCH", "0") == "1",
		)
