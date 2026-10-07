import os
from collections.abc import Iterable
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
