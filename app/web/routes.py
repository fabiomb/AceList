from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.models import Channel, Check, CheckStatus
from app.services.channels import list_channels
from app.services.checks import latest_checks
from app.services.iso import country_name, language_name
from app.services.screenshots import SCREENSHOTS_SUBDIR

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"

STATUS_LABELS = {
    CheckStatus.ALIVE: "Activo",
    CheckStatus.NO_PEERS: "Sin peers",
    CheckStatus.NOT_FOUND: "No encontrado",
    CheckStatus.ERROR: "Error",
}

router = APIRouter()
templates = Jinja2Templates(directory=WEB_DIR / "templates")


def _local_datetime(value: datetime | None) -> str:
    # Stored in UTC; the app runs on the user's machine, so its timezone is the user's.
    return value.astimezone().strftime("%Y-%m-%d %H:%M") if value else ""


def _short_hash(content_id: str) -> str:
    return f"{content_id[:8]}…{content_id[-4:]}"


templates.env.filters["localtime"] = _local_datetime
templates.env.filters["short_hash"] = _short_hash
templates.env.globals.update(
    status_labels=STATUS_LABELS, language_name=language_name, country_name=country_name
)


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


@dataclass(frozen=True)
class ChannelRow:
    channel: Channel
    check: Check | None  # latest one: the channel's current state
    screenshot_url: str | None


def _screenshot_url(request: Request, check: Check | None) -> str | None:
    if check is None or not check.screenshot_path:
        return None
    folder, _, name = check.screenshot_path.partition("/")
    # Only files directly under the screenshots folder are served.
    if folder != SCREENSHOTS_SUBDIR or not name or "/" in name:
        return None
    return request.app.url_path_for("screenshots", path=name)


@router.get("/", response_class=HTMLResponse, name="channel_list")
def channel_list(request: Request, session: SessionDep):
    checks = latest_checks(session)
    rows = []
    for channel in list_channels(session):
        check = checks.get(channel.id)
        rows.append(ChannelRow(channel, check, _screenshot_url(request, check)))
    return templates.TemplateResponse(request, "channels/list.html", {"rows": rows})
