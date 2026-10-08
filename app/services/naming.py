import re

_TITLE_LENGTH = 200  # the column length
# Published names often carry ads: "DAZN 1 1080 elcano.top https://x.com/... https://t.me/...".
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_SEPARATORS = " \t-|,;:"


def placeholder_title(content_id: str) -> str:
    """Provisional title of a channel the user did not name."""
    return f"Canal {content_id[:8]}"


def clean_stream_name(raw: str | None) -> str | None:
    """A usable title from the engine's content name: no URLs, single spaces, column length."""
    if not raw:
        return None
    text = " ".join(_URL.sub(" ", raw).split()).strip(_SEPARATORS)
    return text[:_TITLE_LENGTH].rstrip() or None
