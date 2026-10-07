from datetime import UTC, datetime, timedelta

from app.db.models import CheckStatus
from app.services import categories, channels, checks

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def seed(db):
    sports = categories.create_category(db, "Deportes")
    uno = channels.create_channel(
        db, title="Uno", content_id=HASH_A, category_id=sports.id, language="es", country="AR"
    )
    dos = channels.create_channel(db, title="Dos", content_id=HASH_B, language="en")
    checks.add_check(db, uno.id, status=CheckStatus.ALIVE, peers=3, checked_at=NOW)
    checks.add_check(db, dos.id, status=CheckStatus.ALIVE, peers=9, checked_at=NOW - timedelta(1))
    return sports


def test_filters_come_from_the_url_and_are_shown_selected(web, db):
    sports = seed(db)

    page = web.get(f"/?q=un&category={sports.id}&language=es&country=AR&status=alive").text

    assert ">Uno<" in page and ">Dos<" not in page
    assert 'value="un"' in page
    assert f'<option value="{sports.id}" selected>' in page
    assert '<option value="es" selected>' in page
    assert '<option value="AR" selected>' in page
    assert '<option value="alive" selected>' in page
    assert "1 canal con estos filtros" in page
    assert "Quitar filtros" in page


def test_filter_options_only_list_values_in_use(web, db):
    seed(db)

    page = web.get("/").text

    assert "English (en)" in page and "Spanish (es)" in page
    assert "French (fr)" not in page
    assert "Argentina (AR)" in page


def test_sorting_comes_from_the_url(web, db):
    seed(db)

    by_title = web.get("/").text
    by_peers = web.get("/?sort=peers&dir=desc").text

    assert by_title.index(">Dos<") < by_title.index(">Uno<")
    assert by_peers.index(">Dos<") < by_peers.index(">Uno<")
    assert web.get("/?sort=peers&dir=asc").text.index(">Uno<") < by_peers.index(">Dos<")


def test_headers_link_to_the_flipped_order_keeping_filters(web, db):
    seed(db)

    page = web.get("/?q=o&sort=title&dir=asc").text

    assert 'aria-sort="ascending"' in page
    assert "q=o&amp;sort=title&amp;dir=desc" in page
    # Other columns start at their default direction.
    assert "q=o&amp;sort=peers&amp;dir=desc" in page


def test_invalid_parameters_are_ignored(web, db):
    seed(db)

    response = web.get("/?sort=bogus&dir=sideways&category=abc&language=zz&status=dead")

    assert response.status_code == 200
    assert ">Uno<" in response.text and ">Dos<" in response.text
    assert "Quitar filtros" not in response.text


def test_no_match_is_not_the_empty_catalog(web, db):
    seed(db)

    page = web.get("/?q=nada").text

    assert "Ningún canal coincide con estos filtros." in page
    assert "Todavía no hay canales" not in page
    assert 'value="nada"' in page
