"""Knowledge base: documents and chunks with vector + full-text indexes.

Revision ID: 0001
Revises:
Create Date: 2026-11-02
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Must match Settings.embedding_dim. Changing it requires a new migration and a re-embed.
EMBEDDING_DIM = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE kb_documents (
            id              bigserial PRIMARY KEY,
            source_id       text NOT NULL,
            version         text NOT NULL,
            series          text NOT NULL,
            title           text NOT NULL,
            doc_type        text NOT NULL,
            compound_code   text,
            effective_date  date NOT NULL,
            status          text NOT NULL CHECK (status IN ('active', 'retired')),
            content_hash    text NOT NULL,
            embedding_model text NOT NULL,
            ingested_at     timestamptz NOT NULL DEFAULT now(),
            UNIQUE (source_id, version)
        )
        """
    )
    op.execute("CREATE INDEX kb_documents_series_status ON kb_documents (series, status)")
    op.execute(
        f"""
        CREATE TABLE kb_chunks (
            id           uuid PRIMARY KEY,
            document_id  bigint NOT NULL REFERENCES kb_documents (id) ON DELETE CASCADE,
            ordinal      int NOT NULL,
            heading_path text[] NOT NULL,
            text         text NOT NULL,
            search_text  text NOT NULL,
            tsv          tsvector GENERATED ALWAYS AS (
                             to_tsvector('english'::regconfig, search_text)
                             || to_tsvector('arabic'::regconfig, search_text)
                         ) STORED,
            embedding    vector({EMBEDDING_DIM}) NOT NULL,
            UNIQUE (document_id, ordinal)
        )
        """
    )
    op.execute("CREATE INDEX kb_chunks_tsv ON kb_chunks USING gin (tsv)")
    op.execute(
        "CREATE INDEX kb_chunks_embedding ON kb_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE kb_chunks")
    op.execute("DROP TABLE kb_documents")
