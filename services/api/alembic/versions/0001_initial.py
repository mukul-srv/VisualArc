"""projects, uploads, generations

Revision ID: 0001
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0001"
down_revision = None


def _created():
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("data", JSONB, nullable=False),
        _created(),
    )
    op.create_table(
        "uploads",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("blob_key", sa.String(255), nullable=False),
        _created(),
    )
    op.create_table(
        "generations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("blob_prefix", sa.String(255), nullable=False),
        _created(),
    )


def downgrade() -> None:
    for t in ("generations", "uploads", "projects"):
        op.drop_table(t)
