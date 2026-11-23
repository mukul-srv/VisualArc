"""generations.request: the request a model was generated from

Revision ID: 0008

Lets a standalone model that becomes a project floor be regenerated (parameters). Models generated
before this migration have no stored request and stay "legacy": they cannot be regenerated, and
the app says so with the way out (add the floor again from its DXF).

Downgrade drops the column: the stored requests are lost for good, so project floors made from
standalone models after this migration can no longer be regenerated (they become legacy floors).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.add_column("generations", sa.Column("request", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("generations", "request")
