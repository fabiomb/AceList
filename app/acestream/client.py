import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from app.acestream.content_id import IdKind, parse_content_id
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

# Looking content up by infohash can take the engine about half a minute when it does
# not exist (measured with engine 3.1.74), longer than the usual timeout.
INFOHASH_TIMEOUT = 40.0

# The engine's query parameter for each kind of identifier, per API.
_STREAM_PARAM = {IdKind.CONTENT_ID: "id", IdKind.INFOHASH: "infohash"}
_MEDIA_PARAM = {IdKind.CONTENT_ID: "content_id", IdKind.INFOHASH: "infohash"}


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
    kind: IdKind = IdKind.CONTENT_ID  # how the engine understood `content_id`


@dataclass(frozen=True)
class Media:
    name: str | None
    kind: IdKind  # how the engine understood the identifier


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

    def __init__(
        self,
        base_url: str = ENGINE_URL,
        *,
        timeout: float = ENGINE_TIMEOUT,
        infohash_timeout: float = INFOHASH_TIMEOUT,
    ):
        self._base_url = base_url.rstrip("/") + "/"
        self._http = httpx.Client(timeout=timeout)
        self._infohash_timeout = max(timeout, infohash_timeout)

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

    def media(self, content_id: str, kind: IdKind | None = None) -> Media | None:
        """Name the content is published with, without starting a session.

        None when the engine cannot load the content either way; `kind` is how it
        loaded before, if known, and is tried first (see `_kinds`).
        Raises `EngineError` if the engine cannot be reached or answers nonsense.
        """
        content_id = parse_content_id(content_id)
        for each in _kinds(kind):
            data = self._lookup(
                each,
                urljoin(self._base_url, "server/api"),
                {"api_version": "3", "method": "get_media_files", _MEDIA_PARAM[each]: content_id},
            )
            if data is None or data.get("error"):
                continue
            result = data.get("result")
            if not isinstance(result, dict):
                raise EngineProtocolError("unexpected get_media_files response")
            name = result.get("name")
            if not name:
                files = result.get("files") or []
                name = files[0].get("filename") if files and isinstance(files[0], dict) else None
            return Media(str(name) if name else None, each)
        return None

    def start_stream(self, content_id: str, kind: IdKind | None = None) -> StreamSession:
        """Starts a session, asking for the content both ways, as `kind` first if known.

        Raises `InvalidContentIdError` before any request if the Content ID is malformed,
        and `ContentNotFoundError` if the engine cannot load it either way.
        """
        content_id = parse_content_id(content_id)
        for each in _kinds(kind):
            data = self._lookup(
                each,
                urljoin(self._base_url, "ace/getstream"),
                {_STREAM_PARAM[each]: content_id, "format": "json", "pid": str(uuid.uuid4())},
            )
            if data is None or data.get("error") == _NOT_FOUND:
                continue
            response = self._payload(data, "response")
            try:
                return StreamSession(
                    content_id=content_id,
                    infohash=str(response["infohash"]),
                    playback_url=self._rebase(response["playback_url"]),
                    stat_url=self._rebase(response["stat_url"]),
                    command_url=self._rebase(response["command_url"]),
                    kind=each,
                )
            except (KeyError, TypeError) as exc:
                raise EngineProtocolError("unexpected getstream response") from exc
        raise ContentNotFoundError(content_id)

    def _lookup(self, kind: IdKind, url: str, params: dict[str, str]) -> dict | None:
        """The engine's answer, or None if an infohash lookup ran out of time.

        Content that does not exist makes an infohash lookup slow, so running out of
        time there means "not found", not an engine problem.
        """
        if kind is IdKind.CONTENT_ID:
            return self._get_json(url, params)
        try:
            return self._get_json(url, params, timeout=self._infohash_timeout)
        except EngineTimeoutError:
            log.info("infohash lookup timed out: %s", params)
            return None

    def stats(self, session: StreamSession) -> StreamStats:
        response = self._payload(self._get_json(session.stat_url), "response")
        if not response:
            # Right after start the engine can answer with an empty object, before `idle`.
            return StreamStats(status="idle", peers=None, speed_down=None, downloaded=None)
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
    def stream(self, content_id: str, kind: IdKind | None = None) -> Iterator[StreamSession]:
        """Starts a session and always stops it, whatever happens inside the block."""
        session = self.start_stream(content_id, kind)
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

    def _get_json(
        self, url: str, params: dict[str, str] | None = None, *, timeout: float | None = None
    ) -> dict:
        try:
            if timeout is None:
                response = self._http.get(url, params=params)
            else:
                response = self._http.get(url, params=params, timeout=timeout)
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


def _kinds(kind: IdKind | None) -> list[IdKind]:
    """How to ask the engine for an identifier, in order: both ways, `kind` first if known.

    Most `acestream://` links carry a Content ID, but some carry the torrent's infohash,
    which looks the same (40 hex characters). Ace Player tries both; so does AceList, the
    Content ID first because it is the usual one and fails fast when wrong.
    The other way is still tried when `kind` fails: once the engine has loaded content by
    infohash it also accepts it as a Content ID for a while, so what worked last time may
    only have worked thanks to that cache.
    """
    if kind is IdKind.INFOHASH:
        return [IdKind.INFOHASH, IdKind.CONTENT_ID]
    return [IdKind.CONTENT_ID, IdKind.INFOHASH]
