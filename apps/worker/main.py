"""Worker entrypoint.

Run with: `python -m apps.worker.main`
"""

from __future__ import annotations

from apps.worker.logging_config import configure_logging
from apps.worker.policy_processor import run_worker_forever


def main() -> None:
    configure_logging()
    run_worker_forever()


if __name__ == "__main__":
    main()
