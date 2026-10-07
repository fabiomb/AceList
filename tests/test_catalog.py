from pathlib import Path

import httpx
import pytest

from app.acestream.client import EngineClient
from app.db.base import Base
from app.db.models import CheckStatus
from app.db.session import make_engine, make_session_factory
from app.services import catalog, categories, channels, checks
from app.services.errors import DuplicateError, NotFoundError, ValidationError
from app.services.screenshots import ScreenshotError
from app.services.verification import VerificationSettings

BASE = "http://127.0.0.1:6878"
HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"
INFOHASH = "25f4c7b60edb0433343c777846924d35c65ec4f9"
PATH = f"{INFOHASH}/f4283e11274fae1ced9ef41a4c173857"
FAST = VerificationSettings(timeout=0.05, poll_interval=0.01)

GETSTREAM = {
    "response": {
        "stat_url": f"{BASE}/ace/stat/{PATH}",
        "playback_url": f"{BASE}/ace/r/{PATH}",
        "command_url": f"{BASE}/ace/cmd/{PATH}",
        "infohash": INFOHASH,
    },
    "error": None,
}
STAT_ALIVE = {
    "response": {"status": "dl", "peers": 3, "speed_down": 1200, "downloaded": 10_000_000},
    "error": None,
}
STAT_NO_DATA = {
    "response": {"status": "prebuf", "peers": 2, "speed_down": 0, "downloaded": 0},
    "error": None,
}


@pytest.fixture
def session():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()


@pytest.fixture
def client():
    with EngineClient(BASE, timeout=1) as c:
        yield c


@pytest.fixture
def engine(respx_mock):
    class Engine:
        def __init__(self):
            self.getstream = respx_mock.get(f"{BASE}/ace/getstream").respond(json=GETSTREAM)
            self.stat = respx_mock.get(f"{BASE}/ace/stat/{PATH}").respond(json=STAT_ALIVE)
            self.stop = respx_mock.get(f"{BASE}/ace/cmd/{PATH}").respond(
                json={"response": "ok", "error": None}
            )

    return Engine()


@pytest.fixture
def shots(monkeypatch, tmp_path):
    """Replaces ffmpeg: records calls and writes a real file like the real thing would."""

    class Shots:
        calls = []
        fail = False

        def __call__(self, playback_url, content_id, *, data_dir):
            self.calls.append((playback_url, content_id, data_dir))
            if self.fail:
                raise ScreenshotError("ffmpeg produced no frame")
            relative = f"screenshots/{content_id}_{len(self.calls)}.jpg"
            target = Path(data_dir) / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"jpg")
            return relative

    fake = Shots()
    monkeypatch.setattr(catalog, "capture_screenshot", fake)
    return fake


def add(session, client, tmp_path, link=HASH_A, **kwargs):
    return catalog.add_channel(
        session,
        client,
        title=kwargs.pop("title", "Match"),
        link=link,
        settings=FAST,
        data_dir=tmp_path,
        **kwargs,
    )


# add_channel


def test_add_channel_normalizes_the_link_and_stores_an_alive_check_with_screenshot(
    session, client, engine, shots, tmp_path
):
    channel = add(session, client, tmp_path, link=f"acestream://{HASH_A.upper()}")

    assert channel.content_id == HASH_A
    check = checks.get_latest_check(session, channel.id)
    assert check.status is CheckStatus.ALIVE
    assert (check.peers, check.infohash) == (3, INFOHASH)
    assert check.screenshot_path == f"screenshots/{HASH_A}_1.jpg"
    assert shots.calls == [(f"{BASE}/ace/r/{PATH}", HASH_A, tmp_path)]
    assert engine.stop.call_count == 1


def test_add_channel_keeps_category_language_and_country(session, client, engine, shots, tmp_path):
    sports = categories.create_category(session, "Sports")

    channel = add(session, client, tmp_path, category_id=sports.id, language="es", country="AR")

    assert (channel.category_id, channel.language, channel.country) == (sports.id, "es", "AR")


def test_unknown_content_is_saved_with_a_not_found_check(session, client, respx_mock, tmp_path):
    respx_mock.get(f"{BASE}/ace/getstream").respond(
        json={"response": None, "error": "failed to load content"}
    )

    channel = add(session, client, tmp_path)

    assert checks.get_latest_check(session, channel.id).status is CheckStatus.NOT_FOUND


def test_engine_down_still_saves_the_channel_with_an_error_check(
    session, client, respx_mock, tmp_path
):
    respx_mock.get(f"{BASE}/ace/getstream").mock(side_effect=httpx.ConnectError("refused"))

    channel = add(session, client, tmp_path)

    assert channels.get_channel(session, channel.id).content_id == HASH_A
    check = checks.get_latest_check(session, channel.id)
    assert check.status is CheckStatus.ERROR
    assert "cannot reach the engine" in check.error_message


def test_no_screenshot_is_attempted_when_the_channel_is_not_alive(
    session, client, engine, shots, tmp_path
):
    engine.stat.respond(json=STAT_NO_DATA)

    channel = add(session, client, tmp_path)

    assert checks.get_latest_check(session, channel.id).status is CheckStatus.NO_PEERS
    assert shots.calls == []


def test_screenshot_failure_does_not_spoil_an_alive_check(session, client, engine, shots, tmp_path):
    shots.fail = True

    channel = add(session, client, tmp_path)

    check = checks.get_latest_check(session, channel.id)
    assert check.status is CheckStatus.ALIVE
    assert check.screenshot_path is None
    assert engine.stop.call_count == 1


def test_duplicate_is_rejected_naming_the_existing_channel_without_touching_the_engine(
    session, client, engine, shots, tmp_path
):
    add(session, client, tmp_path, title="Original")
    calls_before = engine.getstream.call_count

    with pytest.raises(DuplicateError, match="'Original'"):
        add(session, client, tmp_path, link=f"acestream://{HASH_A}", title="Copy")

    assert engine.getstream.call_count == calls_before
    assert len(channels.list_channels(session)) == 1


@pytest.mark.parametrize("link", ["nope", "", f"http://{HASH_A}", HASH_A[:-1]])
def test_invalid_link_is_a_validation_error_and_creates_nothing(
    session, client, respx_mock, tmp_path, link
):
    with pytest.raises(ValidationError, match="Content ID"):
        add(session, client, tmp_path, link=link)

    assert channels.list_channels(session) == []
    assert respx_mock.calls.call_count == 0


def test_unknown_category_creates_nothing_and_skips_verification(
    session, client, respx_mock, tmp_path
):
    with pytest.raises(NotFoundError):
        add(session, client, tmp_path, category_id=99)

    assert channels.list_channels(session) == []
    assert respx_mock.calls.call_count == 0


# edit_channel


def edit(session, client, tmp_path, channel_id, **kwargs):
    return catalog.edit_channel(
        session, client, channel_id, settings=FAST, data_dir=tmp_path, **kwargs
    )


def test_editing_the_title_does_not_verify_again(session, client, engine, shots, tmp_path):
    channel = add(session, client, tmp_path)
    calls = engine.getstream.call_count

    edited = edit(session, client, tmp_path, channel.id, title="Final", language="en")

    assert (edited.title, edited.language) == ("Final", "en")
    assert engine.getstream.call_count == calls
    assert len(checks.list_checks(session, channel.id)) == 1


def test_changing_the_hash_verifies_again_and_keeps_the_history(
    session, client, engine, shots, tmp_path
):
    channel = add(session, client, tmp_path, link=HASH_A)
    engine.stat.respond(json=STAT_NO_DATA)

    edited = edit(session, client, tmp_path, channel.id, link=f"acestream://{HASH_B.upper()}")

    assert edited.content_id == HASH_B
    assert engine.getstream.calls.last.request.url.params["id"] == HASH_B
    history = checks.list_checks(session, channel.id)
    assert [c.status for c in history] == [CheckStatus.NO_PEERS, CheckStatus.ALIVE]


def test_the_same_hash_in_another_form_is_not_a_change(session, client, engine, shots, tmp_path):
    channel = add(session, client, tmp_path, link=HASH_A)
    calls = engine.getstream.call_count

    edit(session, client, tmp_path, channel.id, link=f"acestream://{HASH_A.upper()}")

    assert engine.getstream.call_count == calls


def test_changing_to_a_registered_hash_is_rejected_and_leaves_the_channel_untouched(
    session, client, engine, shots, tmp_path
):
    add(session, client, tmp_path, link=HASH_A, title="First")
    second = add(session, client, tmp_path, link=HASH_B, title="Second")

    with pytest.raises(DuplicateError, match="'First'"):
        edit(session, client, tmp_path, second.id, link=HASH_A)

    assert channels.get_channel(session, second.id).content_id == HASH_B


def test_invalid_new_link_is_rejected_and_leaves_the_channel_untouched(
    session, client, engine, shots, tmp_path
):
    channel = add(session, client, tmp_path)

    with pytest.raises(ValidationError):
        edit(session, client, tmp_path, channel.id, link="garbage", title="Other")

    assert channels.get_channel(session, channel.id).title == "Match"


def test_content_id_cannot_be_changed_around_the_link_validation(
    session, client, engine, shots, tmp_path
):
    channel = add(session, client, tmp_path)

    with pytest.raises(ValidationError, match="link"):
        edit(session, client, tmp_path, channel.id, content_id=HASH_B)


def test_editing_a_missing_channel_raises_not_found(session, client, respx_mock, tmp_path):
    with pytest.raises(NotFoundError):
        edit(session, client, tmp_path, 99, title="x")


# delete


def test_deleting_a_channel_removes_its_history_and_screenshots(
    session, client, engine, shots, tmp_path
):
    channel = add(session, client, tmp_path)
    screenshot = tmp_path / checks.get_latest_check(session, channel.id).screenshot_path
    assert screenshot.is_file()

    channels.delete_channel(session, channel.id, data_dir=tmp_path)

    assert not screenshot.exists()
    assert checks.latest_checks(session) == {}
    assert channels.list_channels(session) == []
