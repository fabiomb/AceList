from functools import cache

import pycountry

from app.services.errors import ValidationError


@cache
def _languages() -> dict[str, str]:
    # ISO 639-1 only: two-letter codes, as stored on a channel.
    found = {lang.alpha_2: lang.name for lang in pycountry.languages if hasattr(lang, "alpha_2")}
    return dict(sorted(found.items(), key=lambda item: item[1]))


@cache
def _countries() -> dict[str, str]:
    found = {c.alpha_2: getattr(c, "common_name", c.name) for c in pycountry.countries}
    return dict(sorted(found.items(), key=lambda item: item[1]))


def language_choices() -> list[tuple[str, str]]:
    """(code, name) pairs sorted by name, for form selects."""
    return list(_languages().items())


def country_choices() -> list[tuple[str, str]]:
    return list(_countries().items())


def language_name(code: str | None) -> str | None:
    return _languages().get(code) if code else None


def country_name(code: str | None) -> str | None:
    return _countries().get(code) if code else None


def normalize_language(value: str | None) -> str | None:
    """ISO 639-1 code in lowercase; blank means no language."""
    code = (value or "").strip().lower()
    if not code:
        return None
    if code not in _languages():
        raise ValidationError(f"unknown language code '{value.strip()}' (use ISO 639-1, e.g. 'es')")
    return code


def normalize_country(value: str | None) -> str | None:
    """ISO 3166-1 alpha-2 code in uppercase; blank means no country."""
    code = (value or "").strip().upper()
    if not code:
        return None
    if code not in _countries():
        raise ValidationError(
            f"unknown country code '{value.strip()}' (use ISO 3166-1 alpha-2, e.g. 'AR')"
        )
    return code
