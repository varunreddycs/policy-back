"""Worker entrypoint (Phase 2 scaffold).

Provides a stable import path for running the background worker:
`python -m apps.worker.main`

Currently delegates to the existing Phase-1 worker implementation.
"""

from worker.policy_processor import run_worker_forever


def main() -> None:
	run_worker_forever()


if __name__ == "__main__":
	main()
