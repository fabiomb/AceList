from datetime import UTC, datetime, timedelta

import pytest

from app.db.base import Base
from app.db.models import CheckStatus
from app.db.session import make_engine, make_session_factory
from app.services import channels, checks
from app.services.errors import NotFoundError
from app.services.verification import VerificationResult

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"
INFOHASH = "25f4c7b60edb0433343c777846924d35c65ec4f9"


@pytest.fixture
def session():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()


@pytest.fixture
def channel(session):
    return channels.create_channel(session, title="A", content_id=HASH_A)


def test_record_verification_stores_every_field(session, channel):
    result = VerificationResult(CheckStatus.ALIVE, peers=5, speed_down=1348, infohash=INFOHASH)

    check = checks.record_verification(
        session, channel.id, result, screenshot_path="screenshots/a.jpg"
    )
    session.expire_all()
    stored = checks.get_latest_check(session, channel.id)

    assert stored.id == check.id
    assert stored.status is CheckStatus.ALIVE
    assert (stored.peers, stored.speed_down, stored.infohash) == (5, 1348, INFOHASH)
    assert stored.screenshot_path == "screenshots/a.jpg"
    assert stored.error_message is None
    assert datetime.now(UTC) - stored.checked_at < timedelta(seconds=5)
    assert stored.checked_at.tzinfo is UTC


@pytest.mark.parametrize(
    "result",
    [
        VerificationResult(CheckStatus.NO_PEERS, peers=0, speed_down=0, infohash=INFOHASH),
        VerificationResult(CheckStatus.NOT_FOUND),
        VerificationResult(CheckStatus.ERROR, error_message="cannot reach the engine"),
    ],
    ids=["no_peers", "not_found", "error"],
)
def test_every_status_can_be_recorded_without_a_screenshot(session, channel, result):
    check = checks.record_verification(session, channel.id, result)

    assert check.status is result.status
    assert check.screenshot_path is None
    assert check.error_message == result.error_message


def test_long_error_messages_are_truncated_to_the_column_length(session, channel):
    result = VerificationResult(CheckStatus.ERROR, error_message="x" * 2000)

    check = checks.record_verification(session, channel.id, result)

    assert len(check.error_message) == 500


def test_recording_for_a_missing_channel_stores_nothing(session):
    with pytest.raises(NotFoundError):
        checks.record_verification(session, 99, VerificationResult(CheckStatus.ERROR))

    assert checks.latest_checks(session) == {}


def test_history_keeps_every_verification_newest_first(session, channel):
    now = datetime.now(UTC)
    for days_ago, status in [
        (30, CheckStatus.ALIVE),
        (7, CheckStatus.NO_PEERS),
        (0, CheckStatus.ALIVE),
    ]:
        checks.record_verification(
            session,
            channel.id,
            VerificationResult(status, peers=1),
            checked_at=now - timedelta(days=days_ago),
        )

    history = checks.list_checks(session, channel.id)

    assert [c.status for c in history] == [
        CheckStatus.ALIVE,
        CheckStatus.NO_PEERS,
        CheckStatus.ALIVE,
    ]
    assert history[0].checked_at > history[1].checked_at > history[2].checked_at


def test_current_state_is_the_latest_check_not_the_best_one(session, channel):
    now = datetime.now(UTC)
    checks.record_verification(
        session,
        channel.id,
        VerificationResult(CheckStatus.ALIVE),
        checked_at=now - timedelta(days=3),
    )
    checks.record_verification(
        session, channel.id, VerificationResult(CheckStatus.NO_PEERS), checked_at=now
    )

    assert checks.get_latest_check(session, channel.id).status is CheckStatus.NO_PEERS
    assert checks.latest_checks(session)[channel.id].status is CheckStatus.NO_PEERS


def test_same_timestamp_is_resolved_by_insertion_order(session, channel):
    moment = datetime.now(UTC)
    checks.record_verification(
        session, channel.id, VerificationResult(CheckStatus.NO_PEERS), checked_at=moment
    )
    checks.record_verification(
        session, channel.id, VerificationResult(CheckStatus.ALIVE), checked_at=moment
    )

    assert checks.get_latest_check(session, channel.id).status is CheckStatus.ALIVE
    assert checks.list_checks(session, channel.id)[0].status is CheckStatus.ALIVE


def test_history_is_kept_per_channel(session, channel):
    other = channels.create_channel(session, title="B", content_id=HASH_B)
    checks.record_verification(session, channel.id, VerificationResult(CheckStatus.ALIVE))
    checks.record_verification(session, other.id, VerificationResult(CheckStatus.NOT_FOUND))
    checks.record_verification(session, other.id, VerificationResult(CheckStatus.ERROR))

    assert len(checks.list_checks(session, channel.id)) == 1
    assert len(checks.list_checks(session, other.id)) == 2
    latest = checks.latest_checks(session)
    assert latest[channel.id].status is CheckStatus.ALIVE
    assert latest[other.id].status is CheckStatus.ERROR
