from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import DATA_DIR
from app.db.session import make_engine, make_session_factory
from app.services.screenshots import SCREENSHOTS_SUBDIR
from app.web.routes import STATIC_DIR, router

HOST = "127.0.0.1"
PORT = 8000
# Requests naming any other host are refused, so a web page cannot reach the app
# through DNS rebinding even though it listens on loopback.
ALLOWED_HOSTS = [HOST, "localhost"]


class OptionalStaticFiles(StaticFiles):
    """Static files from a folder that may not exist yet: missing files are a 404."""

    async def check_config(self) -> None:
        if Path(self.directory).is_dir():
            await super().check_config()


app = FastAPI(title="AceList")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
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
