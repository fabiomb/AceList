from datetime import UTC, datetime, timedelta

import pytest

from app.db.base import Base
from app.db.models import CheckStatus
from app.db.session import make_engine, make_session_factory
from app.services import categories, channels, checks
from app.services.errors import (
    CategoryInUseError,
    DuplicateError,
    NotFoundError,
    ValidationError,
)

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"
HASH_C = "efc60cfe5e3a349baa02bcc49f6647c21a9c3c5b"


@pytest.fixture
def session():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()


# categories


def test_category_crud(session):
    sports = categories.create_category(session, "  Sports ")
    categories.create_category(session, "Movies")

    assert [c.name for c in categories.list_categories(session)] == ["Movies", "Sports"]

    categories.rename_category(session, sports.id, "Live sports")
    assert categories.get_category(session, sports.id).name == "Live sports"

    categories.delete_category(session, sports.id)
    with pytest.raises(NotFoundError):
        categories.get_category(session, sports.id)


def test_duplicate_category_is_rejected_and_session_stays_usable(session):
    categories.create_category(session, "Sports")
    with pytest.raises(DuplicateError):
        categories.create_category(session, "Sports")

    assert len(categories.list_categories(session)) == 1


def test_rename_to_existing_category_is_rejected(session):
    categories.create_category(session, "Sports")
    movies = categories.create_category(session, "Movies")

    with pytest.raises(DuplicateError):
        categories.rename_category(session, movies.id, "Sports")


def test_empty_category_name_is_rejected(session):
    with pytest.raises(ValidationError):
        categories.create_category(session, "   ")


def test_category_in_use_cannot_be_deleted_until_reassigned(session):
    sports = categories.create_category(session, "Sports")
    channel = channels.create_channel(session, title="A", content_id=HASH_A, category_id=sports.id)

    with pytest.raises(CategoryInUseError):
        categories.delete_category(session, sports.id)

    channels.update_channel(session, channel.id, category_id=None)
    categories.delete_category(session, sports.id)


# channels


def test_channel_crud(session):
    sports = categories.create_category(session, "Sports")
    channel = channels.create_channel(
        session,
        title=" Match ",
        content_id=HASH_A,
        category_id=sports.id,
        language="es",
        country="AR",
    )

    assert channel.title == "Match"
    assert channels.get_channel(session, channel.id).content_id == HASH_A

    updated = channels.update_channel(session, channel.id, title="Final", language="en")
    assert (updated.title, updated.language, updated.country) == ("Final", "en", "AR")

    channels.delete_channel(session, channel.id)
    with pytest.raises(NotFoundError):
        channels.get_channel(session, channel.id)


def test_list_channels_is_ordered_by_title(session):
    channels.create_channel(session, title="b", content_id=HASH_A)
    channels.create_channel(session, title="a", content_id=HASH_B)

    assert [c.title for c in channels.list_channels(session)] == ["a", "b"]


def test_duplicate_content_id_is_rejected(session):
    channels.create_channel(session, title="A", content_id=HASH_A)
    with pytest.raises(DuplicateError):
        channels.create_channel(session, title="B", content_id=HASH_A)

    assert len(channels.list_channels(session)) == 1


def test_update_content_id_to_existing_one_is_rejected(session):
    channels.create_channel(session, title="A", content_id=HASH_A)
    other = channels.create_channel(session, title="B", content_id=HASH_B)

    with pytest.raises(DuplicateError):
        channels.update_channel(session, other.id, content_id=HASH_A)

    assert channels.get_channel(session, other.id).content_id == HASH_B


def test_malformed_content_id_is_a_validation_error_not_a_duplicate(session):
    with pytest.raises(ValidationError):
        channels.create_channel(session, title="A", content_id="nope")


def test_empty_title_is_rejected(session):
    with pytest.raises(ValidationError):
        channels.create_channel(session, title=" ", content_id=HASH_A)


def test_unknown_category_is_rejected(session):
    with pytest.raises(NotFoundError):
        channels.create_channel(session, title="A", content_id=HASH_A, category_id=999)


def test_update_rejects_unknown_fields(session):
    channel = channels.create_channel(session, title="A", content_id=HASH_A)
    with pytest.raises(ValidationError):
        channels.update_channel(session, channel.id, id=99)


def test_missing_channel_raises_not_found(session):
    with pytest.raises(NotFoundError):
        channels.get_channel(session, 1)
    with pytest.raises(NotFoundError):
        channels.delete_channel(session, 1)


def test_delete_channel_removes_history_and_screenshots(session, tmp_path):
    shot = tmp_path / "screenshots" / "a.jpg"
    shot.parent.mkdir()
    shot.write_bytes(b"jpg")
    channel = channels.create_channel(session, title="A", content_id=HASH_A)
    checks.add_check(
        session, channel.id, status=CheckStatus.ALIVE, screenshot_path="screenshots/a.jpg"
    )
    checks.add_check(session, channel.id, status=CheckStatus.NO_PEERS)

    channels.delete_channel(session, channel.id, data_dir=tmp_path)

    assert not shot.exists()
    assert checks.latest_checks(session) == {}


def test_delete_channel_ignores_missing_screenshot_file(session, tmp_path):
    channel = channels.create_channel(session, title="A", content_id=HASH_A)
    checks.add_check(
        session, channel.id, status=CheckStatus.ALIVE, screenshot_path="screenshots/gone.jpg"
    )

    channels.delete_channel(session, channel.id, data_dir=tmp_path)


def test_delete_channel_never_removes_files_outside_data_dir(session, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("keep me")
    channel = channels.create_channel(session, title="A", content_id=HASH_A)
    checks.add_check(session, channel.id, status=CheckStatus.ALIVE, screenshot_path="../secret.txt")

    channels.delete_channel(session, channel.id, data_dir=data_dir)

    assert outside.exists()


# checks


def test_checks_history_is_newest_first(session):
    channel = channels.create_channel(session, title="A", content_id=HASH_A)
    now = datetime.now(UTC)
    checks.add_check(
        session, channel.id, status=CheckStatus.NO_PEERS, checked_at=now - timedelta(days=2)
    )
    checks.add_check(session, channel.id, status=CheckStatus.ALIVE, peers=4, checked_at=now)

    history = checks.list_checks(session, channel.id)

    assert [c.status for c in history] == [CheckStatus.ALIVE, CheckStatus.NO_PEERS]
    assert checks.get_latest_check(session, channel.id).peers == 4


def test_latest_check_is_none_for_unchecked_channel(session):
    channel = channels.create_channel(session, title="A", content_id=HASH_A)
    assert checks.get_latest_check(session, channel.id) is None


def test_latest_checks_returns_one_per_channel(session):
    a = channels.create_channel(session, title="A", content_id=HASH_A)
    b = channels.create_channel(session, title="B", content_id=HASH_B)
    channels.create_channel(session, title="C", content_id=HASH_C)  # never checked
    now = datetime.now(UTC)
    checks.add_check(
        session, a.id, status=CheckStatus.NO_PEERS, checked_at=now - timedelta(hours=1)
    )
    checks.add_check(session, a.id, status=CheckStatus.ALIVE, checked_at=now)
    checks.add_check(session, b.id, status=CheckStatus.NOT_FOUND, checked_at=now)

    latest = checks.latest_checks(session)

    assert set(latest) == {a.id, b.id}
    assert latest[a.id].status == CheckStatus.ALIVE
    assert latest[b.id].status == CheckStatus.NOT_FOUND


def test_add_check_for_missing_channel_raises_not_found(session):
    with pytest.raises(NotFoundError):
        checks.add_check(session, 1, status=CheckStatus.ERROR)
