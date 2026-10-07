import pytest

from app.acestream.client import EngineClient
from app.db.base import Base
from app.db.session import make_engine, make_session_factory
from app.services import catalog, channels, iso
from app.services.errors import ValidationError

HASH = "78266c15035d0ad8cbc58f821733931e1de434ab"


@pytest.fixture
def session():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()


# value lists


def test_language_choices_are_the_184_iso_639_1_codes_sorted_by_name():
    choices = iso.language_choices()

    assert len(choices) == 184
    assert ("es", "Spanish") in choices
    assert all(len(code) == 2 and code.islower() for code, _ in choices)
    names = [name for _, name in choices]
    assert names == sorted(names)


def test_country_choices_are_the_249_iso_3166_1_codes_sorted_by_name():
    choices = iso.country_choices()

    assert len(choices) == 249
    assert ("AR", "Argentina") in choices
    assert dict(choices)["GB"] == "United Kingdom"
    assert all(len(code) == 2 and code.isupper() for code, _ in choices)
    names = [name for _, name in choices]
    assert names == sorted(names)


# normalization


@pytest.mark.parametrize(
    ("value", "expected"),
    [("es", "es"), ("ES", "es"), (" Es ", "es"), ("", None), ("   ", None), (None, None)],
)
def test_normalize_language(value, expected):
    assert iso.normalize_language(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("AR", "AR"), ("ar", "AR"), (" Ar ", "AR"), ("", None), ("   ", None), (None, None)],
)
def test_normalize_country(value, expected):
    assert iso.normalize_country(value) == expected


@pytest.mark.parametrize("value", ["xx", "spa", "es-AR", "español", "e", "12"])
def test_unknown_language_is_rejected_with_the_offending_code(value):
    with pytest.raises(ValidationError, match="language code"):
        iso.normalize_language(value)


@pytest.mark.parametrize("value", ["XX", "ARG", "UK", "A", "es-AR", "12"])
def test_unknown_country_is_rejected_with_the_offending_code(value):
    # "UK" is a common mistake: the ISO code of the United Kingdom is GB.
    with pytest.raises(ValidationError, match="country code"):
        iso.normalize_country(value)


# channel service


def test_create_channel_normalizes_language_and_country(session):
    channel = channels.create_channel(
        session, title="A", content_id=HASH, language="ES", country="ar"
    )

    assert (channel.language, channel.country) == ("es", "AR")


def test_create_channel_with_invalid_language_creates_nothing(session):
    with pytest.raises(ValidationError):
        channels.create_channel(session, title="A", content_id=HASH, language="xx")

    assert channels.list_channels(session) == []


def test_update_channel_normalizes_and_can_clear_both_fields(session):
    channel = channels.create_channel(
        session, title="A", content_id=HASH, language="es", country="AR"
    )

    channels.update_channel(session, channel.id, language="EN", country="gb")
    assert (channel.language, channel.country) == ("en", "GB")

    channels.update_channel(session, channel.id, language="", country=None)
    assert (channel.language, channel.country) == (None, None)


def test_update_with_an_invalid_code_changes_nothing(session):
    channel = channels.create_channel(
        session, title="A", content_id=HASH, language="es", country="AR"
    )

    with pytest.raises(ValidationError):
        channels.update_channel(session, channel.id, title="B", language="en", country="UK")

    session.refresh(channel)
    assert (channel.title, channel.language, channel.country) == ("A", "es", "AR")


def test_catalog_rejects_invalid_codes_before_touching_the_engine(session, respx_mock):
    with EngineClient("http://127.0.0.1:6878", timeout=1) as client:
        with pytest.raises(ValidationError, match="country code"):
            catalog.add_channel(session, client, title="A", link=HASH, country="UK")

    assert channels.list_channels(session) == []
    assert respx_mock.calls.call_count == 0
