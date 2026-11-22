"""Postgres metadata store (SQLAlchemy). Blobs stay on disk via api.storage."""

import os
from datetime import datetime
from functools import lru_cache

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
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
    # nullable: legacy rows have no owner and stay inaccessible until `import-projects --owner`
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectVersionRow(Base):
    """Immutable history entry; the project's current state is its highest number."""

    __tablename__ = "project_versions"
    __table_args__ = (UniqueConstraint("project_id", "number"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    message: Mapped[str] = mapped_column(String(200))
    # {floors, generation_ids, params: {floor_id: {name: {value, source}}}}
    snapshot: Mapped[dict] = mapped_column(JSONB)


class ProjectGrantRow(Base):
    """A collaborator's role on a project ('viewer' | 'editor'); the owner is projects.owner_id."""

    __tablename__ = "project_grants"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectInviteRow(Base):
    """Role waiting for an unregistered email; becomes a grant when that email registers."""

    __tablename__ = "project_invites"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), primary_key=True)  # lowercased
    role: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShareLinkRow(Base):
    """The project's one read-only link; revoking deletes the row."""

    __tablename__ = "share_links"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectConventionsRow(Base):
    """Per-project layer conventions: a preset name plus the user's layer -> role mapping."""

    __tablename__ = "project_conventions"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    preset: Mapped[str] = mapped_column(String(20))
    mapping: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobRow(Base):
    """A background generation (kind 'generation' | 'floor'); see api.jobs."""

    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10))  # queued | running | succeeded | failed
    stage: Mapped[str] = mapped_column(String(20))
    progress: Mapped[int] = mapped_column(Integer)  # 0-100
    request: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # success body, or {issues} on failure
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UploadRow(Base):
    __tablename__ = "uploads"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    blob_key: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)  # as uploaded, for display
    # nullable: legacy rows and CLI imports have no owner; enforcement is a later subtask
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GenerationRow(Base):
    __tablename__ = "generations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    blob_prefix: Mapped[str] = mapped_column(String(255))  # artifacts live under this key prefix
    # display name of a standalone model: the uploaded file name unless the owner renamed it
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # nullable: legacy rows and CLI imports have no owner; enforcement is a later subtask
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


@lru_cache
def _engine(url: str):
    return create_engine(url, pool_pre_ping=True)


def session() -> Session:
    return Session(_engine(database_url()), expire_on_commit=False)
