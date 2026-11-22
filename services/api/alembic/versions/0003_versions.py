"""project_versions, projects.deleted_at; version 1 for existing projects

Revision ID: 0003
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.add_column("projects", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "project_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(32), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("message", sa.String(200), nullable=False),
        sa.Column("snapshot", JSONB, nullable=False),
        sa.UniqueConstraint("project_id", "number"),
    )
    op.create_index("ix_project_versions_project_id", "project_versions", ["project_id"])
    op.execute(
        """
        INSERT INTO project_versions (id, project_id, number, created_at, created_by, message, snapshot)
        SELECT md5(random()::text || id), id, 1, created_at, owner_id, 'Initial version',
               jsonb_build_object(
                 'floors', COALESCE(data->'floors', '[]'::jsonb),
                 'generation_ids', COALESCE((SELECT jsonb_agg(f->'generation_id')
                                             FROM jsonb_array_elements(data->'floors') f), '[]'::jsonb),
                 'params', COALESCE(data->'params', '{}'::jsonb))
        FROM projects
        """
    )


def downgrade() -> None:
    op.drop_table("project_versions")
    op.drop_column("projects", "deleted_at")
