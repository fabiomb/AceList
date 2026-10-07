import functools
import shutil
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.acestream.content_id import InvalidContentIdError
from app.services import screenshots
from app.services.screenshots import (
    FfmpegNotFoundError,
    ScreenshotError,
    capture_screenshot,
    find_ffmpeg,
)

HASH = "78266c15035d0ad8cbc58f821733931e1de434ab"
URL = "http://127.0.0.1:6878/ace/r/abc/def"


def completed(returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout="", stderr=stderr)


class FakeFfmpeg:
    """Stands in for subprocess.run: writes `content` where ffmpeg would."""

    def __init__(self, content=b"\xff\xd8jpeg", returncode=0, stderr="", exc=None):
        self.content = content
        self.returncode = returncode
        self.stderr = stderr
        self.exc = exc
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self.exc:
            raise self.exc
        if self.content is not None:
            Path(command[-1]).write_bytes(self.content)
        return completed(self.returncode, self.stderr)


def capture(tmp_path, runner, **kwargs):
    return capture_screenshot(
        kwargs.pop("url", URL),
        kwargs.pop("content_id", HASH),
        data_dir=tmp_path,
        ffmpeg_path="ffmpeg",
        runner=runner,
        **kwargs,
    )


def files_left(tmp_path):
    return sorted(p.name for p in (tmp_path / "screenshots").glob("*"))


def test_success_returns_a_path_relative_to_the_data_dir(tmp_path):
    relative = capture(tmp_path, FakeFfmpeg())

    assert relative.startswith(f"screenshots/{HASH}_")
    assert relative.endswith(".jpg")
    assert (tmp_path / relative).read_bytes() == b"\xff\xd8jpeg"
    assert len(files_left(tmp_path)) == 1  # no .part file


def test_each_capture_gets_its_own_file(tmp_path):
    first = capture(tmp_path, FakeFfmpeg())
    second = capture(tmp_path, FakeFfmpeg())

    assert first != second


def test_ffmpeg_runs_without_shell_and_with_a_restricted_protocol_list(tmp_path):
    runner = FakeFfmpeg()

    capture(tmp_path, runner, timeout=12)

    command, kwargs = runner.calls[0]
    assert isinstance(command, list)
    assert "shell" not in kwargs or kwargs["shell"] is False
    assert kwargs["timeout"] == 12
    assert command[command.index("-i") + 1] == URL
    assert command[command.index("-protocol_whitelist") + 1] == "http,https,tcp,tls"
    assert "-nostdin" in command


def test_decoder_warnings_do_not_fail_a_successful_capture(tmp_path):
    runner = FakeFfmpeg(stderr="[h264] non-existing PPS 0 referenced\n[h264] no frame!")

    assert capture(tmp_path, runner).endswith(".jpg")


def test_timeout_raises_and_leaves_no_partial_file(tmp_path):
    runner = FakeFfmpeg(exc=subprocess.TimeoutExpired("ffmpeg", 5))

    with pytest.raises(ScreenshotError, match="timed out"):
        capture(tmp_path, runner, timeout=5)

    assert files_left(tmp_path) == []


def test_failure_reports_stderr_and_removes_the_partial_file(tmp_path):
    runner = FakeFfmpeg(returncode=1, stderr="Server returned 404 Not Found", content=b"half")

    with pytest.raises(ScreenshotError, match="404"):
        capture(tmp_path, runner)

    assert files_left(tmp_path) == []


def test_exit_zero_without_a_file_is_a_failure(tmp_path):
    with pytest.raises(ScreenshotError, match="no frame"):
        capture(tmp_path, FakeFfmpeg(content=None))


def test_empty_output_is_a_failure(tmp_path):
    with pytest.raises(ScreenshotError):
        capture(tmp_path, FakeFfmpeg(content=b""))

    assert files_left(tmp_path) == []


def test_os_error_launching_ffmpeg_is_a_screenshot_error(tmp_path):
    with pytest.raises(ScreenshotError, match="could not run"):
        capture(tmp_path, FakeFfmpeg(exc=PermissionError("denied")))


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "-f", "concat:a|b", "ftp://host/x", "rtsp://host/x", ""],
)
def test_only_http_urls_reach_ffmpeg(tmp_path, url):
    runner = FakeFfmpeg()

    with pytest.raises(ScreenshotError, match="http"):
        capture(tmp_path, runner, url=url)

    assert runner.calls == []


@pytest.mark.parametrize("bad_id", ["../../evil", "nope", HASH[:-1]])
def test_content_id_is_validated_so_it_cannot_shape_the_file_path(tmp_path, bad_id):
    runner = FakeFfmpeg()

    with pytest.raises(InvalidContentIdError):
        capture(tmp_path, runner, content_id=bad_id)

    assert runner.calls == []


def test_missing_ffmpeg_has_a_clear_message(tmp_path, monkeypatch):
    monkeypatch.setattr(screenshots, "find_ffmpeg", lambda *a: None)

    with pytest.raises(FfmpegNotFoundError, match="ACELIST_FFMPEG_PATH"):
        capture_screenshot(URL, HASH, data_dir=tmp_path, runner=FakeFfmpeg())


def test_find_ffmpeg_uses_the_configured_path_when_it_exists(tmp_path):
    exe = tmp_path / "ffmpeg.exe"
    exe.write_bytes(b"")

    assert find_ffmpeg(str(exe)) == str(exe)


def test_find_ffmpeg_does_not_fall_back_when_the_configured_path_is_wrong(tmp_path):
    assert find_ffmpeg(str(tmp_path / "missing.exe")) is None


def test_find_ffmpeg_looks_on_path_by_default(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: f"C:/tools/{name}.exe")

    assert find_ffmpeg(None) == "C:/tools/ffmpeg.exe"


# real ffmpeg against a local HTTP server


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def http_clip(tmp_path):
    ffmpeg = find_ffmpeg(None)
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=64x64:rate=5",
            str(tmp_path / "clip.mp4"),
        ],
        check=True,
        timeout=60,
    )
    handler = functools.partial(_QuietHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/clip.mp4"
    server.shutdown()
    server.server_close()


@pytest.mark.skipif(find_ffmpeg(None) is None, reason="ffmpeg is not installed")
def test_real_ffmpeg_captures_a_jpeg_over_http(tmp_path, http_clip):
    data_dir = tmp_path / "data"

    relative = capture_screenshot(http_clip, HASH, data_dir=data_dir, timeout=60)

    assert (data_dir / relative).read_bytes()[:2] == b"\xff\xd8"
