import json

import pytest

from app.services import categories, channels, checks
from app.services.exchange import FORMAT, VERSION
from app.web import import_routes

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"


def form(**fields):
    values = {"links": "", "category_id": "", "new_category": "", "language": "", "country": ""}
    values.update(fields)
    return values


def export_file(*entries):
    doc = {"format": FORMAT, "version": VERSION, "channels": list(entries)}
    return ("acelist.json", json.dumps(doc).encode("utf-8"), "application/json")


@pytest.fixture
def two(db):
    sports = categories.create_category(db, "Deportes")
    channels.create_channel(
        db, title="Uno", content_id=HASH_A, category_id=sports.id, language="es"
    )
    channels.create_channel(db, title="Dos", content_id=HASH_B)


# export


def test_export_downloads_the_listed_channels(web, two):
    response = web.get("/export?q=uno")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="acelist-') and disposition.endswith(
        '.json"'
    )
    doc = response.json()
    assert doc["format"] == FORMAT
    assert [(c["title"], c["category"], c["language"]) for c in doc["channels"]] == [
        ("Uno", "Deportes", "es")
    ]


def test_export_without_filters_has_the_whole_catalog(web, two):
    assert len(web.get("/export").json()["channels"]) == 2


def test_list_and_gallery_link_to_the_export_with_their_filters(web, two):
    for path in ("/?q=o", "/gallery?q=o"):
        page = web.get(path).text
        assert 'href="http://127.0.0.1/export?q=o" hx-boost="false" download>Exportar</a>' in page


# import from a file


def test_importing_an_export_adds_only_the_new_channels(
    web, db, two, engine_empty, wait_for_checks
):
    new = "0123456789abcdef0123456789abcdef01234567"
    upload = export_file(
        {"content_id": HASH_A, "title": "Uno otra vez"},
        {"content_id": new, "title": "Nuevo", "category": "Cine", "country": "ES"},
    )

    response = web.post("/import", data=form(), files={"file": upload})
    wait_for_checks()

    page = response.text
    assert "<strong>1</strong> canal creado" in page
    assert "<strong>1</strong> duplicado" in page
    assert "Canal 1:" in page and "ya está en el catálogo como" in page
    created = channels.find_channel_by_content_id(db, new)
    assert (created.title, created.category.name, created.country) == ("Nuevo", "Cine", "ES")
    assert len(checks.list_checks(db, created.id)) == 1  # verified in the background
    assert len(channels.list_channels(db)) == 3


def test_invalid_channels_in_an_export_are_explained(web, db, engine_empty):
    upload = export_file({"content_id": HASH_A, "language": "xx"})

    page = web.post("/import", data=form(), files={"file": upload}).text

    assert "1</strong> canal inválido" in page
    assert "Canal 1:" in page and "datos inválidos: unknown language code" in page
    assert channels.list_channels(db) == []


def test_an_m3u_file_is_imported_as_a_list(web, db, engine_empty):
    m3u = f"#EXTM3U\n#EXTINF:-1,Desde archivo\nacestream://{HASH_A}\n".encode()

    page = web.post(
        "/import", data=form(), files={"file": ("lista.m3u", m3u, "audio/x-mpegurl")}
    ).text

    assert "<strong>1</strong> canal creado" in page
    assert channels.find_channel_by_content_id(db, HASH_A).title == "Desde archivo"


def test_a_file_wins_over_the_pasted_text(web, db, engine_empty):
    upload = export_file({"content_id": HASH_A, "title": "Del archivo"})

    web.post("/import", data=form(links=HASH_B), files={"file": upload})

    assert [c.content_id for c in channels.list_channels(db)] == [HASH_A]


def test_a_pasted_export_works_too(web, db, engine_empty):
    text = json.dumps(
        {
            "format": FORMAT,
            "version": VERSION,
            "channels": [{"content_id": HASH_A, "title": "Pegado"}],
        }
    )

    web.post("/import", data=form(links=text))

    assert channels.find_channel_by_content_id(db, HASH_A).title == "Pegado"


def test_a_file_that_is_not_an_export_is_rejected_clearly(web, db):
    upload = ("raro.json", b'{"something": "else"}', "application/json")

    response = web.post("/import", data=form(), files={"file": upload})

    assert response.status_code == 422
    assert "No se pudo importar: not an AceList export" in response.text


def test_files_too_big_or_not_utf8_are_refused(web, db, monkeypatch):
    monkeypatch.setattr(import_routes, "MAX_UPLOAD_BYTES", 10)
    big = web.post("/import", data=form(), files={"file": ("big.txt", b"x" * 11, "text/plain")})
    monkeypatch.undo()
    binary = web.post(
        "/import", data=form(), files={"file": ("bin.txt", b"\xff\xfe\x00bad", "text/plain")}
    )

    assert big.status_code == 422 and "El archivo supera" in big.text
    assert binary.status_code == 422 and "no es texto en UTF-8" in binary.text
    assert channels.list_channels(db) == []


def test_nothing_to_import_asks_for_links_or_a_file(web):
    response = web.post("/import", data=form())

    assert response.status_code == 422
    assert "o elige un archivo" in response.text


def test_import_form_accepts_files(web):
    page = web.get("/import").text

    assert 'enctype="multipart/form-data"' in page
    assert 'type="file"' in page
