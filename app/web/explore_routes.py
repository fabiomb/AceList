from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.models import Category
from app.services import categories, sources
from app.services.catalog import Screenshots
from app.services.errors import DuplicateError, NotFoundError, ServiceError, ValidationError
from app.services.sources import ExploreQuery, SourceFetchError
from app.web.check_routes import start_checks
from app.web.deps import (
    CheckRunnerDep,
    EngineFactoryDep,
    EngineProbeDep,
    SessionDep,
    SessionFactoryDep,
    SettingsDep,
)
from app.web.forms import resolve_category
from app.web.templating import templates

router = APIRouter(prefix="/explore")

FormField = Annotated[str, Form()]


def _explore_query(request: Request) -> ExploreQuery:
    params = request.query_params
    source = params.get("source", "")
    return ExploreQuery(
        text=params.get("q", "").strip() or None,
        source_id=int(source) if source.isdigit() else None,
        only_new=params.get("new") == "1",
    )


def _render_explore(
    request: Request,
    session: Session,
    query: ExploreQuery,
    *,
    result=None,
    engine_down: bool = False,
    error: str | None = None,
) -> HTMLResponse:
    all_sources = sources.list_sources(session)
    response = templates.TemplateResponse(
        request,
        "explore/index.html",
        {
            "query": query,
            "found": sources.explore(session, query, limit=sources.EXPLORE_LIMIT),
            "sources": all_sources,
            "has_enabled": any(source.enabled for source in all_sources),
            "categories": categories.list_categories(session),
            "limit": sources.EXPLORE_LIMIT,
            "result": result,
            "engine_down": engine_down,
            "error": error,
        },
        status_code=422 if error else 200,
    )
    if request.method == "POST":
        # Keeps /explore and its search in the address bar: reloading /explore/add would be
        # a GET it lacks.
        response.headers["HX-Push-Url"] = _explore_url(request, query)
    return response


def _explore_url(request: Request, query: ExploreQuery) -> str:
    params = {
        "q": query.text or "",
        "source": "" if query.source_id is None else str(query.source_id),
        "new": "1" if query.only_new else "",
    }
    url = request.url_for("explore")
    return str(url.include_query_params(**{k: v for k, v in params.items() if v}))


@router.get("", response_class=HTMLResponse, name="explore")
def explore(request: Request, session: SessionDep):
    return _render_explore(request, session, _explore_query(request))


@router.post("/add", response_class=HTMLResponse, name="explore_add")
def explore_add(
    request: Request,
    session: SessionDep,
    session_factory: SessionFactoryDep,
    engine_factory: EngineFactoryDep,
    settings: SettingsDep,
    runner: CheckRunnerDep,
    probe: EngineProbeDep,
    entry: Annotated[list[int] | None, Form()] = None,
    category_id: FormField = "",
    new_category: FormField = "",
    q: FormField = "",
    source: FormField = "",
    new: FormField = "",
):
    # The page comes back with the search the user was looking at.
    query = ExploreQuery(
        text=q.strip() or None,
        source_id=int(source) if source.isdigit() else None,
        only_new=new == "1",
    )
    if not entry:
        return _render_explore(request, session, query, error="Elige al menos un canal.")
    chosen = int(category_id) if category_id.isdigit() else None
    if new_category.strip():
        chosen = None  # the typed name wins, as in the import form
    elif category_id and (chosen is None or session.get(Category, chosen) is None):
        return _render_explore(request, session, query, error="La categoría elegida no existe.")
    try:
        result = sources.add_entries(
            session,
            entry,
            category_id=resolve_category(session, chosen, new_category.strip() or None),
        )
    except ServiceError as exc:
        return _render_explore(request, session, query, error=f"No se pudo agregar: {exc}")

    created = [channel.id for channel in result.created]
    if created and probe() is None:
        # The channels stay; only their checks wait for the engine.
        return _render_explore(request, session, query, result=result, engine_down=True)
    start_checks(
        runner,
        created,
        session_factory,
        engine_factory,
        settings,
        screenshots=Screenshots.IF_MISSING,
    )
    return _render_explore(request, session, query, result=result)


def _render_sources(
    request: Request, session: Session, *, values=None, errors=None
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "explore/sources.html",
        {
            "sources": sources.list_sources(session),
            "values": values or {},
            "errors": errors or {},
        },
        status_code=422 if errors else 200,
    )


def _to_sources(request: Request) -> RedirectResponse:
    # 303 turns the POST into a GET, so reloading the page never resubmits the form.
    return RedirectResponse(request.url_for("sources_page"), status_code=303)


def _source_or_404(session: Session, source_id: int):
    try:
        return sources.get_source(session, source_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Fuente no encontrada") from exc


@router.get("/sources", response_class=HTMLResponse, name="sources_page")
def sources_page(request: Request, session: SessionDep):
    return _render_sources(request, session)


@router.post("/sources", response_class=HTMLResponse, name="source_create")
def source_create(
    request: Request,
    session: SessionDep,
    name: FormField = "",
    url: FormField = "",
    file: Annotated[UploadFile | None, File()] = None,
):
    values = {"name": name, "url": url}
    if file is not None and file.filename:
        return _create_file_source(request, session, values, file)
    try:
        source = sources.create_source(session, name=name, url=url)
    except ValidationError as exc:
        field = "name" if str(exc).startswith("name") else "url"
        message = {
            "name": "Ponle un nombre (hasta 100 caracteres).",
            "url": "Escribe una dirección http:// o https://, o elige un archivo.",
        }[field]
        return _render_sources(request, session, values=values, errors={field: message})
    except DuplicateError:
        return _render_sources(
            request, session, values=values, errors={"name": "Ya hay una fuente con ese nombre."}
        )
    # A new source is read right away, so the user sees at once whether it works.
    with sources.make_client() as client:
        sources.refresh_source(session, source, client)
    return _to_sources(request)


def _create_file_source(request: Request, session: Session, values: dict, file: UploadFile):
    # One byte over the limit is enough to tell the file is too big.
    data = file.file.read(sources.MAX_SOURCE_BYTES + 1)
    try:
        sources.add_file_source(session, name=values["name"], filename=file.filename, data=data)
    except ValidationError:
        errors = {"name": "Ponle un nombre (hasta 100 caracteres)."}
    except DuplicateError:
        errors = {"name": "Ya hay una fuente web con ese nombre; elige otro."}
    except SourceFetchError as exc:
        errors = {"file": str(exc)}
    else:
        return _to_sources(request)
    return _render_sources(request, session, values=values, errors=errors)


@router.post("/sources/refresh", name="sources_refresh")
def sources_refresh(request: Request, session: SessionDep):
    with sources.make_client() as client:
        sources.refresh_sources(session, client)
    return _to_sources(request)


@router.post("/sources/{source_id}/refresh", name="source_refresh")
def source_refresh(request: Request, session: SessionDep, source_id: int):
    source = _source_or_404(session, source_id)
    with sources.make_client() as client:
        sources.refresh_source(session, source, client)
    return _to_sources(request)


@router.post("/sources/{source_id}/toggle", name="source_toggle")
def source_toggle(request: Request, session: SessionDep, source_id: int):
    source = _source_or_404(session, source_id)
    sources.set_enabled(session, source_id, not source.enabled)
    return _to_sources(request)


@router.post("/sources/{source_id}/delete", name="source_delete")
def source_delete(request: Request, session: SessionDep, source_id: int):
    _source_or_404(session, source_id)
    sources.delete_source(session, source_id)
    return _to_sources(request)
