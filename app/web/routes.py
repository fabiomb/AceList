import json
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.acestream.errors import ContentNotFoundError, EngineError
from app.db.base import utcnow
from app.db.models import Channel, Check
from app.services import catalog, categories, channels, checks, exchange, listing, player
from app.services.catalog import Screenshots
from app.services.errors import NotFoundError, ServiceError
from app.services.iso import country_name, language_name
from app.services.listing import DEFAULT_DESCENDING, ChannelQuery, SortKey
from app.services.screenshots import SCREENSHOTS_SUBDIR
from app.web.check_routes import start_checks
from app.web.deps import (
    CheckRunnerDep,
    EngineDep,
    EngineFactoryDep,
    EngineProbeDep,
    SessionDep,
    SessionFactoryDep,
    SettingsDep,
)
from app.web.flash import ENGINE_DOWN, ENGINE_DOWN_SAVED, flash
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
    return screenshot_url(request, check.screenshot_path if check else None)


def screenshot_url(request: Request, path: str | None) -> str | None:
    """URL of a stored screenshot path, or None if it is outside the screenshots folder."""
    if not path:
        return None
    folder, _, name = path.partition("/")
    # Only files directly under the screenshots folder are served.
    if folder != SCREENSHOTS_SUBDIR or not name or "/" in name:
        return None
    return request.app.url_path_for("screenshots", path=name)


def _get_channel_or_404(session: Session, channel_id: int) -> Channel:
    try:
        return channels.get_channel(session, channel_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Canal no encontrado") from exc


def _local_path(target: str) -> str | None:
    """`target` if it is a path within this app, so a form cannot redirect elsewhere."""
    parts = urlsplit(target)
    if (
        not target.startswith("/")
        or target.startswith("//")
        or "\\" in target
        or parts.scheme
        or parts.netloc
    ):
        return None
    return target


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


def _browse_context(request: Request, session: Session) -> dict:
    """What the list and the gallery share: rows for the URL's filters and the filter options."""
    query = parse_query(request.query_params)
    # The newest screenshot, which is usually older than the latest check.
    shots = checks.latest_screenshots(session)
    rows = [
        ChannelRow(channel, check, screenshot_url(request, shots.get(channel.id)))
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
    return {
        "rows": rows,
        "query": query,
        "filtered": filtered,
        # Distinguishes "nothing matches" from "nothing at all".
        "catalog_empty": not rows and not filtered,
        "categories": categories.list_categories(session),
        "languages": sorted(
            listing.used_languages(session), key=lambda code: language_name(code) or code
        ),
        "countries": sorted(
            listing.used_countries(session), key=lambda code: country_name(code) or code
        ),
    }


@router.get("/", response_class=HTMLResponse, name="channel_list")
def channel_list(request: Request, session: SessionDep):
    context = _browse_context(request, session)
    context["sort_links"] = _sort_links(request, context["query"])
    return templates.TemplateResponse(request, "channels/list.html", context)


# Enough to spot a channel while typing; the rest are one click away in the list.
SUGGEST_LIMIT = 8


@router.get("/search/suggest", response_class=HTMLResponse, name="channel_suggest")
def channel_suggest(request: Request, session: SessionDep, q: str = ""):
    """Matches for the top bar search box, as a dropdown loaded by htmx while typing."""
    text = q.strip()
    if not text:
        return HTMLResponse("")
    # Runs on every keystroke: only the rows shown, their screenshots and a count.
    query = ChannelQuery(text=text)
    matches = listing.search_channels(session, query, limit=SUGGEST_LIMIT)
    total = len(matches)
    if total == SUGGEST_LIMIT:
        total = listing.count_channels(session, query)
    shots = checks.latest_screenshots(session, [channel.id for channel, _ in matches])
    rows = [
        ChannelRow(channel, check, screenshot_url(request, shots.get(channel.id)))
        for channel, check in matches
    ]
    all_url = request.url_for("channel_list").include_query_params(q=text)
    return templates.TemplateResponse(
        request,
        "channels/_suggest.html",
        {"rows": rows, "total": total, "text": text, "all_url": all_url},
    )


@dataclass(frozen=True)
class GallerySection:
    title: str
    rows: list[ChannelRow]


def _gallery_sections(rows: list[ChannelRow]) -> list[GallerySection]:
    """One section per category, A-Z, then the uncategorized; rows keep the chosen order."""
    by_category: dict[str | None, list[ChannelRow]] = {}
    for row in rows:
        name = row.channel.category.name if row.channel.category else None
        by_category.setdefault(name, []).append(row)
    names = sorted((name for name in by_category if name is not None), key=str.casefold)
    sections = [GallerySection(name, by_category[name]) for name in names]
    if None in by_category:
        sections.append(GallerySection("Sin categoría", by_category[None]))
    return sections


@router.get("/export", name="channel_export")
def channel_export(request: Request, session: SessionDep):
    """The channels the list shows with the URL's filters, as an AceList export file."""
    query = parse_query(request.query_params)
    rows = [channel for channel, _ in listing.search_channels(session, query)]
    stamp = utcnow().astimezone().strftime("%Y%m%d-%H%M")
    body = json.dumps(exchange.export_channels(rows), ensure_ascii=False, indent=2)
    return Response(
        body,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="acelist-{stamp}.json"'},
    )


@router.get("/gallery", response_class=HTMLResponse, name="channel_gallery")
def channel_gallery(request: Request, session: SessionDep):
    context = _browse_context(request, session)
    context["sections"] = _gallery_sections(context["rows"])
    return templates.TemplateResponse(request, "channels/gallery.html", context)


@router.get("/channels/new", response_class=HTMLResponse, name="channel_new")
def channel_new(request: Request, session: SessionDep):
    return _render_form(request, session, ChannelForm())


@router.post("/channels/new", response_class=HTMLResponse, name="channel_create")
def channel_create(
    request: Request,
    session: SessionDep,
    client: EngineDep,
    probe: EngineProbeDep,
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
    engine_up = probe() is not None
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
            verify=engine_up,
        )
    except ServiceError as exc:
        return _render_form(request, session, form, error=f"No se pudo guardar: {exc}")
    response = _redirect(request, "channel_detail", channel_id=channel.id)
    return response if engine_up else flash(response, ENGINE_DOWN_SAVED)


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
    probe: EngineProbeDep,
    channel_id: int,
    next: FormField = "",
):
    """Checks one channel; `next` is the page to go back to (the list), else its detail."""
    _get_channel_or_404(session, channel_id)
    target = _local_path(next)
    if target is None:
        response = _redirect(request, "channel_detail", channel_id=channel_id)
    else:
        response = RedirectResponse(target, status_code=303)
    if probe() is None:
        return flash(response, ENGINE_DOWN)
    # In the background: the page shows the progress and reloads when it is done.
    start_checks(runner, [channel_id], session_factory, engine_factory, settings)
    return response


@router.post("/channels/{channel_id}/screenshot", name="channel_screenshot")
def channel_screenshot(
    request: Request,
    session: SessionDep,
    session_factory: SessionFactoryDep,
    engine_factory: EngineFactoryDep,
    settings: SettingsDep,
    runner: CheckRunnerDep,
    probe: EngineProbeDep,
    channel_id: int,
):
    _get_channel_or_404(session, channel_id)
    response = _redirect(request, "channel_detail", channel_id=channel_id)
    if probe() is None:
        return flash(response, ENGINE_DOWN)
    start_checks(
        runner,
        [channel_id],
        session_factory,
        engine_factory,
        settings,
        screenshots=Screenshots.ALWAYS,
    )
    return response


@router.post("/channels/{channel_id}/play", response_class=HTMLResponse, name="channel_play")
def channel_play(
    request: Request, session: SessionDep, client: EngineDep, settings: SettingsDep, channel_id: int
):
    channel = _get_channel_or_404(session, channel_id)
    try:
        stream = player.open_in_player(
            client,
            channel.content_id,
            kind=channel.id_kind,
            title=channel.title,
            vlc_path=settings.vlc_path,
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
        if channel.id_kind != stream.kind:
            channel.id_kind = stream.kind  # next time, straight the right way
            session.commit()
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
    probe: EngineProbeDep,
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
    # Only a new Content ID needs the engine.
    engine_up = data.content_id == channel.content_id or probe() is not None
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
            verify=engine_up,
        )
    except ServiceError as exc:
        return _render_form(
            request, session, form, channel=channel, error=f"No se pudo guardar: {exc}"
        )
    response = _redirect(request, "channel_detail", channel_id=channel_id)
    return response if engine_up else flash(response, ENGINE_DOWN_SAVED)


# What the selection bar of the list can do with the chosen channels.
SELECTION_ACTIONS = {"check", "screenshots", "delete"}


@router.post("/channels/selected", name="channels_selected")
def channels_selected(
    request: Request,
    session: SessionDep,
    session_factory: SessionFactoryDep,
    engine_factory: EngineFactoryDep,
    settings: SettingsDep,
    runner: CheckRunnerDep,
    probe: EngineProbeDep,
    channel: Annotated[list[int] | None, Form()] = None,
    action: FormField = "",
    next: FormField = "",
):
    """Checks, rechecks with new screenshots or deletes the channels chosen in the list.

    Comes back to `next` (the list with its filters) when it is a path of this app.
    """
    if action not in SELECTION_ACTIONS:
        raise HTTPException(status_code=400, detail="Acción desconocida")
    response = RedirectResponse(
        _local_path(next) or request.url_for("channel_list"), status_code=303
    )
    # Channels deleted meanwhile (another tab) are skipped, not an error.
    ids = [i for i in dict.fromkeys(channel or []) if session.get(Channel, i) is not None]
    if not ids:
        return response
    if action == "delete":
        for channel_id in ids:
            channels.delete_channel(session, channel_id)
        return response
    if probe() is None:
        return flash(response, ENGINE_DOWN)
    mode = Screenshots.ALWAYS if action == "screenshots" else Screenshots.NEVER
    start_checks(runner, ids, session_factory, engine_factory, settings, screenshots=mode)
    return response


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
