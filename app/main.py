from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.config import DATA_DIR
from app.db.session import make_engine, make_session_factory
from app.services.screenshots import SCREENSHOTS_SUBDIR
from app.web.routes import router
from app.web.templating import STATIC_DIR

HOST = "127.0.0.1"
PORT = 8000
# Requests naming any other host are refused, so a web page cannot reach the app
# through DNS rebinding even though it listens on loopback.
ALLOWED_HOSTS = [HOST, "localhost"]
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class OptionalStaticFiles(StaticFiles):
    """Static files from a folder that may not exist yet: missing files are a 404."""

    async def check_config(self) -> None:
        if Path(self.directory).is_dir():
            await super().check_config()


app = FastAPI(title="AceList")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


@app.middleware("http")
async def reject_cross_site_writes(request: Request, call_next):
    # The Host check does not stop another site from posting a form to the app (CSRF),
    # so writes must come from the app's own pages.
    if request.method not in _SAFE_METHODS:
        origin = request.headers.get("origin")
        cross_site = request.headers.get("sec-fetch-site") == "cross-site"
        if cross_site or (origin and urlsplit(origin).hostname not in ALLOWED_HOSTS):
            return PlainTextResponse("cross-site request rejected", status_code=403)
    return await call_next(request)


app.state.session_factory = make_session_factory(make_engine())

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
# Only the screenshots folder is served, never the rest of the data directory.
# It does not exist until the first capture.
app.mount(
    "/screenshots",
    OptionalStaticFiles(directory=DATA_DIR / SCREENSHOTS_SUBDIR, check_dir=False),
    name="screenshots",
)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def run() -> None:
    # Bound to loopback only: the app is for local use.
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    run()
