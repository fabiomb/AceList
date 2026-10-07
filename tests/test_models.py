import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.db.models import Category, Channel, Check, CheckStatus, Setting
from app.db.session import make_engine, make_session_factory

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"


@pytest.fixture
def session():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()


def test_channel_roundtrip_with_category_and_metadata(session):
    category = Category(name="Sports")
    session.add(
        Channel(title="Match", content_id=HASH_A, category=category, language="es", country="AR")
    )
    session.commit()

    channel = session.scalars(select(Channel)).one()
    assert channel.category.name == "Sports"
    assert (channel.language, channel.country) == ("es", "AR")


def test_datetimes_are_utc_aware_after_roundtrip(session):
    session.add(Channel(title="Match", content_id=HASH_A))
    session.commit()
    session.expire_all()

    channel = session.scalars(select(Channel)).one()
    assert channel.created_at.tzinfo is UTC
    assert datetime.now(UTC) - channel.created_at < timedelta(seconds=5)


def test_naive_datetime_is_rejected(session):
    session.add(Channel(title="Match", content_id=HASH_A, created_at=datetime(2026, 1, 1)))
    with pytest.raises(Exception, match="naive datetime"):
        session.commit()


def test_content_id_is_unique(session):
    session.add_all([Channel(title="A", content_id=HASH_A), Channel(title="B", content_id=HASH_A)])
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize(
    "bad_id",
    [HASH_A.upper(), HASH_A[:-1], HASH_A + "0", "z" * 40, ""],
    ids=["uppercase", "short", "long", "non-hex", "empty"],
)
def test_content_id_format_is_enforced(session, bad_id):
    session.add(Channel(title="Bad", content_id=bad_id))
    with pytest.raises(IntegrityError):
        session.commit()


def test_category_in_use_cannot_be_deleted(session):
    category = Category(name="Sports")
    session.add(Channel(title="Match", content_id=HASH_A, category=category))
    session.commit()

    session.delete(category)
    with pytest.raises(IntegrityError):
        session.commit()


def test_category_name_is_unique(session):
    session.add_all([Category(name="Sports"), Category(name="Sports")])
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_channel_cascades_to_checks(session):
    channel = Channel(title="Match", content_id=HASH_A)
    channel.checks.append(Check(status=CheckStatus.ALIVE, peers=3))
    channel.checks.append(Check(status=CheckStatus.NO_PEERS, peers=0))
    session.add(channel)
    session.commit()

    session.delete(channel)
    session.commit()

    assert session.scalars(select(Check)).all() == []


def test_checks_are_ordered_newest_first(session):
    now = datetime.now(UTC)
    channel = Channel(title="Match", content_id=HASH_A)
    channel.checks.append(Check(status=CheckStatus.NO_PEERS, checked_at=now - timedelta(days=2)))
    channel.checks.append(Check(status=CheckStatus.ALIVE, checked_at=now))
    session.add(channel)
    session.commit()
    session.expire_all()

    assert [c.status for c in session.scalars(select(Channel)).one().checks] == [
        CheckStatus.ALIVE,
        CheckStatus.NO_PEERS,
    ]


def test_check_stores_engine_infohash_separately_from_content_id(session):
    channel = Channel(title="Match", content_id=HASH_B)
    channel.checks.append(
        Check(status=CheckStatus.ALIVE, infohash="25f4c7b60edb0433343c777846924d35c65ec4f9")
    )
    session.add(channel)
    session.commit()

    check = session.scalars(select(Check)).one()
    assert check.infohash != channel.content_id


def test_invalid_check_status_is_rejected(session):
    channel = Channel(title="Match", content_id=HASH_A)
    session.add(channel)
    session.commit()

    with pytest.raises(sqlite3.IntegrityError):
        session.connection().connection.execute(
            "INSERT INTO check_result (channel_id, checked_at, status) VALUES (?, ?, ?)",
            (channel.id, "2026-01-01 00:00:00", "bogus"),
        )


def test_setting_roundtrip(session):
    session.add(Setting(key="engine_url", value="http://127.0.0.1:6878"))
    session.commit()

    assert session.get(Setting, "engine_url").value == "http://127.0.0.1:6878"
