from datetime import datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.db.models import CheckStatus
from app.services.iso import country_choices, country_name, language_choices, language_name

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"

STATUS_LABELS = {
    CheckStatus.ALIVE: "Activo",
    CheckStatus.NO_PEERS: "Sin peers",
    CheckStatus.NOT_FOUND: "No encontrado",
    CheckStatus.ERROR: "Error",
}


def _local_datetime(value: datetime | None) -> str:
    # Stored in UTC; the app runs on the user's machine, so its timezone is the user's.
    return value.astimezone().strftime("%Y-%m-%d %H:%M") if value else ""


def _short_hash(content_id: str) -> str:
    return f"{content_id[:8]}…{content_id[-4:]}"


templates = Jinja2Templates(directory=WEB_DIR / "templates")
templates.env.filters["localtime"] = _local_datetime
templates.env.filters["short_hash"] = _short_hash
templates.env.globals.update(
    status_labels=STATUS_LABELS,
    language_name=language_name,
    country_name=country_name,
    language_choices=language_choices,
    country_choices=country_choices,
)
