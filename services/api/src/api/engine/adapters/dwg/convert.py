"""DWG -> DXF through the ODA File Converter (free download, NOT bundled: its licence forbids redistribution).

The converter is found through `ODA_CONVERTER_PATH` (a file) or the usual install locations; it is run
without a shell, on a private temp directory, with a timeout. The DXF it writes then goes through the normal
DXF pipeline. Without the converter, or when it fails, the user gets a plain InputError.
"""

import glob
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from api.engine.adapters.dxf.reader import InputError
from api.engine.settings import DEFAULTS

ENV = "ODA_CONVERTER_PATH"
OUTPUT_VERSION = "ACAD2018"  # a DXF version ezdxf reads
INSTALL_HELP = (
    "DWG files need the free ODA File Converter, which this app does not bundle. Download it from "
    "https://www.opendesign.com/guestfiles/oda_file_converter, install it, and either keep the default "
    f"install folder or set the {ENV} environment variable to the ODAFileConverter executable. "
    "Or save the drawing as DXF in your CAD program and upload that."
)


def is_dwg(path: Path) -> bool:
    """DWG header sniff: `AC10xx` (R13 and later), not the file name."""
    with path.open("rb") as f:
        return f.read(6).startswith(b"AC10")


def _usable(p: Path) -> bool:
    return p.is_file() and os.access(p, os.X_OK)


def _candidates() -> list[str]:
    if sys.platform == "win32":
        roots = [os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
        return [m for r in roots for m in glob.glob(str(Path(r) / "ODA" / "ODAFileConverter*" / "ODAFileConverter.exe"))]
    if sys.platform == "darwin":
        return ["/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter"]
    return ["/usr/bin/ODAFileConverter", "/usr/local/bin/ODAFileConverter",
            *glob.glob("/opt/ODAFileConverter*/ODAFileConverter"), *glob.glob("/opt/ODAFileConverter*/usr/bin/ODAFileConverter")]


def find_converter() -> Path | None:
    """The configured converter, else the first one found; None when there is none. An env var that
    points at something unusable is an error, not a silent fallback."""
    env = os.environ.get(ENV)
    if env:
        p = Path(env).expanduser().resolve()
        if not _usable(p):
            raise InputError(f"{ENV} is set but is not an executable file ({p.name}). {INSTALL_HELP}")
        return p
    which = shutil.which("ODAFileConverter")
    for c in ([which] if which else []) + _candidates():
        p = Path(c).resolve()
        if _usable(p):
            return p
    return None


def convert_in_place(path: Path) -> None:
    """Replace the DWG at `path` by its DXF (same path, so the upload id and everything after it is unchanged)."""
    exe = find_converter()
    if exe is None:
        raise InputError(INSTALL_HELP)
    with tempfile.TemporaryDirectory(prefix="dwg-") as tmp:
        src_dir, out_dir = Path(tmp, "in"), Path(tmp, "out")
        src_dir.mkdir()
        out_dir.mkdir()
        shutil.copyfile(path, src_dir / "drawing.dwg")  # fixed names: no client string reaches the command line
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}  # headless Linux
        try:
            r = subprocess.run(
                [str(exe), str(src_dir), str(out_dir), OUTPUT_VERSION, "DXF", "0", "1", "drawing.dwg"],
                capture_output=True, text=True, timeout=DEFAULTS.dwg_convert_timeout_s, check=False, shell=False,
                env=env, cwd=tmp)
        except subprocess.TimeoutExpired as e:
            raise InputError(f"the DWG conversion took longer than {DEFAULTS.dwg_convert_timeout_s:g} s and was "
                             "stopped; save the drawing as DXF and upload that") from e
        except OSError as e:
            raise InputError(f"the ODA File Converter could not be started ({e.strerror or e}). {INSTALL_HELP}") from e
        dxf = out_dir / "drawing.dxf"
        if r.returncode != 0 or not dxf.is_file() or dxf.stat().st_size == 0:
            raise InputError("the ODA File Converter could not convert this DWG (corrupt, or a version it does "
                             "not read); save the drawing as DXF in your CAD program and upload that")
        shutil.copyfile(dxf, path)
