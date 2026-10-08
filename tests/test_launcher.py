import json
import socket

import httpx
import pytest
from sqlalchemy import create_engine, inspect

from app import __version__, launcher


@pytest.fixture
def busy_port():
    """A port held by another program for the duration of the test."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        yield holder.getsockname()[1]


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    path = tmp_path / "server.json"
    monkeypatch.setattr(launcher, "STATE_FILE", path)
    return path


def health(respx_mock, port, **body):
    return respx_mock.get(f"http://127.0.0.1:{port}/health").respond(json=body)


# arguments and ports


def test_arguments():
    assert launcher.parse_args([]).port is None
    args = launcher.parse_args(["--port", "8123", "--no-browser"])
    assert (args.port, args.no_browser) == (8123, True)


def test_a_busy_default_port_is_skipped(busy_port, monkeypatch):
    monkeypatch.setattr(launcher, "DEFAULT_PORT", busy_port)

    port = launcher.choose_port()

    assert port != busy_port
    assert launcher.port_is_free(port)


def test_a_busy_requested_port_is_an_error(busy_port):
    assert not launcher.port_is_free(busy_port)
    with pytest.raises(OSError, match=f"el puerto {busy_port} está ocupado"):
        launcher.choose_port(busy_port)


def test_no_free_port_at_all_is_an_error(monkeypatch):
    monkeypatch.setattr(launcher, "port_is_free", lambda port: False)

    with pytest.raises(OSError, match="no hay puertos libres"):
        launcher.choose_port()


# telling AceList from another program


def test_acelist_is_recognized_by_its_health_answer(respx_mock):
    health(respx_mock, 8000, status="ok", app="AceList", version=__version__)
    health(respx_mock, 8001, status="ok")
    respx_mock.get("http://127.0.0.1:8002/health").mock(side_effect=httpx.ConnectError("off"))
    respx_mock.get("http://127.0.0.1:8003/health").respond(text="<html>")

    assert launcher.is_acelist(8000)
    assert not launcher.is_acelist(8001)
    assert not launcher.is_acelist(8002)
    assert not launcher.is_acelist(8003)


def test_running_instance_comes_from_the_state_file(state_file, respx_mock):
    assert launcher.running_port(state_file) is None  # no file
    state_file.write_text(json.dumps({"port": 8007}), encoding="utf-8")
    health(respx_mock, 8007, app="AceList")

    assert launcher.running_port(state_file) == 8007


def test_a_stale_state_file_is_ignored(state_file, respx_mock):
    state_file.write_text(json.dumps({"port": 8007}), encoding="utf-8")
    respx_mock.get("http://127.0.0.1:8007/health").mock(side_effect=httpx.ConnectError("off"))

    assert launcher.running_port(state_file) is None
    state_file.write_text("garbage", encoding="utf-8")
    assert launcher.running_port(state_file) is None


# database


def test_upgrade_database_creates_the_schema_from_the_shipped_migrations(tmp_path):
    url = f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}"

    launcher.upgrade_database(url)
    launcher.upgrade_database(url)  # a second run changes nothing

    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert {"channel", "category", "check_result", "setting", "alembic_version"} <= tables


def test_upgrade_database_copes_with_a_percent_in_the_path(tmp_path):
    folder = tmp_path / "100%"
    folder.mkdir()

    launcher.upgrade_database(f"sqlite:///{(folder / 'a.db').as_posix()}")

    assert (folder / "a.db").is_file()


# opening the browser


def test_the_browser_opens_once_the_server_answers(monkeypatch):
    answers = iter([False, False, True])
    monkeypatch.setattr(launcher, "is_acelist", lambda port, timeout: next(answers))
    monkeypatch.setattr(launcher.time, "sleep", lambda seconds: None)
    opened = []

    assert launcher.open_when_ready("http://127.0.0.1:8000/", 8000, opener=opened.append)
    assert opened == ["http://127.0.0.1:8000/"]


def test_the_browser_is_not_opened_if_the_server_never_answers(monkeypatch):
    monkeypatch.setattr(launcher, "is_acelist", lambda port, timeout: False)
    opened = []

    assert not launcher.open_when_ready("u", 8000, opener=opened.append, timeout=0)
    assert opened == []


# the whole start


@pytest.fixture
def quiet_start(monkeypatch, state_file):
    """main() without migrations, browser or real server; records what would happen."""
    calls = {"upgraded": 0, "opened": [], "served": []}
    monkeypatch.setattr(launcher, "running_port", lambda: None)
    monkeypatch.setattr(launcher, "choose_port", lambda preferred=None: preferred or 8004)
    monkeypatch.setattr(
        launcher, "upgrade_database", lambda: calls.__setitem__("upgraded", calls["upgraded"] + 1)
    )
    monkeypatch.setattr(launcher.webbrowser, "open", calls["opened"].append)

    def server(port):
        calls["served"].append((port, json.loads(state_file.read_text(encoding="utf-8"))))

    calls["server"] = server
    return calls


def test_start_migrates_records_the_port_and_serves(quiet_start, state_file, capsys):
    code = launcher.main(["--no-browser"], server=quiet_start["server"])

    assert code == 0
    assert quiet_start["upgraded"] == 1
    assert quiet_start["served"] == [(8004, {"port": 8004})]
    assert not state_file.exists()  # removed when the server stops
    out = capsys.readouterr().out
    assert f"AceList {__version__}" in out
    assert "AceList funciona en http://127.0.0.1:8004/" in out


def test_start_with_a_requested_port(quiet_start):
    launcher.main(["--port", "8123", "--no-browser"], server=quiet_start["server"])

    assert quiet_start["served"][0][0] == 8123


def test_the_state_file_goes_away_even_if_the_server_fails(quiet_start, state_file):
    def crash(port):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        launcher.main(["--no-browser"], server=crash)

    assert not state_file.exists()


def test_an_open_instance_is_reused(monkeypatch, quiet_start, capsys):
    monkeypatch.setattr(launcher, "running_port", lambda: 8009)

    code = launcher.main([], server=quiet_start["server"])

    assert code == 0
    assert quiet_start["opened"] == ["http://127.0.0.1:8009/"]
    assert quiet_start["served"] == []
    assert quiet_start["upgraded"] == 0
    assert "AceList ya está abierto en http://127.0.0.1:8009/" in capsys.readouterr().out


def test_a_failure_before_serving_is_explained(monkeypatch, quiet_start, capsys):
    def no_ports(preferred=None):
        raise OSError("no hay puertos libres entre 8000 y 8019")

    monkeypatch.setattr(launcher, "choose_port", no_ports)

    code = launcher.main([], server=quiet_start["server"])

    assert code == 1
    assert quiet_start["served"] == []
    assert "No se pudo iniciar AceList: no hay puertos libres" in capsys.readouterr().out
