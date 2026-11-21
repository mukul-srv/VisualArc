"""One-off: import legacy `<data>/projects/<pid>/project.json` files into Postgres."""

import json

from api.db import ProjectRow, session
from api.storage import data_dir, valid_id


def import_projects() -> tuple[int, int]:
    """Returns (imported, skipped). Idempotent: ids already in the DB are left alone."""
    imported = skipped = 0
    with session() as db:
        for f in sorted((data_dir() / "projects").glob("*/project.json")):
            pid = f.parent.name
            if not valid_id(pid) or db.get(ProjectRow, pid) is not None:
                skipped += 1
                continue
            db.add(ProjectRow(id=pid, data=json.loads(f.read_text("utf-8"))))
            imported += 1
        db.commit()
    return imported, skipped
