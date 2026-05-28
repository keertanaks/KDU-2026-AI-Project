"""Initial schema: users, sessions, audit_logs

Revision ID: 001
Revises:
Create Date: 2026-05-13

Uses raw SQL DDL to avoid SQLAlchemy 2.x enum auto-creation conflicts.
"""
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLAlchemy serialises Python enum members by NAME (not value) when
    # the Enum column is declared as Enum(UserRole). The PostgreSQL type
    # must therefore use the same uppercase names.
    op.execute(
        "CREATE TYPE userrole AS ENUM "
        "('TREATING_CLINICIAN', 'NON_TREATING_CLINICIAN', 'ADMINISTRATOR')"
    )

    op.execute(
        """
        CREATE TABLE users (
            user_id      VARCHAR(36)  PRIMARY KEY,
            username     VARCHAR(255) UNIQUE NOT NULL,
            password_hash BYTEA       NOT NULL,
            role         userrole     NOT NULL,
            department   VARCHAR(255),
            created_at   TIMESTAMP WITHOUT TIME ZONE,
            updated_at   TIMESTAMP WITHOUT TIME ZONE,
            is_active    BOOLEAN
        )
        """
    )
    op.execute("CREATE INDEX ix_users_username ON users (username)")

    op.execute(
        """
        CREATE TABLE sessions (
            session_id VARCHAR(36)  PRIMARY KEY,
            user_id    VARCHAR(36)  NOT NULL,
            role       userrole     NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE,
            expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            is_valid   BOOLEAN
        )
        """
    )
    op.execute("CREATE INDEX ix_sessions_user_id ON sessions (user_id)")

    op.execute(
        """
        CREATE TABLE audit_logs (
            audit_id               VARCHAR(36)   PRIMARY KEY,
            user_id                VARCHAR(36)   NOT NULL,
            role                   userrole      NOT NULL,
            timestamp              TIMESTAMP WITHOUT TIME ZONE,
            query_hash             VARCHAR(64)   NOT NULL,
            document_ids_returned  VARCHAR(4096),
            masking_applied        VARCHAR(255),
            result_count           INTEGER,
            latency_ms             INTEGER
        )
        """
    )
    op.execute("CREATE INDEX ix_audit_logs_user_id  ON audit_logs (user_id)")
    op.execute("CREATE INDEX ix_audit_logs_timestamp ON audit_logs (timestamp)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_timestamp")
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_user_id")
    op.execute("DROP TABLE  IF EXISTS audit_logs")

    op.execute("DROP INDEX IF EXISTS ix_sessions_user_id")
    op.execute("DROP TABLE  IF EXISTS sessions")

    op.execute("DROP INDEX IF EXISTS ix_users_username")
    op.execute("DROP TABLE  IF EXISTS users")

    op.execute("DROP TYPE IF EXISTS userrole")
