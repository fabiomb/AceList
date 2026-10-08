# PyInstaller spec for AceList.exe, in folder mode. Build with `python windows/build.py`.
# Findings behind these choices: docs/packaging.md.
import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is provided by PyInstaller
VERSION = re.search(
    r'__version__ = "([^"]+)"', (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
).group(1)

# File properties in Windows Explorer ("Details" tab).
numbers = tuple(int(part) for part in VERSION.split(".")) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "AceList"),
                        StringStruct("FileDescription", "AceList - catálogo local de Ace Stream"),
                        StringStruct("FileVersion", VERSION),
                        StringStruct("InternalName", "AceList"),
                        StringStruct("OriginalFilename", "AceList.exe"),
                        StringStruct("ProductName", "AceList"),
                        StringStruct("ProductVersion", VERSION),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)
version_file = Path(workpath) / "version_info.txt"  # noqa: F821 - provided by PyInstaller
version_file.parent.mkdir(parents=True, exist_ok=True)
version_file.write_text(str(version_info), encoding="utf-8")

# Files the app reads from disk; PyInstaller only finds Python modules by itself.
datas = [
    (str(ROOT / "app" / "web" / "templates"), "app/web/templates"),
    (str(ROOT / "app" / "web" / "static"), "app/web/static"),
    (str(ROOT / "migrations"), "migrations"),  # as source: Alembic loads env.py from disk
    (str(ROOT / "alembic.ini"), "."),
]

a = Analysis(  # noqa: F821
    [str(ROOT / "windows" / "entry.py")],
    pathex=[str(ROOT)],
    datas=datas,
    excludes=["tkinter", "pytest", "respx", "PIL"],
)


def _keep(entry) -> bool:
    parts = Path(entry[0]).parts
    if "__pycache__" in parts:
        return False
    # pycountry's translations (20 MB): AceList shows the names in English.
    return not ("pycountry" in parts and "locales" in parts)


a.datas = [entry for entry in a.datas if _keep(entry)]

pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AceList",
    icon=str(ROOT / "windows" / "acelist.ico"),
    version=str(version_file),
    console=True,  # the console shows what AceList is doing and closing it stops it
    upx=False,  # compressed executables upset antivirus programs more often
)
coll = COLLECT(exe, a.binaries, a.datas, name="AceList", upx=False)  # noqa: F821
