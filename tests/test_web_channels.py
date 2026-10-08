from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.models import CheckStatus
from app.main import app
from app.services import categories, channels, checks
from app.web.templating import _ago

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"


def test_empty_catalog_shows_empty_state(web):
    response = web.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Todavía no hay canales" in response.text
    assert "<table" not in response.text


def test_base_layout_loads_local_htmx_and_styles(web):
    page = web.get("/").text

    assert "/static/htmx.min.js" in page
    assert "/static/style.css" in page
    assert web.get("/static/htmx.min.js").status_code == 200
    assert web.get("/static/style.css").status_code == 200


def test_list_shows_every_column(web, db):
    sports = categories.create_category(db, "Sports")
    channel = channels.create_channel(
        db,
        title="Canal Uno",
        content_id=HASH_A,
        category_id=sports.id,
        language="es",
        country="AR",
    )
    checks.add_check(
        db,
        channel.id,
        status=CheckStatus.ALIVE,
        peers=12,
        screenshot_path=f"screenshots/{HASH_A}_20261007T120000Z_abcd1234.jpg",
        checked_at=datetime(2026, 10, 7, 12, 0, tzinfo=UTC),
    )

    page = web.get("/").text

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


def test_unchecked_channel_has_placeholders(web, db):
    channels.create_channel(db, title="Nuevo", content_id=HASH_A)

    page = web.get("/").text

    assert "Sin verificar" in page
    assert "Nunca" in page
    assert "<img" not in page


def test_status_comes_from_the_latest_check(web, db):
    channel = channels.create_channel(db, title="Uno", content_id=HASH_A)
    now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    checks.add_check(
        db, channel.id, status=CheckStatus.ALIVE, peers=30, checked_at=now - timedelta(days=1)
    )
    checks.add_check(
        db,
        channel.id,
        status=CheckStatus.NOT_FOUND,
        error_message="engine said no",
        checked_at=now,
    )

    page = web.get("/").text

    assert "No encontrado" in page
    assert 'title="engine said no"' in page
    assert "status-alive" not in page
    assert ">30<" not in page


def test_channels_are_listed_by_title(web, db):
    channels.create_channel(db, title="Zeta", content_id=HASH_A)
    channels.create_channel(db, title="Alfa", content_id=HASH_B)

    page = web.get("/").text

    assert page.index("Alfa") < page.index("Zeta")


def test_titles_are_escaped(web, db):
    channels.create_channel(db, title="<script>alert(1)</script>", content_id=HASH_A)

    page = web.get("/").text

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


@pytest.mark.parametrize(
    "stored",
    ["../acelist.db", "screenshots/../acelist.db", "other/frame.jpg", "screenshots/"],
)
def test_screenshot_outside_the_folder_is_not_linked(web, db, stored):
    channel = channels.create_channel(db, title="Uno", content_id=HASH_A)
    checks.add_check(db, channel.id, status=CheckStatus.ALIVE, screenshot_path=stored)

    page = web.get("/").text

    assert "<img" not in page


def test_missing_screenshot_is_not_found(web):
    assert web.get("/screenshots/missing.jpg").status_code == 404


def test_requests_for_other_hosts_are_rejected():
    response = TestClient(app, base_url="http://attacker.example").get("/")

    assert response.status_code == 400


def test_localhost_name_is_accepted(web):
    assert web.get("http://localhost/health").status_code == 200


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(seconds=20), "ahora"),
        (timedelta(minutes=5), "hace 5 min"),
        (timedelta(hours=3, minutes=59), "hace 3 h"),
        (timedelta(days=2), "hace 2 d"),
        (timedelta(days=30), "hace 30 d"),
    ],
)
def test_last_check_is_shown_as_relative_time(age, expected):
    now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)

    assert _ago(now - age, now) == expected


def test_old_checks_show_the_date():
    now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)

    assert _ago(now - timedelta(days=45), now) == "2026-08-23"


def test_list_has_no_creation_column_but_still_sorts_by_it(web, db):
    channels.create_channel(db, title="Viejo", content_id=HASH_A)
    newer = channels.create_channel(db, title="Nuevo", content_id=HASH_B)
    newer.created_at = newer.created_at + timedelta(days=1)
    db.commit()

    page = web.get("/?sort=created&dir=desc").text

    assert ">Alta<" not in page
    assert "Verificado" in page
    assert page.index(">Nuevo<") < page.index(">Viejo<")


def test_last_check_cell_keeps_the_full_date_on_hover(web, db):
    channel = channels.create_channel(db, title="Uno", content_id=HASH_A)
    checked = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    checks.add_check(db, channel.id, status=CheckStatus.ALIVE, checked_at=checked)

    page = web.get("/").text

    local = checked.astimezone().strftime("%Y-%m-%d %H:%M")
    assert f'title="{local}">' in page
