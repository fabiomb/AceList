import httpx
import pytest

from app.main import app
from app.services import channels
from app.services.settings import AppSettings, load_settings, save_settings
from app.web import settings_routes
from app.web.deps import get_engine_factory

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"


@pytest.fixture
def detected(monkeypatch):
    """Fixed autodetection results, so tests do not depend on this machine."""
    found = {"vlc_path": None, "ffmpeg_path": None, "acestream_path": None}
    monkeypatch.setattr(settings_routes, "detect_paths", lambda: dict(found))
    return found


@pytest.fixture
def exe(tmp_path):
    path = tmp_path / "tool.exe"
    path.write_bytes(b"")
    return str(path)


def form(**fields):
    values = {
        "engine_url": "http://127.0.0.1:6878",
        "engine_timeout": "15",
        "min_peers": "1",
        "check_timeout": "20",
        "screenshot_timeout": "30",
        "check_concurrency": "2",
        "vlc_path": "",
        "ffmpeg_path": "",
        "acestream_path": "",
    }
    values.update(fields)
    return values


def test_page_shows_current_values_and_what_was_detected(web, db, detected):
    save_settings(db, AppSettings(min_peers=4))
    detected["vlc_path"] = "C:/Program Files/VideoLAN/VLC/vlc.exe"

    page = web.get("/settings").text

    assert "<h1>Ajustes</h1>" in page
    assert 'name="min_peers" type="text" inputmode="decimal" required value="4"' in page
    assert 'Detectado: <code class="wrap">C:/Program Files/VideoLAN/VLC/vlc.exe</code>' in page
    assert "Probar conexión" in page


def test_nav_links_to_settings(web, detected):
    assert 'href="http://127.0.0.1/settings"' in web.get("/").text


def test_saving_stores_the_settings(web, db, detected, exe):
    response = web.post(
        "/settings",
        data=form(
            engine_url=" http://127.0.0.1:6878/ ",
            engine_timeout="7,5",
            min_peers="2",
            vlc_path=f'"{exe}"',
        ),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "http://127.0.0.1/settings?saved=true"
    saved = load_settings(db)
    assert saved.engine_url == "http://127.0.0.1:6878"
    assert saved.engine_timeout == 7.5
    assert saved.min_peers == 2
    assert saved.vlc_path == exe
    assert saved.ffmpeg_path is None
    assert "Ajustes guardados." in web.get(response.headers["location"]).text


def test_invalid_values_are_explained_and_nothing_is_saved(web, db, detected, tmp_path):
    response = web.post(
        "/settings",
        data=form(
            engine_url="ftp://engine",
            engine_timeout="0",
            min_peers="1.5",
            check_timeout="abc",
            vlc_path=str(tmp_path / "missing.exe"),
        ),
    )

    assert response.status_code == 422
    page = response.text
    assert "Debe ser una URL http:// o https://" in page
    assert "Debe ser un número entre 1 y 120." in page
    assert "Debe ser un número entero entre 0 y 1000." in page
    assert "Debe ser un número entre 5 y 600." in page
    assert "No existe ese archivo." in page
    assert 'value="ftp://engine"' in page
    assert load_settings(db) == AppSettings()


def test_detect_fills_only_empty_paths_and_saves_nothing(web, db, detected, exe):
    detected.update(vlc_path="C:/detected/vlc.exe", ffmpeg_path="C:/detected/ffmpeg.exe")

    response = web.post("/settings/detect", data=form(ffmpeg_path=exe))

    page = response.text
    assert 'value="C:/detected/vlc.exe"' in page
    assert f'value="{exe}"' in page
    assert 'value="C:/detected/ffmpeg.exe"' not in page
    assert "Rutas detectadas." in page
    assert response.headers["HX-Push-Url"] == "http://127.0.0.1/settings"
    assert load_settings(db) == AppSettings()


def test_detect_says_when_nothing_new_was_found(web, detected):
    assert "No se detectaron rutas nuevas." in web.post("/settings/detect", data=form()).text


def test_engine_test_uses_the_typed_url(web, detected, respx_mock):
    route = respx_mock.get("http://10.0.0.2:6878/webui/api/service").respond(
        json={"result": {"version": "3.1.74", "code": 3017400, "platform": "win32"}}
    )

    response = web.post("/settings/test-engine", data=form(engine_url="http://10.0.0.2:6878"))

    assert response.status_code == 200
    assert "Conectado con el engine 3.1.74 (win32)." in response.text
    assert route.called


def test_engine_test_reports_an_engine_that_is_down(web, detected, respx_mock):
    respx_mock.get(url__startswith="http://10.0.0.2:6878").mock(
        side_effect=httpx.ConnectError("refused")
    )

    response = web.post("/settings/test-engine", data=form(engine_url="http://10.0.0.2:6878"))

    assert response.status_code == 503
    assert "El engine no responde en http://10.0.0.2:6878" in response.text


def test_engine_test_rejects_a_bad_url_without_any_request(web, detected, respx_mock):
    response = web.post("/settings/test-engine", data=form(engine_url="nope"))

    assert response.status_code == 503
    assert "Debe ser una URL" in response.text
    assert not respx_mock.calls


def test_saved_engine_url_is_used_for_checks(web, db, respx_mock):
    # The real engine client dependency, not the test double.
    app.dependency_overrides.pop(get_engine_factory, None)
    save_settings(db, AppSettings(engine_url="http://10.0.0.3:7000", engine_timeout=1))
    channel = channels.create_channel(db, title="Uno", content_id=HASH_A)
    route = respx_mock.get(url__startswith="http://10.0.0.3:7000").mock(
        side_effect=httpx.ConnectError("refused")
    )

    page = web.post(f"/channels/{channel.id}/check").text

    # The pre-check went to the saved URL, found nothing and started no checks.
    assert route.called
    assert app.state.check_runner.current() is None
    assert "Ace Stream no está abierto" in page


def test_settings_writes_from_other_sites_are_rejected(web, db, detected):
    response = web.post(
        "/settings", data=form(min_peers="9"), headers={"origin": "http://attacker.example"}
    )

    assert response.status_code == 403
    assert load_settings(db).min_peers == AppSettings().min_peers
