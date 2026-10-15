# PyInstaller spec for the Linux executable, in folder mode. Build with `python linux/build.py`.
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is provided by PyInstaller

datas = [
    (str(ROOT / "app" / "web" / "templates"), "app/web/templates"),
    (str(ROOT / "app" / "web" / "static"), "app/web/static"),
    (str(ROOT / "migrations"), "migrations"),
    (str(ROOT / "alembic.ini"), "."),
]

a = Analysis(  # noqa: F821
    [str(ROOT / "linux" / "entry.py")],
    pathex=[str(ROOT)],
    datas=datas,
    excludes=["tkinter", "pytest", "respx", "PIL"],
)


def _keep(entry) -> bool:
    parts = Path(entry[0]).parts
    if "__pycache__" in parts:
        return False
    return not ("pycountry" in parts and "locales" in parts)


a.datas = [entry for entry in a.datas if _keep(entry)]

pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AceList",
    console=True,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AceList", upx=False)  # noqa: F821
