import sys
from pathlib import Path

from app import config


def test_from_source_the_data_stays_in_the_repository():
    assert config.default_data_dir(frozen=False) == config.ROOT_DIR / "data"


def test_the_executable_keeps_data_in_the_user_profile():
    data_dir = config.default_data_dir(
        frozen=True, environ={"LOCALAPPDATA": r"C:\Users\u\AppData\Local"}, platform="win32"
    )

    assert data_dir == Path(r"C:\Users\u\AppData\Local") / "AceList"


def test_without_localappdata_the_profile_is_found_anyway():
    data_dir = config.default_data_dir(frozen=True, environ={}, platform="win32")

    assert data_dir == Path.home() / "AppData" / "Local" / "AceList"


def test_linux_executable_uses_xdg_data_home():
    data_dir = config.default_data_dir(
        frozen=True, environ={"XDG_DATA_HOME": "/home/u/.data"}, platform="linux"
    )

    assert data_dir == Path("/home/u/.data/AceList")


def test_linux_executable_falls_back_to_the_standard_user_data_folder():
    assert config.default_data_dir(frozen=True, environ={}, platform="linux") == (
        Path.home() / ".local" / "share" / "AceList"
    )


def test_linux_ignores_a_relative_xdg_data_home():
    assert config.default_data_dir(
        frozen=True, environ={"XDG_DATA_HOME": "relative"}, platform="linux"
    ) == (Path.home() / ".local" / "share" / "AceList")


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
