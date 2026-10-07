import os
import shutil
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from app.acestream.content_id import parse_content_id
from app.config import DATA_DIR, FFMPEG_PATH, SCREENSHOT_TIMEOUT

SCREENSHOTS_SUBDIR = "screenshots"


@dataclass(frozen=True)
class CaptureSettings:
    ffmpeg_path: str | None = None  # None: the ACELIST_FFMPEG_PATH setting, then PATH
    timeout: float = SCREENSHOT_TIMEOUT


class ScreenshotError(Exception):
    """The screenshot could not be taken; callers store the check without one."""


class FfmpegNotFoundError(ScreenshotError):
    pass


def find_ffmpeg(configured: str | None = FFMPEG_PATH) -> str | None:
    """Path of the ffmpeg executable, from the setting or from PATH."""
    if configured:
        return configured if Path(configured).is_file() else None
    return shutil.which("ffmpeg")


def capture_screenshot(
    playback_url: str,
    content_id: str,
    *,
    data_dir: Path = DATA_DIR,
    ffmpeg_path: str | None = None,
    timeout: float = SCREENSHOT_TIMEOUT,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> str:
    """Saves one frame of a live stream and returns its path relative to `data_dir`.

    The stream must already be playing (engine status `dl`). Raises
    `FfmpegNotFoundError` or `ScreenshotError`; no partial file is left behind.
    """
    content_id = parse_content_id(content_id)
    if urlsplit(playback_url).scheme not in ("http", "https"):
        raise ScreenshotError("playback URL must be http or https")
    ffmpeg = ffmpeg_path or find_ffmpeg()
    if not ffmpeg:
        raise FfmpegNotFoundError(
            "ffmpeg not found: install it and add it to PATH, or set ACELIST_FFMPEG_PATH"
        )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    # The Windows clock is coarse, so the timestamp alone can repeat; the suffix cannot.
    relative = f"{SCREENSHOTS_SUBDIR}/{content_id}_{stamp}_{uuid.uuid4().hex[:8]}.jpg"
    final = data_dir / relative
    partial = final.with_name(final.stem + ".part.jpg")
    final.parent.mkdir(parents=True, exist_ok=True)

    # An argument list with no shell: the URL can never be interpreted as a command.
    command = [
        ffmpeg,
        "-y",
        "-nostdin",
        "-loglevel",
        "error",
        "-protocol_whitelist",
        "http,https,tcp,tls",
        "-i",
        playback_url,
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(partial),
    ]
    try:
        completed = runner(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _discard(partial)
        raise ScreenshotError(f"ffmpeg timed out after {timeout:g} s") from exc
    except OSError as exc:
        _discard(partial)
        raise ScreenshotError(f"could not run ffmpeg: {exc}") from exc

    # ffmpeg prints decoder warnings while waiting for a keyframe even on success,
    # so only the exit code and the output file decide.
    if completed.returncode != 0 or not partial.is_file() or partial.stat().st_size == 0:
        _discard(partial)
        detail = (completed.stderr or "").strip()[-300:]
        raise ScreenshotError(f"ffmpeg produced no frame (exit {completed.returncode}): {detail}")

    os.replace(partial, final)
    return relative


def _discard(path: Path) -> None:
    path.unlink(missing_ok=True)
