import os
import shutil
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path
from urllib.parse import urlsplit

from app.acestream.client import EngineClient, StreamSession
from app.acestream.content_id import parse_content_id
from app.acestream.errors import EngineError
from app.config import VLC_PATH


class PlayerError(Exception):
    """The player could not be started."""


class VlcNotFoundError(PlayerError):
    pass


def vlc_candidates() -> list[Path]:
    """Where the VLC installer puts the executable on Windows."""
    roots = {os.environ.get(name) for name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")}
    return [Path(root) / "VideoLAN" / "VLC" / "vlc.exe" for root in sorted(filter(None, roots))]


def find_vlc(
    configured: str | None = VLC_PATH, *, candidates: Iterable[Path] | None = None
) -> str | None:
    """Path of the VLC executable: the setting, the usual install folders, or PATH."""
    if configured:
        return configured if Path(configured).is_file() else None
    for candidate in vlc_candidates() if candidates is None else candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("vlc")


def open_in_player(
    client: EngineClient,
    content_id: str,
    *,
    title: str | None = None,
    vlc_path: str | None = None,
    launcher: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> StreamSession:
    """Starts the stream on the engine and opens its playback URL in VLC.

    VLC is looked up first, so a missing player never starts an engine session.
    Raises `PlayerError` (or `VlcNotFoundError`) and the engine's `EngineError`s.
    The session is left running: VLC is now reading it.
    """
    content_id = parse_content_id(content_id)
    vlc = vlc_path or find_vlc()
    if not vlc:
        raise VlcNotFoundError("VLC not found: install it or set ACELIST_VLC_PATH to vlc.exe")

    stream = client.start_stream(content_id)
    if urlsplit(stream.playback_url).scheme not in ("http", "https"):
        _stop_quietly(client, stream)
        raise PlayerError("playback URL must be http or https")

    # An argument list with no shell; the title is glued to its option so it can
    # never be read as an option of its own.
    command = [vlc]
    if title:
        command.append(f"--meta-title={title}")
    command.append(stream.playback_url)
    try:
        launcher(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            # On Windows VLC must outlive the app's console; elsewhere the flag is 0.
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        )
    except OSError as exc:
        _stop_quietly(client, stream)
        raise PlayerError(f"could not start VLC: {exc}") from exc
    return stream


def _stop_quietly(client: EngineClient, stream: StreamSession) -> None:
    # Cleanup after a failure: the original error is the one worth reporting.
    try:
        client.stop(stream)
    except EngineError:
        pass
