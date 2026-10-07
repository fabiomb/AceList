import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("ACELIST_DATA_DIR", ROOT_DIR / "data"))
DB_PATH = DATA_DIR / "acelist.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

ENGINE_URL = os.environ.get("ACELIST_ENGINE_URL", "http://127.0.0.1:6878")
# An unknown hash takes ~4 s to fail on the engine, so the default leaves headroom.
ENGINE_TIMEOUT = float(os.environ.get("ACELIST_ENGINE_TIMEOUT", "15"))

FFMPEG_PATH = os.environ.get("ACELIST_FFMPEG_PATH")  # None: look it up on PATH
SCREENSHOT_TIMEOUT = float(os.environ.get("ACELIST_SCREENSHOT_TIMEOUT", "30"))

VLC_PATH = os.environ.get("ACELIST_VLC_PATH")  # None: usual install folders, then PATH
