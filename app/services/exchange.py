"""AceList's own export file: every channel with the data stored for it, as JSON.

Check history and screenshots belong to the machine that made them and are not exported;
the importing machine verifies the channels itself.
"""

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.acestream.content_id import InvalidContentIdError, parse_content_id
from app.db.base import utcnow
from app.db.models import Channel
from app.services import categories, channels
from app.services.errors import ServiceError, ValidationError
from app.services.importer import MAX_LINES, ImportResult, Reason, Rejected
from app.services.iso import normalize_country, normalize_language
from app.services.naming import placeholder_title
from app.services.resolution import normalize_resolution

FORMAT = "acelist"
VERSION = 1
_TITLE_LENGTH = 200  # the column length


def export_channels(rows: Iterable[Channel], *, exported_at: datetime | None = None) -> dict:
    """The export document for the given channels, ready for `json.dumps`."""
    return {
        "format": FORMAT,
        "version": VERSION,
        "exported_at": (exported_at or utcnow()).isoformat(),
        "channels": [_export_channel(channel) for channel in rows],
    }


def _export_channel(channel: Channel) -> dict[str, Any]:
    return {
        "title": channel.title,
        "title_pending": channel.title_pending,
        "content_id": channel.content_id,
        "link": f"acestream://{channel.content_id}",
        "category": channel.category.name if channel.category else None,
        "language": channel.language,
        "country": channel.country,
        "resolution": channel.resolution.value if channel.resolution else None,
        "created_at": channel.created_at.isoformat(),
    }


def is_export(text: str) -> bool:
    """Whether `text` looks like an AceList export (a JSON object), not a list of links."""
    return text.lstrip().startswith("{")


def parse_export(text: str) -> list[Any]:
    """The `channels` of an export; raises `ValidationError` for anything else."""
    try:
        document = json.loads(text)
    except ValueError as exc:
        raise ValidationError(f"not valid JSON: {exc}") from exc
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise ValidationError('not an AceList export (missing "format": "acelist")')
    version = document.get("version")
    if not isinstance(version, int) or version > VERSION:
        raise ValidationError(f"unsupported export version: {version!r}")
    entries = document.get("channels")
    if not isinstance(entries, list):
        raise ValidationError('the export has no "channels" list')
    if len(entries) > MAX_LINES:
        raise ValidationError(f"too many channels: {len(entries)} (at most {MAX_LINES})")
    return entries


def import_export(
    session: Session,
    text: str,
    *,
    category_id: int | None = None,
    language: str | None = None,
    country: str | None = None,
) -> ImportResult:
    """Creates the channels of an export that are not in the catalog yet.

    Each channel keeps its exported data; the given category, language and country only
    fill in what a channel lacks. A channel with invalid data is reported and skipped,
    without stopping the rest. Callers queue the checks.
    """
    entries = parse_export(text)
    language = normalize_language(language)
    country = normalize_country(country)
    channels.check_category(session, category_id)

    result = ImportResult(unit="channel")
    seen: dict[str, int] = {}
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            result.invalid.append(
                Rejected(position, str(entry)[:120], Reason.INVALID, detail="not a channel")
            )
            continue
        raw_link = str(entry.get("content_id") or entry.get("link") or "")
        try:
            content_id = parse_content_id(raw_link)
        except InvalidContentIdError:
            result.invalid.append(Rejected(position, raw_link[:120], Reason.NO_LINK))
            continue
        if content_id in seen:
            result.duplicates.append(
                Rejected(position, content_id, Reason.REPEATED, first_line=seen[content_id])
            )
            continue
        seen[content_id] = position
        existing = channels.find_channel_by_content_id(session, content_id)
        if existing is not None:
            result.duplicates.append(
                Rejected(position, content_id, Reason.EXISTING, existing=existing)
            )
            continue
        try:
            channel = _create(session, entry, content_id, category_id, language, country)
        except ServiceError as exc:
            result.invalid.append(Rejected(position, content_id, Reason.INVALID, detail=str(exc)))
            continue
        result.created.append(channel)
    return result


def _create(
    session: Session,
    entry: dict,
    content_id: str,
    default_category_id: int | None,
    default_language: str | None,
    default_country: str | None,
) -> Channel:
    # Every field is checked before anything is written, so a bad channel leaves no trace.
    language = normalize_language(_text(entry, "language")) or default_language
    country = normalize_country(_text(entry, "country")) or default_country
    resolution = normalize_resolution(_text(entry, "resolution"))
    created_at = _datetime(entry.get("created_at"))
    title = (_text(entry, "title") or "").strip()[:_TITLE_LENGTH]
    pending = bool(entry.get("title_pending")) or not title
    category_name = (_text(entry, "category") or "").strip()

    category_id = (
        categories.find_or_create(session, category_name).id
        if category_name
        else default_category_id
    )
    channel = channels.create_channel(
        session,
        title=title or placeholder_title(content_id),
        title_pending=pending,
        content_id=content_id,
        category_id=category_id,
        language=language,
        country=country,
        resolution=resolution.value if resolution else None,
    )
    if created_at is not None:
        # The original date of addition travels with the channel.
        channel.created_at = created_at
        session.commit()
    return channel


def _text(entry: dict, key: str) -> str | None:
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{key} must be text, not {type(value).__name__}")
    return value


def _datetime(value: Any) -> datetime | None:
    """An ISO date from the export, as UTC; anything unreadable is ignored."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
