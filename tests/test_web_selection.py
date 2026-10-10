import pytest

from app.db.models import Channel
from app.main import app
from app.services import channels, checks
from app.services.catalog import Screenshots
from app.web import check_routes

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"
HASH_C = "efc60cfe5e3a349baa02bcc49f6647c21a9c3c5b"


@pytest.fixture
def three(db):
    return [
        channels.create_channel(db, title=title, content_id=content_id)
        for title, content_id in (("Uno", HASH_A), ("Dos", HASH_B), ("Tres", HASH_C))
    ]


@pytest.fixture
def checked(monkeypatch):
    """Records each background check and whether it forces a screenshot."""
    calls = []

    def fake_check(session, client, channel_id, **kwargs):
        calls.append((channel_id, kwargs["screenshots"] is Screenshots.ALWAYS))
        return checks.add_check(session, channel_id, status="alive")

    monkeypatch.setattr(check_routes.catalog, "check_channel", fake_check)
    return calls


def test_the_list_has_a_check_box_per_channel_and_the_selection_bar(web, three):
    page = web.get("/?sort=title").text

    assert 'form id="selection"' in page and 'data-selection="channel"' in page
    for channel in three:
        assert f'form="selection" name="channel" value="{channel.id}"' in page
    assert 'data-check-all="channel"' in page
    assert 'name="next" value="/?sort=title"' in page
    assert page.count("data-needs-selection disabled") == 3
    assert 'data-confirm="¿Borrar los canales elegidos' in page


def test_an_empty_list_has_no_selection_bar(web, db):
    assert 'id="selection"' not in web.get("/").text


@pytest.mark.parametrize(("action", "forced"), [("check", False), ("screenshots", True)])
def test_checking_the_chosen_channels(
    web, three, engine_empty, checked, wait_for_checks, action, forced
):
    uno, _, tres = three

    response = web.post(
        "/channels/selected",
        data={
            "channel": [str(tres.id), str(uno.id), str(uno.id)],
            "action": action,
            "next": "/?q=o",
        },
        follow_redirects=False,
    )
    wait_for_checks()

    assert response.status_code == 303 and response.headers["location"] == "/?q=o"
    assert sorted(checked) == sorted([(uno.id, forced), (tres.id, forced)])
    assert app.state.check_runner.current().total == 2


def test_deleting_the_chosen_channels(web, db, three):
    uno, dos, tres = three

    response = web.post(
        "/channels/selected",
        data={"channel": [str(uno.id), str(tres.id), "999"], "action": "delete", "next": "/"},
        follow_redirects=False,
    )

    assert response.headers["location"] == "/"
    db.expire_all()
    assert [c.title for c in db.query(Channel)] == ["Dos"]


def test_nothing_chosen_does_nothing(web, db, three, checked):
    response = web.post(
        "/channels/selected", data={"action": "delete", "next": "/"}, follow_redirects=False
    )

    assert response.status_code == 303
    assert db.query(Channel).count() == 3 and checked == []
    assert app.state.check_runner.current() is None


def test_checks_need_the_engine(web, three, engine_down, checked):
    page = web.post(
        "/channels/selected", data={"channel": [str(three[0].id)], "action": "check", "next": "/"}
    ).text

    assert "Ace Stream no está abierto" in page
    assert checked == []


@pytest.mark.parametrize("target", ["https://attacker.example/", "//attacker.example/", ""])
def test_it_never_redirects_outside_the_app(web, three, target):
    response = web.post(
        "/channels/selected",
        data={"channel": [str(three[0].id)], "action": "delete", "next": target},
        follow_redirects=False,
    )

    assert response.headers["location"] == "http://127.0.0.1/"


def test_unknown_actions_are_rejected(web, three):
    response = web.post(
        "/channels/selected", data={"channel": [str(three[0].id)], "action": "export"}
    )

    assert response.status_code == 400


def test_selection_from_another_site_is_rejected(web, three):
    response = web.post(
        "/channels/selected",
        data={"channel": [str(three[0].id)], "action": "delete"},
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 403
