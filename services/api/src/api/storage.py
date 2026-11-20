"""Server-side file storage for uploads and generated artifacts (T15/T16).

Files live under one data directory and are addressed ONLY by server-generated
ids, so no client-supplied string ever becomes a filesystem path.
shortcut: local disk, no expiry sweep; before deployment (T24+) use object
storage (Render's disk is ephemeral) and a retention policy.
"""

import os
import re
import tempfile
import uuid
from pathlib import Path

_ID = re.compile(r"[0-9a-f]{32}")


def data_dir() -> Path:
    d = Path(
        os.environ.get("API_DATA_DIR") or Path(tempfile.gettempdir()) / "visual_arc"
    )
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_id() -> str:
    return uuid.uuid4().hex


def valid_id(value: str) -> bool:
    return bool(_ID.fullmatch(value))


def upload_path(upload_id: str) -> Path:
    if not valid_id(upload_id):
        raise ValueError("invalid id")
    return data_dir() / f"{upload_id}.dxf"
