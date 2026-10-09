from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.db.models import Category, Channel, Check, CheckStatus, Resolution

UNCHECKED = "unchecked"  # status filter: channels with no check yet
UNKNOWN = "unknown"  # resolution filter: channels whose resolution is not known


class SortKey(StrEnum):
    TITLE = "title"
    CREATED = "created"
    CHECKED = "checked"
    PEERS = "peers"
    STATUS = "status"


# What a first click on a column means: names A-Z, everything else best or newest first.
DEFAULT_DESCENDING = {
    SortKey.TITLE: False,
    SortKey.CREATED: True,
    SortKey.CHECKED: True,
    SortKey.PEERS: True,
    SortKey.STATUS: False,
}

# Best first: a live channel is what the user is looking for.
_STATUS_RANK = [CheckStatus.ALIVE, CheckStatus.NO_PEERS, CheckStatus.NOT_FOUND, CheckStatus.ERROR]


@dataclass(frozen=True)
class ChannelQuery:
    """Filters and order for the channel list; `None` means "any"."""

    text: str | None = None  # in the title, the category name or the Content ID
    category_id: int | None = None
    language: str | None = None  # ISO 639-1
    country: str | None = None  # ISO 3166-1 alpha-2
    resolution: str | None = None  # a `Resolution` value, or `UNKNOWN`
    status: str | None = None  # a `CheckStatus` value or `UNCHECKED`
    sort: SortKey = SortKey.TITLE
    descending: bool = False


def search_channels(session: Session, query: ChannelQuery) -> list[tuple[Channel, Check | None]]:
    """Channels with their latest check, filtered and sorted.

    Status, peers and check date always come from the latest check. Channels with
    no value for the sort column go last in either direction.
    """
    ranked = select(
        Check.id.label("id"),
        Check.channel_id.label("channel_id"),
        func.row_number()
        .over(
            partition_by=Check.channel_id,
            order_by=(Check.checked_at.desc(), Check.id.desc()),
        )
        .label("rank"),
    ).subquery()
    latest = aliased(Check)
    stmt = (
        select(Channel, latest)
        .outerjoin(ranked, and_(ranked.c.channel_id == Channel.id, ranked.c.rank == 1))
        .outerjoin(latest, latest.id == ranked.c.id)
    )

    if query.text and query.text.strip():
        stmt = stmt.where(_matches_text(query.text.strip()))
    if query.category_id is not None:
        stmt = stmt.where(Channel.category_id == query.category_id)
    if query.language:
        stmt = stmt.where(Channel.language == query.language.lower())
    if query.country:
        stmt = stmt.where(Channel.country == query.country.upper())
    if query.resolution == UNKNOWN:
        stmt = stmt.where(Channel.resolution.is_(None))
    elif query.resolution:
        stmt = stmt.where(Channel.resolution == Resolution(query.resolution))
    if query.status == UNCHECKED:
        stmt = stmt.where(latest.id.is_(None))
    elif query.status:
        stmt = stmt.where(latest.status == CheckStatus(query.status))

    column = {
        SortKey.TITLE: func.lower(Channel.title),
        SortKey.CREATED: Channel.created_at,
        SortKey.CHECKED: latest.checked_at,
        SortKey.PEERS: latest.peers,
        SortKey.STATUS: case(
            *((latest.status == s, rank) for rank, s in enumerate(_STATUS_RANK)),
            else_=None,
        ),
    }[query.sort]
    stmt = stmt.order_by(
        column.is_(None),  # missing values last, whatever the direction
        column.desc() if query.descending else column.asc(),
        func.lower(Channel.title),
        Channel.id,
    )
    return [(channel, check) for channel, check in session.execute(stmt)]


def _matches_text(text: str):
    # LIKE wildcards typed by the user are literal characters, not patterns.
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    content_id = text.lower().removeprefix("acestream://")
    return or_(
        Channel.title.ilike(pattern, escape="\\"),
        Channel.category.has(Category.name.ilike(pattern, escape="\\")),
        Channel.content_id.contains(content_id, autoescape=True),
    )


def used_languages(session: Session) -> list[str]:
    """Languages that at least one channel has, for the filter options."""
    return list(
        session.scalars(select(Channel.language).where(Channel.language.is_not(None)).distinct())
    )


def used_countries(session: Session) -> list[str]:
    return list(
        session.scalars(select(Channel.country).where(Channel.country.is_not(None)).distinct())
    )
