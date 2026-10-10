import asyncio
import time

import httpx
import pytest

from app.acestream.client import EngineClient
from app.acestream.content_id import IdKind, InvalidContentIdError
from app.acestream.errors import EngineUnavailableError
from app.db.models import CheckStatus
from app.services.verification import (
    VerificationSettings,
    probe,
    verify,
    verify_async,
)

BASE = "http://127.0.0.1:6878"
HASH = "78266c15035d0ad8cbc58f821733931e1de434ab"
INFOHASH = "25f4c7b60edb0433343c777846924d35c65ec4f9"
PATH = f"{INFOHASH}/f4283e11274fae1ced9ef41a4c173857"

GETSTREAM = {
    "response": {
        "stat_url": f"{BASE}/ace/stat/{PATH}",
        "playback_url": f"{BASE}/ace/r/{PATH}",
        "command_url": f"{BASE}/ace/cmd/{PATH}",
        "infohash": INFOHASH,
    },
    "error": None,
}


def stat(status=None, peers=None, speed=0, downloaded=0):
    if status is None:
        return {"response": {}, "error": None}
    return {
        "response": {
            "status": status,
            "peers": peers,
            "speed_down": speed,
            "downloaded": downloaded,
        },
        "error": None,
    }


class FakeClock:
    """Time only moves when the code under test sleeps."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def client():
    with EngineClient(BASE, timeout=1) as c:
        yield c


@pytest.fixture
def engine(respx_mock):
    """Engine double: `engine.stats(...)` queues replies, the last one repeats."""

    class Engine:
        def __init__(self):
            respx_mock.get(f"{BASE}/ace/getstream").respond(json=GETSTREAM)
            self.stop = respx_mock.get(f"{BASE}/ace/cmd/{PATH}").respond(
                json={"response": "ok", "error": None}
            )
            self._stat = respx_mock.get(f"{BASE}/ace/stat/{PATH}")

        def stats(self, *replies):
            queue = list(replies)

            def reply(_request):
                payload = queue.pop(0) if len(queue) > 1 else queue[0]
                return httpx.Response(200, json=payload)

            self._stat.mock(side_effect=reply)
            return self._stat

    return Engine()


def run(client, clock, settings=None):
    return verify(client, HASH, settings, sleep=clock.sleep, clock=clock)


# alive


def test_alive_once_the_engine_is_downloading(client, clock, engine):
    stat_route = engine.stats(
        stat(),
        stat("prebuf", peers=3, downloaded=16384),
        stat("dl", peers=4, speed=1522, downloaded=13107200),
    )

    result = run(client, clock)

    assert result.status is CheckStatus.ALIVE
    assert (result.peers, result.speed_down, result.infohash) == (4, 1522, INFOHASH)
    assert result.error_message is None
    assert stat_route.call_count == 3
    assert engine.stop.call_count == 1


def test_data_in_prebuf_is_not_alive_yet(client, clock, engine):
    engine.stats(
        stat("prebuf", peers=2, downloaded=5226496),
        stat("dl", peers=2, speed=900, downloaded=12746752),
    )

    assert run(client, clock).status is CheckStatus.ALIVE


def test_alive_with_a_single_peer_by_default(client, clock, engine):
    engine.stats(stat("dl", peers=1, speed=1049, downloaded=7700480))

    assert run(client, clock).status is CheckStatus.ALIVE


# no peers


def test_peers_without_data_is_no_peers_after_the_timeout(client, clock, engine):
    stat_route = engine.stats(
        stat("prebuf", peers=3), stat("prebuf", peers=9), stat("prebuf", peers=1)
    )

    result = run(client, clock, VerificationSettings(timeout=10, poll_interval=2))

    assert result.status is CheckStatus.NO_PEERS
    assert result.peers == 9  # highest seen, not the last value
    assert clock.now == pytest.approx(10)
    assert stat_route.call_count == 6
    assert engine.stop.call_count == 1


def test_zero_peers_is_no_peers(client, clock, engine):
    engine.stats(stat("prebuf", peers=0))

    result = run(client, clock)

    assert (result.status, result.peers) == (CheckStatus.NO_PEERS, 0)


def test_session_that_never_reports_status_is_no_peers_without_peer_data(client, clock, engine):
    engine.stats(stat())

    result = run(client, clock)

    assert (result.status, result.peers) == (CheckStatus.NO_PEERS, None)


def test_dl_without_downloaded_bytes_is_not_alive(client, clock, engine):
    engine.stats(stat("dl", peers=3, downloaded=0))

    assert run(client, clock).status is CheckStatus.NO_PEERS


# peer threshold


def test_min_peers_threshold_blocks_alive(client, clock, engine):
    engine.stats(stat("dl", peers=1, downloaded=1000))

    result = run(client, clock, VerificationSettings(min_peers=2, timeout=6))

    assert result.status is CheckStatus.NO_PEERS


def test_min_peers_threshold_is_met_when_peers_arrive(client, clock, engine):
    engine.stats(stat("dl", peers=1, downloaded=1000), stat("dl", peers=2, downloaded=2000))

    result = run(client, clock, VerificationSettings(min_peers=2))

    assert (result.status, result.peers) == (CheckStatus.ALIVE, 2)


def test_min_peers_zero_accepts_data_without_peer_count(client, clock, engine):
    engine.stats(stat("dl", peers=None, downloaded=1000))

    result = run(client, clock, VerificationSettings(min_peers=0))

    assert result.status is CheckStatus.ALIVE


@pytest.mark.parametrize(
    "kwargs",
    [{"min_peers": -1}, {"timeout": 0}, {"poll_interval": 0}, {"timeout": -5}],
)
def test_invalid_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        VerificationSettings(**kwargs)


# not found and errors


def test_unknown_content_is_not_found_and_nothing_to_stop(client, clock, respx_mock):
    respx_mock.get(f"{BASE}/ace/getstream").respond(
        json={"response": None, "error": "failed to load content"}
    )

    result = run(client, clock)

    assert result.status is CheckStatus.NOT_FOUND
    assert (result.peers, result.infohash) == (None, None)
    assert respx_mock.calls.call_count == 2  # as a Content ID, then as an infohash


def test_engine_down_is_not_a_channel_result(client, clock, respx_mock):
    # Unreachable engine: nothing is known about the channel, so no result (#62).
    respx_mock.get(f"{BASE}/ace/getstream").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(EngineUnavailableError):
        run(client, clock)


def test_engine_failure_while_polling_is_an_error_and_the_session_is_stopped(
    client, clock, respx_mock, engine
):
    engine._stat.mock(side_effect=httpx.ReadTimeout("slow"))

    result = run(client, clock)

    assert result.status is CheckStatus.ERROR
    assert "in time" in result.error_message
    assert engine.stop.call_count == 1


def test_invalid_content_id_raises_before_any_request(client, clock, respx_mock):
    with pytest.raises(InvalidContentIdError):
        verify(client, "nope", sleep=clock.sleep, clock=clock)

    assert respx_mock.calls.call_count == 0


# probe on a session owned by the caller


def test_probe_does_not_stop_the_session(client, clock, engine):
    engine.stats(stat("dl", peers=2, speed=10, downloaded=100))

    with client.stream(HASH) as session:
        result = probe(client, session, sleep=clock.sleep, clock=clock)
        assert engine.stop.call_count == 0

    assert result.status is CheckStatus.ALIVE
    assert engine.stop.call_count == 1


# async


def test_verify_async_does_not_block_the_event_loop(client, engine):
    engine.stats(*[stat("prebuf", peers=1)] * 4, stat("dl", peers=2, speed=5, downloaded=100))
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    async def main():
        task = asyncio.create_task(ticker())
        result = await verify_async(
            client,
            HASH,
            VerificationSettings(timeout=5, poll_interval=1),
            sleep=lambda _seconds: time.sleep(0.05),
        )
        task.cancel()
        return result

    result = asyncio.run(main())

    assert result.status is CheckStatus.ALIVE
    assert ticks >= 5


# on_alive hook


def test_on_alive_runs_while_the_session_is_still_open(client, clock, engine):
    engine.stats(stat("dl", peers=2, speed=10, downloaded=100))
    seen = []

    result = verify(
        client,
        HASH,
        sleep=clock.sleep,
        clock=clock,
        on_alive=lambda s: seen.append((s.infohash, engine.stop.call_count)),
    )

    assert result.status is CheckStatus.ALIVE
    assert seen == [(INFOHASH, 0)]
    assert engine.stop.call_count == 1


def test_on_alive_is_skipped_when_the_channel_is_not_alive(client, clock, engine):
    engine.stats(stat("prebuf", peers=2))
    seen = []

    result = verify(client, HASH, sleep=clock.sleep, clock=clock, on_alive=seen.append)

    assert result.status is CheckStatus.NO_PEERS
    assert seen == []


def test_a_failing_on_alive_still_stops_the_session(client, clock, engine):
    engine.stats(stat("dl", peers=2, speed=10, downloaded=100))

    def boom(_session):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        verify(client, HASH, sleep=clock.sleep, clock=clock, on_alive=boom)

    assert engine.stop.call_count == 1


# how the identifier was loaded


def test_the_result_says_how_the_engine_loaded_the_identifier(client, clock, engine):
    engine.stats(stat("prebuf", peers=0))

    assert run(client, clock).kind is IdKind.CONTENT_ID


def test_a_known_kind_is_passed_to_the_engine(client, clock, respx_mock):
    route = respx_mock.get(f"{BASE}/ace/getstream", params={"infohash": HASH}).respond(
        json=GETSTREAM
    )
    respx_mock.get(f"{BASE}/ace/cmd/{PATH}").respond(json={"response": "ok", "error": None})
    respx_mock.get(f"{BASE}/ace/stat/{PATH}").respond(json=stat("dl", peers=2, downloaded=1000))

    result = verify(client, HASH, kind=IdKind.INFOHASH, sleep=clock.sleep, clock=clock)

    assert result.status is CheckStatus.ALIVE and result.kind is IdKind.INFOHASH
    assert route.call_count == 1


def test_content_that_does_not_load_has_no_kind(client, clock, respx_mock):
    respx_mock.get(f"{BASE}/ace/getstream").respond(
        json={"response": None, "error": "failed to load content"}
    )

    result = run(client, clock)

    assert result.status is CheckStatus.NOT_FOUND and result.kind is None
