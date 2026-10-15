import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path


def engine_candidates(platform: str = sys.platform) -> list[Path]:
    """Usual Ace Stream engine locations for the current operating system."""
    if platform != "win32":
        return [
            Path("/usr/bin/acestreamengine"),
            Path("/usr/local/bin/acestreamengine"),
            Path("/opt/acestream/start-engine"),
            Path("/opt/acestream/acestreamengine"),
        ]
    found = []
    for name in ("APPDATA", "LOCALAPPDATA"):
        if root := os.environ.get(name):
            found.append(Path(root) / "ACEStream" / "engine" / "ace_engine.exe")
    roots = {os.environ.get(name) for name in ("ProgramFiles", "ProgramFiles(x86)")}
    for root in sorted(filter(None, roots)):
        found.append(Path(root) / "ACEStream" / "engine" / "ace_engine.exe")
    return found


def find_engine_executable(
    candidates: Iterable[Path] | None = None, *, platform: str = sys.platform
) -> str | None:
    """Path of the installed engine executable, if Ace Stream is installed."""
    for candidate in engine_candidates(platform) if candidates is None else candidates:
        if candidate.is_file():
            return str(candidate)
    if candidates is None and platform != "win32":
        return shutil.which("acestreamengine") or shutil.which("start-engine")
    return None


class EngineStartError(Exception):
    """The engine executable could not be launched."""


def start_engine(
    path: str,
    *,
    launcher: Callable[..., subprocess.Popen] = subprocess.Popen,
    platform: str = sys.platform,
) -> None:
    """Launches the installed engine and returns at once; it takes a few seconds to answer."""
    executable = Path(path)
    if not executable.is_file():
        raise EngineStartError(f"engine executable not found: {path}")
    try:
        # An argument list and no shell; detached so it outlives AceList, like VLC.
        # The official Linux engine needs an explicit client mode. Windows' GUI
        # executable selects it itself.
        command = [str(executable)]
        if platform != "win32":
            command.append("--client-console")
        options = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if platform == "win32":
            options["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0)
        else:
            options["start_new_session"] = True
        launcher(
            command,
            cwd=str(executable.parent),
            **options,
        )
    except OSError as exc:
        raise EngineStartError(f"could not start the engine: {exc}") from exc
