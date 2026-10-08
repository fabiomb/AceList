from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Category, Channel
from app.services.errors import CategoryInUseError, DuplicateError, NotFoundError, ValidationError


def _clean_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValidationError("category name must not be empty")
    return name


def create_category(session: Session, name: str) -> Category:
    category = Category(name=_clean_name(name))
    session.add(category)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateError(f"category already exists: {category.name}") from exc
    return category


def find_or_create(session: Session, name: str) -> Category:
    """The category with this name, ignoring case, created if there is none."""
    clean = _clean_name(name)
    existing = session.scalars(
        select(Category).where(func.lower(Category.name) == clean.lower())
    ).first()
    return existing if existing is not None else create_category(session, clean)


def get_category(session: Session, category_id: int) -> Category:
    category = session.get(Category, category_id)
    if category is None:
        raise NotFoundError(f"category not found: {category_id}")
    return category


def list_categories(session: Session) -> list[Category]:
    return list(session.scalars(select(Category).order_by(Category.name)))


def rename_category(session: Session, category_id: int, name: str) -> Category:
    category = get_category(session, category_id)
    category.name = _clean_name(name)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateError(f"category already exists: {name.strip()}") from exc
    return category


def delete_category(session: Session, category_id: int) -> None:
    category = get_category(session, category_id)
    in_use = session.scalar(
        select(func.count()).select_from(Channel).where(Channel.category_id == category_id)
    )
    if in_use:
        raise CategoryInUseError(
            f"category '{category.name}' is used by {in_use} channel(s); reassign them first"
        )
    session.delete(category)
    session.commit()
