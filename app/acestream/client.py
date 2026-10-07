import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from app.acestream.content_id import parse_content_id
from app.acestream.errors import (
    ContentNotFoundError,
    EngineError,
    EngineProtocolError,
    EngineTimeoutError,
    EngineUnavailableError,
)
from app.config import ENGINE_TIMEOUT, ENGINE_URL

log = logging.getLogger(__name__)

_NOT_FOUND = "failed to load content"


@dataclass(frozen=True)
class EngineVersion:
    version: str
    code: int
    platform: str


@dataclass(frozen=True)
class StreamSession:
    content_id: str
    infohash: str
    playback_url: str
    stat_url: str
    command_url: str


@dataclass(frozen=True)
class StreamStats:
    """`status` goes idle -> prebuf -> dl; peers and downloaded are absent while idle."""

    status: str
    peers: int | None
    speed_down: int | None
    downloaded: int | None


class EngineClient:
    """Synchronous client for the engine HTTP API (see docs/engine-api.md).

    Calls block, so callers run it from a worker thread, not from the event loop.
    """

    def __init__(self, base_url: str = ENGINE_URL, *, timeout: float = ENGINE_TIMEOUT):
        self._base_url = base_url.rstrip("/") + "/"
        self._http = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "EngineClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def version(self) -> EngineVersion:
        data = self._get_json(
            urljoin(self._base_url, "webui/api/service"), {"method": "get_version"}
        )
        result = self._payload(data, "result")
        try:
            return EngineVersion(
                version=str(result["version"]),
                code=int(result["code"]),
                platform=str(result["platform"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise EngineProtocolError("unexpected get_version response") from exc

    def is_available(self) -> bool:
        try:
            self.version()
        except EngineError:
            return False
        return True

    def start_stream(self, content_id: str) -> StreamSession:
        """Raises `InvalidContentIdError` before any request if the Content ID is malformed."""
        content_id = parse_content_id(content_id)
        data = self._get_json(
            urljoin(self._base_url, "ace/getstream"),
            {"id": content_id, "format": "json", "pid": str(uuid.uuid4())},
        )
        if data.get("error") == _NOT_FOUND:
            raise ContentNotFoundError(content_id)
        response = self._payload(data, "response")
        try:
            return StreamSession(
                content_id=content_id,
                infohash=str(response["infohash"]),
                playback_url=self._rebase(response["playback_url"]),
                stat_url=self._rebase(response["stat_url"]),
                command_url=self._rebase(response["command_url"]),
            )
        except (KeyError, TypeError) as exc:
            raise EngineProtocolError("unexpected getstream response") from exc

    def stats(self, session: StreamSession) -> StreamStats:
        response = self._payload(self._get_json(session.stat_url), "response")
        try:
            return StreamStats(
                status=str(response["status"]),
                peers=response.get("peers"),
                speed_down=response.get("speed_down"),
                downloaded=response.get("downloaded"),
            )
        except KeyError as exc:
            raise EngineProtocolError("unexpected stat response") from exc

    def stop(self, session: StreamSession) -> None:
        data = self._get_json(session.command_url, {"method": "stop"})
        if self._payload(data, "response", str) != "ok":
            raise EngineProtocolError("engine did not confirm stopping the session")

    @contextmanager
    def stream(self, content_id: str) -> Iterator[StreamSession]:
        """Starts a session and always stops it, whatever happens inside the block."""
        session = self.start_stream(content_id)
        try:
            yield session
        finally:
            try:
                self.stop(session)
            except EngineError:
                # A failed stop must not hide the error that is already propagating.
                log.warning("could not stop session for %s", session.content_id, exc_info=True)

    def _rebase(self, url: str) -> str:
        """Points an engine-provided URL at the configured engine, never at another host."""
        parts = urlsplit(url)
        path = parts.path.lstrip("/")
        return urljoin(self._base_url, path + (f"?{parts.query}" if parts.query else ""))

    def _get_json(self, url: str, params: dict[str, str] | None = None) -> dict:
        try:
            response = self._http.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise EngineTimeoutError(f"engine did not answer in time: {url}") from exc
        except httpx.TransportError as exc:
            raise EngineUnavailableError(f"cannot reach the engine at {self._base_url}") from exc
        if response.status_code != 200:
            raise EngineProtocolError(f"unexpected HTTP {response.status_code} from engine")
        try:
            data = response.json()
        except ValueError as exc:
            raise EngineProtocolError("engine returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise EngineProtocolError("engine returned an unexpected JSON shape")
        return data

    @staticmethod
    def _payload(data: dict, key: str, kind: type = dict):
        # The engine answers HTTP 200 even on failure, so the `error` field decides.
        if data.get("error"):
            raise EngineProtocolError(f"engine error: {data['error']}")
        payload = data.get(key)
        if not isinstance(payload, kind):
            raise EngineProtocolError(f"engine response has no valid '{key}'")
        return payload
