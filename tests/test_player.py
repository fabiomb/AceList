import httpx
import pytest

from app.acestream.client import EngineClient
from app.acestream.content_id import InvalidContentIdError
from app.acestream.errors import ContentNotFoundError, EngineUnavailableError
from app.services import player
from app.services.player import (
    PlayerError,
    VlcNotFoundError,
    find_vlc,
    open_in_player,
    vlc_candidates,
)

BASE = "http://127.0.0.1:6878"
HASH = "78266c15035d0ad8cbc58f821733931e1de434ab"
INFOHASH = "25f4c7b60edb0433343c777846924d35c65ec4f9"
PATH = f"{INFOHASH}/f4283e11274fae1ced9ef41a4c173857"
PLAYBACK = f"{BASE}/ace/r/{PATH}"
GETSTREAM = {
    "response": {
        "stat_url": f"{BASE}/ace/stat/{PATH}",
        "playback_url": PLAYBACK,
        "command_url": f"{BASE}/ace/cmd/{PATH}",
        "infohash": INFOHASH,
    },
    "error": None,
}


class FakeLauncher:
    """Stands in for subprocess.Popen and records how it was called."""

    def __init__(self, exc=None):
        self.calls = []
        self.exc = exc

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self.exc:
            raise self.exc


@pytest.fixture
def client():
    with EngineClient(BASE, timeout=1) as c:
        yield c


@pytest.fixture
def engine(respx_mock):
    class Engine:
        getstream = respx_mock.get(f"{BASE}/ace/getstream").respond(json=GETSTREAM)
        stop = respx_mock.get(f"{BASE}/ace/cmd/{PATH}").respond(
            json={"response": "ok", "error": None}
        )

    return Engine


@pytest.fixture
def vlc(tmp_path):
    exe = tmp_path / "vlc.exe"
    exe.write_bytes(b"")
    return str(exe)


# find_vlc


def test_configured_path_wins_when_it_exists(vlc):
    assert find_vlc(vlc, candidates=[]) == vlc


def test_configured_path_that_does_not_exist_is_not_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(player.shutil, "which", lambda name: "C:/elsewhere/vlc.exe")

    assert find_vlc(str(tmp_path / "missing.exe"), candidates=[]) is None


def test_usual_install_folders_come_before_path(tmp_path, vlc, monkeypatch):
    monkeypatch.setattr(player.shutil, "which", lambda name: "C:/on-path/vlc.exe")

    assert find_vlc(None, candidates=[tmp_path / "nope.exe", tmp_path / "vlc.exe"]) == vlc


def test_path_is_the_last_resort(tmp_path, monkeypatch):
    monkeypatch.setattr(player.shutil, "which", lambda name: f"/usr/bin/{name}")

    assert find_vlc(None, candidates=[tmp_path / "nope.exe"]) == "/usr/bin/vlc"


def test_candidates_are_under_the_program_files_folders(monkeypatch):
    monkeypatch.setenv("ProgramFiles", "C:/PF")
    monkeypatch.setenv("ProgramFiles(x86)", "C:/PF86")
    monkeypatch.delenv("ProgramW6432", raising=False)

    found = {path.as_posix() for path in vlc_candidates()}

    assert found == {"C:/PF/VideoLAN/VLC/vlc.exe", "C:/PF86/VideoLAN/VLC/vlc.exe"}


# open_in_player


def test_opens_the_playback_url_in_vlc_without_a_shell(client, engine, vlc):
    launcher = FakeLauncher()

    stream = open_in_player(
        client, f"acestream://{HASH.upper()}", title="Canal", vlc_path=vlc, launcher=launcher
    )

    [(command, kwargs)] = launcher.calls
    assert command == [vlc, "--meta-title=Canal", PLAYBACK]
    assert "shell" not in kwargs
    assert stream.content_id == HASH
    assert engine.getstream.calls.last.request.url.params["id"] == HASH
    # VLC is now reading the session: it must not be stopped.
    assert not engine.stop.called


def test_a_title_that_looks_like_an_option_stays_a_value(client, engine, vlc):
    launcher = FakeLauncher()

    open_in_player(client, HASH, title="--extraintf=http", vlc_path=vlc, launcher=launcher)

    [(command, _)] = launcher.calls
    assert command[1] == "--meta-title=--extraintf=http"
    assert len(command) == 3


def test_without_a_title_only_the_url_is_passed(client, engine, vlc):
    launcher = FakeLauncher()

    open_in_player(client, HASH, vlc_path=vlc, launcher=launcher)

    assert launcher.calls[0][0] == [vlc, PLAYBACK]


def test_missing_vlc_never_touches_the_engine(client, engine, monkeypatch):
    monkeypatch.setattr(player, "find_vlc", lambda: None)

    with pytest.raises(VlcNotFoundError):
        open_in_player(client, HASH, launcher=FakeLauncher())

    assert not engine.getstream.called


def test_invalid_content_id_is_rejected_first(client, engine, vlc):
    with pytest.raises(InvalidContentIdError):
        open_in_player(client, "nope", vlc_path=vlc, launcher=FakeLauncher())

    assert not engine.getstream.called


def test_engine_errors_reach_the_caller_and_vlc_is_not_started(client, respx_mock, vlc):
    respx_mock.get(f"{BASE}/ace/getstream").respond(
        json={"response": None, "error": "failed to load content"}
    )
    launcher = FakeLauncher()

    with pytest.raises(ContentNotFoundError):
        open_in_player(client, HASH, vlc_path=vlc, launcher=launcher)

    assert launcher.calls == []


def test_engine_down_is_reported(client, respx_mock, vlc):
    respx_mock.get(f"{BASE}/ace/getstream").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(EngineUnavailableError):
        open_in_player(client, HASH, vlc_path=vlc, launcher=FakeLauncher())


def test_vlc_that_fails_to_start_stops_the_session(client, engine, vlc):
    with pytest.raises(PlayerError, match="could not start VLC"):
        open_in_player(client, HASH, vlc_path=vlc, launcher=FakeLauncher(OSError("denied")))

    assert engine.stop.called


def test_a_failing_stop_does_not_hide_the_launch_error(client, respx_mock, vlc):
    respx_mock.get(f"{BASE}/ace/getstream").respond(json=GETSTREAM)
    respx_mock.get(f"{BASE}/ace/cmd/{PATH}").mock(side_effect=httpx.ConnectError("gone"))

    with pytest.raises(PlayerError, match="could not start VLC"):
        open_in_player(client, HASH, vlc_path=vlc, launcher=FakeLauncher(OSError("denied")))
