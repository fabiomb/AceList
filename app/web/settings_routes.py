from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.acestream.client import EngineClient
from app.acestream.errors import EngineError
from app.acestream.install import find_engine_executable
from app.services import player, screenshots
from app.services.settings import save_settings
from app.web.deps import SessionDep, SettingsDep
from app.web.forms import SettingsForm
from app.web.templating import templates

router = APIRouter(prefix="/settings")

FormField = Annotated[str, Form()]


def _posted_form(
    engine_url: FormField = "",
    engine_timeout: FormField = "",
    min_peers: FormField = "",
    check_timeout: FormField = "",
    screenshot_timeout: FormField = "",
    vlc_path: FormField = "",
    ffmpeg_path: FormField = "",
    acestream_path: FormField = "",
) -> SettingsForm:
    return SettingsForm(
        engine_url,
        engine_timeout,
        min_peers,
        check_timeout,
        screenshot_timeout,
        vlc_path,
        ffmpeg_path,
        acestream_path,
    )


PostedForm = Annotated[SettingsForm, Depends(_posted_form)]


def detect_paths() -> dict[str, str | None]:
    """What autodetection finds, ignoring saved settings and environment variables."""
    return {
        "vlc_path": player.find_vlc(None),
        "ffmpeg_path": screenshots.find_ffmpeg(None),
        "acestream_path": find_engine_executable(),
    }


def _render(request: Request, form: SettingsForm, *, notice: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"form": form, "detected": detect_paths(), "notice": notice},
        # 422 marks a rejected form; htmx is configured to show it (see base.html).
        status_code=422 if form.errors else 200,
    )


@router.get("", response_class=HTMLResponse, name="settings")
def settings_page(request: Request, settings: SettingsDep, saved: bool = False):
    notice = "Ajustes guardados." if saved else None
    return _render(request, SettingsForm.from_settings(settings), notice=notice)


@router.post("", response_class=HTMLResponse, name="settings_save")
def settings_save(request: Request, session: SessionDep, form: PostedForm):
    settings = form.validate()
    if settings is None:
        return _render(request, form)
    save_settings(session, settings)
    # 303 turns the POST into a GET, so reloading the page never resubmits the form.
    url = request.url_for("settings").include_query_params(saved="true")
    return RedirectResponse(url, status_code=303)


@router.post("/detect", response_class=HTMLResponse, name="settings_detect")
def settings_detect(request: Request, form: PostedForm):
    """Fills the empty path fields with what is found; nothing is saved yet."""
    found = []
    for name, path in detect_paths().items():
        if path and not getattr(form, name).strip():
            setattr(form, name, path)
            found.append(name)
    if found:
        notice = "Rutas detectadas. Revisa y pulsa «Guardar» para aplicarlas."
    else:
        notice = "No se detectaron rutas nuevas."
    response = _render(request, form, notice=notice)
    # Keeps /settings in the address bar: reloading /settings/detect would be a GET it lacks.
    response.headers["HX-Push-Url"] = str(request.url_for("settings"))
    return response


@router.post("/test-engine", response_class=HTMLResponse, name="settings_test_engine")
def settings_test_engine(request: Request, form: PostedForm):
    """Tries the engine URL and timeout as typed, before saving them."""
    form.validate()
    problem = form.errors.get("engine_url") or form.errors.get("engine_timeout")
    version = None
    if problem is None:
        url = form.engine_url.strip().rstrip("/")
        timeout = float(form.engine_timeout.strip().replace(",", "."))
        try:
            with EngineClient(url, timeout=timeout) as client:
                version = client.version()
        except EngineError as exc:
            problem = f"El engine no responde en {url}: {exc}"
    return templates.TemplateResponse(
        request,
        "_engine_test.html",
        {"version": version, "problem": problem},
        status_code=503 if problem else 200,
    )
