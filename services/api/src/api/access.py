"""One access check for every owned row (project, upload, generation).

Today only the owner has access; non-owners, NULL-owner rows and soft-deleted projects all get the
same 404 so ids cannot be probed. Sharing/roles (subtask 04) extends `can_access` only.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from api.storage import valid_id


def can_access(row, user_id: str) -> bool:
    return row.owner_id is not None and row.owner_id == user_id and not getattr(row, "deleted_at", None)


def owned(db: Session, model, id: str, user_id: str, what: str, lock: bool = False):
    """The row, or HTTPException 404 `what` when missing, not accessible or deleted."""
    row = db.get(model, id, with_for_update=lock) if valid_id(id) else None
    if row is None or not can_access(row, user_id):
        raise HTTPException(404, what)
    return row
