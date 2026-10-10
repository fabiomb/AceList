from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.acestream.content_id import IdKind
from app.db.base import Base, UTCDateTime, utcnow


class CheckStatus(StrEnum):
    ALIVE = "alive"
    NO_PEERS = "no_peers"
    NOT_FOUND = "not_found"
    ERROR = "error"


class Resolution(StrEnum):
    """Video resolution class of a channel, detected from its screenshots or set by hand."""

    SD = "480p"
    HD = "720p"
    FULL_HD = "1080p"
    UHD = "4k"
    OTHER = "other"


class Category(Base):
    __tablename__ = "category"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)

    # "all": leave the FK alone on delete so the database RESTRICT rule applies.
    channels: Mapped[list["Channel"]] = relationship(
        back_populates="category", passive_deletes="all"
    )


class Channel(Base):
    __tablename__ = "channel"
    __table_args__ = (
        # Content ID is stored normalized: 40 lowercase hex characters.
        CheckConstraint(
            "length(content_id) = 40 AND content_id NOT GLOB '*[^0-9a-f]*'",
            name="content_id_format",
        ),
        Index("ix_channel_title", "title"),
        Index("ix_channel_language", "language"),
        Index("ix_channel_country", "country"),
        Index("ix_channel_created_at", "created_at"),
        Index("ix_channel_resolution", "resolution"),
        CheckConstraint(
            "resolution IN (" + ", ".join(f"'{r.value}'" for r in Resolution) + ")",
            name="resolution_valid",
        ),
        CheckConstraint(
            "id_kind IN (" + ", ".join(f"'{k.value}'" for k in IdKind) + ")",
            name="id_kind_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    # The user gave no title: this one is provisional until the stream's name is known.
    title_pending: Mapped[bool] = mapped_column(default=False, server_default=false())
    content_id: Mapped[str] = mapped_column(String(40), unique=True)
    # How the engine loaded `content_id` last time (some links carry the infohash
    # instead); None until it has loaded it once.
    id_kind: Mapped[IdKind | None] = mapped_column(
        Enum(
            IdKind,
            native_enum=False,
            create_constraint=False,
            length=10,
            values_callable=lambda e: [m.value for m in e],
        )
    )
    # RESTRICT: a category in use cannot be deleted without reassigning its channels.
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("category.id", ondelete="RESTRICT"), index=True
    )
    language: Mapped[str | None] = mapped_column(String(2))  # ISO 639-1, lowercase
    country: Mapped[str | None] = mapped_column(String(2))  # ISO 3166-1 alpha-2, uppercase
    resolution: Mapped[Resolution | None] = mapped_column(
        Enum(
            Resolution,
            native_enum=False,
            create_constraint=False,
            length=8,
            values_callable=lambda e: [m.value for m in e],
        )
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    category: Mapped[Category | None] = relationship(back_populates="channels")
    checks: Mapped[list["Check"]] = relationship(
        back_populates="channel",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Check.checked_at.desc()",
    )


class Check(Base):
    __tablename__ = "check_result"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s.value}'" for s in CheckStatus) + ")",
            name="status_valid",
        ),
        Index("ix_check_result_channel_id_checked_at", "channel_id", "checked_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channel.id", ondelete="CASCADE"))
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    status: Mapped[CheckStatus] = mapped_column(
        Enum(
            CheckStatus,
            native_enum=False,
            create_constraint=False,
            length=16,
            values_callable=lambda e: [m.value for m in e],
        )
    )
    peers: Mapped[int | None]
    speed_down: Mapped[int | None]
    # The engine resolves a Content ID to a different infohash, so it is kept separately.
    infohash: Mapped[str | None] = mapped_column(String(40))
    screenshot_path: Mapped[str | None] = mapped_column(String(500))
    # Frame size of the screenshot, when one was taken.
    width: Mapped[int | None]
    height: Mapped[int | None]
    error_message: Mapped[str | None] = mapped_column(String(500))

    channel: Mapped[Channel] = relationship(back_populates="checks")


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(1000))


class Source(Base):
    """A channel list (M3U, links or an AceList export) to explore and pick from."""

    __tablename__ = "source"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    url: Mapped[str | None] = mapped_column(String(1000))  # None: uploaded from a file
    enabled: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # Outcome of the last refresh: when, how many channels it brought, or why it failed.
    fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    entry_count: Mapped[int | None]
    error_message: Mapped[str | None] = mapped_column(String(500))

    entries: Mapped[list["SourceEntry"]] = relationship(
        back_populates="source", cascade="all, delete-orphan", passive_deletes=True
    )
    dismissed: Mapped[list["SourceDismissed"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )


class SourceEntry(Base):
    """A channel read from a source on its last refresh; replaced on the next one."""

    __tablename__ = "source_entry"
    __table_args__ = (
        UniqueConstraint("source_id", "content_id"),
        Index("ix_source_entry_content_id", "content_id"),
        CheckConstraint(
            "check_status IN (" + ", ".join(f"'{s.value}'" for s in CheckStatus) + ")",
            name="check_status_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"))
    content_id: Mapped[str] = mapped_column(String(40))
    title: Mapped[str | None] = mapped_column(String(200))  # None: the list gave no name
    group: Mapped[str | None] = mapped_column(String(100))  # the list's own grouping, if any
    position: Mapped[int]  # order in the list
    # Last check run from Explorar, without adding the channel; kept across refreshes.
    check_status: Mapped[CheckStatus | None] = mapped_column(
        Enum(
            CheckStatus,
            native_enum=False,
            create_constraint=False,
            length=16,
            values_callable=lambda e: [m.value for m in e],
        )
    )
    check_peers: Mapped[int | None]
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    source: Mapped[Source] = relationship(back_populates="entries")


class SourceDismissed(Base):
    """A channel the user removed from a source: hidden from Explorar, even after a refresh.

    Kept by Content ID, as entries are replaced on every refresh.
    """

    __tablename__ = "source_dismissed"
    __table_args__ = (UniqueConstraint("source_id", "content_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"))
    content_id: Mapped[str] = mapped_column(String(40))
