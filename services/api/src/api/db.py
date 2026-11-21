"""Postgres metadata store (SQLAlchemy). Blobs stay on disk via api.storage."""

import os
from datetime import datetime
from functools import lru_cache

from sqlalchemy import DateTime, String, create_engine, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

# compose credentials from docker-compose.yml / .env.example (local dev only)
DEFAULT_URL = "postgresql+psycopg://visual_arc:visual_arc@localhost:5432/visual_arc"


def database_url() -> str:
    return os.environ.get("DATABASE_URL") or DEFAULT_URL


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # the project manifest ({id, name, floors}) as served by GET /projects/{id}
    data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UploadRow(Base):
    __tablename__ = "uploads"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    blob_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GenerationRow(Base):
    __tablename__ = "generations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    blob_prefix: Mapped[str] = mapped_column(String(255))  # artifacts live under this key prefix
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


@lru_cache
def _engine(url: str):
    return create_engine(url, pool_pre_ping=True)


def session() -> Session:
    return Session(_engine(database_url()), expire_on_commit=False)
