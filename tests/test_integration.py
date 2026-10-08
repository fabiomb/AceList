"""End to end through the web app, with the engine simulated over HTTP.

Each Content ID gets its own engine behavior, so one test can mix outcomes the way a
real catalog does. Only ffmpeg is replaced; everything else is the real code.
"""

import subprocess

import httpx
import pytest

from app.acestream.client import EngineClient
from app.db.models import CheckStatus
from app.main import app
from app.services import catalog, channels, checks, screenshots
from app.services.settings import AppSettings, save_settings
from app.web.deps import get_engine_factory

ENGINE = "http://engine.sim:6878"

ALIVE = "1" * 40
NO_PEERS = "2" * 40
NOT_FOUND = "3" * 40
DIES = "4" * 40  # the engine drops in the middle of the check
SLOW = "5" * 40  # the engine does not answer in time
GARBLED = "6" * 40  # the engine answers something unexpected


def _session_path(content_id):
    return f"{content_id[:8]}/session"


class SimulatedEngine:
    """Answers getstream, stat and stop per Content ID, and records stops."""

    def __init__(self, respx_mock):
        self.stopped = []
        respx_mock.get(f"{ENGINE}/ace/getstream").mock(side_effect=self._getstream)
        respx_mock.get(url__startswith=f"{ENGINE}/ace/stat/").mock(side_effect=self._stat)
        respx_mock.get(url__startswith=f"{ENGINE}/ace/cmd/").mock(side_effect=self._stop)

    def _getstream(self, request):
        content_id = request.url.params["id"]
        if content_id == NOT_FOUND:
            return httpx.Response(200, json={"response": None, "error": "failed to load content"})
        if content_id == SLOW:
            raise httpx.ReadTimeout("slow", request=request)
        if content_id == GARBLED:
            return httpx.Response(200, json={"response": {"nothing": "useful"}, "error": None})
        path = _session_path(content_id)
        return httpx.Response(
            200,
            json={
                "response": {
                    "stat_url": f"{ENGINE}/ace/stat/{path}",
                    "playback_url": f"{ENGINE}/ace/r/{path}",
                    "command_url": f"{ENGINE}/ace/cmd/{path}",
                    "infohash": content_id[::-1],
                },
                "error": None,
            },
        )

    def _stat(self, request):
        prefix = request.url.path.split("/")[3]
        if prefix == DIES[:8]:
            raise httpx.ConnectError("engine went away", request=request)
        if prefix == ALIVE[:8]:
            stats = {"status": "dl", "peers": 7, "speed_down": 950, "downloaded": 5_000_000}
        else:
            stats = {"status": "prebuf", "peers": 0, "speed_down": 0, "downloaded": 0}
        return httpx.Response(200, json={"response": stats, "error": None})

    def _stop(self, request):
        self.stopped.append(request.url.path.split("/")[3])
        return httpx.Response(200, json={"response": "ok", "error": None})


@pytest.fixture
def engine(web, db, respx_mock):
    app.dependency_overrides[get_engine_factory] = lambda: lambda: EngineClient(ENGINE, timeout=1)
    # Short checks: a channel without peers gives up after a fraction of a second.
    save_settings(db, AppSettings(engine_url=ENGINE, check_timeout=0.3, engine_timeout=1))
    return SimulatedEngine(respx_mock)


@pytest.fixture
def ffmpeg(monkeypatch, make_jpeg):
    """Real `capture_screenshot`, with a fake ffmpeg process (files go to the test data dir)."""

    class Ffmpeg:
        present = True
        commands = []

    def fake_run(command, **kwargs):
        Ffmpeg.commands.append(command)
        with open(command[-1], "wb") as frame:
            frame.write(make_jpeg(1920, 1080))
        return subprocess.CompletedProcess(command, 0, "", "")

    def capture(playback_url, content_id, *, data_dir, **options):
        if not Ffmpeg.present:
            monkeypatch.setattr(screenshots, "find_ffmpeg", lambda *args: None)
            options["ffmpeg_path"] = None
        else:
            options["ffmpeg_path"] = "ffmpeg"
        return screenshots.capture_screenshot(
            playback_url, content_id, data_dir=data_dir, runner=fake_run, **options
        )

    monkeypatch.setattr(catalog, "capture_screenshot", capture)
    return Ffmpeg


def add(web, content_id, title):
    response = web.post(
        "/channels/new",
        data={"title": title, "link": f"acestream://{content_id}"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response


def latest(db, content_id):
    channel = channels.find_channel_by_content_id(db, content_id)
    return checks.get_latest_check(db, channel.id)


def test_alive_channel_flows_from_the_form_to_the_list(web, db, engine, ffmpeg):
    add(web, ALIVE, "Vivo")

    check = latest(db, ALIVE)
    assert check.status is CheckStatus.ALIVE
    assert (check.peers, check.speed_down, check.infohash) == (7, 950, ALIVE[::-1])
    assert check.screenshot_path.startswith(f"screenshots/{ALIVE}_")
    assert (check.width, check.height) == (1920, 1080)
    assert channels.find_channel_by_content_id(db, ALIVE).resolution.value == "1080p"
    # ffmpeg read the engine's playback URL, and the session was stopped afterwards.
    assert ffmpeg.commands[0][ffmpeg.commands[0].index("-i") + 1].startswith(f"{ENGINE}/ace/r/")
    assert engine.stopped == [ALIVE[:8]]

    page = web.get("/").text
    assert "status-alive" in page and ">7<" in page
    assert '<span class="resolution">1080p</span>' in page
    assert f'src="/screenshots/{check.screenshot_path.split("/")[1]}"' in page


def test_channel_without_peers(web, db, engine, ffmpeg):
    add(web, NO_PEERS, "Callado")

    check = latest(db, NO_PEERS)
    assert check.status is CheckStatus.NO_PEERS
    assert check.screenshot_path is None
    assert ffmpeg.commands == []
    assert engine.stopped == [NO_PEERS[:8]]
    assert "Sin peers" in web.get("/").text


def test_unknown_hash(web, db, engine, ffmpeg):
    add(web, NOT_FOUND, "Muerto")

    assert latest(db, NOT_FOUND).status is CheckStatus.NOT_FOUND
    assert "No encontrado" in web.get("/").text


def test_engine_down_still_saves_the_channel(web, db, engine_down):
    add(web, ALIVE, "Sin engine")

    check = latest(db, ALIVE)
    assert check.status is CheckStatus.ERROR
    assert "engine.test" in check.error_message
    page = web.get("/").text
    assert "Sin engine" in page and "status-error" in page


def test_engine_timeout(web, db, engine):
    add(web, SLOW, "Lento")

    check = latest(db, SLOW)
    assert check.status is CheckStatus.ERROR
    assert "did not answer in time" in check.error_message


def test_engine_dropping_mid_check_is_an_error_and_cleans_up(web, db, engine):
    add(web, DIES, "Se cae")

    check = latest(db, DIES)
    assert check.status is CheckStatus.ERROR
    assert engine.stopped == [DIES[:8]]


def test_unexpected_engine_answer(web, db, engine):
    add(web, GARBLED, "Raro")

    check = latest(db, GARBLED)
    assert check.status is CheckStatus.ERROR
    assert "unexpected getstream response" in check.error_message


def test_missing_ffmpeg_keeps_the_channel_alive_without_screenshot(web, db, engine, ffmpeg):
    ffmpeg.present = False

    add(web, ALIVE, "Sin ffmpeg")

    check = latest(db, ALIVE)
    assert check.status is CheckStatus.ALIVE
    assert check.screenshot_path is None
    assert engine.stopped == [ALIVE[:8]]


def test_bulk_import_checks_a_mixed_list_in_the_background(
    web, db, engine, ffmpeg, wait_for_checks
):
    links = "\n".join(
        f"{name} acestream://{cid}"
        for name, cid in [
            ("Vivo", ALIVE),
            ("Callado", NO_PEERS),
            ("Muerto", NOT_FOUND),
            ("Lento", SLOW),
        ]
    )

    page = web.post("/import", data={"links": links}).text
    wait_for_checks()

    assert "<strong>4</strong> canales creados" in page
    batch = app.state.check_runner.current()
    assert dict(batch.counts) == {"alive": 1, "no_peers": 1, "not_found": 1, "error": 1}
    statuses = {cid: latest(db, cid).status for cid in (ALIVE, NO_PEERS, NOT_FOUND, SLOW)}
    assert statuses == {
        ALIVE: CheckStatus.ALIVE,
        NO_PEERS: CheckStatus.NO_PEERS,
        NOT_FOUND: CheckStatus.NOT_FOUND,
        SLOW: CheckStatus.ERROR,
    }
    alive_only = web.get("/?status=alive").text
    assert ">Vivo<" in alive_only and ">Callado<" not in alive_only


def test_history_records_a_channel_that_dies(web, db, engine, ffmpeg, wait_for_checks):
    add(web, ALIVE, "Efímero")
    channel = channels.find_channel_by_content_id(db, ALIVE)

    # The link dies: the user swaps it for a dead hash and checks again.
    web.post(
        f"/channels/{channel.id}/edit",
        data={"title": "Efímero", "link": NOT_FOUND},
    )

    history = [c.status for c in checks.list_checks(db, channel.id)]
    assert history == [CheckStatus.NOT_FOUND, CheckStatus.ALIVE]
    detail = web.get(f"/channels/{channel.id}").text
    assert "No encontrado" in detail and "Activo" in detail
