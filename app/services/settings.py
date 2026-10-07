from collections.abc import Callable
from dataclasses import dataclass, fields, replace

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import ENGINE_TIMEOUT, ENGINE_URL, FFMPEG_PATH, SCREENSHOT_TIMEOUT, VLC_PATH
from app.db.models import Setting
from app.services.screenshots import CaptureSettings
from app.services.verification import VerificationSettings


@dataclass(frozen=True)
class AppSettings:
    """User settings. Defaults come from the environment (`ACELIST_*`); saved values win.

    A path set to `None` means "detect it": usual install folders, then PATH.
    """

    engine_url: str = ENGINE_URL
    engine_timeout: float = ENGINE_TIMEOUT
    min_peers: int = VerificationSettings.min_peers
    check_timeout: float = VerificationSettings.timeout
    screenshot_timeout: float = SCREENSHOT_TIMEOUT
    vlc_path: str | None = VLC_PATH
    ffmpeg_path: str | None = FFMPEG_PATH
    acestream_path: str | None = None  # the installed engine, for reference

    def verification(self) -> VerificationSettings:
        return VerificationSettings(min_peers=self.min_peers, timeout=self.check_timeout)

    def capture(self) -> CaptureSettings:
        return CaptureSettings(ffmpeg_path=self.ffmpeg_path, timeout=self.screenshot_timeout)


_PARSERS: dict[str, Callable[[str], object]] = {
    "engine_url": str,
    "engine_timeout": float,
    "min_peers": int,
    "check_timeout": float,
    "screenshot_timeout": float,
    "vlc_path": str,
    "ffmpeg_path": str,
    "acestream_path": str,
}
assert _PARSERS.keys() == {f.name for f in fields(AppSettings)}


def load_settings(session: Session) -> AppSettings:
    """Saved settings over the defaults; a stored value that no longer parses is skipped."""
    stored = {s.key: s.value for s in session.scalars(select(Setting))}
    values = {}
    for name, parse in _PARSERS.items():
        if name in stored:
            try:
                values[name] = parse(stored[name])
            except ValueError:
                continue
    return replace(AppSettings(), **values)


def save_settings(session: Session, settings: AppSettings) -> None:
    """Stores every setting; a `None` path is removed so it is detected again.

    Values must already be validated: this layer only persists them.
    """
    for name in _PARSERS:
        value = getattr(settings, name)
        if value is None:
            session.execute(delete(Setting).where(Setting.key == name))
        else:
            session.merge(Setting(key=name, value=str(value)))
    session.commit()
