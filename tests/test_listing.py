from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import CheckStatus
from app.services import categories, channels, checks
from app.services.listing import (
    UNCHECKED,
    ChannelQuery,
    SortKey,
    search_channels,
    used_countries,
    used_languages,
)

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"
HASH_C = "efc60cfe5e3a349baa02bcc49f6647c21a9c3c5b"
HASH_D = "0123456789abcdef0123456789abcdef01234567"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
def catalog(db):
    """Four channels covering every status, with and without metadata."""
    sports = categories.create_category(db, "Deportes")
    news = categories.create_category(db, "Noticias")
    alfa = channels.create_channel(
        db,
        title="alfa deportes",
        content_id=HASH_A,
        category_id=sports.id,
        language="es",
        country="AR",
    )
    beta = channels.create_channel(
        db, title="Beta News", content_id=HASH_B, category_id=news.id, language="en", country="GB"
    )
    gamma = channels.create_channel(
        db, title="Gamma 100%_real", content_id=HASH_C, language="es", country="ES"
    )
    delta = channels.create_channel(db, title="Delta", content_id=HASH_D)
    for i, channel in enumerate((alfa, beta, gamma, delta)):
        channel.created_at = NOW - timedelta(days=10 - i)
    db.commit()

    # alfa: was alive, now dead; beta: alive; gamma: no peers; delta: never checked.
    checks.add_check(db, alfa.id, status=CheckStatus.ALIVE, peers=50, checked_at=NOW - timedelta(2))
    checks.add_check(db, alfa.id, status=CheckStatus.NOT_FOUND, checked_at=NOW - timedelta(1))
    checks.add_check(db, beta.id, status=CheckStatus.ALIVE, peers=7, checked_at=NOW - timedelta(3))
    checks.add_check(db, gamma.id, status=CheckStatus.NO_PEERS, peers=0, checked_at=NOW)
    return {"alfa": alfa, "beta": beta, "gamma": gamma, "delta": delta, "sports": sports}


def titles(db, **kwargs):
    return [channel.title for channel, _ in search_channels(db, ChannelQuery(**kwargs))]


def test_default_order_is_by_title_ignoring_case(db, catalog):
    assert titles(db) == ["alfa deportes", "Beta News", "Delta", "Gamma 100%_real"]


def test_each_channel_comes_with_its_latest_check(db, catalog):
    result = dict((c.title, check) for c, check in search_channels(db, ChannelQuery()))

    assert result["alfa deportes"].status == CheckStatus.NOT_FOUND
    assert result["Beta News"].peers == 7
    assert result["Delta"] is None


def test_text_matches_title_case_insensitively_or_content_id(db, catalog):
    assert titles(db, text="NEWS") == ["Beta News"]
    assert titles(db, text="efc60c") == ["Gamma 100%_real"]
    assert titles(db, text=f"acestream://{HASH_A.upper()}") == ["alfa deportes"]


def test_like_wildcards_in_the_text_are_literal(db, catalog):
    assert titles(db, text="%") == ["Gamma 100%_real"]
    assert titles(db, text="0%_r") == ["Gamma 100%_real"]
    assert titles(db, text="_") == ["Gamma 100%_real"]


def test_filters_by_category_language_and_country(db, catalog):
    assert titles(db, category_id=catalog["sports"].id) == ["alfa deportes"]
    assert titles(db, language="ES") == ["alfa deportes", "Gamma 100%_real"]
    assert titles(db, country="gb") == ["Beta News"]
    assert titles(db, language="es", country="ES") == ["Gamma 100%_real"]


def test_status_filter_uses_only_the_latest_check(db, catalog):
    assert titles(db, status="alive") == ["Beta News"]
    assert titles(db, status="not_found") == ["alfa deportes"]
    assert titles(db, status="no_peers") == ["Gamma 100%_real"]
    assert titles(db, status=UNCHECKED) == ["Delta"]
    assert titles(db, status="error") == []


def test_sort_by_created(db, catalog):
    assert titles(db, sort=SortKey.CREATED) == [
        "alfa deportes",
        "Beta News",
        "Gamma 100%_real",
        "Delta",
    ]
    assert titles(db, sort=SortKey.CREATED, descending=True)[0] == "Delta"


def test_sort_by_last_check_puts_unchecked_last_both_ways(db, catalog):
    assert titles(db, sort=SortKey.CHECKED, descending=True) == [
        "Gamma 100%_real",
        "alfa deportes",
        "Beta News",
        "Delta",
    ]
    assert titles(db, sort=SortKey.CHECKED) == [
        "Beta News",
        "alfa deportes",
        "Gamma 100%_real",
        "Delta",
    ]


def test_sort_by_peers_uses_the_latest_check(db, catalog):
    # alfa had 50 peers once, but its latest check has none: it goes last with Delta.
    assert titles(db, sort=SortKey.PEERS, descending=True) == [
        "Beta News",
        "Gamma 100%_real",
        "alfa deportes",
        "Delta",
    ]


def test_sort_by_status_puts_live_channels_first(db, catalog):
    assert titles(db, sort=SortKey.STATUS) == [
        "Beta News",
        "Gamma 100%_real",
        "alfa deportes",
        "Delta",
    ]
    assert titles(db, sort=SortKey.STATUS, descending=True) == [
        "alfa deportes",
        "Gamma 100%_real",
        "Beta News",
        "Delta",
    ]


def test_used_languages_and_countries(db, catalog):
    assert sorted(used_languages(db)) == ["en", "es"]
    assert sorted(used_countries(db)) == ["AR", "ES", "GB"]


def test_filters_by_resolution(db, catalog):
    channels.update_channel(db, catalog["alfa"].id, resolution="1080p")
    channels.update_channel(db, catalog["beta"].id, resolution="720p")

    assert titles(db, resolution="1080p") == ["alfa deportes"]
    assert titles(db, resolution="unknown") == ["Delta", "Gamma 100%_real"]
