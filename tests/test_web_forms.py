import pytest

from app.db.models import CheckStatus
from app.services import categories, channels, checks

HASH_A = "78266c15035d0ad8cbc58f821733931e1de434ab"
HASH_B = "ecc85e5d2b6088d2d307fd0b5de4f09f089e762f"


def form(**fields):
    values = {
        "title": "Canal Uno",
        "link": HASH_A,
        "category_id": "",
        "new_category": "",
        "language": "",
        "country": "",
    }
    values.update(fields)
    return values


# add


def test_new_form_lists_categories_languages_and_countries(web, db):
    categories.create_category(db, "Deportes")

    page = web.get("/channels/new").text

    assert "Agregar canal" in page
    assert ">Deportes</option>" in page
    assert '<option value="es">Spanish (es)</option>' in page
    assert '<option value="AR">Argentina (AR)</option>' in page


def test_adding_stores_the_channel_and_its_first_check(web, db, engine_empty):
    sports = categories.create_category(db, "Deportes")

    response = web.post(
        "/channels/new",
        data=form(
            link=f"acestream://{HASH_A.upper()}",
            category_id=str(sports.id),
            language="es",
            country="ar",
        ),
        follow_redirects=False,
    )

    assert response.status_code == 303
    [channel] = channels.list_channels(db)
    assert response.headers["location"] == f"http://127.0.0.1/channels/{channel.id}"
    assert (channel.title, channel.content_id) == ("Canal Uno", HASH_A)
    assert (channel.category_id, channel.language, channel.country) == (sports.id, "es", "AR")
    [check] = checks.list_checks(db, channel.id)
    assert check.status == CheckStatus.NOT_FOUND
    assert engine_empty.called


def test_invalid_input_is_shown_again_with_errors_and_nothing_is_saved(web, db, engine_down):
    response = web.post(
        "/channels/new", data=form(title="  ", link="not-a-hash", language="xx", country="UK")
    )

    assert response.status_code == 422
    page = response.text
    assert "No es un Content ID válido" in page
    assert "Idioma desconocido" in page
    assert "País desconocido" in page
    assert 'value="not-a-hash"' in page
    assert channels.list_channels(db) == []
    assert not engine_down.called


def test_duplicate_names_the_existing_channel_without_calling_the_engine(web, db, engine_down):
    channels.create_channel(db, title="El original", content_id=HASH_A)

    response = web.post("/channels/new", data=form(link=f"acestream://{HASH_A}"))

    assert response.status_code == 422
    assert "Este Content ID ya está registrado como «El original»." in response.text
    assert len(channels.list_channels(db)) == 1
    assert not engine_down.called


def test_unknown_category_is_rejected(web, db, engine_down):
    response = web.post("/channels/new", data=form(category_id="999"))

    assert response.status_code == 422
    assert "La categoría elegida no existe." in response.text
    assert channels.list_channels(db) == []


def test_new_category_is_created_or_reused_by_name(web, db, engine_down):
    web.post("/channels/new", data=form(new_category="Cine"))
    web.post("/channels/new", data=form(title="Dos", link=HASH_B, new_category=" cine "))

    [cine] = categories.list_categories(db)
    assert cine.name == "Cine"
    assert {c.category_id for c in channels.list_channels(db)} == {cine.id}


def test_form_values_are_escaped(web, db, engine_down):
    response = web.post("/channels/new", data=form(title='"><script>x()</script>', link="bad"))

    assert "<script>x()</script>" not in response.text
    assert "&#34;&gt;&lt;script&gt;x()&lt;/script&gt;" in response.text


# edit


def test_edit_form_is_prefilled(web, db):
    sports = categories.create_category(db, "Deportes")
    channel = channels.create_channel(
        db, title="Uno", content_id=HASH_A, category_id=sports.id, language="es", country="AR"
    )

    page = web.get(f"/channels/{channel.id}/edit").text

    assert "Editar canal" in page
    assert 'value="Uno"' in page
    assert f'value="{HASH_A}"' in page
    assert f'<option value="{sports.id}" selected>' in page
    assert '<option value="es" selected>' in page
    assert '<option value="AR" selected>' in page


def test_editing_other_fields_does_not_verify_again(web, db, engine_down):
    channel = channels.create_channel(db, title="Uno", content_id=HASH_A)

    response = web.post(
        f"/channels/{channel.id}/edit",
        data=form(title="Uno renombrado", language="en"),
        follow_redirects=False,
    )

    assert response.status_code == 303
    db.expire_all()
    edited = channels.get_channel(db, channel.id)
    assert (edited.title, edited.language) == ("Uno renombrado", "en")
    assert checks.list_checks(db, channel.id) == []
    assert not engine_down.called


def test_changing_the_hash_verifies_again(web, db, engine_empty):
    channel = channels.create_channel(db, title="Uno", content_id=HASH_A)

    web.post(f"/channels/{channel.id}/edit", data=form(title="Uno", link=HASH_B))

    db.expire_all()
    assert channels.get_channel(db, channel.id).content_id == HASH_B
    assert len(checks.list_checks(db, channel.id)) == 1
    assert engine_empty.called


def test_editing_keeps_its_own_hash_but_rejects_another_channels(web, db, engine_down):
    channels.create_channel(db, title="Otro", content_id=HASH_B)
    channel = channels.create_channel(db, title="Uno", content_id=HASH_A)

    assert web.post(f"/channels/{channel.id}/edit", data=form()).status_code == 200
    response = web.post(f"/channels/{channel.id}/edit", data=form(link=HASH_B))

    assert response.status_code == 422
    assert "registrado como «Otro»" in response.text
    db.expire_all()
    assert channels.get_channel(db, channel.id).content_id == HASH_A


def test_missing_channel_is_404(web):
    assert web.get("/channels/999/edit").status_code == 404
    assert web.post("/channels/999/edit", data=form()).status_code == 404
    assert web.get("/channels/999/delete").status_code == 404
    assert web.post("/channels/999/delete").status_code == 404


# delete


def test_delete_asks_for_confirmation_first(web, db):
    channel = channels.create_channel(db, title="<b>Uno</b>", content_id=HASH_A)
    checks.add_check(db, channel.id, status=CheckStatus.ALIVE)

    page = web.get(f"/channels/{channel.id}/delete").text

    assert "¿Seguro que quieres borrar" in page
    assert "&lt;b&gt;Uno&lt;/b&gt;" in page
    assert "sus 1 verificaciones" in page
    assert channels.list_channels(db) != []


def test_confirmed_delete_removes_the_channel(web, db):
    channel = channels.create_channel(db, title="Uno", content_id=HASH_A)

    response = web.post(f"/channels/{channel.id}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert channels.list_channels(db) == []


def test_list_links_to_add_edit_and_delete(web, db):
    channel = channels.create_channel(db, title="Uno", content_id=HASH_A)

    page = web.get("/").text

    assert 'href="http://127.0.0.1/channels/new"' in page
    assert f'href="http://127.0.0.1/channels/{channel.id}/edit"' in page
    assert f'href="http://127.0.0.1/channels/{channel.id}/delete"' in page


# cross-site requests


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "http://attacker.example"},
        {"origin": "null"},
        {"sec-fetch-site": "cross-site"},
    ],
)
def test_writes_from_other_sites_are_rejected(web, db, headers):
    channel = channels.create_channel(db, title="Uno", content_id=HASH_A)

    response = web.post(f"/channels/{channel.id}/delete", headers=headers)

    assert response.status_code == 403
    assert len(channels.list_channels(db)) == 1


def test_writes_from_the_app_itself_are_accepted(web, db):
    channel = channels.create_channel(db, title="Uno", content_id=HASH_A)

    response = web.post(
        f"/channels/{channel.id}/delete",
        headers={"origin": "http://127.0.0.1:8000", "sec-fetch-site": "same-origin"},
        follow_redirects=False,
    )

    assert response.status_code == 303


def test_row_actions_are_icons_with_accessible_names(web, db):
    channels.create_channel(db, title="Uno", content_id=HASH_A)

    page = web.get("/").text

    for action in ("Reproducir", "Editar", "Borrar"):
        assert f'aria-label="{action} Uno" title="{action}"' in page


def test_resolution_can_be_chosen_on_add_and_edit(web, db, engine_down):
    response = web.post("/channels/new", data=form(resolution="720p"), follow_redirects=False)
    [channel] = channels.list_channels(db)
    assert channel.resolution.value == "720p"

    page = web.get(f"/channels/{channel.id}/edit").text
    assert '<option value="720p" selected>720p</option>' in page

    web.post(f"/channels/{channel.id}/edit", data=form(resolution=""))
    db.expire_all()
    assert channels.get_channel(db, channel.id).resolution is None
    assert response.status_code == 303


def test_unknown_resolution_is_rejected(web, db, engine_down):
    response = web.post("/channels/new", data=form(resolution="8k"))

    assert response.status_code == 422
    assert "Resolución desconocida." in response.text
