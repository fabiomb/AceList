import httpx
import pytest

from app.db.models import Channel, Source, SourceEntry
from app.services import categories, channels

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"
URL = "https://lists.test/canales.m3u"
M3U = f"""#EXTM3U
#EXTINF:-1 group-title="Deportes",Uno HD
acestream://{HASH_A}
#EXTINF:-1 group-title="Noticias",Dos
acestream://{HASH_B}
"""


@pytest.fixture
def listed(web, db, respx_mock):
    """One source with two channels; the second one is already in the catalog."""
    respx_mock.get(URL).respond(text=M3U)
    web.post("/explore/sources", data={"name": "Lista", "url": URL})
    mine = channels.create_channel(db, title="Mío", content_id=HASH_B)
    return mine


def entry_id(db, title):
    return db.query(SourceEntry).filter_by(title=title).one().id


def test_nav_links_to_explore(web, db):
    assert 'href="http://127.0.0.1/explore">Explorar<' in web.get("/").text


def test_explore_without_sources_invites_to_add_one(web, db):
    page = web.get("/explore").text

    assert "Todavía no hay fuentes de canales." in page
    assert "Agregar una fuente" in page


def test_adding_a_source_downloads_it_and_lists_it(web, db, respx_mock):
    respx_mock.get(URL).respond(text=M3U)

    response = web.post("/explore/sources", data={"name": "Lista", "url": URL})

    assert response.history[0].status_code == 303
    page = response.text
    assert ">Lista<" in page and "Nunca" not in page
    assert '<td class="num">2</td>' in page


def test_source_form_errors(web, db, respx_mock):
    respx_mock.get(URL).respond(text=M3U)
    web.post("/explore/sources", data={"name": "Lista", "url": URL})

    bad_url = web.post("/explore/sources", data={"name": "Otra", "url": "file:///etc/passwd"})
    no_name = web.post("/explore/sources", data={"name": "", "url": URL})
    repeated = web.post("/explore/sources", data={"name": "Lista", "url": URL})

    assert bad_url.status_code == 422 and "Escribe una dirección http://" in bad_url.text
    assert 'value="file:///etc/passwd"' in bad_url.text
    assert no_name.status_code == 422 and "Ponle un nombre" in no_name.text
    assert repeated.status_code == 422 and "Ya hay una fuente con ese nombre." in repeated.text


def test_a_failing_source_shows_its_error(web, db, respx_mock):
    respx_mock.get(URL).mock(side_effect=httpx.ConnectError("refused"))

    page = web.post("/explore/sources", data={"name": "Caída", "url": URL}).text

    assert "No se pudo descargar: refused" in page


def test_refresh_toggle_and_delete_a_source(web, db, respx_mock):
    route = respx_mock.get(URL).respond(text=M3U)
    web.post("/explore/sources", data={"name": "Lista", "url": URL})
    source_id = db.query(Source).one().id

    web.post(f"/explore/sources/{source_id}/refresh")
    web.post("/explore/sources/refresh")
    assert route.call_count == 3

    page = web.post(f"/explore/sources/{source_id}/toggle").text
    assert "Desactivada" in page and ">Activar<" in page
    assert "Todas las fuentes están desactivadas." in web.get("/explore").text
    web.post("/explore/sources/refresh")
    assert route.call_count == 3  # disabled sources are not downloaded

    page = web.post(f"/explore/sources/{source_id}/delete").text
    assert ">Lista<" not in page
    db.expire_all()
    assert db.query(SourceEntry).count() == 0


@pytest.mark.parametrize("action", ["refresh", "toggle", "delete"])
def test_unknown_source_is_404(web, db, action):
    assert web.post(f"/explore/sources/99/{action}").status_code == 404


def test_explore_shows_entries_and_marks_the_catalog(web, db, listed):
    page = web.get("/explore").text

    assert "2 canales." in page
    assert "Uno HD" in page and "Deportes" in page
    assert f'name="entry" value="{entry_id(db, "Uno HD")}"' in page
    assert "En el catálogo" in page
    assert f'href="http://127.0.0.1/channels/{listed.id}"' in page


def test_explore_filters_come_from_the_url(web, db, listed):
    only_new = web.get("/explore", params={"new": "1"}).text
    searched = web.get("/explore", params={"q": "noticias"}).text
    nothing = web.get("/explore", params={"q": "zzz"}).text

    assert "Uno HD" in only_new and "En el catálogo" not in only_new
    assert "Dos" in searched and "Uno HD" not in searched
    assert "Ningún canal de las fuentes coincide" in nothing
    assert "Quitar filtros" in nothing


def test_explore_says_when_it_shows_only_some(web, db, listed, monkeypatch):
    from app.services import sources

    monkeypatch.setattr(sources, "EXPLORE_LIMIT", 1)

    page = web.get("/explore").text

    assert "se muestran los primeros 1" in page


def test_adding_entries_creates_channels_and_keeps_the_search(web, db, listed, engine_down):
    news = categories.create_category(db, "Nuevos")
    chosen = [entry_id(db, "Uno HD"), entry_id(db, "Dos")]

    page = web.post(
        "/explore/add",
        data={"entry": chosen, "category_id": str(news.id), "q": "o", "new": ""},
    ).text

    assert "<strong>1</strong> canal agregado" in page
    assert "<strong>1</strong> ya estaba en el catálogo" in page
    assert "Ace Stream no responde" in page
    assert 'value="o"' in page
    created = db.query(Channel).filter_by(content_id=HASH_A).one()
    assert (created.title, created.category_id) == ("Uno HD", news.id)


def test_adding_with_a_new_category(web, db, listed, engine_down):
    page = web.post(
        "/explore/add", data={"entry": [entry_id(db, "Uno HD")], "new_category": "Desde fuentes"}
    ).text

    assert "<strong>1</strong> canal agregado" in page
    assert db.query(Channel).filter_by(content_id=HASH_A).one().category.name == "Desde fuentes"


def test_adding_checks_new_channels_in_the_background(web, db, listed, monkeypatch):
    started = []
    monkeypatch.setattr(
        "app.web.explore_routes.start_checks", lambda runner, ids, *a, **k: started.append(ids)
    )
    from app.main import app
    from app.web.deps import get_engine_probe

    app.dependency_overrides[get_engine_probe] = lambda: lambda: object()

    page = web.post("/explore/add", data={"entry": [entry_id(db, "Uno HD")]}).text

    assert "Se están verificando en segundo plano." in page
    assert len(started) == 1 and len(started[0]) == 1


def test_adding_nothing_or_to_a_missing_category_is_rejected(web, db, listed):
    nothing = web.post("/explore/add", data={"q": ""})
    missing = web.post(
        "/explore/add", data={"entry": [entry_id(db, "Uno HD")], "category_id": "999"}
    )

    assert nothing.status_code == 422 and "Elige al menos un canal." in nothing.text
    assert missing.status_code == 422 and "La categoría elegida no existe." in missing.text


def upload(name, content, filename="mis canales.m3u8"):
    return {
        "data": {"name": name, "url": ""},
        "files": {"file": (filename, content, "audio/x-mpegurl")},
    }


def test_explore_offers_the_source_form_with_a_drop_zone(web, db):
    page = web.get("/explore").text

    assert 'enctype="multipart/form-data"' in page and "data-dropzone" in page
    assert '<details class="add-source" open>' in page


def test_adding_a_file_source(web, db, respx_mock):
    response = web.post("/explore/sources", **upload("", M3U))

    assert response.history[0].status_code == 303
    page = response.text
    assert ">mis canales<" in page and "Archivo local" in page
    assert '<td class="num">2</td>' in page
    source_id = db.query(Source).one().id
    assert f"/explore/sources/{source_id}/refresh" not in page  # nothing to download
    assert "Uno HD" in web.get("/explore").text


def test_file_source_errors(web, db, respx_mock):
    respx_mock.get(URL).respond(text=M3U)
    web.post("/explore/sources", data={"name": "Lista", "url": URL})

    empty = web.post("/explore/sources", **upload("", "#EXTM3U\n"))
    taken = web.post("/explore/sources", **upload("Lista", M3U))
    unnamed = web.post("/explore/sources", **upload("", M3U, filename="   .m3u"))

    assert empty.status_code == 422 and "El archivo no tiene enlaces de Ace Stream." in empty.text
    assert taken.status_code == 422 and "Ya hay una fuente web con ese nombre" in taken.text
    assert unnamed.status_code == 422 and "Ponle un nombre" in unnamed.text


@pytest.mark.parametrize(
    ("form", "pushed"),
    [
        ({"q": "uno", "source": "1", "new": "1"}, "http://127.0.0.1/explore?q=uno&source=1&new=1"),
        ({"q": "", "source": "", "new": ""}, "http://127.0.0.1/explore"),
    ],
)
def test_adding_keeps_explore_in_the_address_bar(web, db, listed, engine_down, form, pushed):
    added = web.post("/explore/add", data={"entry": [entry_id(db, "Uno HD")], **form})
    nothing = web.post("/explore/add", data=form)

    assert added.headers["HX-Push-Url"] == pushed
    assert nothing.status_code == 422 and nothing.headers["HX-Push-Url"] == pushed
    assert "HX-Push-Url" not in web.get("/explore").headers
