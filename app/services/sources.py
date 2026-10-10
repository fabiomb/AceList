"""Channel sources: lists (M3U, links, AceList exports) to explore and pick from.

A source is a list on the web or a file the user uploaded. A refresh downloads a web list
and stores what it found in `source_entry`, so exploring and searching never wait for the
network; a file is read once, when it is uploaded. AceList ships with no sources.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePath
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import __version__
from app.acestream.content_id import InvalidContentIdError, parse_content_id
from app.db.base import utcnow
from app.db.models import Channel, Source, SourceEntry
from app.services import channels, exchange, importer
from app.services.errors import DuplicateError, NotFoundError, ValidationError
from app.services.importer import ImportResult, Reason, Rejected
from app.services.naming import clean_stream_name, placeholder_title

MAX_SOURCE_BYTES = 5 * 1024 * 1024
MAX_ENTRIES = 5000  # per source
FETCH_TIMEOUT = 20.0
EXPLORE_LIMIT = 200  # rows shown at once; the search narrows the rest
_NAME_LENGTH = 100
_URL_LENGTH = 1000
_TITLE_LENGTH = 200
_GROUP_LENGTH = 100
_ERROR_LENGTH = 500


class SourceFetchError(Exception):
    """A source could not be downloaded or read; the message is shown to the user."""


@dataclass(frozen=True)
class ParsedEntry:
    content_id: str
    title: str | None
    group: str | None


@dataclass(frozen=True)
class ExploreQuery:
    text: str | None = None  # in the title, the group or the Content ID
    source_id: int | None = None
    only_new: bool = False  # hide the channels already in the catalog


@dataclass(frozen=True)
class ExploreRow:
    entry: SourceEntry
    source_name: str
    channel: Channel | None  # the catalog channel with this Content ID, if any


@dataclass(frozen=True)
class ExploreResult:
    rows: list[ExploreRow]
    total: int  # matches before the limit


def list_sources(session: Session) -> list[Source]:
    return list(session.scalars(select(Source).order_by(func.lower(Source.name))))


def get_source(session: Session, source_id: int) -> Source:
    source = session.get(Source, source_id)
    if source is None:
        raise NotFoundError(f"source not found: {source_id}")
    return source


def _normalize_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise ValidationError("name: required")
    if len(name) > _NAME_LENGTH:
        raise ValidationError(f"name: at most {_NAME_LENGTH} characters")
    return name


def normalize_source(name: str, url: str) -> tuple[str, str]:
    """Validated name and URL; raises `ValidationError` naming the bad field."""
    name = _normalize_name(name)
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValidationError("url: must be an http:// or https:// address")
    if len(url) > _URL_LENGTH:
        raise ValidationError(f"url: at most {_URL_LENGTH} characters")
    return name, url


def create_source(session: Session, *, name: str, url: str) -> Source:
    name, url = normalize_source(name, url)
    source = Source(name=name, url=url)
    session.add(source)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateError(f"a source named {name!r} already exists") from exc
    return source


def add_file_source(session: Session, *, name: str, filename: str, data: bytes) -> Source:
    """A source read from an uploaded file, named after the file unless `name` is given.

    Uploading again under the name of a file source replaces its entries. A file that is
    too big or has no Ace Stream links raises `SourceFetchError` and changes nothing.
    """
    name = _normalize_name(name or PurePath(filename.replace("\\", "/")).stem)
    if len(data) > MAX_SOURCE_BYTES:
        raise SourceFetchError(f"El archivo supera los {MAX_SOURCE_BYTES // (1024 * 1024)} MB.")
    entries = parse_source(decode_text(data))
    if not entries:
        raise SourceFetchError("El archivo no tiene enlaces de Ace Stream.")
    source = session.scalar(select(Source).where(Source.name == name))
    if source is not None and source.url is not None:
        raise DuplicateError(f"a web source named {name!r} already exists")
    if source is None:
        source = Source(name=name, url=None)
        session.add(source)
        session.flush()
    source.fetched_at = utcnow()
    _store_entries(session, source, entries)
    return source


def set_enabled(session: Session, source_id: int, enabled: bool) -> Source:
    source = get_source(session, source_id)
    source.enabled = enabled
    session.commit()
    return source


def delete_source(session: Session, source_id: int) -> None:
    session.delete(get_source(session, source_id))
    session.commit()


def parse_source(text: str) -> list[ParsedEntry]:
    """Channels in a list: an AceList export, or links / M3U as the importer reads them.

    Repeated Content IDs keep their first appearance; lines without one are skipped.
    """
    if exchange.is_export(text):
        try:
            items = exchange.parse_export(text)
        except ValidationError as exc:
            raise SourceFetchError(f"No es una exportación de AceList válida: {exc}") from exc
        parsed = [_export_entry(item) for item in items if isinstance(item, dict)]
        found = [entry for entry in parsed if entry is not None]
    else:
        links, _ = importer.parse_links(text)
        found = [ParsedEntry(e.content_id, e.title, e.group) for e in links]
    unique: dict[str, ParsedEntry] = {}
    for entry in found:
        unique.setdefault(entry.content_id, entry)
    return list(unique.values())[:MAX_ENTRIES]


def _export_entry(item: dict) -> ParsedEntry | None:
    try:
        content_id = parse_content_id(str(item.get("content_id") or item.get("link") or ""))
    except InvalidContentIdError:
        return None
    title = item.get("title") if not item.get("title_pending") else None
    group = item.get("category")
    return ParsedEntry(
        content_id,
        _text(title, _TITLE_LENGTH),
        _text(group, _GROUP_LENGTH),
    )


def _text(value: object, length: int) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split())[:length] or None


def make_client() -> httpx.Client:
    return httpx.Client(
        timeout=FETCH_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": f"AceList/{__version__}"},
    )


def fetch_text(client: httpx.Client, url: str) -> str:
    """The list at `url` as text, refusing anything over `MAX_SOURCE_BYTES`."""
    try:
        with client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise SourceFetchError(f"El servidor respondió {response.status_code}.")
            data = bytearray()
            for chunk in response.iter_bytes():
                data += chunk
                if len(data) > MAX_SOURCE_BYTES:
                    raise SourceFetchError(
                        f"La lista supera los {MAX_SOURCE_BYTES // (1024 * 1024)} MB."
                    )
    except httpx.TimeoutException as exc:
        raise SourceFetchError("No respondió a tiempo.") from exc
    except httpx.HTTPError as exc:
        raise SourceFetchError(f"No se pudo descargar: {exc}") from exc
    return decode_text(bytes(data))


def decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Old M3U lists are often Latin-1; any byte decodes, so this never fails.
        return data.decode("latin-1")


def refresh_source(session: Session, source: Source, client: httpx.Client) -> Source:
    """Downloads the source and replaces its entries.

    On failure the previous entries stay, so a list that is down for a while can still
    be explored; the error is recorded and shown next to the source. A file source has
    nothing to download and is left as it is.
    """
    if source.url is None:
        return source
    source.fetched_at = utcnow()
    try:
        entries = parse_source(fetch_text(client, source.url))
    except SourceFetchError as exc:
        source.error_message = str(exc)[:_ERROR_LENGTH]
        session.commit()
        return source
    _store_entries(session, source, entries)
    return source


def _store_entries(session: Session, source: Source, entries: list[ParsedEntry]) -> None:
    session.execute(delete(SourceEntry).where(SourceEntry.source_id == source.id))
    session.add_all(
        SourceEntry(
            source_id=source.id,
            content_id=entry.content_id,
            title=entry.title,
            group=entry.group,
            position=position,
        )
        for position, entry in enumerate(entries, start=1)
    )
    source.entry_count = len(entries)
    source.error_message = None if entries else "La lista no tiene enlaces de Ace Stream."
    session.commit()


def refresh_sources(session: Session, client: httpx.Client) -> list[Source]:
    """Refreshes every enabled web source, one after the other."""
    refreshed = []
    for source in list_sources(session):
        if source.enabled and source.url is not None:
            refreshed.append(refresh_source(session, source, client))
    return refreshed


def explore(session: Session, query: ExploreQuery, *, limit: int = EXPLORE_LIMIT) -> ExploreResult:
    """Entries of the enabled sources, with the catalog channel each one matches, if any."""
    stmt = (
        select(SourceEntry, Source.name, Channel)
        .join(Source, Source.id == SourceEntry.source_id)
        .outerjoin(Channel, Channel.content_id == SourceEntry.content_id)
        .where(Source.enabled)
    )
    if query.text and query.text.strip():
        text = query.text.strip()
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        stmt = stmt.where(
            or_(
                SourceEntry.title.ilike(pattern, escape="\\"),
                SourceEntry.group.ilike(pattern, escape="\\"),
                SourceEntry.content_id.contains(
                    text.lower().removeprefix("acestream://"), autoescape=True
                ),
            )
        )
    if query.source_id is not None:
        stmt = stmt.where(SourceEntry.source_id == query.source_id)
    if query.only_new:
        stmt = stmt.where(Channel.id.is_(None))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(
        SourceEntry.title.is_(None),
        func.lower(SourceEntry.title),
        func.lower(Source.name),
        SourceEntry.position,
    ).limit(limit)
    rows = [ExploreRow(entry, name, channel) for entry, name, channel in session.execute(stmt)]
    return ExploreResult(rows, total)


def add_entries(
    session: Session, entry_ids: Iterable[int], *, category_id: int | None = None
) -> ImportResult:
    """Creates a catalog channel for each chosen entry not in the catalog yet.

    Channels are not verified here: callers queue the checks, as with an import.
    """
    channels.check_category(session, category_id)
    ids = sorted(set(entry_ids))
    entries = session.scalars(select(SourceEntry).where(SourceEntry.id.in_(ids))).all()
    result = ImportResult(unit="channel")
    seen: dict[str, int] = {}
    for entry in sorted(entries, key=lambda e: e.id):
        if entry.content_id in seen:
            result.duplicates.append(
                Rejected(
                    entry.id, entry.content_id, Reason.REPEATED, first_line=seen[entry.content_id]
                )
            )
            continue
        seen[entry.content_id] = entry.id
        existing = channels.find_channel_by_content_id(session, entry.content_id)
        if existing is not None:
            result.duplicates.append(
                Rejected(entry.id, entry.content_id, Reason.EXISTING, existing=existing)
            )
            continue
        title = clean_stream_name(entry.title)
        result.created.append(
            channels.create_channel(
                session,
                title=title or placeholder_title(entry.content_id),
                title_pending=title is None,
                content_id=entry.content_id,
                category_id=category_id,
            )
        )
    return result
