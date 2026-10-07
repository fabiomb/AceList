import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("ACELIST_DATA_DIR", ROOT_DIR / "data"))
DB_PATH = DATA_DIR / "acelist.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"
