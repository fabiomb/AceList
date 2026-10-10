from types import SimpleNamespace

import pytest

from app.acestream.content_id import IdKind
from app.acestream.errors import ContentNotFoundError, EngineUnavailableError
from app.services import channels, player
from app.web import routes

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"


@pytest.fixture
def opened(monkeypatch):
    """Replaces the player: records what would be opened, or raises `error`."""

    class Opened:
        calls = []
        error = None
        kinds = []  # the kind each call was asked with
        loaded_as = IdKind.CONTENT_ID  # how the "engine" loads the channel

        def __call__(self, client, content_id, *, kind=None, title=None, vlc_path=None):
            self.calls.append((content_id, title))
            self.kinds.append(kind)
            self.vlc_path = vlc_path
            if self.error:
                raise self.error
            return SimpleNamespace(kind=self.loaded_as)

    fake = Opened()
    monkeypatch.setattr(routes.player, "open_in_player", fake)
    return fake


@pytest.fixture
def channel(db):
    return channels.create_channel(db, title="Canal <Uno>", content_id=HASH_A)


def test_play_opens_the_channel_and_reports_it(web, channel, opened):
    response = web.post(f"/channels/{channel.id}/play", headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert opened.calls == [(HASH_A, "Canal <Uno>")]
    assert "Abriendo «Canal &lt;Uno&gt;» en VLC…" in response.text
    # A fragment for #notices, not a whole page.
    assert "<html" not in response.text


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (player.VlcNotFoundError("x"), "No se encontró VLC"),
        (ContentNotFoundError(HASH_A), "puede que el enlace haya muerto"),
        (EngineUnavailableError("x"), "El engine de Ace Stream no responde"),
        (player.PlayerError("denied"), "No se pudo abrir VLC: denied"),
    ],
)
def test_failures_are_explained(web, channel, opened, error, message):
    opened.error = error

    response = web.post(f"/channels/{channel.id}/play")

    assert response.status_code == 503
    assert message in response.text


def test_play_buttons_are_on_the_list_and_the_detail(web, channel):
    target = f'hx-post="http://127.0.0.1/channels/{channel.id}/play"'

    assert target in web.get("/").text
    detail = web.get(f"/channels/{channel.id}").text
    assert target in detail
    assert "Abrir en reproductor" in detail


def test_missing_channel_is_404(web, opened):
    assert web.post("/channels/999/play").status_code == 404
    assert opened.calls == []


def test_play_from_another_site_is_rejected(web, channel, opened):
    response = web.post(f"/channels/{channel.id}/play", headers={"sec-fetch-site": "cross-site"})

    assert response.status_code == 403
    assert opened.calls == []


def test_playing_remembers_how_the_engine_loaded_the_channel(web, db, channel, opened):
    opened.loaded_as = IdKind.INFOHASH

    web.post(f"/channels/{channel.id}/play")
    web.post(f"/channels/{channel.id}/play")

    assert opened.kinds == [None, IdKind.INFOHASH]
    db.refresh(channel)
    assert channel.id_kind is IdKind.INFOHASH
