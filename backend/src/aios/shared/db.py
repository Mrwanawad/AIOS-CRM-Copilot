"""Async SQLAlchemy engine factory (psycopg 3 driver)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """``database_url`` uses the ``postgresql+psycopg://`` scheme (sync and async capable)."""
    return create_async_engine(database_url, echo=echo, pool_pre_ping=True, pool_size=5)
