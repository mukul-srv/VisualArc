"""Sharing: owner-managed collaborator roles (by email), pending invites and one read-only link.

Only the owner manages sharing. A link is a random token passed as `?share=` on the read-only
endpoints (project manifest, artifacts); `principal` resolves session user and/or link.
"""

import secrets
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import func, select

from api.access import MAX_COLLABORATORS, Who, owned
from api.auth import CurrentUser, _norm_email, current_user, optional_user
from api.db import (
    ProjectGrantRow,
    ProjectInviteRow,
    ProjectRow,
    ShareLinkRow,
    UserRow,
    session,
)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_user)])


def principal(request: Request, share: str | None = None) -> Who:
    """Signed-in user and/or a valid share link. 401 with neither; an unknown or revoked token is a 404."""
    user = optional_user(request)
    link = None
    if share:
        with session() as db:
            row = db.scalar(select(ShareLinkRow).where(ShareLinkRow.token == share))
        if row is None and user is None:
            raise HTTPException(404, "unknown or revoked link")
        link = row.project_id if row else None
    elif user is None:
        raise HTTPException(401, "not authenticated")
    return Who(user.id if user else None, link)


Principal = Annotated[Who, Depends(principal)]


class GrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    role: Literal["viewer", "editor"]

    _email = field_validator("email")(lambda cls, v: _norm_email(v))


def _view(db, pid: str) -> dict:
    grants = db.execute(select(ProjectGrantRow.role, UserRow).join(
        UserRow, UserRow.id == ProjectGrantRow.user_id).where(ProjectGrantRow.project_id == pid)
        .order_by(UserRow.email)).all()
    invites = db.scalars(select(ProjectInviteRow).where(ProjectInviteRow.project_id == pid)
                         .order_by(ProjectInviteRow.email)).all()
    link = db.get(ShareLinkRow, pid)
    return {
        "collaborators": [{"user_id": u.id, "email": u.email, "display_name": u.display_name,
                           "role": role} for role, u in grants],
        "invites": [{"email": i.email, "role": i.role} for i in invites],
        "link_token": link.token if link else None,
        "max_collaborators": MAX_COLLABORATORS,
    }


def _owner_project(db, pid: str, user: UserRow) -> ProjectRow:
    return owned(db, ProjectRow, pid, user.id, "unknown project", lock=True)


@router.get("/projects/{pid}/access")
def get_access(pid: str, user: CurrentUser):
    with session() as db:
        _owner_project(db, pid, user)
        return _view(db, pid)


@router.put("/projects/{pid}/access")
def put_access(pid: str, req: GrantRequest, user: CurrentUser):
    """Grant a role (or change it). Unregistered emails get a pending invite."""
    with session() as db, db.begin():
        _owner_project(db, pid, user)  # row lock serialises the cap check
        if req.email == user.email:
            raise HTTPException(422, "you own this project")
        target = db.scalar(select(UserRow).where(UserRow.email == req.email))
        existing = (db.get(ProjectGrantRow, (pid, target.id)) if target
                    else db.get(ProjectInviteRow, (pid, req.email)))
        if target and (stale := db.get(ProjectInviteRow, (pid, req.email))):
            db.delete(stale)  # invite left from before the account registered
        if existing is not None:
            existing.role = req.role
        else:
            used = (db.scalar(select(func.count()).select_from(ProjectGrantRow)
                              .where(ProjectGrantRow.project_id == pid))
                    + db.scalar(select(func.count()).select_from(ProjectInviteRow)
                                .where(ProjectInviteRow.project_id == pid)))
            if used >= MAX_COLLABORATORS:
                raise HTTPException(
                    422, f"a project can have at most {MAX_COLLABORATORS} collaborators and invites")
            db.add(ProjectGrantRow(project_id=pid, user_id=target.id, role=req.role) if target
                   else ProjectInviteRow(project_id=pid, email=req.email, role=req.role))
        db.flush()
        return _view(db, pid)


@router.delete("/projects/{pid}/access")
def delete_access(pid: str, email: str, user: CurrentUser):
    """Remove a collaborator or pending invite by email."""
    try:
        email = _norm_email(email)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    with session() as db, db.begin():
        _owner_project(db, pid, user)
        target = db.scalar(select(UserRow).where(UserRow.email == email))
        row = (db.get(ProjectGrantRow, (pid, target.id)) if target else None) or db.get(
            ProjectInviteRow, (pid, email))
        if row is None:
            raise HTTPException(404, "no such collaborator")
        db.delete(row)
        db.flush()
        return _view(db, pid)


@router.post("/projects/{pid}/link")
def create_link(pid: str, user: CurrentUser):
    """The project's read-only link token; created on first call, the same one after."""
    with session() as db, db.begin():
        _owner_project(db, pid, user)
        link = db.get(ShareLinkRow, pid)
        if link is None:
            link = ShareLinkRow(project_id=pid, token=secrets.token_urlsafe(24))
            db.add(link)
        return {"token": link.token}


@router.delete("/projects/{pid}/link", status_code=204)
def revoke_link(pid: str, user: CurrentUser):
    with session() as db, db.begin():
        _owner_project(db, pid, user)
        link = db.get(ShareLinkRow, pid)
        if link is not None:
            db.delete(link)
    return Response(status_code=204)
