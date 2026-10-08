import json
from datetime import UTC, datetime

import pytest

from app.db.base import Base
from app.db.models import Resolution
from app.db.session import make_engine, make_session_factory
from app.services import categories, channels
from app.services.errors import ValidationError
from app.services.exchange import (
    FORMAT,
    VERSION,
    export_channels,
    import_export,
    is_export,
    parse_export,
)
from app.services.importer import MAX_LINES, Reason

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"
HASH_C = "efc60cfe5e3a349baa02bcc49f6647c21a9c3c5b"
CREATED = datetime(2026, 9, 1, 10, 30, tzinfo=UTC)


def document(*entries, **overrides):
    doc = {"format": FORMAT, "version": VERSION, "exported_at": "2026-10-08T00:00:00+00:00"}
    doc["channels"] = list(entries)
    doc.update(overrides)
    return json.dumps(doc)


def channel(content_id, **fields):
    return {"content_id": content_id, "title": "Canal", **fields}


@pytest.fixture
def other_db(tmp_path):
    """A second, empty catalog: where an export is imported on another machine."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'other.db').as_posix()}")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()


# export


def test_export_has_every_stored_field(db):
    sports = categories.create_category(db, "Deportes")
    stored = channels.create_channel(
        db,
        title="Uno",
        content_id=HASH_A,
        category_id=sports.id,
        language="es",
        country="AR",
        resolution="1080p",
    )
    stored.created_at = CREATED
    db.commit()

    doc = export_channels([stored], exported_at=datetime(2026, 10, 8, tzinfo=UTC))

    assert doc["format"] == FORMAT and doc["version"] == VERSION
    assert doc["exported_at"] == "2026-10-08T00:00:00+00:00"
    assert doc["channels"] == [
        {
            "title": "Uno",
            "title_pending": False,
            "content_id": HASH_A,
            "link": f"acestream://{HASH_A}",
            "category": "Deportes",
            "language": "es",
            "country": "AR",
            "resolution": "1080p",
            "created_at": "2026-09-01T10:30:00+00:00",
        }
    ]


def test_export_and_import_round_trip_to_another_catalog(db, other_db):
    sports = categories.create_category(db, "Deportes")
    uno = channels.create_channel(
        db, title="Uno", content_id=HASH_A, category_id=sports.id, language="es", resolution="4k"
    )
    channels.create_channel(
        db, title="Canal ecc85e5d", content_id=HASH_B, country="GB", title_pending=True
    )
    uno.created_at = CREATED
    db.commit()
    text = json.dumps(export_channels(channels.list_channels(db)))

    result = import_export(other_db, text)

    assert len(result.created) == 2
    copy = channels.find_channel_by_content_id(other_db, HASH_A)
    assert (copy.title, copy.category.name, copy.language, copy.resolution) == (
        "Uno",
        "Deportes",
        "es",
        Resolution.UHD,
    )
    assert copy.created_at == CREATED
    pending = channels.find_channel_by_content_id(other_db, HASH_B)
    assert (pending.title_pending, pending.country) == (True, "GB")


# reading the file


def test_is_export_tells_json_from_a_list_of_links():
    assert is_export('  {"format": "acelist"}')
    assert not is_export(f"acestream://{HASH_A}")
    assert not is_export("#EXTM3U")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{not json", "not valid JSON"),
        ('{"format": "other", "channels": []}', "not an AceList export"),
        ("[1, 2]", "not an AceList export"),
        (document(version=VERSION + 1), "unsupported export version"),
        (document(version="1"), "unsupported export version"),
        (json.dumps({"format": FORMAT, "version": VERSION}), 'no "channels" list'),
    ],
)
def test_parse_export_rejects_anything_else(text, message):
    with pytest.raises(ValidationError, match=message):
        parse_export(text)


def test_parse_export_limits_the_size():
    with pytest.raises(ValidationError, match="too many channels"):
        parse_export(document(*[channel(HASH_A)] * (MAX_LINES + 1)))


# importing


def test_only_new_channels_are_added(db):
    channels.create_channel(db, title="Ya estaba", content_id=HASH_A)

    result = import_export(
        db,
        document(channel(HASH_A), channel(f"acestream://{HASH_B.upper()}"), channel(HASH_B)),
    )

    assert [c.content_id for c in result.created] == [HASH_B]
    assert [(d.line, d.reason) for d in result.duplicates] == [
        (1, Reason.EXISTING),
        (3, Reason.REPEATED),
    ]
    assert result.duplicates[0].existing.title == "Ya estaba"
    assert result.duplicates[1].first_line == 2
    assert result.unit == "channel"


def test_the_link_is_accepted_when_there_is_no_content_id(db):
    result = import_export(db, document({"link": f"acestream://{HASH_A}", "title": "Uno"}))

    assert result.created[0].content_id == HASH_A


def test_categories_are_reused_by_name_or_created(db):
    existing = categories.create_category(db, "Deportes")

    import_export(
        db,
        document(
            channel(HASH_A, category="deportes"),
            channel(HASH_B, category="Cine"),
        ),
    )

    assert channels.find_channel_by_content_id(db, HASH_A).category_id == existing.id
    assert channels.find_channel_by_content_id(db, HASH_B).category.name == "Cine"
    assert sorted(c.name for c in categories.list_categories(db)) == ["Cine", "Deportes"]


def test_form_defaults_only_fill_what_a_channel_lacks(db):
    news = categories.create_category(db, "Noticias")

    import_export(
        db,
        document(
            channel(HASH_A, language="en", country="GB", category="Deportes"),
            channel(HASH_B),
        ),
        category_id=news.id,
        language="es",
        country="AR",
    )

    first = channels.find_channel_by_content_id(db, HASH_A)
    second = channels.find_channel_by_content_id(db, HASH_B)
    assert (first.language, first.country, first.category.name) == ("en", "GB", "Deportes")
    assert (second.language, second.country, second.category_id) == ("es", "AR", news.id)


def test_untitled_or_pending_channels_get_a_provisional_title(db):
    import_export(
        db,
        document(
            {"content_id": HASH_A},
            {"content_id": HASH_B, "title": "Canal ecc85e5d", "title_pending": True},
        ),
    )

    untitled = channels.find_channel_by_content_id(db, HASH_A)
    assert (untitled.title, untitled.title_pending) == (f"Canal {HASH_A[:8]}", True)
    assert channels.find_channel_by_content_id(db, HASH_B).title_pending


def test_a_bad_channel_is_reported_and_the_rest_imported(db):
    result = import_export(
        db,
        document(
            channel(HASH_A, language="xx"),
            "not a channel",
            channel("bad-hash"),
            channel(HASH_B, country=5),
            channel(HASH_C, category="Nueva", resolution="8k"),
            channel("0123456789abcdef0123456789abcdef01234567", title="Bien"),
        ),
    )

    assert [c.title for c in result.created] == ["Bien"]
    assert [(r.line, r.reason) for r in result.invalid] == [
        (1, Reason.INVALID),
        (2, Reason.INVALID),
        (3, Reason.NO_LINK),
        (4, Reason.INVALID),
        (5, Reason.INVALID),
    ]
    assert "unknown language code" in result.invalid[0].detail
    assert "country must be text" in result.invalid[3].detail
    # A rejected channel leaves nothing behind, not even its new category.
    assert categories.list_categories(db) == []


def test_unreadable_dates_are_ignored(db):
    import_export(db, document(channel(HASH_A, created_at="yesterday")))

    assert channels.find_channel_by_content_id(db, HASH_A).created_at.year >= 2026


def test_bad_form_defaults_fail_before_creating_anything(db):
    with pytest.raises(ValidationError):
        import_export(db, document(channel(HASH_A)), language="xx")

    assert channels.list_channels(db) == []
