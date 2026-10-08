import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.acestream import install
from app.acestream.client import EngineVersion
from app.services.settings import AppSettings
from app.web.deps import EngineProbe, EngineProbeDep, SettingsDep
from app.web.templating import templates

router = APIRouter(prefix="/engine")

# The engine takes a few seconds to answer after launching; this is the most we wait.
START_TIMEOUT = 30.0
POLL_INTERVAL = 1.0


def engine_executable(settings: AppSettings) -> str | None:
    """The engine to launch: the one in the settings, else the installed one."""
    configured = settings.acestream_path
    if configured and Path(configured).is_file():
        return configured
    return install.find_engine_executable()


def _indicator(
    request: Request,
    settings: AppSettings,
    version: EngineVersion | None,
    *,
    error: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "_engine_status.html",
        {
            "engine_checked": True,
            "engine_version": version,
            "engine_url": settings.engine_url,
            "engine_can_start": version is None and engine_executable(settings) is not None,
            "engine_error": error,
        },
    )


@router.get("/status", response_class=HTMLResponse, name="engine_status")
def engine_status(request: Request, probe: EngineProbeDep, settings: SettingsDep):
    """The top bar indicator; it polls itself, so pages never wait for the engine."""
    return _indicator(request, settings, probe())


def _wait_until_up(probe: EngineProbe) -> EngineVersion | None:
    deadline = time.monotonic() + START_TIMEOUT
    while True:
        version = probe()
        if version is not None or time.monotonic() >= deadline:
            return version
        time.sleep(POLL_INTERVAL)


@router.post("/start", response_class=HTMLResponse, name="engine_start")
def engine_start(request: Request, probe: EngineProbeDep, settings: SettingsDep):
    """Launches the installed engine and waits until it answers (blocks a worker thread)."""
    version = probe()
    if version is not None:
        return _indicator(request, settings, version)  # already running
    executable = engine_executable(settings)
    if executable is None:
        error = "No se encontró ace_engine.exe: indica su ruta en Ajustes."
        return _indicator(request, settings, None, error=error)
    try:
        install.start_engine(executable)
    except install.EngineStartError as exc:
        return _indicator(request, settings, None, error=f"No se pudo iniciar: {exc}")
    version = _wait_until_up(probe)
    if version is None:
        error = f"Ace Stream no respondió en {START_TIMEOUT:g} s."
        return _indicator(request, settings, None, error=error)
    return _indicator(request, settings, version)
