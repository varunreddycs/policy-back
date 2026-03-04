"""Backfill embeddings for policy sections.

Usage:
python -m scripts.backfill_embeddings --tenant-id <uuid> --only-current
"""

from __future__ import annotations

from apps.worker.jobs.embed_backfill import main

if __name__ == "__main__":
    main()
