"""Add document_hashes table for ingest deduplication

Revision ID: 002
Revises: 001
Create Date: 2026-05-13
"""
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS document_hashes (
            file_hash   VARCHAR(64) PRIMARY KEY,
            doc_id      VARCHAR(36) NOT NULL,
            filename    TEXT        NOT NULL,
            ingested_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_hashes")
