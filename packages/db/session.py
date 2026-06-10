from __future__ import annotations

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def _require_env(name: str) -> str:
	value = os.getenv(name)
	if not value:
		raise RuntimeError(f"Missing required environment variable: {name}")
	return value


def create_engine_from_env():
	# Example: postgresql+psycopg://user:pass@host:5432/db
	database_url = _require_env("DATABASE_URL")
	return create_engine(
		database_url,
		pool_pre_ping=True,
		future=True,
	)


_ENGINE = None
_SessionLocal = None


def get_engine():
	global _ENGINE
	if _ENGINE is None:
		_ENGINE = create_engine_from_env()
	return _ENGINE


def get_sessionmaker():
	global _SessionLocal
	if _SessionLocal is None:
		_SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)
	return _SessionLocal


def get_db_session() -> Generator[Session, None, None]:
	session = get_sessionmaker()()
	try:
		yield session
	finally:
		session.close()


__all__ = ["create_engine_from_env", "get_engine", "get_sessionmaker", "get_db_session"]
