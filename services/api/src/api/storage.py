"""Server-side file storage for uploads and generated artifacts (T15/T16).

Files live under one data directory and are addressed ONLY by server-generated
ids, so no client-supplied string ever becomes a filesystem path.
Blobs are addressed by key (relative, "/"-separated) through put_blob/get_blob/
blob_path; the only implementation is local disk. shortcut: no expiry sweep and no
object storage yet (Render's disk is ephemeral); add an S3 implementation and a
retention policy before deployment. Metadata lives in Postgres (api.db).
"""

import os
import re
import uuid
from pathlib import Path

_DEFAULT_DIR = Path(__file__).resolve().parents[4] / "var" / "data"  # <repo>/var/data
_ID = re.compile(r"[0-9a-f]{32}")


def data_dir() -> Path:
    d = Path(os.environ.get("API_DATA_DIR") or _DEFAULT_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_id() -> str:
    return uuid.uuid4().hex


def valid_id(value: str) -> bool:
    return bool(_ID.fullmatch(value))


def blob_path(key: str) -> Path:
    """Disk location of a blob key; the parent directory is created."""
    if any(p in ("", ".", "..") or "\\" in p or ":" in p for p in key.split("/")):
        raise ValueError("invalid blob key")
    p = data_dir() / key
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def put_blob(key: str, data: bytes) -> None:
    blob_path(key).write_bytes(data)


def get_blob(key: str) -> bytes:
    return blob_path(key).read_bytes()


def upload_key(upload_id: str) -> str:
    if not valid_id(upload_id):
        raise ValueError("invalid id")
    return f"{upload_id}.dxf"


def upload_path(upload_id: str) -> Path:
    return blob_path(upload_key(upload_id))
