import pytest

from app.acestream.content_id import InvalidContentIdError, parse_content_id

HASH = "78266c15035d0ad8cbc58f821733931e1de434ab"


@pytest.mark.parametrize(
    "value",
    [
        HASH,
        HASH.upper(),
        HASH[:20].upper() + HASH[20:],
        f"acestream://{HASH}",
        f"ACESTREAM://{HASH.upper()}",
        f"  {HASH}\n",
        f"\tacestream://{HASH}  ",
    ],
    ids=["lower", "upper", "mixed", "link", "upper-link", "whitespace", "link-whitespace"],
)
def test_valid_inputs_are_normalized_to_lowercase(value):
    assert parse_content_id(value) == HASH


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        HASH[:-1],
        HASH + "0",
        "g" + HASH[1:],
        "acestream://",
        f"acestream://{HASH[:-1]}",
        f"http://{HASH}",
        f"acestream:/{HASH}",
        f"acestream://acestream://{HASH}",
        f"{HASH}/",
        f"{HASH}?x=1",
        f"{HASH[:20]} {HASH[20:]}",
        f"{HASH}\n{HASH}",
        "\uff17" + HASH[1:],  # fullwidth digit that looks numeric
    ],
    ids=[
        "empty",
        "blank",
        "short",
        "long",
        "non-hex",
        "scheme-only",
        "scheme-short",
        "other-scheme",
        "malformed-scheme",
        "double-scheme",
        "trailing-slash",
        "query",
        "inner-space",
        "two-hashes",
        "unicode-digit",
    ],
)
def test_invalid_inputs_are_rejected(value):
    with pytest.raises(InvalidContentIdError):
        parse_content_id(value)


def test_error_message_is_clear_and_truncates_long_input():
    with pytest.raises(InvalidContentIdError, match="40 hexadecimal characters") as info:
        parse_content_id("x" * 500)

    assert len(str(info.value)) < 200


def test_error_is_a_value_error():
    assert issubclass(InvalidContentIdError, ValueError)
