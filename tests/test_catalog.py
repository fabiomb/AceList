from pathlib import Path

import httpx
import pytest

from app.acestream.client import EngineClient
from app.db.base import Base
from app.db.models import CheckStatus, Resolution
from app.db.session import make_engine, make_session_factory
from app.services import catalog, categories, channels, checks
from app.services.errors import DuplicateError, NotFoundError, ValidationError
from app.services.screenshots import CaptureSettings, ScreenshotError
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
        content = b"jpg"  # not a real JPEG unless a test sets one

        def __call__(self, playback_url, content_id, *, data_dir, **options):
            self.calls.append((playback_url, content_id, data_dir))
            self.options = options
            if self.fail:
                raise ScreenshotError("ffmpeg produced no frame")
            relative = f"screenshots/{content_id}_{len(self.calls)}.jpg"
            target = Path(data_dir) / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.content)
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


def test_capture_settings_reach_ffmpeg(session, client, engine, shots, tmp_path):
    capture = CaptureSettings(ffmpeg_path="C:/tools/ffmpeg.exe", timeout=7)

    add(session, client, tmp_path, capture=capture)

    assert shots.options == {"ffmpeg_path": "C:/tools/ffmpeg.exe", "timeout": 7}


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


# screenshots: only when missing, unless forced


def recheck(session, client, tmp_path, channel_id, **kwargs):
    return catalog.check_channel(
        session, client, channel_id, settings=FAST, data_dir=tmp_path, **kwargs
    )


def test_a_channel_with_a_screenshot_is_not_captured_again(
    session, client, engine, shots, tmp_path
):
    channel = add(session, client, tmp_path)

    check = recheck(session, client, tmp_path, channel.id)

    assert check.status is CheckStatus.ALIVE
    assert check.screenshot_path is None
    assert len(shots.calls) == 1


def test_forcing_takes_a_new_screenshot(session, client, engine, shots, tmp_path):
    channel = add(session, client, tmp_path)

    check = recheck(session, client, tmp_path, channel.id, force_capture=True)

    assert check.screenshot_path is not None
    assert len(shots.calls) == 2


def test_a_channel_whose_screenshot_failed_gets_one_next_time(
    session, client, engine, shots, tmp_path
):
    shots.fail = True
    channel = add(session, client, tmp_path)
    shots.fail = False

    check = recheck(session, client, tmp_path, channel.id)

    assert check.screenshot_path is not None


def test_a_new_hash_always_gets_a_new_screenshot(session, client, engine, shots, tmp_path):
    channel = add(session, client, tmp_path, link=HASH_A)

    edit(session, client, tmp_path, channel.id, link=HASH_B)

    assert len(shots.calls) == 2
    assert shots.calls[1][1] == HASH_B


# resolution


def test_a_screenshot_records_its_size_and_the_channel_resolution(
    session, client, engine, shots, tmp_path, make_jpeg
):
    shots.content = make_jpeg(1280, 720)

    channel = add(session, client, tmp_path, resolution="4k")

    check = checks.get_latest_check(session, channel.id)
    assert (check.width, check.height) == (1280, 720)
    # Detected from the stream, it replaces the value chosen by hand.
    assert channels.get_channel(session, channel.id).resolution is Resolution.HD


def test_without_a_readable_screenshot_the_resolution_is_kept(
    session, client, engine, shots, tmp_path
):
    channel = add(session, client, tmp_path, resolution="1080p")

    check = checks.get_latest_check(session, channel.id)
    assert (check.width, check.height) == (None, None)
    assert channels.get_channel(session, channel.id).resolution is Resolution.FULL_HD


# names from the stream


def media_files(respx_mock, **answer):
    return respx_mock.get(f"{BASE}/server/api").respond(json=answer)


def test_an_untitled_channel_takes_the_stream_name(
    session, client, engine, shots, tmp_path, respx_mock
):
    media_files(respx_mock, result={"name": "DAZN 1 1080 https://t.me/ads"})

    channel = add(session, client, tmp_path, title="  ")

    stored = channels.get_channel(session, channel.id)
    assert (stored.title, stored.title_pending) == ("DAZN 1 1080", False)


def test_without_a_stream_name_the_title_stays_provisional_until_a_later_check(
    session, client, engine, shots, tmp_path, respx_mock
):
    route = media_files(respx_mock, error={"message": "cannot get transport file"})
    channel = add(session, client, tmp_path, title="")
    stored = channels.get_channel(session, channel.id)
    assert (stored.title, stored.title_pending) == (f"Canal {HASH_A[:8]}", True)

    route.respond(json={"result": {"name": "Canal Real"}})
    recheck(session, client, tmp_path, channel.id)

    stored = channels.get_channel(session, channel.id)
    assert (stored.title, stored.title_pending) == ("Canal Real", False)


def test_engine_down_while_naming_keeps_the_provisional_title(
    session, client, engine, shots, tmp_path, respx_mock
):
    respx_mock.get(f"{BASE}/server/api").mock(side_effect=httpx.ConnectError("refused"))

    channel = add(session, client, tmp_path, title="")

    stored = channels.get_channel(session, channel.id)
    assert stored.title_pending
    # The check itself still ran.
    assert checks.get_latest_check(session, channel.id).status is CheckStatus.ALIVE


def test_a_title_the_user_wrote_is_never_replaced(
    session, client, engine, shots, tmp_path, respx_mock
):
    route = media_files(respx_mock, result={"name": "Stream"})

    channel = add(session, client, tmp_path, title="Mío")
    recheck(session, client, tmp_path, channel.id)

    assert channels.get_channel(session, channel.id).title == "Mío"
    assert not route.called


def test_renaming_a_provisional_title_makes_it_final(
    session, client, engine, shots, tmp_path, respx_mock
):
    route = media_files(respx_mock, error={"message": "cannot get transport file"})
    channel = add(session, client, tmp_path, title="")

    channels.update_channel(session, channel.id, title=f"Canal {HASH_A[:8]}")  # unchanged
    assert channels.get_channel(session, channel.id).title_pending
    channels.update_channel(session, channel.id, title="Elegido")
    route.respond(json={"result": {"name": "Stream"}})
    recheck(session, client, tmp_path, channel.id)

    stored = channels.get_channel(session, channel.id)
    assert (stored.title, stored.title_pending) == ("Elegido", False)
