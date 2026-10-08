import os
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path


def engine_candidates() -> list[Path]:
    """Where Ace Stream Media puts its engine on Windows (per user, or for everyone)."""
    found = []
    for name in ("APPDATA", "LOCALAPPDATA"):
        if root := os.environ.get(name):
            found.append(Path(root) / "ACEStream" / "engine" / "ace_engine.exe")
    roots = {os.environ.get(name) for name in ("ProgramFiles", "ProgramFiles(x86)")}
    for root in sorted(filter(None, roots)):
        found.append(Path(root) / "ACEStream" / "engine" / "ace_engine.exe")
    return found


def find_engine_executable(candidates: Iterable[Path] | None = None) -> str | None:
    """Path of the installed engine executable, if Ace Stream is installed."""
    for candidate in engine_candidates() if candidates is None else candidates:
        if candidate.is_file():
            return str(candidate)
    return None


class EngineStartError(Exception):
    """The engine executable could not be launched."""


def start_engine(
    path: str, *, launcher: Callable[..., subprocess.Popen] = subprocess.Popen
) -> None:
    """Launches the installed engine and returns at once; it takes a few seconds to answer."""
    executable = Path(path)
    if not executable.is_file():
        raise EngineStartError(f"engine executable not found: {path}")
    try:
        # An argument list and no shell; detached so it outlives AceList, like VLC.
        launcher(
            [str(executable)],
            cwd=str(executable.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        )
    except OSError as exc:
        raise EngineStartError(f"could not start the engine: {exc}") from exc
