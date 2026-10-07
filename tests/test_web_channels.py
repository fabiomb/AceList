from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.models import CheckStatus
from app.db.session import make_engine, make_session_factory
from app.main import app
from app.services import categories, channels, checks
from app.web.routes import get_session

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"


@pytest.fixture
def session_factory(tmp_path):
    # A file database: the test client runs endpoints in other threads.
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def session(session_factory):
    with session_factory() as s:
        yield s


@pytest.fixture
def client(session_factory):
    def _session():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    yield TestClient(app, base_url="http://127.0.0.1")
    app.dependency_overrides.clear()


def test_empty_catalog_shows_empty_state(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Todavía no hay canales" in response.text
    assert "<table" not in response.text


def test_base_layout_loads_local_htmx_and_styles(client):
    page = client.get("/").text

    assert "/static/htmx.min.js" in page
    assert "/static/style.css" in page
    assert client.get("/static/htmx.min.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_list_shows_every_column(client, session):
    sports = categories.create_category(session, "Sports")
    channel = channels.create_channel(
        session,
        title="Canal Uno",
        content_id=HASH_A,
        category_id=sports.id,
        language="es",
        country="AR",
    )
    checks.add_check(
        session,
        channel.id,
        status=CheckStatus.ALIVE,
        peers=12,
        screenshot_path=f"screenshots/{HASH_A}_20261007T120000Z_abcd1234.jpg",
        checked_at=datetime(2026, 10, 7, 12, 0, tzinfo=UTC),
    )

    page = client.get("/").text

    assert "Canal Uno" in page
    assert f'title="{HASH_A}"' in page
    assert "78266c15…34ab" in page
    assert "Sports" in page
    assert 'title="Spanish"' in page and ">es<" in page
    assert 'title="Argentina"' in page and ">AR<" in page
    assert "status-alive" in page and "Activo" in page
    assert ">12<" in page
    local = datetime(2026, 10, 7, 12, 0, tzinfo=UTC).astimezone().strftime("%Y-%m-%d %H:%M")
    assert local in page
    assert f'src="/screenshots/{HASH_A}_20261007T120000Z_abcd1234.jpg"' in page
    assert "Todavía no hay canales" not in page


def test_unchecked_channel_has_placeholders(client, session):
    channels.create_channel(session, title="Nuevo", content_id=HASH_A)

    page = client.get("/").text

    assert "Sin verificar" in page
    assert "Nunca" in page
    assert "<img" not in page


def test_status_comes_from_the_latest_check(client, session):
    channel = channels.create_channel(session, title="Uno", content_id=HASH_A)
    now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    checks.add_check(
        session, channel.id, status=CheckStatus.ALIVE, peers=30, checked_at=now - timedelta(days=1)
    )
    checks.add_check(
        session,
        channel.id,
        status=CheckStatus.NOT_FOUND,
        error_message="engine said no",
        checked_at=now,
    )

    page = client.get("/").text

    assert "No encontrado" in page
    assert 'title="engine said no"' in page
    assert "Activo" not in page
    assert ">30<" not in page


def test_channels_are_listed_by_title(client, session):
    channels.create_channel(session, title="Zeta", content_id=HASH_A)
    channels.create_channel(session, title="Alfa", content_id=HASH_B)

    page = client.get("/").text

    assert page.index("Alfa") < page.index("Zeta")


def test_titles_are_escaped(client, session):
    channels.create_channel(session, title="<script>alert(1)</script>", content_id=HASH_A)

    page = client.get("/").text

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


@pytest.mark.parametrize(
    "stored",
    ["../acelist.db", "screenshots/../acelist.db", "other/frame.jpg", "screenshots/"],
)
def test_screenshot_outside_the_folder_is_not_linked(client, session, stored):
    channel = channels.create_channel(session, title="Uno", content_id=HASH_A)
    checks.add_check(session, channel.id, status=CheckStatus.ALIVE, screenshot_path=stored)

    page = client.get("/").text

    assert "<img" not in page


def test_missing_screenshot_is_not_found(client):
    assert client.get("/screenshots/missing.jpg").status_code == 404


def test_requests_for_other_hosts_are_rejected():
    response = TestClient(app, base_url="http://attacker.example").get("/")

    assert response.status_code == 400


def test_localhost_name_is_accepted(client):
    assert client.get("http://localhost/health").status_code == 200
