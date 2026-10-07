from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.models import Channel, Check, CheckStatus
from app.services import catalog, categories, channels, listing
from app.services.errors import NotFoundError, ServiceError
from app.services.iso import country_name, language_name
from app.services.listing import DEFAULT_DESCENDING, UNCHECKED, ChannelQuery, SortKey
from app.services.screenshots import SCREENSHOTS_SUBDIR
from app.web.deps import EngineDep, SessionDep
from app.web.forms import ChannelForm, resolve_category
from app.web.templating import templates

router = APIRouter()

FormField = Annotated[str, Form()]

STATUS_FILTERS = [*(s.value for s in CheckStatus), UNCHECKED]


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


def _parse_query(params) -> ChannelQuery:
    """Reads filters and order from the URL; values that make no sense are ignored."""
    text = params.get("q", "").strip() or None
    category = params.get("category", "")
    language = params.get("language", "").strip().lower()
    country = params.get("country", "").strip().upper()
    status = params.get("status", "")
    try:
        sort = SortKey(params.get("sort", ""))
    except ValueError:
        sort = SortKey.TITLE
    direction = params.get("dir")
    return ChannelQuery(
        text=text,
        category_id=int(category) if category.isdigit() else None,
        language=language if language_name(language) else None,
        country=country if country_name(country) else None,
        status=status if status in STATUS_FILTERS else None,
        sort=sort,
        descending=direction == "desc"
        if direction in ("asc", "desc")
        else DEFAULT_DESCENDING[sort],
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
    query = _parse_query(request.query_params)
    rows = [
        ChannelRow(channel, check, _screenshot_url(request, check))
        for channel, check in listing.search_channels(session, query)
    ]
    filtered = any((query.text, query.category_id, query.language, query.country, query.status))
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
