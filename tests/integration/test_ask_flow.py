from __future__ import annotations

import os

import pytest


pytestmark = pytest.mark.integration


def test_ask_flow_smoke_imports() -> None:
	if os.getenv("RUN_INTEGRATION") != "1":
		pytest.skip("Set RUN_INTEGRATION=1 to run integration tests")

	import apps.api.main  # noqa: F401
	import packages.db.models.policy_models  # noqa: F401
