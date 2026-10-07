from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Check, CheckStatus
from app.services.channels import get_channel


def add_check(
    session: Session,
    channel_id: int,
    *,
    status: CheckStatus,
    peers: int | None = None,
    speed_down: int | None = None,
    infohash: str | None = None,
    screenshot_path: str | None = None,
    error_message: str | None = None,
    checked_at: datetime | None = None,
) -> Check:
    """`screenshot_path` is relative to the data directory."""
    get_channel(session, channel_id)
    check = Check(
        channel_id=channel_id,
        status=status,
        peers=peers,
        speed_down=speed_down,
        infohash=infohash,
        screenshot_path=screenshot_path,
        error_message=error_message,
    )
    if checked_at is not None:
        check.checked_at = checked_at
    session.add(check)
    session.commit()
    return check


def list_checks(session: Session, channel_id: int) -> list[Check]:
    """History of a channel, newest first."""
    get_channel(session, channel_id)
    return list(
        session.scalars(
            select(Check)
            .where(Check.channel_id == channel_id)
            .order_by(Check.checked_at.desc(), Check.id.desc())
        )
    )


def get_latest_check(session: Session, channel_id: int) -> Check | None:
    get_channel(session, channel_id)
    return session.scalars(
        select(Check)
        .where(Check.channel_id == channel_id)
        .order_by(Check.checked_at.desc(), Check.id.desc())
        .limit(1)
    ).first()


def latest_checks(session: Session) -> dict[int, Check]:
    """Most recent check of every channel that has at least one, keyed by channel id."""
    ranked = select(
        Check.id.label("id"),
        func.row_number()
        .over(
            partition_by=Check.channel_id,
            order_by=(Check.checked_at.desc(), Check.id.desc()),
        )
        .label("rank"),
    ).subquery()
    stmt = select(Check).join(ranked, Check.id == ranked.c.id).where(ranked.c.rank == 1)
    return {check.channel_id: check for check in session.scalars(stmt)}
