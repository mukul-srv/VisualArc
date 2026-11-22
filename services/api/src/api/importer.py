"""One-off: import legacy `<data>/projects/<pid>/project.json` files into Postgres."""

import json

from sqlalchemy import select

from api.db import GenerationRow, ProjectRow, ProjectVersionRow, UserRow, session
from api.storage import blob_path, data_dir, new_id, valid_id


def import_projects(owner_email: str | None = None) -> tuple[int, int]:
    """Returns (imported, skipped). Idempotent: ids already in the DB are left alone, except that
    `owner_email` also claims ownerless projects (and their generations). Without an owner the
    rows are inaccessible through the API."""
    imported = skipped = 0
    with session() as db:
        owner = None
        if owner_email:
            owner = db.scalar(select(UserRow.id).where(UserRow.email == owner_email.strip().lower()))
            if owner is None:
                raise ValueError(f"no account with email {owner_email!r}")
        for f in sorted((data_dir() / "projects").glob("*/project.json")):
            pid = f.parent.name
            if not valid_id(pid):
                skipped += 1
                continue
            row = db.get(ProjectRow, pid)
            if row is None:
                data = json.loads(f.read_text("utf-8"))
                row = ProjectRow(id=pid, data=data)
                db.add(row)
                imported += 1
            else:
                skipped += 1
            if owner and row.owner_id is None:
                row.owner_id = owner
                _claim(db, row, owner)
            db.flush()
        db.commit()
    return imported, skipped


def _claim(db, row: ProjectRow, owner: str) -> None:
    """Owner on the project's generations (rows created when the blobs exist) and a first version."""
    floors = row.data.get("floors", [])
    for fl in floors:
        gid = fl["generation_id"]
        g = db.get(GenerationRow, gid)
        if g is None and valid_id(gid) and blob_path(f"generations/{gid}").is_dir():
            db.add(GenerationRow(id=gid, blob_prefix=f"generations/{gid}", owner_id=owner))
        elif g is not None and g.owner_id is None:
            g.owner_id = owner
    if db.scalar(select(ProjectVersionRow.id).where(ProjectVersionRow.project_id == row.id).limit(1)) is None:
        db.add(ProjectVersionRow(
            id=new_id(), project_id=row.id, number=1, created_by=owner, message="Imported",
            snapshot={"floors": floors, "generation_ids": [f["generation_id"] for f in floors],
                      "params": row.data.get("params", {})},
        ))
