from datetime import UTC, datetime, timedelta

from app.db.models import CheckStatus
from app.services import categories, channels, checks

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
INFOHASH = "25f4c7b60edb0433343c777846924d35c65ec4f9"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def local(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def test_detail_shows_channel_data(web, db):
    sports = categories.create_category(db, "Deportes")
    channel = channels.create_channel(
        db, title="Uno", content_id=HASH_A, category_id=sports.id, language="es", country="AR"
    )

    page = web.get(f"/channels/{channel.id}").text

    assert "<h1>Uno</h1>" in page
    assert HASH_A in page
    assert f"acestream://{HASH_A}" in page
    assert "Deportes" in page
    assert "Spanish (es)" in page
    assert "Argentina (AR)" in page
    assert "Este canal todavía no se ha verificado." in page
    assert "Sin capturas todavía" in page


def test_history_is_listed_newest_first_with_every_field(web, db):
    channel = channels.create_channel(db, title="Uno", content_id=HASH_A)
    old = NOW - timedelta(days=2)
    checks.add_check(
        db,
        channel.id,
        status=CheckStatus.ALIVE,
        peers=12,
        speed_down=345,
        infohash=INFOHASH,
        screenshot_path="screenshots/old.jpg",
        checked_at=old,
    )
    checks.add_check(
        db,
        channel.id,
        status=CheckStatus.NOT_FOUND,
        error_message="gone <for good>",
        checked_at=NOW,
    )

    page = web.get(f"/channels/{channel.id}").text
    history = page[page.index("Historial de verificaciones") :]

    assert history.index(local(NOW)) < history.index(local(old))
    assert ">345<" in history
    assert f'title="{INFOHASH}"' in history
    assert "gone &lt;for good&gt;" in page
    assert "No encontrado" in page
    # The latest check failed, but the newest screenshot is still shown at the top.
    assert 'src="/screenshots/old.jpg" alt="Última captura de Uno"' in page
    assert f"Captura del {local(old)}" in page


def test_list_links_titles_to_the_detail(web, db):
    channel = channels.create_channel(db, title="Uno", content_id=HASH_A)

    page = web.get("/").text

    assert f'<a href="http://127.0.0.1/channels/{channel.id}">Uno</a>' in page


def test_check_again_stores_a_new_check_and_returns_to_the_detail(web, db, engine_down):
    channel = channels.create_channel(db, title="Uno", content_id=HASH_A)

    response = web.post(f"/channels/{channel.id}/check", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"http://127.0.0.1/channels/{channel.id}"
    [check] = checks.list_checks(db, channel.id)
    assert check.status == CheckStatus.ERROR
    assert engine_down.called
    assert "Error" in web.get(f"/channels/{channel.id}").text


def test_missing_channel_is_404(web, engine_down):
    assert web.get("/channels/999").status_code == 404
    assert web.post("/channels/999/check").status_code == 404
    assert not engine_down.called


def test_check_again_from_another_site_is_rejected(web, db, engine_down):
    channel = channels.create_channel(db, title="Uno", content_id=HASH_A)

    response = web.post(
        f"/channels/{channel.id}/check", headers={"origin": "http://attacker.example"}
    )

    assert response.status_code == 403
    assert not engine_down.called
