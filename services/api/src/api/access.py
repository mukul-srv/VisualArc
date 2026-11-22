"""One access check for every owned row (project, upload, generation).

Roles: owner > editor > viewer. A share link is a read-only (viewer) principal for one project.
Uploads and generations belong to their creator; a generation is also readable by anyone with
viewer access to a project whose versions use it. Non-accessible, NULL-owner and soft-deleted rows
all give the same 404 so ids cannot be probed. Callers pass `need` (default owner = strictest).
"""

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import (
    GenerationRow,
    ProjectGrantRow,
    ProjectInviteRow,
    ProjectRow,
    ProjectVersionRow,
    UserRow,
)
from api.storage import valid_id

RANK = {"viewer": 1, "editor": 2, "owner": 3}
MAX_COLLABORATORS = 8  # grants + pending invites per project


@dataclass(frozen=True)
class Who:
    """The caller: a signed-in user and/or the project a valid share link opens."""

    user_id: str | None = None
    link_project: str | None = None


def _who(who: "str | Who") -> Who:
    return who if isinstance(who, Who) else Who(user_id=who)


def project_role(db: Session, p: ProjectRow, who: "str | Who") -> str | None:
    who = _who(who)
    if p.deleted_at or p.owner_id is None:
        return None
    if who.user_id:
        if p.owner_id == who.user_id:
            return "owner"
        g = db.get(ProjectGrantRow, (p.id, who.user_id))
        if g:
            return g.role
    return "viewer" if who.link_project == p.id else None


def can_access(db: Session, row, who: "str | Who", need: str = "owner") -> bool:
    who = _who(who)
    if isinstance(row, ProjectRow):
        r = project_role(db, row, who)
        return r is not None and RANK[r] >= RANK[need]
    if isinstance(row, GenerationRow) and need == "viewer":
        ps = db.scalars(select(ProjectRow).join(
            ProjectVersionRow, ProjectVersionRow.project_id == ProjectRow.id).where(
            ProjectVersionRow.snapshot["generation_ids"].contains([row.id])).distinct()).all()
        if ps:  # project roles decide, so a removed editor loses the floors they generated
            return any(project_role(db, p, who) for p in ps)
    return row.owner_id is not None and row.owner_id == who.user_id


def owned(db: Session, model, id: str, who: "str | Who", what: str, lock: bool = False,
          need: str = "owner"):
    """The row, or HTTPException 404 `what` when missing, not accessible at `need` or deleted."""
    row = db.get(model, id, with_for_update=lock) if valid_id(id) else None
    if row is None or not can_access(db, row, who, need):
        raise HTTPException(404, what)
    return row


def claim_invites(db: Session, user: UserRow) -> None:
    """Turn pending invites for the user's VERIFIED email (OAuth only) into grants. Caller commits."""
    for inv in db.scalars(select(ProjectInviteRow).where(ProjectInviteRow.email == user.email)).all():
        db.add(ProjectGrantRow(project_id=inv.project_id, user_id=user.id, role=inv.role))
        db.delete(inv)
