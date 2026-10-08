import threading

import pytest

from app.db.models import CheckStatus
from app.main import app
from app.services import channels, checks
from app.services.catalog import Screenshots
from app.web import check_routes

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"


@pytest.fixture
def two(db):
    uno = channels.create_channel(db, title="Uno", content_id=HASH_A)
    dos = channels.create_channel(db, title="Dos", content_id=HASH_B)
    return uno, dos


@pytest.fixture
def blocked(web):
    """A batch held running until the test ends."""
    gate = threading.Event()

    def work(channel_id):
        assert gate.wait(5)
        return CheckStatus.ALIVE

    batch = app.state.check_runner.submit([101, 102], work, max_workers=1)
    yield batch
    gate.set()
    batch.finished_event.wait(5)


def test_list_offers_to_check_what_it_shows(web, two):
    page = web.get("/?q=o&sort=title&dir=asc").text

    assert 'action="http://127.0.0.1/checks?q=o&amp;sort=title&amp;dir=asc"' in page
    assert "Verificar los 2 canales" in page
    assert "Verificar este canal" in web.get("/?q=uno").text


def test_checking_the_filtered_list_checks_only_those_channels(
    web, db, two, engine_empty, wait_for_checks
):
    uno, dos = two

    response = web.post("/checks?q=uno", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "http://127.0.0.1/?q=uno"
    wait_for_checks()
    assert [c.status for c in checks.list_checks(db, uno.id)] == [CheckStatus.NOT_FOUND]
    assert checks.list_checks(db, dos.id) == []
    batch = app.state.check_runner.current()
    assert (batch.total, batch.counts["not_found"]) == (1, 1)


def test_nothing_matching_starts_nothing(web, two):
    response = web.post("/checks?q=nada", follow_redirects=False)

    assert response.status_code == 303
    assert app.state.check_runner.current() is None


def test_running_batch_is_shown_on_every_page_and_polled(web, two, blocked):
    page = web.get(f"/channels/{two[0].id}").text

    assert "Verificando canales: 0 de 2" in page
    assert 'hx-trigger="every 1s"' in page
    assert f'"watching": "{blocked.id}"' in page


def test_status_reloads_the_watching_page_once_the_batch_ends(web, wait_for_checks):
    app.state.check_runner.submit([1], lambda _: CheckStatus.NO_PEERS, max_workers=1)
    wait_for_checks()
    batch = app.state.check_runner.current()

    watched = web.get(f"/checks/status?watching={batch.id}")
    other = web.get("/checks/status?watching=old")

    assert watched.headers.get("HX-Refresh") == "true"
    assert "HX-Refresh" not in other.headers
    assert "Verificación terminada: 1 canal" in watched.text
    assert "Sin peers: 1" in watched.text
    assert "every 1s" not in watched.text


def test_dismiss_hides_a_finished_batch(web, wait_for_checks):
    app.state.check_runner.submit([1], lambda _: CheckStatus.ALIVE, max_workers=1)
    wait_for_checks()

    response = web.post("/checks/dismiss")

    assert response.text.strip() == '<div id="batch-status"></div>'
    assert "Verificación terminada" not in web.get("/").text


def test_detail_check_runs_in_the_background(web, db, two, engine_down, blocked):
    uno, _ = two

    response = web.post(f"/channels/{uno.id}/check", follow_redirects=False)

    assert response.status_code == 303
    # It joined the running batch instead of waiting for the engine.
    assert blocked.total == 3


def test_starting_checks_from_another_site_is_rejected(web, two):
    response = web.post("/checks", headers={"origin": "http://attacker.example"})

    assert response.status_code == 403
    assert app.state.check_runner.current() is None


def test_import_page_never_asks_for_a_reload(web, blocked):
    page = web.get("/import").text

    assert 'hx-trigger="every 1s"' in page
    assert '"watching": ""' in page


def test_polling_keeps_what_the_page_watches(web, blocked):
    assert f'"watching": "{blocked.id}"' in web.get(f"/checks/status?watching={blocked.id}").text
    assert '"watching": ""' in web.get("/checks/status?watching=").text


@pytest.fixture
def checked(monkeypatch):
    """Records whether each background check forces a screenshot, instead of running it."""
    calls = []

    def fake_check(session, client, channel_id, **kwargs):
        calls.append((channel_id, kwargs["screenshots"] is Screenshots.ALWAYS))
        return checks.add_check(session, channel_id, status=CheckStatus.ALIVE)

    monkeypatch.setattr(check_routes.catalog, "check_channel", fake_check)
    return calls


def test_list_offers_to_regenerate_screenshots_with_a_warning(web, two):
    page = web.get("/?q=o").text

    assert 'action="http://127.0.0.1/checks/screenshots?q=o"' in page
    assert 'hx-confirm="Regenerar las capturas de los 2 canales:' in page
    assert "Tarda bastante más" in page


def test_regenerating_forces_screenshots_of_the_listed_channels(
    web, two, engine_down, checked, wait_for_checks
):
    response = web.post("/checks/screenshots?q=uno", follow_redirects=False)
    wait_for_checks()

    assert response.headers["location"] == "http://127.0.0.1/?q=uno"
    assert checked == [(two[0].id, True)]


def test_plain_checks_do_not_force_screenshots(web, two, engine_down, checked, wait_for_checks):
    web.post("/checks")
    wait_for_checks()

    assert sorted(checked) == sorted([(two[0].id, False), (two[1].id, False)])


def test_detail_new_screenshot_forces_one(web, two, engine_down, checked, wait_for_checks):
    uno, _ = two
    page = web.get(f"/channels/{uno.id}").text
    assert "Nueva captura" in page and "hx-confirm=" in page

    response = web.post(f"/channels/{uno.id}/screenshot", follow_redirects=False)
    wait_for_checks()

    assert response.headers["location"] == f"http://127.0.0.1/channels/{uno.id}"
    assert checked == [(uno.id, True)]
    assert web.post("/channels/999/screenshot").status_code == 404


def test_import_takes_screenshots_only_of_new_channels(
    web, db, engine_down, monkeypatch, wait_for_checks
):
    modes = []

    def fake_check(session, client, channel_id, **kwargs):
        modes.append(kwargs["screenshots"])
        return checks.add_check(session, channel_id, status=CheckStatus.ALIVE)

    monkeypatch.setattr(check_routes.catalog, "check_channel", fake_check)

    web.post("/import", data={"links": HASH_A})
    wait_for_checks()

    assert modes == [Screenshots.IF_MISSING]


def test_a_batch_that_loses_the_engine_stops_and_blames_no_channel(
    web, db, two, engine_down, wait_for_checks
):
    # #62: an engine that is off says nothing about the channels.
    web.post("/checks")
    wait_for_checks()

    batch = app.state.check_runner.current()
    assert batch.aborted == check_routes.ENGINE_UNAVAILABLE
    assert batch.done == 0
    assert all(checks.list_checks(db, channel.id) == [] for channel in two)
    page = web.get("/").text
    assert "Verificación interrumpida" in page
    assert "Ace Stream no responde" in page
    assert "status-error" not in page
