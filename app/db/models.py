from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utcnow


class CheckStatus(StrEnum):
    ALIVE = "alive"
    NO_PEERS = "no_peers"
    NOT_FOUND = "not_found"
    ERROR = "error"


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
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    content_id: Mapped[str] = mapped_column(String(40), unique=True)
    # RESTRICT: a category in use cannot be deleted without reassigning its channels.
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("category.id", ondelete="RESTRICT"), index=True
    )
    language: Mapped[str | None] = mapped_column(String(2))  # ISO 639-1, lowercase
    country: Mapped[str | None] = mapped_column(String(2))  # ISO 3166-1 alpha-2, uppercase
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
    error_message: Mapped[str | None] = mapped_column(String(500))

    channel: Mapped[Channel] = relationship(back_populates="checks")


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(1000))
