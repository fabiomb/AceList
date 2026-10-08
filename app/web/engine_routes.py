from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web.deps import EngineProbeDep, SettingsDep
from app.web.templating import templates

router = APIRouter(prefix="/engine")


@router.get("/status", response_class=HTMLResponse, name="engine_status")
def engine_status(request: Request, probe: EngineProbeDep, settings: SettingsDep):
    """The top bar indicator; it polls itself, so pages never wait for the engine."""
    return templates.TemplateResponse(
        request,
        "_engine_status.html",
        {"engine_checked": True, "engine_version": probe(), "engine_url": settings.engine_url},
    )
