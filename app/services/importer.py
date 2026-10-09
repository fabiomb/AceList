import re
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy.orm import Session

from app.db.models import Channel
from app.services import channels
from app.services.errors import ValidationError
from app.services.iso import normalize_country, normalize_language
from app.services.naming import placeholder_title

MAX_LINES = 2000
_TITLE_LENGTH = 200  # the column length
_GROUP_LENGTH = 100  # SourceEntry.group
_GROUP_TITLE = re.compile(r'group-title="([^"]*)"', re.IGNORECASE)

# A Content ID anywhere in the line, bare or as an acestream:// link, in any case.
_LINK = re.compile(r"(?:acestream://)?(?<![0-9a-f])([0-9a-f]{40})(?![0-9a-f])", re.IGNORECASE)
# What usually separates a title from its link: "Title - acestream://...", "hash | Title".
_SEPARATORS = " \t-|,;:"


@dataclass(frozen=True)
class Entry:
    line: int  # 1-based, as the user sees it
    content_id: str
    title: str | None  # None: take the stream's name
    group: str | None = None  # an M3U list's `group-title`, if any


class Reason(StrEnum):
    NO_LINK = "no_link"  # the line has no Content ID
    INVALID = "invalid"  # an exported channel with data that does not validate
    REPEATED = "repeated"  # the same Content ID appeared on an earlier line
    EXISTING = "existing"  # the Content ID is already in the catalog


@dataclass(frozen=True)
class Rejected:
    line: int
    text: str
    reason: Reason
    first_line: int | None = None  # for REPEATED
    existing: Channel | None = None  # for EXISTING
    detail: str | None = None  # for INVALID: what was wrong


@dataclass
class ImportResult:
    unit: str = "line"  # what `Rejected.line` counts: "line" of text or exported "channel"
    created: list[Channel] = field(default_factory=list)
    duplicates: list[Rejected] = field(default_factory=list)
    invalid: list[Rejected] = field(default_factory=list)


def parse_links(text: str) -> tuple[list[Entry], list[Rejected]]:
    """Reads one link per line; `#EXTINF` lines of an M3U list name the link below them.

    Other `#` lines and blank lines are ignored. Text around the link becomes the title;
    without any, the title is None and the stream's name is used later.
    """
    entries: list[Entry] = []
    invalid: list[Rejected] = []
    pending_title: str | None = None
    pending_group: str | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("#EXTINF"):
            pending_title = _extinf_title(line)
            pending_group = _extinf_group(line)
            continue
        if line.startswith("#"):
            continue
        match = _LINK.search(line)
        if match is None:
            invalid.append(Rejected(number, line, Reason.NO_LINK))
            pending_title = pending_group = None
            continue
        content_id = match.group(1).lower()
        around = (line[: match.start()] + " " + line[match.end() :]).strip(_SEPARATORS)
        title = pending_title or around or None
        group = pending_group[:_GROUP_LENGTH] if pending_group else None
        entries.append(Entry(number, content_id, title[:_TITLE_LENGTH] if title else None, group))
        pending_title = pending_group = None
    return entries, invalid


def import_links(
    session: Session,
    text: str,
    *,
    category_id: int | None = None,
    language: str | None = None,
    country: str | None = None,
) -> ImportResult:
    """Creates a channel per new link, without verifying them (callers queue the checks).

    Links already in the catalog, or repeated in the text, are reported as duplicates.
    """
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        raise ValidationError(f"too many lines: {len(lines)} (at most {MAX_LINES})")
    # Checked once up front, so a bad value fails the whole import before creating anything.
    language = normalize_language(language)
    country = normalize_country(country)
    channels.check_category(session, category_id)

    entries, invalid = parse_links(text)
    result = ImportResult(invalid=invalid)
    seen: dict[str, int] = {}
    for entry in entries:
        if entry.content_id in seen:
            result.duplicates.append(
                Rejected(
                    entry.line, entry.content_id, Reason.REPEATED, first_line=seen[entry.content_id]
                )
            )
            continue
        seen[entry.content_id] = entry.line
        existing = channels.find_channel_by_content_id(session, entry.content_id)
        if existing is not None:
            result.duplicates.append(
                Rejected(entry.line, entry.content_id, Reason.EXISTING, existing=existing)
            )
            continue
        result.created.append(
            channels.create_channel(
                session,
                title=entry.title or placeholder_title(entry.content_id),
                title_pending=entry.title is None,
                content_id=entry.content_id,
                category_id=category_id,
                language=language,
                country=country,
            )
        )
    return result


def _extinf_title(line: str) -> str | None:
    # "#EXTINF:-1 tvg-name="a,b" group-title="Sports",Title": the title follows the
    # first comma outside quotes.
    quoted = False
    for index, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        elif char == "," and not quoted:
            return line[index + 1 :].strip() or None
    return None


def _extinf_group(line: str) -> str | None:
    match = _GROUP_TITLE.search(line)
    return (match.group(1).strip() or None) if match else None
