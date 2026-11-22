"""upload file names; generation display names and soft delete

Revision ID: 0007
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.add_column("uploads", sa.Column("filename", sa.String(255), nullable=True))
    op.add_column("generations", sa.Column("name", sa.String(100), nullable=True))
    op.add_column("generations", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("generations", "deleted_at")
    op.drop_column("generations", "name")
    op.drop_column("uploads", "filename")
