"""project_grants, project_invites, share_links

Revision ID: 0004
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    now = sa.func.now()
    op.create_table(
        "project_grants",
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.CheckConstraint("role in ('viewer','editor')"),
    )
    op.create_index("ix_project_grants_user_id", "project_grants", ["user_id"])
    op.create_table(
        "project_invites",
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("email", sa.String(254), primary_key=True),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.CheckConstraint("role in ('viewer','editor')"),
    )
    op.create_index("ix_project_invites_email", "project_invites", ["email"])
    op.create_table(
        "share_links",
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("share_links")
    op.drop_table("project_invites")
    op.drop_table("project_grants")
