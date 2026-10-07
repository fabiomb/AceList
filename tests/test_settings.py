from app.acestream.install import engine_candidates, find_engine_executable
from app.db.models import Setting
from app.services.settings import AppSettings, load_settings, save_settings


def test_defaults_when_nothing_is_saved(db):
    assert load_settings(db) == AppSettings()


def test_saved_settings_are_loaded_back(db):
    saved = AppSettings(
        engine_url="http://192.168.1.5:6878",
        engine_timeout=9.5,
        min_peers=3,
        check_timeout=45,
        screenshot_timeout=12,
        check_concurrency=4,
        vlc_path="C:/VLC/vlc.exe",
        ffmpeg_path="C:/ffmpeg/ffmpeg.exe",
        acestream_path="C:/ace/ace_engine.exe",
    )

    save_settings(db, saved)

    assert load_settings(db) == saved


def test_a_cleared_path_is_removed_so_it_is_detected_again(db):
    save_settings(db, AppSettings(vlc_path="C:/VLC/vlc.exe"))
    save_settings(db, AppSettings(vlc_path=None))

    assert db.get(Setting, "vlc_path") is None
    assert load_settings(db).vlc_path is None


def test_a_stored_value_that_does_not_parse_falls_back_to_the_default(db):
    db.add(Setting(key="min_peers", value="many"))
    db.add(Setting(key="check_timeout", value="30"))
    db.commit()

    loaded = load_settings(db)

    assert loaded.min_peers == AppSettings().min_peers
    assert loaded.check_timeout == 30


def test_settings_build_the_verification_and_capture_options():
    settings = AppSettings(min_peers=4, check_timeout=33, screenshot_timeout=8, ffmpeg_path="f")

    verification = settings.verification()
    capture = settings.capture()

    assert (verification.min_peers, verification.timeout) == (4, 33)
    assert (capture.ffmpeg_path, capture.timeout) == ("f", 8)


# engine install detection


def test_engine_candidates_cover_appdata_and_program_files(monkeypatch):
    monkeypatch.setenv("APPDATA", "C:/Users/u/AppData/Roaming")
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/u/AppData/Local")
    monkeypatch.setenv("ProgramFiles", "C:/PF")
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)

    found = [path.as_posix() for path in engine_candidates()]

    assert found == [
        "C:/Users/u/AppData/Roaming/ACEStream/engine/ace_engine.exe",
        "C:/Users/u/AppData/Local/ACEStream/engine/ace_engine.exe",
        "C:/PF/ACEStream/engine/ace_engine.exe",
    ]


def test_find_engine_returns_the_first_existing_candidate(tmp_path):
    exe = tmp_path / "ace_engine.exe"
    exe.write_bytes(b"")

    assert find_engine_executable([tmp_path / "nope.exe", exe]) == str(exe)
    assert find_engine_executable([tmp_path / "nope.exe"]) is None
