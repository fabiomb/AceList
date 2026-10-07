import pytest

from app.services import categories, channels
from app.services.errors import NotFoundError, ValidationError
from app.services.importer import MAX_LINES, Reason, import_links, parse_links

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"
HASH_C = "efc60cfe5e3a349baa02bcc49f6647c21a9c3c5b"


def parsed(text):
    entries, invalid = parse_links(text)
    return [(e.line, e.content_id, e.title) for e in entries], [(r.line, r.text) for r in invalid]


def test_bare_ids_and_links_in_any_case():
    entries, invalid = parsed(f"{HASH_A}\nacestream://{HASH_B.upper()}\n")

    assert entries == [
        (1, HASH_A, f"Canal {HASH_A[:8]}"),
        (2, HASH_B, f"Canal {HASH_B[:8]}"),
    ]
    assert invalid == []


def test_text_around_the_link_becomes_the_title():
    entries, _ = parsed(
        f"Partido 1 - acestream://{HASH_A}\n{HASH_B} | Noticias 24\n  Cine: {HASH_C}  "
    )

    assert [title for _, _, title in entries] == ["Partido 1", "Noticias 24", "Cine"]


def test_m3u_titles_apply_to_the_next_link():
    text = "\n".join(
        [
            "#EXTM3U",
            '#EXTINF:-1 tvg-name="Uno, Dos" group-title="Sports",Deportes HD',
            f"acestream://{HASH_A}",
            "#EXTINF:-1,Noticias, edición noche",
            f"http://127.0.0.1:6878/ace/getstream?id={HASH_B}",
            f"acestream://{HASH_C}",
        ]
    )

    entries, invalid = parsed(text)

    assert [(cid, title) for _, cid, title in entries] == [
        (HASH_A, "Deportes HD"),
        (HASH_B, "Noticias, edición noche"),
        (HASH_C, f"Canal {HASH_C[:8]}"),
    ]
    assert invalid == []


def test_comments_and_blank_lines_are_ignored_and_bad_lines_reported():
    entries, invalid = parsed(f"# my list\n\n{HASH_A}\nnot a link\n{HASH_A[:39]}\n{HASH_A}0\n")

    assert [line for line, _, _ in entries] == [3]
    assert invalid == [(4, "not a link"), (5, HASH_A[:39]), (6, f"{HASH_A}0")]


def test_long_titles_are_cut_to_the_column_length():
    entries, _ = parsed(f"{'x' * 300} {HASH_A}")

    assert len(entries[0][2]) == 200


# import_links


def test_import_creates_new_channels_with_the_shared_fields(db):
    sports = categories.create_category(db, "Deportes")

    result = import_links(
        db,
        f"Uno {HASH_A}\nDos {HASH_B}",
        category_id=sports.id,
        language="ES",
        country="ar",
    )

    assert [c.title for c in result.created] == ["Uno", "Dos"]
    stored = channels.list_channels(db)
    assert {(c.category_id, c.language, c.country) for c in stored} == {(sports.id, "es", "AR")}


def test_duplicates_in_the_catalog_and_in_the_text_are_skipped(db):
    existing = channels.create_channel(db, title="Ya estaba", content_id=HASH_A)

    result = import_links(db, f"{HASH_A}\n{HASH_B}\nbad\nacestream://{HASH_B}")

    assert [c.content_id for c in result.created] == [HASH_B]
    assert [(d.line, d.reason) for d in result.duplicates] == [
        (1, Reason.EXISTING),
        (4, Reason.REPEATED),
    ]
    assert result.duplicates[0].existing.id == existing.id
    assert result.duplicates[1].first_line == 2
    assert [r.line for r in result.invalid] == [3]
    assert len(channels.list_channels(db)) == 2


def test_bad_shared_values_fail_before_creating_anything(db):
    with pytest.raises(ValidationError):
        import_links(db, HASH_A, language="xx")
    with pytest.raises(NotFoundError):
        import_links(db, HASH_A, category_id=99)

    assert channels.list_channels(db) == []


def test_too_many_lines_are_refused(db):
    with pytest.raises(ValidationError, match="too many lines"):
        import_links(db, "\n".join([HASH_A] * (MAX_LINES + 1)))
