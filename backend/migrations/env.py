"""Alembic environment. Migrations are plain SQL; there is no ORM metadata to diff."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from aios.shared.config import get_settings


def run_migrations_online() -> None:
    url = context.config.attributes.get("database_url") or get_settings().database_url
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("offline mode is not supported; run against a database")
run_migrations_online()
