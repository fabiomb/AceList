from app.services.settings import AppSettings, save_settings

VERSION = {"result": {"version": "3.1.74", "code": 3017400, "platform": "win32"}, "error": None}


def test_pages_load_the_indicator_without_waiting_for_the_engine(web, engine_down):
    page = web.get("/").text

    assert 'id="engine-status"' in page
    assert 'hx-get="http://127.0.0.1/engine/status"' in page
    assert 'hx-trigger="load, every 30s"' in page
    assert "Ace Stream…" in page
    # Rendering the page never asks the engine: the indicator does, afterwards.
    assert not engine_down.called


def test_indicator_shows_the_engine_version(web, engine_empty):
    fragment = web.get("/engine/status").text

    assert 'class="engine-status up"' in fragment
    assert "Ace Stream 3.1.74" in fragment
    assert 'title="Engine en ' in fragment
    assert 'hx-trigger="every 30s"' in fragment


def test_indicator_shows_an_engine_that_is_off(web, engine_down):
    fragment = web.get("/engine/status").text

    assert 'class="engine-status down"' in fragment
    assert "Ace Stream apagado" in fragment
    assert engine_down.called


def test_indicator_names_the_configured_url(web, db, respx_mock):
    save_settings(db, AppSettings(engine_url="http://10.0.0.9:6878", engine_timeout=1))
    respx_mock.get("http://10.0.0.9:6878/webui/api/service").respond(json=VERSION)

    fragment = web.get("/engine/status").text

    assert 'title="Engine en http://10.0.0.9:6878"' in fragment
    assert "Ace Stream 3.1.74" in fragment
