from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Category, Channel
from app.services import categories, channels
from app.services.catalog import parse_link
from app.services.errors import ValidationError
from app.services.iso import normalize_country, normalize_language


@dataclass(frozen=True)
class ChannelData:
    """Validated form input, ready for the catalog services."""

    title: str
    content_id: str
    category_id: int | None
    new_category: str | None  # created on save; wins over `category_id`
    language: str | None
    country: str | None


@dataclass
class ChannelForm:
    """Raw values as typed, so a rejected form is shown again unchanged."""

    title: str = ""
    link: str = ""
    category_id: str = ""
    new_category: str = ""
    language: str = ""
    country: str = ""
    errors: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_channel(cls, channel: Channel) -> "ChannelForm":
        return cls(
            title=channel.title,
            link=channel.content_id,
            category_id=str(channel.category_id or ""),
            language=channel.language or "",
            country=channel.country or "",
        )

    def validate(self, session: Session, *, channel_id: int | None = None) -> ChannelData | None:
        """Checks every field and fills `errors` in Spanish; returns None if any failed.

        `channel_id` is the channel being edited, so its own Content ID is not a duplicate.
        """
        self.errors = {}
        title = self.title.strip()
        if not title:
            self.errors["title"] = "El título es obligatorio."

        content_id = ""
        try:
            content_id = parse_link(self.link)
        except ValidationError:
            self.errors["link"] = (
                "No es un Content ID válido: se esperan 40 caracteres hexadecimales "
                "o un enlace acestream://."
            )
        else:
            existing = channels.find_channel_by_content_id(session, content_id)
            if existing is not None and existing.id != channel_id:
                self.errors["link"] = f"Este Content ID ya está registrado como «{existing.title}»."

        category_id = None
        new_category = self.new_category.strip() or None
        if not new_category and self.category_id:
            chosen = int(self.category_id) if self.category_id.isdigit() else None
            if chosen is None or session.get(Category, chosen) is None:
                self.errors["category_id"] = "La categoría elegida no existe."
            else:
                category_id = chosen

        language = country = None
        try:
            language = normalize_language(self.language)
        except ValidationError:
            self.errors["language"] = "Idioma desconocido: usa un código ISO 639-1, como «es»."
        try:
            country = normalize_country(self.country)
        except ValidationError:
            self.errors["country"] = "País desconocido: usa un código ISO 3166-1, como «AR»."

        if self.errors:
            return None
        return ChannelData(title, content_id, category_id, new_category, language, country)


def resolve_category(session: Session, data: ChannelData) -> int | None:
    """Category id to store, creating the new category unless one has that name already."""
    if data.new_category is None:
        return data.category_id
    existing = session.scalars(
        select(Category).where(func.lower(Category.name) == data.new_category.lower())
    ).first()
    if existing is not None:
        return existing.id
    return categories.create_category(session, data.new_category).id
