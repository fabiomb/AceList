import pytest

from app.acestream import install
from app.acestream.client import EngineVersion
from app.acestream.install import EngineStartError, start_engine
from app.main import app
from app.services.settings import AppSettings, save_settings
from app.web import engine_routes
from app.web.deps import get_engine_probe

VERSION = EngineVersion(version="3.1.74", code=3017400, platform="win32")


class Launcher:
    """Stands in for subprocess.Popen."""

    def __init__(self, exc=None):
        self.calls = []
        self.exc = exc

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self.exc:
            raise self.exc


@pytest.fixture
def exe(tmp_path):
    path = tmp_path / "engine" / "ace_engine.exe"
    path.parent.mkdir()
    path.write_bytes(b"")
    return str(path)


@pytest.fixture
def engine(web, monkeypatch):
    """A probe that answers as scripted, and a launch that only records itself."""

    class Engine:
        answers = []  # what each probe returns; the last one repeats
        launched = []

        def probe(self):
            return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]

    fake = Engine()
    fake.answers = [None]
    app.dependency_overrides[get_engine_probe] = lambda: fake.probe
    monkeypatch.setattr(install, "start_engine", lambda path: fake.launched.append(path))
    monkeypatch.setattr(engine_routes, "POLL_INTERVAL", 0)
    return fake


# start_engine


def test_start_engine_launches_it_without_a_shell(exe):
    launcher = Launcher()

    start_engine(exe, launcher=launcher)

    [(command, kwargs)] = launcher.calls
    assert command == [exe]
    assert "shell" not in kwargs
    assert kwargs["cwd"].endswith("engine")


def test_start_engine_needs_the_file(tmp_path):
    with pytest.raises(EngineStartError, match="not found"):
        start_engine(str(tmp_path / "missing.exe"), launcher=Launcher())


def test_start_engine_reports_a_launch_failure(exe):
    with pytest.raises(EngineStartError, match="could not start"):
        start_engine(exe, launcher=Launcher(OSError("denied")))


# which executable


def test_configured_executable_wins(exe, monkeypatch):
    monkeypatch.setattr(install, "find_engine_executable", lambda: "C:/detected/ace_engine.exe")

    assert engine_routes.engine_executable(AppSettings(acestream_path=exe)) == exe


def test_missing_configured_executable_falls_back_to_detection(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "find_engine_executable", lambda: "C:/detected/ace_engine.exe")
    settings = AppSettings(acestream_path=str(tmp_path / "gone.exe"))

    assert engine_routes.engine_executable(settings) == "C:/detected/ace_engine.exe"


# indicator and button


def test_button_is_offered_when_off_and_installed(web, db, engine, exe):
    save_settings(db, AppSettings(acestream_path=exe))

    fragment = web.get("/engine/status").text

    assert "Ace Stream apagado" in fragment
    assert 'hx-post="http://127.0.0.1/engine/start"' in fragment


def test_no_button_without_an_installed_engine(web, engine, monkeypatch):
    monkeypatch.setattr(install, "find_engine_executable", lambda: None)

    assert "engine/start" not in web.get("/engine/status").text


def test_no_button_when_running(web, db, engine, exe):
    save_settings(db, AppSettings(acestream_path=exe))
    engine.answers = [VERSION]

    assert "engine/start" not in web.get("/engine/status").text


def test_start_launches_and_waits_until_the_engine_answers(web, db, engine, exe):
    save_settings(db, AppSettings(acestream_path=exe))
    engine.answers = [None, None, None, VERSION]

    fragment = web.post("/engine/start").text

    assert engine.launched == [exe]
    assert "Ace Stream 3.1.74" in fragment
    assert 'class="engine-status up"' in fragment


def test_start_does_nothing_if_already_running(web, db, engine, exe):
    save_settings(db, AppSettings(acestream_path=exe))
    engine.answers = [VERSION]

    assert "Ace Stream 3.1.74" in web.post("/engine/start").text
    assert engine.launched == []


def test_start_without_an_executable_says_where_to_set_it(web, engine, monkeypatch):
    monkeypatch.setattr(install, "find_engine_executable", lambda: None)

    fragment = web.post("/engine/start").text

    assert "No se encontró ace_engine.exe" in fragment
    assert engine.launched == []


def test_start_that_never_answers_times_out(web, db, engine, exe, monkeypatch):
    save_settings(db, AppSettings(acestream_path=exe))
    monkeypatch.setattr(engine_routes, "START_TIMEOUT", 0)

    fragment = web.post("/engine/start").text

    assert engine.launched == [exe]
    assert "Ace Stream no respondió en 0 s." in fragment
    assert 'class="engine-status down"' in fragment


def test_start_reports_a_launch_failure(web, db, engine, exe, monkeypatch):
    save_settings(db, AppSettings(acestream_path=exe))

    def fail(path):
        raise EngineStartError("could not start the engine: denied")

    monkeypatch.setattr(install, "start_engine", fail)

    assert (
        "No se pudo iniciar: could not start the engine: denied" in web.post("/engine/start").text
    )


def test_start_from_another_site_is_rejected(web, db, engine, exe):
    save_settings(db, AppSettings(acestream_path=exe))

    response = web.post("/engine/start", headers={"origin": "http://attacker.example"})

    assert response.status_code == 403
    assert engine.launched == []
