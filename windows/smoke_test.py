"""Starts the built AceList.exe with throwaway data and checks that it works.

`python windows/smoke_test.py [--exe dist/AceList/AceList.exe] [--expect-version 1.3.0]`
Exits with 0 if it works, 1 otherwise. Only the standard library, so it runs anywhere.
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STARTUP_TIMEOUT = 90.0


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - loopback only
        return response.status, response.read()


def wait_for_health(base: str, process: subprocess.Popen) -> dict:
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"AceList.exe exited with code {process.returncode}")
        try:
            status, body = get(f"{base}/health")
            if status == 200:
                return json.loads(body)
        except OSError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"no answer from {base}/health in {STARTUP_TIMEOUT:g} s")


def check(exe: Path, expected_version: str | None) -> None:
    data = Path(tempfile.mkdtemp(prefix="acelist-smoke-"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "ACELIST_DATA_DIR": str(data),
        "ACELIST_ENGINE_URL": "http://127.0.0.1:1",  # no engine: nothing may depend on it
    }
    process = subprocess.Popen(
        [str(exe), "--no-browser", "--port", str(port)],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        health = wait_for_health(base, process)
        print(f"health: {health}")
        if health.get("app") != "AceList":
            raise RuntimeError(f"not AceList answering: {health}")
        if expected_version and health.get("version") != expected_version:
            raise RuntimeError(f"version {health.get('version')}, expected {expected_version}")
        for path in ("/", "/gallery", "/import", "/settings", "/static/style.css"):
            status, _ = get(base + path)
            print(f"{path}: {status}")
            if status != 200:
                raise RuntimeError(f"{path} answered {status}")
        if not (data / "acelist.db").is_file():
            raise RuntimeError("the database was not created")
    finally:
        process.kill()
        try:
            output, _ = process.communicate(timeout=30)
            print("--- AceList.exe output ---")
            print(output.decode("utf-8", errors="replace"))
        finally:
            shutil.rmtree(data, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=ROOT / "dist" / "AceList" / "AceList.exe")
    parser.add_argument("--expect-version")
    args = parser.parse_args(argv)
    # Never fail on printing what AceList said, whatever the console's code page.
    sys.stdout.reconfigure(errors="backslashreplace")
    try:
        check(args.exe, args.expect_version)
    except Exception as exc:  # noqa: BLE001 - report any failure and fail the job
        print(f"SMOKE TEST FAILED: {exc}")
        return 1
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
