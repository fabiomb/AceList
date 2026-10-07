import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.acestream.client import EngineClient, StreamSession
from app.acestream.content_id import InvalidContentIdError, parse_content_id
from app.config import DATA_DIR
from app.db.models import Channel, Check
from app.services import channels
from app.services.checks import record_verification
from app.services.errors import DuplicateError, ValidationError
from app.services.screenshots import CaptureSettings, ScreenshotError, capture_screenshot
from app.services.verification import VerificationSettings, verify

log = logging.getLogger(__name__)


def parse_link(link: str) -> str:
    """Content ID from user input, as a `ValidationError` like every other bad input."""
    try:
        return parse_content_id(link)
    except InvalidContentIdError as exc:
        raise ValidationError(str(exc)) from exc


def check_channel(
    session: Session,
    client: EngineClient,
    channel_id: int,
    *,
    settings: VerificationSettings | None = None,
    capture: CaptureSettings | None = None,
    data_dir: Path = DATA_DIR,
) -> Check:
    """Verifies a channel, takes a screenshot if it is alive, and stores the result.

    Never raises for engine or screenshot problems: they end up in the stored check.
    Blocks while the engine is polled, so call it from a worker thread.
    """
    channel = channels.get_channel(session, channel_id)
    content_id = channel.content_id
    capture = capture or CaptureSettings()
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

    result = verify(client, content_id, settings, on_alive=take_screenshot)
    return record_verification(session, channel_id, result, screenshot_path=screenshot)


def add_channel(
    session: Session,
    client: EngineClient,
    *,
    title: str,
    link: str,
    category_id: int | None = None,
    language: str | None = None,
    country: str | None = None,
    settings: VerificationSettings | None = None,
    capture: CaptureSettings | None = None,
    data_dir: Path = DATA_DIR,
) -> Channel:
    """Registers a channel from a Content ID or `acestream://` link and verifies it.

    The channel is saved before verifying, so an engine that is down leaves it stored
    with an `error` check instead of losing what the user typed.
    """
    content_id = parse_link(link)
    _ensure_free(session, content_id)
    channel = channels.create_channel(
        session,
        title=title,
        content_id=content_id,
        category_id=category_id,
        language=language,
        country=country,
    )
    check_channel(
        session, client, channel.id, settings=settings, capture=capture, data_dir=data_dir
    )
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

    `changes` accepts `title`, `category_id`, `language` and `country`.
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
        # History is kept: it is how the user sees that the old link died.
        check_channel(
            session, client, channel_id, settings=settings, capture=capture, data_dir=data_dir
        )
    return channel


def _ensure_free(session: Session, content_id: str, *, ignore: int | None = None) -> None:
    existing = channels.find_channel_by_content_id(session, content_id)
    if existing is not None and existing.id != ignore:
        raise DuplicateError(f"this Content ID is already registered as '{existing.title}'")
