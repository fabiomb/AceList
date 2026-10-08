import httpx
import pytest

from app.acestream.client import EngineClient, StreamSession
from app.acestream.content_id import InvalidContentIdError
from app.acestream.errors import (
    ContentNotFoundError,
    EngineProtocolError,
    EngineTimeoutError,
    EngineUnavailableError,
)

BASE = "http://127.0.0.1:6878"
HASH = "78266c15035d0ad8cbc58f821733931e1de434ab"
SESSION_PATH = f"{HASH}/f4283e11274fae1ced9ef41a4c173857"

# Shapes taken from the real engine (docs/engine-api.md).
GETSTREAM_OK = {
    "response": {
        "stat_url": f"{BASE}/ace/stat/{SESSION_PATH}",
        "playback_url": f"{BASE}/ace/r/{SESSION_PATH}",
        "command_url": f"{BASE}/ace/cmd/{SESSION_PATH}",
        "playback_session_id": "c3fa22427da41d688afe5811fd445c94f451c5d5",
        "is_live": 1,
        "is_encrypted": 0,
        "client_session_id": -1,
        "infohash": HASH,
    },
    "error": None,
}
STAT_IDLE = {"response": {"status": "idle", "is_live": 1, "infohash": HASH}, "error": None}
STAT_DL = {
    "response": {"status": "dl", "peers": 4, "speed_down": 1522, "downloaded": 13107200},
    "error": None,
}
STOP_OK = {"response": "ok", "error": None}
VERSION_OK = {"result": {"code": 3017400, "platform": "win32", "version": "3.1.74"}, "error": None}


@pytest.fixture
def client():
    with EngineClient(BASE, timeout=1) as c:
        yield c


@pytest.fixture
def session():
    return StreamSession(
        content_id=HASH,
        infohash=HASH,
        playback_url=f"{BASE}/ace/r/{SESSION_PATH}",
        stat_url=f"{BASE}/ace/stat/{SESSION_PATH}",
        command_url=f"{BASE}/ace/cmd/{SESSION_PATH}",
    )


# version and availability


def test_version(client, respx_mock):
    route = respx_mock.get(f"{BASE}/webui/api/service").respond(json=VERSION_OK)

    version = client.version()

    assert (version.version, version.code, version.platform) == ("3.1.74", 3017400, "win32")
    assert route.calls.last.request.url.params["method"] == "get_version"


def test_is_available_true_when_engine_answers(client, respx_mock):
    respx_mock.get(f"{BASE}/webui/api/service").respond(json=VERSION_OK)
    assert client.is_available() is True


def test_is_available_false_when_engine_is_down(client, respx_mock):
    respx_mock.get(f"{BASE}/webui/api/service").mock(side_effect=httpx.ConnectError("refused"))
    assert client.is_available() is False


def test_version_with_malformed_result_is_a_protocol_error(client, respx_mock):
    respx_mock.get(f"{BASE}/webui/api/service").respond(json={"result": {"version": "3"}})
    with pytest.raises(EngineProtocolError):
        client.version()


# start_stream


def test_start_stream_returns_session_and_sends_expected_query(client, respx_mock):
    route = respx_mock.get(f"{BASE}/ace/getstream").respond(json=GETSTREAM_OK)

    session = client.start_stream(HASH.upper())

    params = route.calls.last.request.url.params
    assert (params["id"], params["format"]) == (HASH, "json")
    assert params["pid"]
    assert session.content_id == HASH
    assert session.infohash == HASH
    assert session.stat_url == f"{BASE}/ace/stat/{SESSION_PATH}"
    assert session.command_url == f"{BASE}/ace/cmd/{SESSION_PATH}"


def test_start_stream_accepts_acestream_link(client, respx_mock):
    route = respx_mock.get(f"{BASE}/ace/getstream").respond(json=GETSTREAM_OK)

    client.start_stream(f"acestream://{HASH}")

    assert route.calls.last.request.url.params["id"] == HASH


def test_engine_urls_are_rebased_onto_the_configured_engine(respx_mock):
    remote = "http://192.168.1.50:6878"
    respx_mock.get(f"{remote}/ace/getstream").respond(json=GETSTREAM_OK)

    with EngineClient(remote, timeout=1) as c:
        session = c.start_stream(HASH)

    assert session.playback_url == f"{remote}/ace/r/{SESSION_PATH}"
    assert session.stat_url == f"{remote}/ace/stat/{SESSION_PATH}"
    assert session.command_url == f"{remote}/ace/cmd/{SESSION_PATH}"


def test_foreign_host_in_engine_response_is_never_followed(client, respx_mock):
    hostile = {
        "response": {
            **GETSTREAM_OK["response"],
            "stat_url": f"http://evil.example/ace/stat/{SESSION_PATH}",
        },
        "error": None,
    }
    respx_mock.get(f"{BASE}/ace/getstream").respond(json=hostile)

    assert client.start_stream(HASH).stat_url == f"{BASE}/ace/stat/{SESSION_PATH}"


def test_invalid_content_id_is_rejected_without_calling_the_engine(client, respx_mock):
    with pytest.raises(InvalidContentIdError):
        client.start_stream("not-a-hash")

    assert respx_mock.calls.call_count == 0


def test_unknown_content_raises_content_not_found(client, respx_mock):
    respx_mock.get(f"{BASE}/ace/getstream").respond(
        json={"response": None, "error": "failed to load content"}
    )

    with pytest.raises(ContentNotFoundError) as info:
        client.start_stream(HASH)

    assert info.value.content_id == HASH


def test_other_engine_errors_are_protocol_errors(client, respx_mock):
    respx_mock.get(f"{BASE}/ace/getstream").respond(json={"response": None, "error": "boom"})
    with pytest.raises(EngineProtocolError, match="boom"):
        client.start_stream(HASH)


def test_response_missing_urls_is_a_protocol_error(client, respx_mock):
    respx_mock.get(f"{BASE}/ace/getstream").respond(
        json={"response": {"infohash": HASH}, "error": None}
    )
    with pytest.raises(EngineProtocolError):
        client.start_stream(HASH)


def test_engine_down_raises_unavailable(client, respx_mock):
    respx_mock.get(f"{BASE}/ace/getstream").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(EngineUnavailableError):
        client.start_stream(HASH)


def test_slow_engine_raises_timeout(client, respx_mock):
    respx_mock.get(f"{BASE}/ace/getstream").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(EngineTimeoutError):
        client.start_stream(HASH)


def test_http_error_status_is_a_protocol_error(client, respx_mock):
    respx_mock.get(f"{BASE}/ace/getstream").respond(status_code=500)
    with pytest.raises(EngineProtocolError, match="500"):
        client.start_stream(HASH)


def test_invalid_json_is_a_protocol_error(client, respx_mock):
    respx_mock.get(f"{BASE}/ace/getstream").respond(text="<html>")
    with pytest.raises(EngineProtocolError):
        client.start_stream(HASH)


def test_non_object_json_is_a_protocol_error(client, respx_mock):
    respx_mock.get(f"{BASE}/ace/getstream").respond(json=["nope"])
    with pytest.raises(EngineProtocolError):
        client.start_stream(HASH)


# stats and stop


def test_stats_while_idle_has_no_peer_data(client, session, respx_mock):
    respx_mock.get(session.stat_url).respond(json=STAT_IDLE)

    stats = client.stats(session)

    assert stats.status == "idle"
    assert (stats.peers, stats.speed_down, stats.downloaded) == (None, None, None)


def test_stats_while_downloading(client, session, respx_mock):
    respx_mock.get(session.stat_url).respond(json=STAT_DL)

    stats = client.stats(session)

    assert (stats.status, stats.peers, stats.speed_down, stats.downloaded) == (
        "dl",
        4,
        1522,
        13107200,
    )


def test_stats_with_empty_response_right_after_start_is_idle(client, session, respx_mock):
    # Observed on the real engine: the very first stat call can return `{"response": {}}`.
    respx_mock.get(session.stat_url).respond(json={"response": {}, "error": None})

    stats = client.stats(session)

    assert stats.status == "idle"
    assert (stats.peers, stats.speed_down, stats.downloaded) == (None, None, None)


def test_stats_without_status_is_a_protocol_error(client, session, respx_mock):
    respx_mock.get(session.stat_url).respond(json={"response": {"peers": 1}, "error": None})
    with pytest.raises(EngineProtocolError):
        client.stats(session)


def test_stop_sends_stop_command(client, session, respx_mock):
    route = respx_mock.get(session.command_url).respond(json=STOP_OK)

    client.stop(session)

    assert route.calls.last.request.url.params["method"] == "stop"


def test_stop_without_confirmation_is_a_protocol_error(client, session, respx_mock):
    respx_mock.get(session.command_url).respond(json={"response": "nope", "error": None})
    with pytest.raises(EngineProtocolError):
        client.stop(session)


# stream() context manager


def test_stream_stops_the_session_on_success(client, respx_mock):
    respx_mock.get(f"{BASE}/ace/getstream").respond(json=GETSTREAM_OK)
    stop = respx_mock.get(f"{BASE}/ace/cmd/{SESSION_PATH}").respond(json=STOP_OK)

    with client.stream(HASH) as session:
        assert session.infohash == HASH

    assert stop.call_count == 1


def test_stream_stops_the_session_when_the_block_fails(client, respx_mock):
    respx_mock.get(f"{BASE}/ace/getstream").respond(json=GETSTREAM_OK)
    stop = respx_mock.get(f"{BASE}/ace/cmd/{SESSION_PATH}").respond(json=STOP_OK)

    with pytest.raises(RuntimeError, match="boom"), client.stream(HASH):
        raise RuntimeError("boom")

    assert stop.call_count == 1


def test_failed_stop_does_not_hide_the_original_error(client, respx_mock):
    respx_mock.get(f"{BASE}/ace/getstream").respond(json=GETSTREAM_OK)
    respx_mock.get(f"{BASE}/ace/cmd/{SESSION_PATH}").mock(side_effect=httpx.ConnectError("gone"))

    with pytest.raises(RuntimeError, match="boom"), client.stream(HASH):
        raise RuntimeError("boom")


def test_stream_does_not_stop_when_it_never_started(client, respx_mock):
    respx_mock.get(f"{BASE}/ace/getstream").respond(
        json={"response": None, "error": "failed to load content"}
    )

    with pytest.raises(ContentNotFoundError), client.stream(HASH):
        pytest.fail("block must not run")

    assert respx_mock.calls.call_count == 1


# media_name (observed shape in docs/engine-api.md)

MEDIA_FILES = {
    "result": {
        "files": [{"index": 0, "filename": "Sky Sports Main Event [UK]"}],
        "name": "Sky Sports Main Event [UK]",
        "infohash": HASH,
        "transport_type": "bt",
        "type": "live",
    }
}


def test_media_name_without_starting_a_session(client, respx_mock):
    route = respx_mock.get(f"{BASE}/server/api").respond(json=MEDIA_FILES)

    assert client.media_name(f"acestream://{HASH.upper()}") == "Sky Sports Main Event [UK]"
    params = route.calls.last.request.url.params
    assert (params["method"], params["content_id"], params["api_version"]) == (
        "get_media_files",
        HASH,
        "3",
    )


def test_media_name_falls_back_to_the_file_name(client, respx_mock):
    respx_mock.get(f"{BASE}/server/api").respond(
        json={"result": {"files": [{"index": 0, "filename": "Canal Uno"}]}}
    )

    assert client.media_name(HASH) == "Canal Uno"


def test_media_name_of_unknown_content_is_none(client, respx_mock):
    respx_mock.get(f"{BASE}/server/api").respond(
        json={"error": {"message": "cannot get transport file", "code": 0}}
    )

    assert client.media_name(HASH) is None


def test_media_name_with_an_unexpected_answer_is_a_protocol_error(client, respx_mock):
    respx_mock.get(f"{BASE}/server/api").respond(json={"result": "nope"})

    with pytest.raises(EngineProtocolError):
        client.media_name(HASH)


def test_media_name_rejects_a_bad_content_id_before_any_request(client, respx_mock):
    with pytest.raises(InvalidContentIdError):
        client.media_name("nope")

    assert not respx_mock.calls
