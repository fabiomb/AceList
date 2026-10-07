from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import CheckStatus
from app.services import catalog, listing
from app.services.batch import CheckRunner, CheckWork
from app.services.settings import AppSettings
from app.web.deps import (
    CheckRunnerDep,
    EngineFactory,
    EngineFactoryDep,
    SessionDep,
    SessionFactoryDep,
    SettingsDep,
)
from app.web.query import parse_query
from app.web.templating import templates

router = APIRouter(prefix="/checks")


def check_work(
    session_factory: sessionmaker[Session], engine_factory: EngineFactory, settings: AppSettings
) -> CheckWork:
    """One background check: its own session and engine client, as it runs in another thread."""

    def work(channel_id: int) -> CheckStatus:
        with session_factory() as session, engine_factory() as client:
            check = catalog.check_channel(
                session,
                client,
                channel_id,
                settings=settings.verification(),
                capture=settings.capture(),
            )
            return check.status

    return work


def start_checks(
    runner: CheckRunner,
    channel_ids: list[int],
    session_factory: sessionmaker[Session],
    engine_factory: EngineFactory,
    settings: AppSettings,
) -> None:
    work = check_work(session_factory, engine_factory, settings)
    runner.submit(channel_ids, work, max_workers=settings.check_concurrency)


@router.post("", name="checks_start")
def checks_start(
    request: Request,
    session: SessionDep,
    session_factory: SessionFactoryDep,
    engine_factory: EngineFactoryDep,
    settings: SettingsDep,
    runner: CheckRunnerDep,
):
    """Checks every channel the list shows with the filters in the query string."""
    query = parse_query(request.query_params)
    ids = [channel.id for channel, _ in listing.search_channels(session, query)]
    start_checks(runner, ids, session_factory, engine_factory, settings)
    url = request.url_for("channel_list").include_query_params(**request.query_params)
    # 303 turns the POST into a GET, so reloading the list never starts the checks again.
    return RedirectResponse(url, status_code=303)


@router.get("/status", response_class=HTMLResponse, name="checks_status")
def checks_status(request: Request, runner: CheckRunnerDep, watching: str = ""):
    """The progress panel, polled while a batch runs."""
    batch = runner.current()
    response = templates.TemplateResponse(request, "_batch_status.html", {"batch": batch})
    if batch is not None and batch.finished and batch.id == watching:
        # The page that watched the batch shows stale states: reload it once.
        response.headers["HX-Refresh"] = "true"
    return response


@router.post("/dismiss", response_class=HTMLResponse, name="checks_dismiss")
def checks_dismiss(request: Request, runner: CheckRunnerDep):
    runner.dismiss()
    return templates.TemplateResponse(request, "_batch_status.html", {"batch": runner.current()})
