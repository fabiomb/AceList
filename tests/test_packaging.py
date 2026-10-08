"""Checks of the Windows packaging that need no build (the CI builds it, see #79)."""

import importlib.util
import re
import struct
from pathlib import Path

from app import __version__

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = ROOT / "windows"
SPEC = (WINDOWS / "acelist.spec").read_text(encoding="utf-8")


def load_build_script():
    spec = importlib.util.spec_from_file_location("acelist_build", WINDOWS / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def icon_sizes(path: Path) -> set[tuple[int, int]]:
    """Sizes in an .ico file, read from its directory (0 means 256)."""
    data = path.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1), "not an icon file"
    sizes = set()
    for index in range(count):
        width, height = data[6 + index * 16], data[7 + index * 16]
        sizes.add((width or 256, height or 256))
    return sizes


def test_every_file_the_spec_bundles_exists():
    sources = re.findall(r"\(str\((ROOT / [^)]+)\),", SPEC)
    paths = [ROOT.joinpath(*re.findall(r'"([^"]+)"', source)) for source in sources]

    assert len(paths) == 4
    assert all(path.exists() for path in paths), paths


def test_the_build_reads_the_app_version():
    assert load_build_script().version() == __version__


def test_the_icon_has_every_windows_size():
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= icon_sizes(WINDOWS / "acelist.ico")
    assert icon_sizes(ROOT / "app" / "web" / "static" / "favicon.ico") >= {(16, 16), (32, 32)}


def test_pages_use_the_favicon(web):
    page = web.get("/").text

    assert re.search(r'<link rel="icon" href="[^"]*/static/favicon\.ico\?v=[0-9a-f]{10}">', page)
    assert web.get("/static/favicon.ico").status_code == 200
