from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.acestream.errors import ContentNotFoundError, EngineError
from app.db.models import Channel, Check
from app.services import catalog, categories, channels, checks, listing, player
from app.services.errors import NotFoundError, ServiceError
from app.services.iso import country_name, language_name
from app.services.listing import DEFAULT_DESCENDING, ChannelQuery, SortKey
from app.services.screenshots import SCREENSHOTS_SUBDIR
from app.web.check_routes import start_checks
from app.web.deps import (
    CheckRunnerDep,
    EngineDep,
    EngineFactoryDep,
    SessionDep,
    SessionFactoryDep,
    SettingsDep,
)
from app.web.forms import ChannelForm, resolve_category
from app.web.query import parse_query
from app.web.templating import templates

router = APIRouter()

FormField = Annotated[str, Form()]


@dataclass(frozen=True)
class ChannelRow:
    channel: Channel
    check: Check | None  # latest one: the channel's current state
    screenshot_url: str | None


@dataclass(frozen=True)
class CheckRow:
    check: Check
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


def _redirect(request: Request, name: str, **path_params) -> RedirectResponse:
    # 303 turns the POST into a GET, so reloading the page never resubmits the form.
    return RedirectResponse(request.url_for(name, **path_params), status_code=303)


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


def _sort_links(request: Request, query: ChannelQuery) -> dict[str, str]:
    """URL for each column header: the active column flips, others start at their default."""
    links = {}
    for key in SortKey:
        descending = not query.descending if key == query.sort else DEFAULT_DESCENDING[key]
        url = request.url.include_query_params(sort=key.value, dir="desc" if descending else "asc")
        links[key.value] = str(url)
    return links


@router.get("/", response_class=HTMLResponse, name="channel_list")
def channel_list(request: Request, session: SessionDep):
    query = parse_query(request.query_params)
    rows = [
        ChannelRow(channel, check, _screenshot_url(request, check))
        for channel, check in listing.search_channels(session, query)
    ]
    filtered = any(
        (
            query.text,
            query.category_id,
            query.language,
            query.country,
            query.status,
            query.resolution,
        )
    )
    return templates.TemplateResponse(
        request,
        "channels/list.html",
        {
            "rows": rows,
            "query": query,
            "filtered": filtered,
            # Distinguishes "nothing matches" from "nothing at all".
            "catalog_empty": not rows and not filtered,
            "sort_links": _sort_links(request, query),
            "categories": categories.list_categories(session),
            "languages": sorted(
                listing.used_languages(session), key=lambda code: language_name(code) or code
            ),
            "countries": sorted(
                listing.used_countries(session), key=lambda code: country_name(code) or code
            ),
        },
    )


@router.get("/channels/new", response_class=HTMLResponse, name="channel_new")
def channel_new(request: Request, session: SessionDep):
    return _render_form(request, session, ChannelForm())


@router.post("/channels/new", response_class=HTMLResponse, name="channel_create")
def channel_create(
    request: Request,
    session: SessionDep,
    client: EngineDep,
    settings: SettingsDep,
    title: FormField = "",
    link: FormField = "",
    category_id: FormField = "",
    new_category: FormField = "",
    language: FormField = "",
    country: FormField = "",
    resolution: FormField = "",
):
    form = ChannelForm(title, link, category_id, new_category, language, country, resolution)
    data = form.validate(session)
    if data is None:
        return _render_form(request, session, form)
    try:
        # Blocks while the engine verifies the new channel; FastAPI runs it in a worker.
        channel = catalog.add_channel(
            session,
            client,
            title=data.title,
            link=data.content_id,
            category_id=resolve_category(session, data.category_id, data.new_category),
            language=data.language,
            country=data.country,
            resolution=data.resolution,
            settings=settings.verification(),
            capture=settings.capture(),
        )
    except ServiceError as exc:
        return _render_form(request, session, form, error=f"No se pudo guardar: {exc}")
    return _redirect(request, "channel_detail", channel_id=channel.id)


@router.get("/channels/{channel_id}", response_class=HTMLResponse, name="channel_detail")
def channel_detail(request: Request, session: SessionDep, channel_id: int):
    channel = _get_channel_or_404(session, channel_id)
    history = [
        CheckRow(check, _screenshot_url(request, check))
        for check in checks.list_checks(session, channel_id)
    ]
    return templates.TemplateResponse(
        request,
        "channels/detail.html",
        {
            "channel": channel,
            "history": history,
            "latest": history[0].check if history else None,
            # The newest screenshot, even if later checks found the channel dead.
            "last_capture": next((row for row in history if row.screenshot_url), None),
        },
    )


@router.post("/channels/{channel_id}/check", name="channel_check")
def channel_check(
    request: Request,
    session: SessionDep,
    session_factory: SessionFactoryDep,
    engine_factory: EngineFactoryDep,
    settings: SettingsDep,
    runner: CheckRunnerDep,
    channel_id: int,
):
    _get_channel_or_404(session, channel_id)
    # In the background: the detail page shows the progress and reloads when it is done.
    start_checks(runner, [channel_id], session_factory, engine_factory, settings)
    return _redirect(request, "channel_detail", channel_id=channel_id)


@router.post("/channels/{channel_id}/screenshot", name="channel_screenshot")
def channel_screenshot(
    request: Request,
    session: SessionDep,
    session_factory: SessionFactoryDep,
    engine_factory: EngineFactoryDep,
    settings: SettingsDep,
    runner: CheckRunnerDep,
    channel_id: int,
):
    _get_channel_or_404(session, channel_id)
    start_checks(
        runner, [channel_id], session_factory, engine_factory, settings, force_capture=True
    )
    return _redirect(request, "channel_detail", channel_id=channel_id)


@router.post("/channels/{channel_id}/play", response_class=HTMLResponse, name="channel_play")
def channel_play(
    request: Request, session: SessionDep, client: EngineDep, settings: SettingsDep, channel_id: int
):
    channel = _get_channel_or_404(session, channel_id)
    try:
        player.open_in_player(
            client, channel.content_id, title=channel.title, vlc_path=settings.vlc_path
        )
    except player.VlcNotFoundError:
        error = "No se encontró VLC. Instálalo o indica la ruta de vlc.exe en Ajustes."
    except ContentNotFoundError:
        error = "El engine no pudo cargar este Content ID: puede que el enlace haya muerto."
    except EngineError:
        error = (
            f"El engine de Ace Stream no responde en {settings.engine_url}. "
            "¿Está abierto Ace Stream?"
        )
    except player.PlayerError as exc:
        error = f"No se pudo abrir VLC: {exc}"
    else:
        error = None
    return templates.TemplateResponse(
        request,
        "channels/_play_result.html",
        {"channel": channel, "error": error},
        # 503: the player or the engine is not available; htmx shows it (see base.html).
        status_code=503 if error else 200,
    )


@router.get("/channels/{channel_id}/edit", response_class=HTMLResponse, name="channel_edit")
def channel_edit(request: Request, session: SessionDep, channel_id: int):
    channel = _get_channel_or_404(session, channel_id)
    return _render_form(request, session, ChannelForm.from_channel(channel), channel=channel)


@router.post("/channels/{channel_id}/edit", response_class=HTMLResponse, name="channel_update")
def channel_update(
    request: Request,
    session: SessionDep,
    client: EngineDep,
    settings: SettingsDep,
    channel_id: int,
    title: FormField = "",
    link: FormField = "",
    category_id: FormField = "",
    new_category: FormField = "",
    language: FormField = "",
    country: FormField = "",
    resolution: FormField = "",
):
    channel = _get_channel_or_404(session, channel_id)
    form = ChannelForm(title, link, category_id, new_category, language, country, resolution)
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
            category_id=resolve_category(session, data.category_id, data.new_category),
            language=data.language,
            country=data.country,
            resolution=data.resolution,
            settings=settings.verification(),
            capture=settings.capture(),
        )
    except ServiceError as exc:
        return _render_form(
            request, session, form, channel=channel, error=f"No se pudo guardar: {exc}"
        )
    return _redirect(request, "channel_detail", channel_id=channel_id)


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
    return _redirect(request, "channel_list")
