from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Check, CheckStatus
from app.services.channels import get_channel
from app.services.verification import VerificationResult

_MAX_MESSAGE = 500


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
    width: int | None = None,
    height: int | None = None,
    checked_at: datetime | None = None,
) -> Check:
    """`screenshot_path` is relative to the data directory; width and height are its size."""
    get_channel(session, channel_id)
    check = Check(
        channel_id=channel_id,
        status=status,
        peers=peers,
        speed_down=speed_down,
        infohash=infohash,
        screenshot_path=screenshot_path,
        error_message=error_message,
        width=width,
        height=height,
    )
    if checked_at is not None:
        check.checked_at = checked_at
    session.add(check)
    session.commit()
    return check


def record_verification(
    session: Session,
    channel_id: int,
    result: VerificationResult,
    *,
    screenshot_path: str | None = None,
    frame: tuple[int, int] | None = None,
    checked_at: datetime | None = None,
) -> Check:
    """Stores a verification outcome as the newest entry of the channel's history."""
    message = result.error_message
    return add_check(
        session,
        channel_id,
        status=result.status,
        peers=result.peers,
        speed_down=result.speed_down,
        infohash=result.infohash,
        screenshot_path=screenshot_path,
        # Matches the column length so a long engine message cannot break the insert.
        error_message=message[:_MAX_MESSAGE] if message else None,
        width=frame[0] if frame else None,
        height=frame[1] if frame else None,
        checked_at=checked_at,
    )


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
