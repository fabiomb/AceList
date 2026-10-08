import pytest

from app.db.models import Resolution
from app.services.errors import ValidationError
from app.services.resolution import classify, frame_size, normalize_resolution


@pytest.mark.parametrize(
    ("kwargs", "size"),
    [
        ({}, (1920, 1080)),
        ({"sof": 0xC2}, (1920, 1080)),  # progressive
        ({"extra_segments": False}, (1920, 1080)),
    ],
)
def test_frame_size_reads_the_jpeg_header(tmp_path, make_jpeg, kwargs, size):
    path = tmp_path / "frame.jpg"
    path.write_bytes(make_jpeg(*size, **kwargs))

    assert frame_size(path) == size


@pytest.mark.parametrize(
    "content",
    [b"", b"not a jpeg", b"\xff\xd8\xff\xe0\x00", b"\xff\xd8\x00\x00\x00\x00"],
)
def test_frame_size_of_anything_else_is_none(tmp_path, content):
    path = tmp_path / "frame.jpg"
    path.write_bytes(content)

    assert frame_size(path) is None


def test_frame_size_of_a_missing_file_is_none(tmp_path):
    assert frame_size(tmp_path / "missing.jpg") is None


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (3840, 2160, Resolution.UHD),
        (4096, 1716, Resolution.UHD),  # cinema 4K, letterboxed
        (1920, 1080, Resolution.FULL_HD),
        (1440, 1080, Resolution.FULL_HD),  # anamorphic HD broadcast
        (1920, 1088, Resolution.FULL_HD),
        (1280, 720, Resolution.HD),
        (720, 480, Resolution.SD),
        (854, 480, Resolution.SD),
        (720, 576, Resolution.OTHER),  # PAL SD
        (2560, 1440, Resolution.OTHER),
        (320, 180, Resolution.OTHER),
    ],
)
def test_classify(width, height, expected):
    assert classify(width, height) is expected


def test_normalize_resolution():
    assert normalize_resolution(" 1080P ") is Resolution.FULL_HD
    assert normalize_resolution("4K") is Resolution.UHD
    assert normalize_resolution("") is None
    assert normalize_resolution(None) is None
    with pytest.raises(ValidationError):
        normalize_resolution("8k")
