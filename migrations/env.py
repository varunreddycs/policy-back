from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))


def _load_dotenv_if_present() -> None:
	try:
		from dotenv import load_dotenv  # type: ignore

		load_dotenv()
	except Exception:
		return

from alembic import context
from sqlalchemy import engine_from_config, pool

from packages.db.base import Base


config = context.config

if config.config_file_name is not None:
	fileConfig(config.config_file_name)


target_metadata = Base.metadata


def _get_database_url() -> str:
	_load_dotenv_if_present()
	url = os.getenv("DATABASE_URL")
	if not url:
		raise RuntimeError("Missing required environment variable: DATABASE_URL")
	return url


def run_migrations_offline() -> None:
	url = _get_database_url()
	context.configure(
		url=url,
		target_metadata=target_metadata,
		literal_binds=True,
		dialect_opts={"paramstyle": "named"},
		compare_type=True,
	)

	with context.begin_transaction():
		context.run_migrations()


def run_migrations_online() -> None:
	configuration = config.get_section(config.config_ini_section) or {}
	configuration["sqlalchemy.url"] = _get_database_url()

	connectable = engine_from_config(
		configuration,
		prefix="sqlalchemy.",
		poolclass=pool.NullPool,
		future=True,
	)

	with connectable.connect() as connection:
		context.configure(
			connection=connection,
			target_metadata=target_metadata,
			compare_type=True,
		)

		with context.begin_transaction():
			context.run_migrations()


if context.is_offline_mode():
	run_migrations_offline()
else:
	run_migrations_online()
