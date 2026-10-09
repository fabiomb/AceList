from app.db.models import CheckStatus
from app.services import categories, channels, checks
from app.web.routes import SUGGEST_LIMIT

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"


def seed(db):
    sports = categories.create_category(db, "Deportes")
    uno = channels.create_channel(
        db, title="Uno Deportivo", content_id=HASH_A, category_id=sports.id
    )
    channels.create_channel(db, title="Dos", content_id=HASH_B)
    checks.add_check(db, uno.id, status=CheckStatus.ALIVE, peers=3)
    return uno


def test_every_page_has_the_search_box(web, db):
    page = web.get("/settings").text

    assert 'id="topbar-q"' in page
    assert 'action="http://127.0.0.1/"' in page
    assert 'hx-get="http://127.0.0.1/search/suggest"' in page


def test_suggest_lists_matches_with_status_and_a_link_to_the_detail(web, db):
    uno = seed(db)

    page = web.get("/search/suggest", params={"q": "deport"}).text

    assert "Uno Deportivo" in page and "Dos" not in page
    assert f'href="http://127.0.0.1/channels/{uno.id}"' in page
    assert "status-alive" in page
    assert "Deportes" in page
    assert "Ver el resultado en el listado" in page
    assert 'href="http://127.0.0.1/?q=deport"' in page


def test_suggest_marks_unchecked_channels(web, db):
    seed(db)

    page = web.get("/search/suggest", params={"q": "dos"}).text

    assert "Sin verificar" in page


def test_suggest_matches_by_category_and_content_id(web, db):
    seed(db)

    assert "Uno Deportivo" in web.get("/search/suggest", params={"q": "deportes"}).text
    assert "Dos" in web.get("/search/suggest", params={"q": HASH_B[:8]}).text


def test_suggest_is_empty_without_text(web, db):
    seed(db)

    response = web.get("/search/suggest", params={"q": "   "})

    assert response.status_code == 200
    assert response.text == ""


def test_suggest_says_when_nothing_matches_and_escapes_the_text(web, db):
    seed(db)

    page = web.get("/search/suggest", params={"q": "<b>zzz</b>"}).text

    assert "Ningún canal coincide" in page
    assert "<b>zzz</b>" not in page
    assert "&lt;b&gt;zzz&lt;/b&gt;" in page


def test_suggest_shows_a_few_and_links_to_all_of_them(web, db):
    for i in range(SUGGEST_LIMIT + 3):
        channels.create_channel(db, title=f"Canal {i:02}", content_id=f"{i:040x}")

    page = web.get("/search/suggest", params={"q": "canal 1"}).text
    many = web.get("/search/suggest", params={"q": "canal"}).text

    assert many.count('class="suggest-item"') == SUGGEST_LIMIT
    assert f"Ver los {SUGGEST_LIMIT + 3} resultados en el listado" in many
    assert 'href="http://127.0.0.1/?q=canal"' in many
    assert page.count('class="suggest-item"') == 1  # only "Canal 10"
