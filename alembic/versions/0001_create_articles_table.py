"""create articles table

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00

Initial schema per:
 id UUID PK
 title TEXT
 content TEXT
 author TEXT
 status ENUM(article_status) pending|processing|completed|failed
 embedding_id UUID NULL
 error_message TEXT NULL
 retry_count INTEGER NOT NULL DEFAULT 0
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
 processed_at TIMESTAMPTZ NULL
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

STATUS_VALUES = ("pending", "processing", "completed", "failed")
article_status_enum = postgresql.ENUM(*STATUS_VALUES, name="article_status", create_type=False)


def upgrade() -> None:
 article_status_enum.create(op.get_bind(), checkfirst=True)
 op.create_table(
 "articles",
 sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
 sa.Column("title", sa.Text(), nullable=False),
 sa.Column("content", sa.Text(), nullable=False),
 sa.Column("author", sa.Text(), nullable=False),
 sa.Column("status", article_status_enum, nullable=False),
 sa.Column("embedding_id", postgresql.UUID(as_uuid=True), nullable=True),
 sa.Column("error_message", sa.Text(), nullable=True),
 sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
 sa.Column(
 "created_at",
 sa.DateTime(timezone=True),
 nullable=False,
 server_default=sa.text("now()"),
 ),
 sa.Column(
 "updated_at",
 sa.DateTime(timezone=True),
 nullable=False,
 server_default=sa.text("now()"),
 ),
 sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
 )
 op.create_index("ix_articles_status", "articles", ["status"])
 op.create_index("ix_articles_created_at", "articles", ["created_at"])


def downgrade() -> None:
 op.drop_index("ix_articles_created_at", table_name="articles")
 op.drop_index("ix_articles_status", table_name="articles")
 op.drop_table("articles")
 article_status_enum.drop(op.get_bind(), checkfirst=True)
