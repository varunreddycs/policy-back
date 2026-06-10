from __future__ import annotations

import os

import pytest


pytestmark = pytest.mark.integration


def test_worker_extract_flow_smoke_imports() -> None:
	if os.getenv("RUN_INTEGRATION") != "1":
		pytest.skip("Set RUN_INTEGRATION=1 to run integration tests")

	import apps.worker.main  # noqa: F401
	import apps.worker.jobs.extract_policy  # noqa: F401
