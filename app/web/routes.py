from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.models import Channel, Check
from app.services import catalog, categories, channels
from app.services.checks import latest_checks
from app.services.errors import NotFoundError, ServiceError
from app.services.screenshots import SCREENSHOTS_SUBDIR
from app.web.deps import EngineDep, SessionDep
from app.web.forms import ChannelForm, resolve_category
from app.web.templating import templates

router = APIRouter()

FormField = Annotated[str, Form()]


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


def _get_channel_or_404(session: Session, channel_id: int) -> Channel:
    try:
        return channels.get_channel(session, channel_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Canal no encontrado") from exc


def _redirect_to_list(request: Request) -> RedirectResponse:
    # 303 turns the POST into a GET, so reloading the list never resubmits the form.
    return RedirectResponse(request.url_for("channel_list"), status_code=303)


def _render_form(
    request: Request,
    session: Session,
    form: ChannelForm,
    *,
    channel: Channel | None = None,
    error: str | None = None,
) -> HTMLResponse:
    rejected = bool(form.errors or error)
    return templates.TemplateResponse(
        request,
        "channels/form.html",
        {
            "form": form,
            "channel": channel,
            "error": error,
            "categories": categories.list_categories(session),
        },
        # 422 marks a rejected form; htmx is configured to show it (see base.html).
        status_code=422 if rejected else 200,
    )


@router.get("/", response_class=HTMLResponse, name="channel_list")
def channel_list(request: Request, session: SessionDep):
    checks = latest_checks(session)
    rows = []
    for channel in channels.list_channels(session):
        check = checks.get(channel.id)
        rows.append(ChannelRow(channel, check, _screenshot_url(request, check)))
    return templates.TemplateResponse(request, "channels/list.html", {"rows": rows})


@router.get("/channels/new", response_class=HTMLResponse, name="channel_new")
def channel_new(request: Request, session: SessionDep):
    return _render_form(request, session, ChannelForm())


@router.post("/channels/new", response_class=HTMLResponse, name="channel_create")
def channel_create(
    request: Request,
    session: SessionDep,
    client: EngineDep,
    title: FormField = "",
    link: FormField = "",
    category_id: FormField = "",
    new_category: FormField = "",
    language: FormField = "",
    country: FormField = "",
):
    form = ChannelForm(title, link, category_id, new_category, language, country)
    data = form.validate(session)
    if data is None:
        return _render_form(request, session, form)
    try:
        # Blocks while the engine verifies the new channel; FastAPI runs it in a worker.
        catalog.add_channel(
            session,
            client,
            title=data.title,
            link=data.content_id,
            category_id=resolve_category(session, data),
            language=data.language,
            country=data.country,
        )
    except ServiceError as exc:
        return _render_form(request, session, form, error=f"No se pudo guardar: {exc}")
    return _redirect_to_list(request)


@router.get("/channels/{channel_id}/edit", response_class=HTMLResponse, name="channel_edit")
def channel_edit(request: Request, session: SessionDep, channel_id: int):
    channel = _get_channel_or_404(session, channel_id)
    return _render_form(request, session, ChannelForm.from_channel(channel), channel=channel)


@router.post("/channels/{channel_id}/edit", response_class=HTMLResponse, name="channel_update")
def channel_update(
    request: Request,
    session: SessionDep,
    client: EngineDep,
    channel_id: int,
    title: FormField = "",
    link: FormField = "",
    category_id: FormField = "",
    new_category: FormField = "",
    language: FormField = "",
    country: FormField = "",
):
    channel = _get_channel_or_404(session, channel_id)
    form = ChannelForm(title, link, category_id, new_category, language, country)
    data = form.validate(session, channel_id=channel_id)
    if data is None:
        return _render_form(request, session, form, channel=channel)
    try:
        # A changed Content ID is verified again; other edits do not touch the engine.
        catalog.edit_channel(
            session,
            client,
            channel_id,
            link=data.content_id,
            title=data.title,
            category_id=resolve_category(session, data),
            language=data.language,
            country=data.country,
        )
    except ServiceError as exc:
        return _render_form(
            request, session, form, channel=channel, error=f"No se pudo guardar: {exc}"
        )
    return _redirect_to_list(request)


@router.get("/channels/{channel_id}/delete", response_class=HTMLResponse, name="channel_delete")
def channel_delete_confirm(request: Request, session: SessionDep, channel_id: int):
    channel = _get_channel_or_404(session, channel_id)
    return templates.TemplateResponse(
        request,
        "channels/delete.html",
        {"channel": channel, "check_count": len(channel.checks)},
    )


@router.post("/channels/{channel_id}/delete", name="channel_destroy")
def channel_destroy(request: Request, session: SessionDep, channel_id: int):
    _get_channel_or_404(session, channel_id)
    channels.delete_channel(session, channel_id)
    return _redirect_to_list(request)
