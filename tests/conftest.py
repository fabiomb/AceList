import pytest
from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import make_engine, make_session_factory
from app.main import app
from app.web.deps import get_session


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
    """Test client for the web UI, backed by `db_factory`."""

    def _session():
        with db_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    yield TestClient(app, base_url="http://127.0.0.1")
    app.dependency_overrides.clear()
