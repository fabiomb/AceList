import os
import struct
import tempfile

# Set before the app is imported: a test that forgets to simulate the engine must fail,
# never reach a real engine running on the developer's machine, and nothing may be
# written to the repository's data directory.
os.environ["ACELIST_ENGINE_URL"] = "http://engine.invalid:6878"
os.environ["ACELIST_DATA_DIR"] = tempfile.mkdtemp(prefix="acelist-tests-")

import httpx
import pytest
from fastapi.testclient import TestClient

from app.acestream.client import EngineClient
from app.db.base import Base
from app.db.session import make_engine, make_session_factory
from app.main import app
from app.services.batch import CheckRunner
from app.web.deps import get_engine_factory, get_session_factory


@pytest.fixture
def db_factory(tmp_path):
    # A file database: the web test client runs endpoints in other threads.
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def db(db_factory):
    with db_factory() as s:
        yield s


@pytest.fixture
def web(db_factory):
    """Test client for the web UI, backed by `db_factory`, with its own check runner."""
    app.dependency_overrides[get_session_factory] = lambda: db_factory
    previous_runner = app.state.check_runner
    app.state.check_runner = CheckRunner()
    yield TestClient(app, base_url="http://127.0.0.1")
    app.state.check_runner.shutdown()
    app.state.check_runner = previous_runner
    app.dependency_overrides.clear()


@pytest.fixture
def engine_down(web, respx_mock):
    """The web app's engine, unreachable: channels are saved but never checked."""
    base = "http://engine.test"

    app.dependency_overrides[get_engine_factory] = lambda: lambda: EngineClient(base, timeout=1)
    return respx_mock.route(url__startswith=base).mock(side_effect=httpx.ConnectError("down"))


@pytest.fixture
def wait_for_checks(web):
    """Call it to block until the web app's background checks finish."""

    def wait(timeout: float = 10) -> None:
        batch = app.state.check_runner.current()
        assert batch is not None, "no checks were started"
        assert batch.finished_event.wait(timeout), "background checks did not finish"

    return wait


def _jpeg(width: int, height: int, *, sof: int = 0xC0, extra_segments: bool = True) -> bytes:
    """SOI, optional APP0 and DHT segments, a SOF with the size, and EOI."""
    parts = [b"\xff\xd8"]
    if extra_segments:
        app0 = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        parts.append(b"\xff\xe0" + struct.pack(">H", len(app0) + 2) + app0)
        dht = b"\x00" + b"\x00" * 16  # an empty Huffman table
        parts.append(b"\xff\xc4" + struct.pack(">H", len(dht) + 2) + dht)
    body = struct.pack(">BHHB", 8, height, width, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    parts.append(bytes([0xFF, sof]) + struct.pack(">H", len(body) + 2) + body)
    parts.append(b"\xff\xd9")
    return b"".join(parts)


@pytest.fixture
def make_jpeg():
    """Builds JPEG headers by hand, so tests need no image library and no ffmpeg."""
    return _jpeg


@pytest.fixture
def engine_empty(web, respx_mock):
    """The web app's engine, running but unable to load anything: every check is `not_found`."""
    base = "http://engine-empty.test"
    app.dependency_overrides[get_engine_factory] = lambda: lambda: EngineClient(base, timeout=1)
    respx_mock.get(f"{base}/server/api").respond(
        json={"error": {"message": "cannot get transport file", "code": 0}}
    )
    return respx_mock.get(f"{base}/ace/getstream").respond(
        json={"response": None, "error": "failed to load content"}
    )
