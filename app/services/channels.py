from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import DATA_DIR
from app.db.models import Category, Channel
from app.services.errors import DuplicateError, NotFoundError, ValidationError

_UPDATABLE = {"title", "content_id", "category_id", "language", "country"}


def _clean_title(title: str) -> str:
    title = title.strip()
    if not title:
        raise ValidationError("title must not be empty")
    return title


def _check_category(session: Session, category_id: int | None) -> None:
    if category_id is not None and session.get(Category, category_id) is None:
        raise NotFoundError(f"category not found: {category_id}")


def create_channel(
    session: Session,
    *,
    title: str,
    content_id: str,
    category_id: int | None = None,
    language: str | None = None,
    country: str | None = None,
) -> Channel:
    """`content_id` must already be normalized (40 lowercase hex characters)."""
    _check_category(session, category_id)
    channel = Channel(
        title=_clean_title(title),
        content_id=content_id,
        category_id=category_id,
        language=language,
        country=country,
    )
    session.add(channel)
    _commit_unique(session, content_id)
    return channel


def get_channel(session: Session, channel_id: int) -> Channel:
    channel = session.get(Channel, channel_id)
    if channel is None:
        raise NotFoundError(f"channel not found: {channel_id}")
    return channel


def find_channel_by_content_id(session: Session, content_id: str) -> Channel | None:
    return session.scalars(select(Channel).where(Channel.content_id == content_id)).first()


def list_channels(session: Session) -> list[Channel]:
    return list(session.scalars(select(Channel).order_by(Channel.title, Channel.id)))


def update_channel(session: Session, channel_id: int, **changes) -> Channel:
    """Updates only the given fields; passing `category_id=None` clears the category."""
    unknown = changes.keys() - _UPDATABLE
    if unknown:
        raise ValidationError(f"cannot update: {', '.join(sorted(unknown))}")
    channel = get_channel(session, channel_id)
    if "title" in changes:
        changes["title"] = _clean_title(changes["title"])
    if "category_id" in changes:
        _check_category(session, changes["category_id"])
    for field, value in changes.items():
        setattr(channel, field, value)
    _commit_unique(session, changes.get("content_id", channel.content_id))
    return channel


def delete_channel(session: Session, channel_id: int, data_dir: Path = DATA_DIR) -> None:
    """Deletes the channel, its history and the screenshots stored under `data_dir`."""
    channel = get_channel(session, channel_id)
    screenshots = [c.screenshot_path for c in channel.checks if c.screenshot_path]
    session.delete(channel)
    session.commit()
    # Files go only after the commit, so a failed delete does not lose them.
    for relative in screenshots:
        _remove_screenshot(data_dir, relative)


def _commit_unique(session: Session, content_id: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if "UNIQUE" in str(exc.orig):
            raise DuplicateError(f"channel already exists: {content_id}") from exc
        raise ValidationError(f"invalid channel data: {exc.orig}") from exc


def _remove_screenshot(data_dir: Path, relative: str) -> None:
    root = data_dir.resolve()
    target = (root / relative).resolve()
    # Never delete outside the data directory, whatever the stored path says.
    if not target.is_relative_to(root):
        return
    target.unlink(missing_ok=True)
