from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from app.db.models import Category
from app.services import categories, exchange, importer
from app.services.catalog import Screenshots
from app.services.errors import ServiceError, ValidationError
from app.services.iso import normalize_country, normalize_language
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

router = APIRouter(prefix="/import")

FormField = Annotated[str, Form()]

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _render(
    request: Request, session, values: dict, *, errors=None, result=None, engine_down=False
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "import.html",
        {
            "values": values,
            "errors": errors or {},
            "result": result,
            "engine_down": engine_down,
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
    probe: EngineProbeDep,
    links: FormField = "",
    category_id: FormField = "",
    new_category: FormField = "",
    language: FormField = "",
    country: FormField = "",
    file: Annotated[UploadFile | None, File()] = None,
):
    values = {
        "links": links,
        "category_id": category_id,
        "new_category": new_category,
        "language": language,
        "country": country,
    }
    errors = {}
    # A chosen file wins over the pasted text.
    text = links
    if file is not None and file.filename:
        text, file_error = _read_upload(file)
        if file_error:
            errors["file"] = file_error
    if "file" not in errors and not text.strip():
        errors["links"] = "Pega al menos un enlace o Content ID, o elige un archivo."
    elif not exchange.is_export(text) and len(text.splitlines()) > importer.MAX_LINES:
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

    # An AceList export brings each channel's data; anything else is a list of links.
    run_import = exchange.import_export if exchange.is_export(text) else importer.import_links
    try:
        result = run_import(
            session,
            text,
            category_id=resolve_category(session, chosen, new_category.strip() or None),
            language=language,
            country=country,
        )
    except ServiceError as exc:
        return _render(request, session, values, errors={"links": f"No se pudo importar: {exc}"})

    # New channels are verified in the background; the progress panel shows how it goes.
    created = [channel.id for channel in result.created]
    if created and probe() is None:
        # The import stands; only the checks wait for the engine.
        return _render(request, session, {}, result=result, engine_down=True)
    # New channels have no screenshot yet: their first check takes one.
    start_checks(
        runner,
        created,
        session_factory,
        engine_factory,
        settings,
        screenshots=Screenshots.IF_MISSING,
    )
    # The form comes back empty, ready for the next list; the summary stays below.
    return _render(request, session, {}, result=result)


def _read_upload(file: UploadFile) -> tuple[str, str | None]:
    """The uploaded file as text, or an error in Spanish."""
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        return "", f"El archivo supera los {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
    try:
        return data.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        return "", "El archivo no es texto en UTF-8."
