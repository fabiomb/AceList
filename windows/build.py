"""Builds AceList.exe and its zip: `python windows/build.py`.

Needs the `build` extra (`pip install -e ".[build]"`). Leaves in `dist/`:
- `AceList/` with `AceList.exe` and `_internal/`;
- `AceList-<version>-win64.zip` and `AceList-<version>-win64.zip.sha256`.
"""

import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
WORK = ROOT / "build"
SPEC = ROOT / "windows" / "acelist.spec"


def version() -> str:
    text = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> Path:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(WORK),
            str(SPEC),
        ],
        check=True,
        cwd=ROOT,
    )
    name = f"AceList-{version()}-win64"
    archive = Path(shutil.make_archive(str(DIST / name), "zip", root_dir=DIST, base_dir="AceList"))
    checksum = archive.with_name(archive.name + ".sha256")
    # The usual `sha256sum` format, so `sha256sum -c` can check it.
    checksum.write_text(f"{sha256(archive)}  {archive.name}\n", encoding="utf-8")
    size = archive.stat().st_size / (1024 * 1024)
    print(f"\n{archive} ({size:.1f} MB)\n{checksum.read_text(encoding='utf-8').strip()}")
    return archive


if __name__ == "__main__":
    main()
