from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.db import models  # noqa: F401
from app.db.base import Base

ROOT = Path(__file__).resolve().parent.parent


def _config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_migrations_match_models(tmp_path):
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    command.upgrade(_config(url), "head")

    engine = create_engine(url)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()

    assert diff == []


def test_downgrade_removes_all_tables(tmp_path):
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    config = _config(url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()

    assert tables <= {"alembic_version"}
