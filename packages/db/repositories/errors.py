"""Repository-level errors that are meaningful across backends.

PostgreSQL enforces uniqueness with constraints and signals a violation by
raising IntegrityError. Cosmos enforces nothing beyond (partition key, id), so
the equivalent guard is a re-check performed under an ETag precondition. These
errors let both backends report the same outcomes to a caller that must not
know which one it is talking to.
"""

from __future__ import annotations

import uuid


class RepositoryError(RuntimeError):
    """Base class for errors raised by the repository layer."""


class RepositoryConflict(RepositoryError):
    """A write lost a race against a concurrent writer and was not applied."""


class DuplicateVersionConflict(RepositoryConflict):
    """A version with the same content and metadata hashes already exists."""

    def __init__(self, existing_version_id: uuid.UUID) -> None:
        super().__init__(f"Duplicate policy version: {existing_version_id}")
        self.existing_version_id = existing_version_id


class VersionLabelConflict(RepositoryConflict):
    """Another version under the same policy already carries this label."""

    def __init__(self, version_label: str, existing_version_id: uuid.UUID) -> None:
        super().__init__(f"Version label already in use: {version_label!r}")
        self.version_label = version_label
        self.existing_version_id = existing_version_id
