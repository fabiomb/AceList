import json

import httpx
import pytest

from app.db.models import SourceEntry
from app.services import categories, channels, sources
from app.services.errors import DuplicateError, NotFoundError, ValidationError
from app.services.sources import ExploreQuery, SourceFetchError

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"
HASH_C = "efc60cfe5e3a349baa02bcc49f6647c21a9c3c5b"
URL = "https://lists.test/canales.m3u"

M3U = f"""#EXTM3U
#EXTINF:-1 group-title="Deportes",Uno HD
acestream://{HASH_A}
#EXTINF:-1 group-title="Noticias",Dos
acestream://{HASH_B}
#EXTINF:-1,Repetido
acestream://{HASH_A}
"""


@pytest.fixture
def client():
    with httpx.Client() as c:
        yield c


def test_create_source_validates_and_normalizes(db):
    source = sources.create_source(db, name="  Mi   lista ", url=f" {URL} ")

    assert (source.name, source.url, source.enabled) == ("Mi lista", URL, True)
    with pytest.raises(ValidationError, match="^name"):
        sources.create_source(db, name=" ", url=URL)
    with pytest.raises(ValidationError, match="^url"):
        sources.create_source(db, name="Otra", url="ftp://lists.test/x")
    with pytest.raises(ValidationError, match="^url"):
        sources.create_source(db, name="Otra", url="https://")
    with pytest.raises(ValidationError, match="^name"):
        sources.create_source(db, name="x" * 101, url=URL)
    with pytest.raises(ValidationError, match="^url"):
        sources.create_source(db, name="Otra", url=URL + "?" + "a" * 1000)
    with pytest.raises(DuplicateError):
        sources.create_source(db, name="Mi lista", url=URL)


def test_sources_are_listed_by_name_and_can_be_toggled_and_deleted(db):
    b = sources.create_source(db, name="beta", url=URL)
    sources.create_source(db, name="Alfa", url=URL)

    assert [s.name for s in sources.list_sources(db)] == ["Alfa", "beta"]
    assert sources.set_enabled(db, b.id, False).enabled is False
    sources.delete_source(db, b.id)
    assert [s.name for s in sources.list_sources(db)] == ["Alfa"]
    with pytest.raises(NotFoundError):
        sources.get_source(db, b.id)


def test_parse_m3u_keeps_titles_groups_and_first_appearance():
    entries = sources.parse_source(M3U)

    assert [(e.content_id, e.title, e.group) for e in entries] == [
        (HASH_A, "Uno HD", "Deportes"),
        (HASH_B, "Dos", "Noticias"),
    ]


def test_parse_plain_links():
    entries = sources.parse_source(f"Partido - acestream://{HASH_C}\n{HASH_B}\nbasura\n")

    assert [(e.content_id, e.title) for e in entries] == [(HASH_C, "Partido"), (HASH_B, None)]


def test_parse_an_acelist_export():
    document = {
        "format": "acelist",
        "version": 1,
        "channels": [
            {"title": "Uno", "content_id": HASH_A, "category": "Cine"},
            {"title": "Canal ecc85e5d", "title_pending": True, "link": f"acestream://{HASH_B}"},
            {"title": "Sin hash", "content_id": "nope"},
            "no es un canal",
        ],
    }

    entries = sources.parse_source(json.dumps(document))

    assert [(e.content_id, e.title, e.group) for e in entries] == [
        (HASH_A, "Uno", "Cine"),
        (HASH_B, None, None),
    ]


def test_parse_rejects_a_broken_export():
    with pytest.raises(SourceFetchError, match="exportación"):
        sources.parse_source('{"format": "otra"}')


def test_parse_caps_the_entries(monkeypatch):
    monkeypatch.setattr(sources, "MAX_ENTRIES", 1)

    assert len(sources.parse_source(M3U)) == 1


def test_refresh_stores_the_entries(db, client, respx_mock):
    respx_mock.get(URL).respond(text=M3U)
    source = sources.create_source(db, name="Lista", url=URL)

    sources.refresh_source(db, source, client)

    assert source.entry_count == 2 and source.error_message is None
    assert source.fetched_at is not None
    stored = db.query(SourceEntry).order_by(SourceEntry.position).all()
    assert [(e.content_id, e.title, e.group, e.position) for e in stored] == [
        (HASH_A, "Uno HD", "Deportes", 1),
        (HASH_B, "Dos", "Noticias", 2),
    ]


def test_refresh_replaces_entries_and_keeps_them_when_it_fails(db, client, respx_mock):
    route = respx_mock.get(URL)
    route.respond(text=M3U)
    source = sources.create_source(db, name="Lista", url=URL)
    sources.refresh_source(db, source, client)

    route.respond(text=f"acestream://{HASH_C}")
    sources.refresh_source(db, source, client)
    assert [e.content_id for e in db.query(SourceEntry)] == [HASH_C]

    route.respond(status_code=404)
    sources.refresh_source(db, source, client)
    assert source.error_message == "El servidor respondió 404."
    assert [e.content_id for e in db.query(SourceEntry)] == [HASH_C]
    assert source.entry_count == 1


@pytest.mark.parametrize(
    ("side_effect", "message"),
    [
        (httpx.ReadTimeout("slow"), "No respondió a tiempo."),
        (httpx.ConnectError("refused"), "No se pudo descargar: refused"),
    ],
)
def test_refresh_reports_network_errors(db, client, respx_mock, side_effect, message):
    respx_mock.get(URL).mock(side_effect=side_effect)
    source = sources.create_source(db, name="Lista", url=URL)

    sources.refresh_source(db, source, client)

    assert source.error_message == message
    assert source.entry_count is None


def test_refresh_refuses_big_lists(db, client, respx_mock, monkeypatch):
    monkeypatch.setattr(sources, "MAX_SOURCE_BYTES", 10)
    respx_mock.get(URL).respond(text=M3U)
    source = sources.create_source(db, name="Lista", url=URL)

    sources.refresh_source(db, source, client)

    assert source.error_message.startswith("La lista supera")


def test_refresh_reads_latin1_and_reports_lists_without_links(db, client, respx_mock):
    respx_mock.get(URL).respond(content=f"Canal Ñandú {HASH_A}".encode("latin-1"))
    other = "https://lists.test/vacia.txt"
    respx_mock.get(other).respond(text="nada por aquí")
    source = sources.create_source(db, name="Lista", url=URL)
    empty = sources.create_source(db, name="Vacía", url=other)

    sources.refresh_source(db, source, client)
    sources.refresh_source(db, empty, client)

    assert db.query(SourceEntry).one().title == "Canal Ñandú"
    assert empty.entry_count == 0
    assert empty.error_message == "La lista no tiene enlaces de Ace Stream."


def test_refresh_sources_skips_disabled_ones(db, client, respx_mock):
    route = respx_mock.get(URL).respond(text=M3U)
    sources.create_source(db, name="Activa", url=URL)
    off = sources.create_source(db, name="Apagada", url="https://lists.test/off.m3u")
    sources.set_enabled(db, off.id, False)

    refreshed = sources.refresh_sources(db, client)

    assert [s.name for s in refreshed] == ["Activa"]
    assert route.call_count == 1


def test_make_client_identifies_aceList():
    with sources.make_client() as c:
        assert c.headers["User-Agent"].startswith("AceList/")
        assert c.follow_redirects is True


@pytest.fixture
def explored(db, client, respx_mock):
    """Two sources sharing a channel, one of them already in the catalog."""
    respx_mock.get(URL).respond(text=M3U)
    respx_mock.get("https://lists.test/otra.txt").respond(
        text=f"Tres 100%_real acestream://{HASH_C}\nUno otra vez {HASH_A}"
    )
    lista = sources.create_source(db, name="Lista", url=URL)
    otra = sources.create_source(db, name="Otra", url="https://lists.test/otra.txt")
    sources.refresh_sources(db, client)
    mine = channels.create_channel(db, title="Mío", content_id=HASH_B)
    return {"lista": lista, "otra": otra, "mine": mine}


def names(db, **kwargs):
    found = sources.explore(db, ExploreQuery(**kwargs))
    return [(row.entry.title, row.source_name) for row in found.rows]


def test_explore_lists_entries_of_enabled_sources_and_marks_the_catalog(db, explored):
    found = sources.explore(db, ExploreQuery())

    assert found.total == 4
    assert [(r.entry.title, r.source_name) for r in found.rows] == [
        ("Dos", "Lista"),
        ("Tres 100%_real", "Otra"),
        ("Uno HD", "Lista"),
        ("Uno otra vez", "Otra"),
    ]
    assert found.rows[0].channel == explored["mine"]
    assert found.rows[1].channel is None


def test_explore_filters(db, explored):
    assert names(db, text="uno") == [("Uno HD", "Lista"), ("Uno otra vez", "Otra")]
    assert names(db, text="NOTICIAS") == [("Dos", "Lista")]
    assert names(db, text=f"acestream://{HASH_C[:10]}") == [("Tres 100%_real", "Otra")]
    assert names(db, text="0%_") == [("Tres 100%_real", "Otra")]
    assert names(db, source_id=explored["otra"].id) == [
        ("Tres 100%_real", "Otra"),
        ("Uno otra vez", "Otra"),
    ]
    assert ("Dos", "Lista") not in names(db, only_new=True)
    sources.set_enabled(db, explored["otra"].id, False)
    assert names(db) == [("Dos", "Lista"), ("Uno HD", "Lista")]


def test_explore_limits_the_rows_but_counts_them_all(db, explored):
    found = sources.explore(db, ExploreQuery(), limit=2)

    assert len(found.rows) == 2 and found.total == 4


def test_add_entries_creates_new_channels_only(db, explored):
    entries = {e.title: e for e in db.query(SourceEntry)}
    news = categories.create_category(db, "Nuevos")
    chosen = [entries["Uno HD"].id, entries["Uno otra vez"].id, entries["Dos"].id, 9999]

    result = sources.add_entries(db, chosen, category_id=news.id)

    assert [(c.title, c.content_id, c.category_id) for c in result.created] == [
        ("Uno HD", HASH_A, news.id)
    ]
    reasons = sorted(d.reason.value for d in result.duplicates)
    assert reasons == ["existing", "repeated"]


def test_add_entries_without_a_name_gets_a_provisional_title(db, client, respx_mock):
    respx_mock.get(URL).respond(text=f"{HASH_C}\n")
    source = sources.create_source(db, name="Lista", url=URL)
    sources.refresh_source(db, source, client)

    result = sources.add_entries(db, [db.query(SourceEntry).one().id])

    channel = result.created[0]
    assert channel.title == f"Canal {HASH_C[:8]}" and channel.title_pending is True


def test_add_entries_checks_the_category(db, explored):
    with pytest.raises(NotFoundError):
        sources.add_entries(db, [1], category_id=123)


def test_add_file_source_reads_the_file_and_is_named_after_it(db):
    source = sources.add_file_source(
        db, name="", filename=r"C:\listas\mis canales.m3u8", data=M3U.encode()
    )

    assert source.name == "mis canales" and source.url is None
    assert source.entry_count == 2 and source.error_message is None
    assert source.fetched_at is not None
    assert [e.title for e in db.query(SourceEntry).order_by(SourceEntry.position)] == [
        "Uno HD",
        "Dos",
    ]


def test_add_file_source_again_replaces_its_entries(db):
    first = sources.add_file_source(db, name="Mía", filename="a.m3u", data=M3U.encode())
    again = sources.add_file_source(
        db, name="Mía", filename="b.txt", data=f"acestream://{HASH_C}".encode("latin-1")
    )

    assert again.id == first.id and again.entry_count == 1
    assert [e.content_id for e in db.query(SourceEntry)] == [HASH_C]


def test_add_file_source_rejects_bad_files_without_changes(db, client, respx_mock, monkeypatch):
    respx_mock.get(URL).respond(text=M3U)
    web_source = sources.create_source(db, name="Web", url=URL)
    sources.refresh_source(db, web_source, client)

    with pytest.raises(DuplicateError):
        sources.add_file_source(db, name="Web", filename="x.m3u", data=M3U.encode())
    with pytest.raises(SourceFetchError, match="no tiene enlaces"):
        sources.add_file_source(db, name="", filename="x.m3u", data=b"#EXTM3U\n")
    with pytest.raises(ValidationError):
        sources.add_file_source(db, name="", filename="   .m3u", data=M3U.encode())
    monkeypatch.setattr(sources, "MAX_SOURCE_BYTES", 10)
    with pytest.raises(SourceFetchError, match="supera"):
        sources.add_file_source(db, name="", filename="x.m3u", data=M3U.encode())

    assert [s.name for s in sources.list_sources(db)] == ["Web"]


def test_file_sources_are_never_downloaded(db, client, respx_mock):
    source = sources.add_file_source(db, name="", filename="x.m3u", data=M3U.encode())

    assert sources.refresh_source(db, source, client) is source
    assert sources.refresh_sources(db, client) == []
    assert source.entry_count == 2
