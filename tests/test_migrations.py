from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

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


def test_resolution_migration_keeps_existing_channels_and_enforces_values(tmp_path):
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    config = _config(url)
    command.upgrade(config, "0001")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO channel (title, content_id, created_at, updated_at) VALUES "
            "('Uno', '78266c15035d0ad8cbc58f821733931e1de434ab', '2026-10-07', '2026-10-07')"
        )

    command.upgrade(config, "head")

    with engine.begin() as connection:
        assert connection.exec_driver_sql("SELECT title, resolution FROM channel").all() == [
            ("Uno", None)
        ]
        connection.exec_driver_sql("UPDATE channel SET resolution = '1080p'")
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.exec_driver_sql("UPDATE channel SET resolution = '8k'")
    constraints = {c["name"] for c in inspect(engine).get_check_constraints("channel")}
    engine.dispose()

    assert "ck_channel_resolution_valid" in constraints


def test_source_files_migration_allows_sources_without_url(tmp_path):
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    config = _config(url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO source (id, name, url, enabled, created_at) VALUES "
            "(1, 'Web', 'https://lists.test/a.m3u', 1, '2026-10-10'), "
            "(2, 'Archivo', NULL, 1, '2026-10-10')"
        )
        connection.exec_driver_sql(
            "INSERT INTO source_entry (source_id, content_id, position) VALUES "
            "(1, '78266c15035d0ad8cbc58f821733931e1de434ab', 1), "
            "(2, 'ecc85e5d2b6088d2d307fd0b5de4f09f089e762f', 1)"
        )

    command.downgrade(config, "0004")

    with engine.begin() as connection:
        assert connection.exec_driver_sql("SELECT name FROM source").all() == [("Web",)]
        assert connection.exec_driver_sql("SELECT source_id FROM source_entry").all() == [(1,)]
    engine.dispose()
