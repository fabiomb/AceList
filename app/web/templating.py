from datetime import datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.db.base import utcnow
from app.db.models import CheckStatus, Resolution
from app.services.iso import country_choices, country_name, language_choices, language_name
from app.web.flash import flash_message

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"

RESOLUTION_LABELS = {
    Resolution.SD: "480p",
    Resolution.HD: "720p",
    Resolution.FULL_HD: "1080p",
    Resolution.UHD: "4K",
    Resolution.OTHER: "Otra",
}

STATUS_LABELS = {
    CheckStatus.ALIVE: "Activo",
    CheckStatus.NO_PEERS: "Sin peers",
    CheckStatus.NOT_FOUND: "No encontrado",
    CheckStatus.ERROR: "Error",
}


def _local_datetime(value: datetime | None) -> str:
    # Stored in UTC; the app runs on the user's machine, so its timezone is the user's.
    return value.astimezone().strftime("%Y-%m-%d %H:%M") if value else ""


def _ago(value: datetime, now: datetime | None = None) -> str:
    """Short relative time ("hace 3 h"); older than a month falls back to the date."""
    seconds = ((now or utcnow()) - value).total_seconds()
    if seconds < 60:
        return "ahora"
    if seconds < 3600:
        return f"hace {int(seconds // 60)} min"
    if seconds < 86400:
        return f"hace {int(seconds // 3600)} h"
    days = int(seconds // 86400)
    if days <= 30:
        return f"hace {days} d"
    return value.astimezone().strftime("%Y-%m-%d")


def _short_hash(content_id: str) -> str:
    return f"{content_id[:8]}…{content_id[-4:]}"


templates = Jinja2Templates(directory=WEB_DIR / "templates")
templates.env.filters["localtime"] = _local_datetime
templates.env.filters["short_hash"] = _short_hash
templates.env.filters["ago"] = _ago
templates.env.globals.update(
    status_labels=STATUS_LABELS,
    flash_message=flash_message,
    resolution_labels=RESOLUTION_LABELS,
    language_name=language_name,
    country_name=country_name,
    language_choices=language_choices,
    country_choices=country_choices,
)
