"""Static checks for the Linux package; CI also builds and runs the artifact."""

import importlib.util
import re
from pathlib import Path

from app import __version__

ROOT = Path(__file__).resolve().parent.parent
LINUX = ROOT / "linux"
SPEC = (LINUX / "acelist.spec").read_text(encoding="utf-8")


def load_build_script():
    spec = importlib.util.spec_from_file_location("acelist_linux_build", LINUX / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_file_the_linux_spec_bundles_exists():
    sources = re.findall(r"\(str\((ROOT / [^)]+)\),", SPEC)
    paths = [ROOT.joinpath(*re.findall(r'"([^"]+)"', source)) for source in sources]

    assert len(paths) == 4
    assert all(path.exists() for path in paths), paths


def test_the_linux_build_reads_the_app_version():
    assert load_build_script().version() == __version__


def test_the_linux_build_ships_the_license():
    assert 'shutil.copyfile(ROOT / "LICENSE", DIST / "AceList" / "LICENSE.txt")' in (
        LINUX / "build.py"
    ).read_text(encoding="utf-8")


def test_linux_source_launcher_is_executable():
    assert (ROOT / "start.sh").stat().st_mode & 0o111
