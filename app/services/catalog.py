import logging
from enum import StrEnum
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.acestream.client import EngineClient, StreamSession
from app.acestream.content_id import InvalidContentIdError, parse_content_id
from app.acestream.errors import EngineError, EngineUnavailableError
from app.config import DATA_DIR
from app.db.models import Channel, Check
from app.services import channels
from app.services.checks import record_verification
from app.services.errors import DuplicateError, ValidationError
from app.services.naming import clean_stream_name, placeholder_title
from app.services.resolution import classify, frame_size
from app.services.screenshots import CaptureSettings, ScreenshotError, capture_screenshot
from app.services.verification import VerificationSettings, verify

log = logging.getLogger(__name__)


def parse_link(link: str) -> str:
    """Content ID from user input, as a `ValidationError` like every other bad input."""
    try:
        return parse_content_id(link)
    except InvalidContentIdError as exc:
        raise ValidationError(str(exc)) from exc


class Screenshots(StrEnum):
    """When a check of a live channel takes a screenshot."""

    NEVER = "never"  # a plain check: availability and peers only
    IF_MISSING = "if_missing"  # a new channel that has none yet
    ALWAYS = "always"  # regenerating, or a new link that is another stream


def check_channel(
    session: Session,
    client: EngineClient,
    channel_id: int,
    *,
    settings: VerificationSettings | None = None,
    capture: CaptureSettings | None = None,
    screenshots: Screenshots = Screenshots.NEVER,
    data_dir: Path = DATA_DIR,
) -> Check:
    """Verifies a channel and stores the result.

    By default only availability and peers are checked; `screenshots` decides whether a
    live channel also gets a screenshot, which adds seconds per channel.
    Engine and screenshot problems end up in the stored check, except an engine that
    cannot be reached: then `EngineUnavailableError` propagates and nothing is stored.
    Blocks while the engine is polled, so call it from a worker thread.
    """
    channel = channels.get_channel(session, channel_id)
    content_id = channel.content_id
    if channel.title_pending:
        _name_from_stream(session, client, channel)
    capture = capture or CaptureSettings()
    wants_screenshot = screenshots is Screenshots.ALWAYS or (
        screenshots is Screenshots.IF_MISSING and not has_screenshot(session, channel_id)
    )
    screenshot: str | None = None

    def take_screenshot(stream: StreamSession) -> None:
        nonlocal screenshot
        try:
            screenshot = capture_screenshot(
                stream.playback_url,
                content_id,
                data_dir=data_dir,
                ffmpeg_path=capture.ffmpeg_path,
                timeout=capture.timeout,
            )
        except ScreenshotError as exc:
            # A missing screenshot must not turn a live channel into a failed check.
            log.warning("no screenshot for %s: %s", content_id, exc)

    result = verify(
        client, content_id, settings, on_alive=take_screenshot if wants_screenshot else None
    )
    frame = frame_size(data_dir / screenshot) if screenshot else None
    check = record_verification(
        session, channel_id, result, screenshot_path=screenshot, frame=frame
    )
    if frame is not None:
        # The stream is the authority: a detected resolution replaces one set by hand.
        channels.update_channel(session, channel_id, resolution=classify(*frame).value)
    return check


def _name_from_stream(session: Session, client: EngineClient, channel: Channel) -> None:
    """Replaces a provisional title with the content's published name, if the engine has it."""
    try:
        name = clean_stream_name(client.media_name(channel.content_id))
    except EngineError as exc:
        # The title stays provisional and the next check tries again.
        log.warning("no stream name for %s: %s", channel.content_id, exc)
        return
    if name is not None:
        channels.update_channel(session, channel.id, title=name)


def has_screenshot(session: Session, channel_id: int) -> bool:
    return (
        session.scalar(
            select(Check.id)
            .where(Check.channel_id == channel_id, Check.screenshot_path.is_not(None))
            .limit(1)
        )
        is not None
    )


def add_channel(
    session: Session,
    client: EngineClient,
    *,
    title: str = "",
    link: str,
    category_id: int | None = None,
    language: str | None = None,
    country: str | None = None,
    resolution: str | None = None,
    settings: VerificationSettings | None = None,
    capture: CaptureSettings | None = None,
    data_dir: Path = DATA_DIR,
) -> Channel:
    """Registers a channel from a Content ID or `acestream://` link and verifies it.

    The channel is saved before verifying, so an engine that is down leaves it stored
    and unchecked instead of losing what the user typed. Without a title it
    gets the stream's name, or a provisional one until a check finds that name.
    """
    content_id = parse_link(link)
    _ensure_free(session, content_id)
    pending = not title.strip()
    channel = channels.create_channel(
        session,
        title=placeholder_title(content_id) if pending else title,
        title_pending=pending,
        content_id=content_id,
        category_id=category_id,
        language=language,
        country=country,
        resolution=resolution,
    )
    try:
        check_channel(
            session,
            client,
            channel.id,
            settings=settings,
            capture=capture,
            screenshots=Screenshots.IF_MISSING,
            data_dir=data_dir,
        )
    except EngineUnavailableError as exc:
        # Kept unchecked: the engine being off says nothing about the channel.
        log.warning("engine unavailable, %s saved unchecked: %s", content_id, exc)
    return channel


def edit_channel(
    session: Session,
    client: EngineClient,
    channel_id: int,
    *,
    link: str | None = None,
    settings: VerificationSettings | None = None,
    capture: CaptureSettings | None = None,
    data_dir: Path = DATA_DIR,
    **changes,
) -> Channel:
    """Updates a channel; a new Content ID is verified again, other edits are not.

    `changes` accepts `title`, `category_id`, `language`, `country` and `resolution`.
    """
    if "content_id" in changes:
        raise ValidationError("change the Content ID through `link` so it is validated")
    channel = channels.get_channel(session, channel_id)
    new_content_id = parse_link(link) if link is not None else None
    hash_changed = new_content_id is not None and new_content_id != channel.content_id
    if hash_changed:
        _ensure_free(session, new_content_id, ignore=channel_id)
        changes["content_id"] = new_content_id

    channels.update_channel(session, channel_id, **changes)
    if hash_changed:
        # History is kept: it is how the user sees that the old link died. The new
        # link is another stream, so the old screenshots no longer show it.
        try:
            check_channel(
                session,
                client,
                channel_id,
                settings=settings,
                capture=capture,
                screenshots=Screenshots.ALWAYS,
                data_dir=data_dir,
            )
        except EngineUnavailableError as exc:
            log.warning("engine unavailable, %s left unchecked: %s", new_content_id, exc)
    return channel


def _ensure_free(session: Session, content_id: str, *, ignore: int | None = None) -> None:
    existing = channels.find_channel_by_content_id(session, content_id)
    if existing is not None and existing.id != ignore:
        raise DuplicateError(f"this Content ID is already registered as '{existing.title}'")
