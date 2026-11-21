from sqlalchemy import create_engine

from alembic import context
from api.db import Base, database_url

with create_engine(database_url()).connect() as conn:
    context.configure(connection=conn, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
    conn.commit()
