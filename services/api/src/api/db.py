"""Postgres metadata store (SQLAlchemy). Blobs stay on disk via api.storage."""

import os
from datetime import datetime
from functools import lru_cache

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

# compose credentials from docker-compose.yml / .env.example (local dev only)
DEFAULT_URL = "postgresql+psycopg://visual_arc:visual_arc@localhost:5432/visual_arc"


def database_url() -> str:
    return os.environ.get("DATABASE_URL") or DEFAULT_URL


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)  # stored lowercased
    password_hash: Mapped[str | None] = mapped_column(String(255))  # None: OAuth-only account
    display_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OAuthAccountRow(Base):
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_user_id: Mapped[str] = mapped_column(String(255))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # SHA-256 hex of the cookie token
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectRow(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # the project manifest ({id, name, floors}) as served by GET /projects/{id}
    data: Mapped[dict] = mapped_column(JSONB)
    # nullable: legacy rows and CLI imports have no owner; enforcement is a later subtask
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UploadRow(Base):
    __tablename__ = "uploads"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    blob_key: Mapped[str] = mapped_column(String(255))
    # nullable: legacy rows and CLI imports have no owner; enforcement is a later subtask
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GenerationRow(Base):
    __tablename__ = "generations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    blob_prefix: Mapped[str] = mapped_column(String(255))  # artifacts live under this key prefix
    # nullable: legacy rows and CLI imports have no owner; enforcement is a later subtask
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


@lru_cache
def _engine(url: str):
    return create_engine(url, pool_pre_ping=True)


def session() -> Session:
    return Session(_engine(database_url()), expire_on_commit=False)
