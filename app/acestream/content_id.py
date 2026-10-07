import re

_SCHEME = "acestream://"
_CONTENT_ID = re.compile(r"[0-9a-f]{40}", re.IGNORECASE | re.ASCII)


class InvalidContentIdError(ValueError):
    pass


def parse_content_id(value: str) -> str:
    """Returns the Content ID in canonical form (40 lowercase hex characters).

    Accepts a bare Content ID or an `acestream://` link, with surrounding
    whitespace ignored. Anything else raises `InvalidContentIdError`.
    """
    candidate = value.strip()
    if candidate[: len(_SCHEME)].lower() == _SCHEME:
        candidate = candidate[len(_SCHEME) :]
    if not _CONTENT_ID.fullmatch(candidate):
        shown = value.strip()
        if len(shown) > 60:
            shown = shown[:57] + "..."
        raise InvalidContentIdError(
            f"not a valid Acestream Content ID or acestream:// link: {shown!r} "
            "(expected 40 hexadecimal characters)"
        )
    return candidate.lower()
