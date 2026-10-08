import re
from datetime import UTC, datetime

import pytest

from app.db.models import CheckStatus
from app.main import app
from app.services import categories, channels, checks

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"
HASH_C = "efc60cfe5e3a349baa02bcc49f6647c21a9c3c5b"
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


@pytest.fixture
def catalog(db):
    sports = categories.create_category(db, "Deportes")
    cinema = categories.create_category(db, "cine")
    uno = channels.create_channel(
        db,
        title="Uno",
        content_id=HASH_A,
        category_id=sports.id,
        language="es",
        country="AR",
        resolution="1080p",
    )
    dos = channels.create_channel(db, title="Dos", content_id=HASH_B, category_id=cinema.id)
    tres = channels.create_channel(db, title="Tres <b>", content_id=HASH_C)
    checks.add_check(
        db, uno.id, status=CheckStatus.ALIVE, screenshot_path="screenshots/uno.jpg", checked_at=NOW
    )
    checks.add_check(db, dos.id, status=CheckStatus.NOT_FOUND, checked_at=NOW)
    return {"uno": uno, "dos": dos, "tres": tres, "sports": sports}


def sections(page):
    """Section titles in page order."""
    return re.findall(r'<h2 id="section-\d+">([^<]+?) <span', page)


def test_gallery_groups_channels_by_category(web, catalog):
    page = web.get("/gallery").text

    # Categories A-Z regardless of case, the uncategorized last.
    assert sections(page) == ["cine", "Deportes", "Sin categoría"]


def test_tile_has_screenshot_title_tags_and_status(web, catalog):
    page = web.get("/gallery").text

    assert '<img src="/screenshots/uno.jpg" alt="" loading="lazy">' in page
    assert f'href="http://127.0.0.1/channels/{catalog["uno"].id}" aria-label="Uno"' in page
    for tag in (
        '<li class="tag tag-resolution">1080p</li>',
        '<li class="tag">Deportes</li>',
        '<li class="tag" title="Spanish">ES</li>',
        '<li class="tag" title="Argentina">AR</li>',
    ):
        assert tag in page
    assert 'class="tile-status status-alive"' in page
    assert 'class="tile-status status-not_found"' in page
    assert 'class="tile-status status-unchecked"' in page


def test_tile_without_screenshot_shows_a_placeholder_and_escapes_the_title(web, catalog):
    page = web.get("/gallery").text

    assert '<span class="tile-placeholder" aria-hidden="true">TR</span>' in page
    assert "Tres &lt;b&gt;" in page
    assert "Tres <b>" not in page


def test_tiles_can_play(web, catalog):
    page = web.get("/gallery").text

    assert f'hx-post="http://127.0.0.1/channels/{catalog["uno"].id}/play"' in page
    assert 'aria-label="Reproducir Uno"' in page


def test_gallery_uses_the_same_filters_and_order(web, catalog):
    filtered = web.get(f"/gallery?category={catalog['sports'].id}").text
    by_status = web.get("/gallery?sort=status").text

    assert sections(filtered) == ["Deportes"]
    assert '<option value="title" selected>' not in by_status
    assert '<option value="status" selected>' in by_status
    assert "Quitar filtros" in filtered
    assert 'href="http://127.0.0.1/gallery"' in filtered


def test_gallery_without_matches(web, catalog):
    assert "Ningún canal coincide" in web.get("/gallery?q=nada").text


def test_empty_catalog_gallery(web):
    assert "Todavía no hay canales" in web.get("/gallery").text


def test_views_link_to_each_other_keeping_filters(web, catalog):
    gallery = web.get("/gallery?q=o").text
    listing = web.get("/?q=o").text

    assert 'href="http://127.0.0.1/?q=o">Lista</a>' in gallery
    assert 'href="http://127.0.0.1/gallery?q=o" aria-current="page">Galería</a>' in gallery
    assert 'href="http://127.0.0.1/?q=o" aria-current="page">Lista</a>' in listing
    assert 'href="http://127.0.0.1/gallery"' in web.get("/").text  # nav link


def test_batch_actions_from_the_gallery_come_back_to_it(web, catalog, engine_down, wait_for_checks):
    page = web.get("/gallery?q=uno").text
    assert 'action="http://127.0.0.1/checks?q=uno&amp;view=gallery"' in page

    response = web.post("/checks?q=uno&view=gallery", follow_redirects=False)
    wait_for_checks()

    assert response.headers["location"] == "http://127.0.0.1/gallery?q=uno"
    assert app.state.check_runner.current().total == 1


def filter_labels(page):
    """Labels of the filter bar, in page order."""
    form = page[page.index('<form class="filters"') : page.index("</form>")]
    return re.findall(r'<label for="[^"]+">([^<]+)</label>', form)


def test_both_views_list_the_filters_in_the_same_order(web, catalog):
    shared = ["Buscar", "Categoría", "Idioma", "País", "Estado", "Resolución"]

    assert filter_labels(web.get("/").text) == shared
    # The gallery adds its order select after them, since it has no column headers.
    assert filter_labels(web.get("/gallery").text) == [*shared, "Ordenar por"]
