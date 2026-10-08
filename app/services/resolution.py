import struct
from pathlib import Path

from app.db.models import Resolution
from app.services.errors import ValidationError

# Start Of Frame markers carry the image size; C4, C8 and CC are other segments.
_SOF_MARKERS = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def frame_size(path: Path) -> tuple[int, int] | None:
    """(width, height) of a JPEG, read from its header; None if it is not a readable JPEG."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data[:2] != b"\xff\xd8":
        return None
    index = 2
    while index + 4 <= len(data):
        if data[index] != 0xFF:
            return None
        marker = data[index + 1]
        if marker == 0xFF:  # fill byte before a marker
            index += 1
            continue
        (length,) = struct.unpack(">H", data[index + 2 : index + 4])
        if marker in _SOF_MARKERS:
            if index + 9 > len(data):
                return None
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return (width, height) if width and height else None
        index += 2 + length
    return None


def classify(width: int, height: int) -> Resolution:
    """Resolution class of a frame size, by its height (width only to spot 4K)."""
    if height >= 2000 or width >= 3800:
        return Resolution.UHD
    if 1000 <= height < 1200:
        return Resolution.FULL_HD
    if 680 <= height < 800:
        return Resolution.HD
    if 440 <= height < 500:
        return Resolution.SD
    return Resolution.OTHER


def normalize_resolution(value: str | None) -> Resolution | None:
    """A `Resolution` from user input; blank means unknown."""
    text = (value or "").strip().lower()
    if not text:
        return None
    try:
        return Resolution(text)
    except ValueError:
        allowed = ", ".join(r.value for r in Resolution)
        raise ValidationError(f"unknown resolution '{value}' (use one of: {allowed})") from None
