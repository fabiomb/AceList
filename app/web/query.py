from starlette.datastructures import QueryParams

from app.db.models import CheckStatus
from app.services.iso import country_name, language_name
from app.services.listing import DEFAULT_DESCENDING, UNCHECKED, ChannelQuery, SortKey

STATUS_FILTERS = [*(s.value for s in CheckStatus), UNCHECKED]


def parse_query(params: QueryParams) -> ChannelQuery:
    """Reads filters and order from the URL; values that make no sense are ignored."""
    text = params.get("q", "").strip() or None
    category = params.get("category", "")
    language = params.get("language", "").strip().lower()
    country = params.get("country", "").strip().upper()
    status = params.get("status", "")
    try:
        sort = SortKey(params.get("sort", ""))
    except ValueError:
        sort = SortKey.TITLE
    direction = params.get("dir")
    return ChannelQuery(
        text=text,
        category_id=int(category) if category.isdigit() else None,
        language=language if language_name(language) else None,
        country=country if country_name(country) else None,
        status=status if status in STATUS_FILTERS else None,
        sort=sort,
        descending=direction == "desc"
        if direction in ("asc", "desc")
        else DEFAULT_DESCENDING[sort],
    )
