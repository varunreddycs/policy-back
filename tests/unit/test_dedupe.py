from __future__ import annotations

from packages.ingestion.dedupe import content_hash, metadata_hash


def test_content_hash_is_sha256_hex() -> None:
	value = content_hash(b"hello")
	assert isinstance(value, str)
	assert len(value) == 64
	assert all(ch in "0123456789abcdef" for ch in value)


def test_metadata_hash_is_sha256_hex() -> None:
	value = metadata_hash({"a": 1, "b": True, "c": None})
	assert isinstance(value, str)
	assert len(value) == 64
	assert all(ch in "0123456789abcdef" for ch in value)
