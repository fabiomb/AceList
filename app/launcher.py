"""AceList.exe: prepares the database, starts the local server and opens the browser.

Also runs from source with `python -m app.launcher`. Messages are for the person who
double-clicked the program, so they are in Spanish.
"""

import argparse
import json
import socket
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config

from app import __version__
from app.config import DATA_DIR, DATABASE_URL, FROZEN, RESOURCE_DIR

HOST = "127.0.0.1"
DEFAULT_PORT = 8000
PORTS_TO_TRY = 20  # 8000 to 8019
READY_TIMEOUT = 60.0
STATE_FILE = DATA_DIR / "server.json"  # the port of the running instance


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="AceList", description="Catálogo local de Ace Stream.")
    parser.add_argument(
        "--port", type=int, help=f"puerto local (por defecto {DEFAULT_PORT} o el siguiente libre)"
    )
    parser.add_argument("--no-browser", action="store_true", help="no abrir el navegador")
    return parser.parse_args(argv)


def is_acelist(port: int, timeout: float = 2.0) -> bool:
    """Whether an AceList server answers on this port (not some other program)."""
    try:
        response = httpx.get(f"http://{HOST}:{port}/health", timeout=timeout)
        return response.status_code == 200 and response.json().get("app") == "AceList"
    except (httpx.HTTPError, ValueError):
        return False


def running_port(state_file: Path = STATE_FILE) -> int | None:
    """The port of an AceList already running for this data folder, if any."""
    try:
        port = int(json.loads(state_file.read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return port if is_acelist(port) else None


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, port))
        except OSError:
            return False
    return True


def choose_port(preferred: int | None = None) -> int:
    """The requested port, else the first free one from 8000; raises if none is free."""
    if preferred is not None:
        if port_is_free(preferred):
            return preferred
        raise OSError(f"el puerto {preferred} está ocupado")
    for port in range(DEFAULT_PORT, DEFAULT_PORT + PORTS_TO_TRY):
        if port_is_free(port):
            return port
    raise OSError(f"no hay puertos libres entre {DEFAULT_PORT} y {DEFAULT_PORT + PORTS_TO_TRY - 1}")


def upgrade_database(database_url: str = DATABASE_URL) -> None:
    """Creates or updates the database with the migrations that ship with AceList."""
    config = Config(str(RESOURCE_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(RESOURCE_DIR / "migrations"))
    # ConfigParser treats "%" as interpolation: a path containing one must be escaped.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def open_when_ready(
    url: str,
    port: int,
    *,
    opener: Callable[[str], object] = webbrowser.open,
    timeout: float = READY_TIMEOUT,
) -> bool:
    """Opens the browser once the server answers; False if it never did."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_acelist(port, timeout=1.0):
            opener(url)
            return True
        time.sleep(0.25)
    return False


def set_console_title(title: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW(title)
        except (AttributeError, OSError):
            pass


def serve(port: int) -> None:  # pragma: no cover - runs the real server until Ctrl+C
    import uvicorn

    from app.main import app

    uvicorn.run(app, host=HOST, port=port, log_level="info")


def main(argv: list[str] | None = None, *, server: Callable[[int], None] = serve) -> int:
    args = parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        # Show each message at once, also when the output goes to a file.
        sys.stdout.reconfigure(line_buffering=True)
    set_console_title("AceList")
    print(f"AceList {__version__}")
    print(f"Datos: {DATA_DIR}")

    existing = running_port()
    if existing is not None:
        url = f"http://{HOST}:{existing}/"
        print(f"AceList ya está abierto en {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    try:
        port = choose_port(args.port)
        print("Preparando la base de datos…")
        upgrade_database()
    except Exception as exc:  # noqa: BLE001 - the person needs to read why, whatever it is
        print(f"\nNo se pudo iniciar AceList: {exc}")
        return 1

    url = f"http://{HOST}:{port}/"
    STATE_FILE.write_text(json.dumps({"port": port}), encoding="utf-8")
    print(f"\nAceList funciona en {url}")
    print("Deja esta ventana abierta mientras lo uses; ciérrala o pulsa Ctrl+C para salir.\n")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url, port), daemon=True).start()
    try:
        server(port)
    finally:
        STATE_FILE.unlink(missing_ok=True)
    return 0


def run() -> None:  # pragma: no cover - process entry point
    code = main()
    if code != 0 and FROZEN:
        # A double-clicked console closes at once: leave the error on screen.
        input("Pulsa Enter para cerrar…")
    sys.exit(code)


if __name__ == "__main__":  # pragma: no cover
    run()
