from app.db.models import CheckStatus
from app.main import app
from app.services import categories, channels, checks

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"


def form(**fields):
    values = {"links": "", "category_id": "", "new_category": "", "language": "", "country": ""}
    values.update(fields)
    return values


def test_import_page_and_nav_link(web):
    page = web.get("/import").text

    assert "<h1>Importar enlaces</h1>" in page
    assert 'href="http://127.0.0.1/import"' in page
    assert "<textarea" in page


def test_import_creates_reports_and_verifies_in_the_background(
    web, db, engine_empty, wait_for_checks
):
    existing = channels.create_channel(db, title="<Viejo>", content_id=HASH_A)

    response = web.post(
        "/import",
        data=form(
            links=f"{HASH_A}\nPartido <b> - acestream://{HASH_B}\nbasura",
            new_category="Deportes",
            language="es",
        ),
    )

    assert response.status_code == 200
    page = response.text
    assert "<strong>1</strong> canal creado" in page
    assert "<strong>1</strong> duplicado" in page
    assert "<strong>1</strong> línea inválida" in page
    assert "Partido &lt;b&gt;" in page
    assert "ya está en el catálogo como" in page and "&lt;Viejo&gt;" in page
    assert "Línea 3:" in page and "basura" in page
    # The form is ready for the next list.
    assert "basura</textarea>" not in page

    wait_for_checks()
    new = channels.find_channel_by_content_id(db, HASH_B)
    assert new.language == "es"
    assert new.category.name == "Deportes"
    assert [c.status for c in checks.list_checks(db, new.id)] == [CheckStatus.NOT_FOUND]
    assert checks.list_checks(db, existing.id) == []


def test_only_duplicates_start_no_checks(web, db):
    channels.create_channel(db, title="Uno", content_id=HASH_A)

    page = web.post("/import", data=form(links=HASH_A)).text

    assert "<strong>0</strong> canales creados" in page
    assert app.state.check_runner.current() is None


def test_empty_or_invalid_form_is_rejected_keeping_the_text(web, db):
    empty = web.post("/import", data=form(links="  \n "))
    bad = web.post("/import", data=form(links=HASH_A, category_id="77", country="UK"))

    assert empty.status_code == 422
    assert "Pega al menos un enlace" in empty.text
    assert bad.status_code == 422
    assert "La categoría elegida no existe." in bad.text
    assert "Código desconocido." in bad.text
    assert f">{HASH_A}</textarea>" in bad.text
    assert channels.list_channels(db) == []


def test_existing_category_is_used(web, db, engine_down):
    sports = categories.create_category(db, "Deportes")

    web.post("/import", data=form(links=HASH_A, category_id=str(sports.id)))

    assert channels.find_channel_by_content_id(db, HASH_A).category_id == sports.id


def test_import_from_another_site_is_rejected(web, db):
    response = web.post(
        "/import", data=form(links=HASH_A), headers={"sec-fetch-site": "cross-site"}
    )

    assert response.status_code == 403
    assert channels.list_channels(db) == []
