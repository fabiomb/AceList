from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.db.models import Category
from app.services import categories, importer
from app.services.errors import ServiceError, ValidationError
from app.services.iso import normalize_country, normalize_language
from app.web.check_routes import start_checks
from app.web.deps import (
    CheckRunnerDep,
    EngineFactoryDep,
    SessionDep,
    SessionFactoryDep,
    SettingsDep,
)
from app.web.forms import resolve_category
from app.web.templating import templates

router = APIRouter(prefix="/import")

FormField = Annotated[str, Form()]


def _render(request: Request, session, values: dict, *, errors=None, result=None) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "import.html",
        {
            "values": values,
            "errors": errors or {},
            "result": result,
            "categories": categories.list_categories(session),
            "max_lines": importer.MAX_LINES,
        },
        status_code=422 if errors else 200,
    )


@router.get("", response_class=HTMLResponse, name="import_page")
def import_page(request: Request, session: SessionDep):
    return _render(request, session, {})


@router.post("", response_class=HTMLResponse, name="import_run")
def import_run(
    request: Request,
    session: SessionDep,
    session_factory: SessionFactoryDep,
    engine_factory: EngineFactoryDep,
    settings: SettingsDep,
    runner: CheckRunnerDep,
    links: FormField = "",
    category_id: FormField = "",
    new_category: FormField = "",
    language: FormField = "",
    country: FormField = "",
):
    values = {
        "links": links,
        "category_id": category_id,
        "new_category": new_category,
        "language": language,
        "country": country,
    }
    errors = {}
    if not links.strip():
        errors["links"] = "Pega al menos un enlace o Content ID."
    elif len(links.splitlines()) > importer.MAX_LINES:
        errors["links"] = f"Como máximo {importer.MAX_LINES} líneas por importación."
    chosen = int(category_id) if category_id.isdigit() else None
    if new_category.strip():
        chosen = None  # the typed name wins, as in the channel form
    elif category_id and (chosen is None or session.get(Category, chosen) is None):
        errors["category_id"] = "La categoría elegida no existe."
    for name, normalize in (("language", normalize_language), ("country", normalize_country)):
        try:
            normalize(values[name])
        except ValidationError:
            errors[name] = "Código desconocido."
    if errors:
        return _render(request, session, values, errors=errors)

    try:
        result = importer.import_links(
            session,
            links,
            category_id=resolve_category(session, chosen, new_category.strip() or None),
            language=language,
            country=country,
        )
    except ServiceError as exc:
        return _render(request, session, values, errors={"links": f"No se pudo importar: {exc}"})

    # New channels are verified in the background; the progress panel shows how it goes.
    created = [channel.id for channel in result.created]
    start_checks(runner, created, session_factory, engine_factory, settings)
    # The form comes back empty, ready for the next list; the summary stays below.
    return _render(request, session, {}, result=result)
