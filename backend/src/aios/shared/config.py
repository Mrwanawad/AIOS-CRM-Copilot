"""Application settings, loaded once from environment variables (prefix ``AIOS_``)."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Typed runtime configuration. Secrets use ``SecretStr`` so they never leak into logs."""

    model_config = SettingsConfigDict(
        env_prefix="AIOS_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    env: Environment = Environment.LOCAL
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://aios:aios@localhost:5432/aios"
    redis_url: str = "redis://localhost:6379/0"

    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"

    # Embeddings (Google Gemini API). 1536 dims: Matryoshka-truncated, and under
    # pgvector's 2000-dim HNSW limit for the ``vector`` type.
    gemini_api_key: SecretStr | None = None
    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 1536
    embedding_batch_size: int = 100

    # Reranking (Cohere Rerank). Off when no key is set: retrieval keeps the RRF order.
    cohere_api_key: SecretStr | None = None
    rerank_model: str = "rerank-v3.5"
    rerank_candidates: int = 30
    rerank_timeout_s: float = 10.0

    # Maximum discount (percent of list price) each role may grant without escalation.
    discount_limits_pct: dict[str, Decimal] = Field(
        default_factory=lambda: {
            "rep": Decimal("2"),
            "team_lead": Decimal("5"),
            "manager": Decimal("10"),
        }
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
