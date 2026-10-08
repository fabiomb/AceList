import sys
from pathlib import Path

from app import config


def test_from_source_the_data_stays_in_the_repository():
    assert config.default_data_dir(frozen=False) == config.ROOT_DIR / "data"


def test_the_executable_keeps_data_in_the_user_profile():
    data_dir = config.default_data_dir(
        frozen=True, environ={"LOCALAPPDATA": r"C:\Users\u\AppData\Local"}
    )

    assert data_dir == Path(r"C:\Users\u\AppData\Local") / "AceList"


def test_without_localappdata_the_profile_is_found_anyway():
    data_dir = config.default_data_dir(frozen=True, environ={})

    assert data_dir == Path.home() / "AppData" / "Local" / "AceList"


def test_resources_come_from_the_repository_when_running_from_source():
    assert config.resource_dir(frozen=False) == config.ROOT_DIR
    assert (config.resource_dir(frozen=False) / "migrations" / "env.py").is_file()


def test_resources_come_from_the_bundle_in_the_executable(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert config.resource_dir(frozen=True) == tmp_path


def test_the_tests_never_use_the_real_data_directory():
    # conftest.py points ACELIST_DATA_DIR at a temporary folder before the app is imported.
    assert config.DATA_DIR != config.default_data_dir()
    assert "acelist-tests-" in str(config.DATA_DIR)
