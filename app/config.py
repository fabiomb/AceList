import os
import sys
from collections.abc import Mapping
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

# True inside the Windows executable built with PyInstaller (see docs/packaging.md).
FROZEN = bool(getattr(sys, "frozen", False))


def resource_dir(frozen: bool = FROZEN) -> Path:
    """Where the files that ship with AceList live: templates, static files, migrations.

    Read-only: in the executable it is the bundle's `_internal` folder.
    """
    return Path(getattr(sys, "_MEIPASS", ROOT_DIR)) if frozen else ROOT_DIR


def default_data_dir(frozen: bool = FROZEN, environ: Mapping[str, str] = os.environ) -> Path:
    """Where the database and screenshots go unless `ACELIST_DATA_DIR` says otherwise.

    The executable keeps them in the user's profile, so replacing the program folder on
    an update, or unpacking it somewhere read-only, never touches them.
    """
    if not frozen:
        return ROOT_DIR / "data"
    local = environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "AceList"


RESOURCE_DIR = resource_dir()
DATA_DIR = Path(os.environ.get("ACELIST_DATA_DIR") or default_data_dir())
DB_PATH = DATA_DIR / "acelist.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

ENGINE_URL = os.environ.get("ACELIST_ENGINE_URL", "http://127.0.0.1:6878")
# An unknown hash takes ~4 s to fail on the engine, so the default leaves headroom.
ENGINE_TIMEOUT = float(os.environ.get("ACELIST_ENGINE_TIMEOUT", "15"))

FFMPEG_PATH = os.environ.get("ACELIST_FFMPEG_PATH")  # None: look it up on PATH
SCREENSHOT_TIMEOUT = float(os.environ.get("ACELIST_SCREENSHOT_TIMEOUT", "30"))

# Channels verified at once in the background; each one is a live engine session.
CHECK_CONCURRENCY = int(os.environ.get("ACELIST_CHECK_CONCURRENCY", "2"))

VLC_PATH = os.environ.get("ACELIST_VLC_PATH")  # None: usual install folders, then PATH
