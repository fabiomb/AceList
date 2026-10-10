import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from app.acestream.client import EngineClient, StreamSession
from app.acestream.content_id import IdKind, parse_content_id
from app.acestream.errors import ContentNotFoundError, EngineError, EngineUnavailableError
from app.db.models import CheckStatus


@dataclass(frozen=True)
class VerificationSettings:
    min_peers: int = 1
    timeout: float = 20.0
    poll_interval: float = 2.0

    def __post_init__(self) -> None:
        if self.min_peers < 0:
            raise ValueError("min_peers must not be negative")
        if self.timeout <= 0 or self.poll_interval <= 0:
            raise ValueError("timeout and poll_interval must be positive")


@dataclass(frozen=True)
class VerificationResult:
    status: CheckStatus
    # Highest peer count seen during the check; it fluctuates a lot between polls.
    peers: int | None = None
    speed_down: int | None = None
    infohash: str | None = None
    error_message: str | None = None
    # How the engine loaded the identifier; None when it could not load it.
    kind: IdKind | None = None


def probe(
    client: EngineClient,
    session: StreamSession,
    settings: VerificationSettings | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> VerificationResult:
    """Polls an already started session; the caller owns it and must stop it.

    Alive means the engine reached `dl` with data downloaded and at least
    `min_peers` peers: peers alone do not prove the stream delivers anything.
    Engine errors propagate.
    """
    settings = settings or VerificationSettings()
    deadline = clock() + settings.timeout
    max_peers: int | None = None
    while True:
        stats = client.stats(session)
        if stats.peers is not None:
            max_peers = stats.peers if max_peers is None else max(max_peers, stats.peers)
        if (
            stats.status == "dl"
            and (stats.downloaded or 0) > 0
            and (stats.peers or 0) >= settings.min_peers
        ):
            return VerificationResult(
                CheckStatus.ALIVE, max_peers, stats.speed_down, session.infohash
            )
        remaining = deadline - clock()
        if remaining <= 0:
            return VerificationResult(
                CheckStatus.NO_PEERS, max_peers, stats.speed_down, session.infohash
            )
        sleep(min(settings.poll_interval, remaining))


def verify(
    client: EngineClient,
    content_id: str,
    settings: VerificationSettings | None = None,
    *,
    kind: IdKind | None = None,
    on_alive: Callable[[StreamSession], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> VerificationResult:
    """Starts a session, checks it and always stops it.

    A malformed Content ID raises `InvalidContentIdError`. Engine failures are
    returned as `ERROR` so a caller can store them; the session is stopped either way.
    An engine that cannot be reached raises `EngineUnavailableError` instead: that says
    nothing about the channel, so it must not be stored as the channel's result.
    `on_alive` runs while the session is still playing, which is the only moment a
    screenshot can be taken; exceptions it raises propagate.
    `kind` is how the engine loaded the identifier before, if known (see
    `EngineClient.start_stream`).
    """
    settings = settings or VerificationSettings()
    content_id = parse_content_id(content_id)
    try:
        with client.stream(content_id, kind) as session:
            result = probe(client, session, settings, sleep=sleep, clock=clock)
            if on_alive is not None and result.status is CheckStatus.ALIVE:
                on_alive(session)
            return replace(result, kind=session.kind)
    except ContentNotFoundError:
        return VerificationResult(CheckStatus.NOT_FOUND)
    except EngineUnavailableError:
        raise
    except EngineError as exc:
        return VerificationResult(CheckStatus.ERROR, error_message=str(exc))


async def verify_async(
    client: EngineClient,
    content_id: str,
    settings: VerificationSettings | None = None,
    **kwargs,
) -> VerificationResult:
    """Runs `verify` in a worker thread so the event loop keeps serving requests."""
    return await asyncio.to_thread(verify, client, content_id, settings, **kwargs)
