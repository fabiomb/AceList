import pytest

from app.services.naming import clean_stream_name, placeholder_title


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Sky Sports Main Event [UK]", "Sky Sports Main Event [UK]"),
        (
            "DAZN 1 1080 elcano.top https://x.com/ace_stream_ https://t.me/acestreamf1",
            "DAZN 1 1080 elcano.top",
        ),
        ("  Canal   con\tespacios  ", "Canal con espacios"),
        ("Partido - www.example.com/x", "Partido"),
        ("https://only.example.com", None),
        ("", None),
        (None, None),
    ],
)
def test_clean_stream_name(raw, expected):
    assert clean_stream_name(raw) == expected


def test_clean_stream_name_fits_the_title_column():
    assert len(clean_stream_name("x" * 300)) == 200


def test_placeholder_title():
    assert placeholder_title("78266c15035d0ad8cbc58f821733931e1de434ab") == "Canal 78266c15"
