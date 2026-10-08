"""One-shot notices for the page a redirect lands on (the POST cannot render them)."""

from fastapi import Request, Response

FLASH_COOKIE = "acelist_notice"

ENGINE_DOWN = "engine_down"
ENGINE_DOWN_SAVED = "engine_down_saved"

MESSAGES = {
    ENGINE_DOWN: (
        "Ace Stream no está abierto o no responde: no se verificó ningún canal. "
        "Ábrelo y vuelve a intentarlo."
    ),
    ENGINE_DOWN_SAVED: (
        "Se guardó el canal, pero Ace Stream no responde: queda sin verificar hasta que lo abras."
    ),
}


def flash(response: Response, code: str) -> Response:
    """Leaves a notice for the next page; only codes from `MESSAGES` are ever shown."""
    response.set_cookie(FLASH_COOKIE, code, max_age=60, httponly=True, samesite="strict")
    return response


def flash_message(request: Request) -> str | None:
    """The pending notice, marking it shown so the response that renders it clears it."""
    message = MESSAGES.get(request.cookies.get(FLASH_COOKIE, ""))
    if message is not None:
        request.state.flash_shown = True
    return message


def clear_shown_flash(request: Request, response: Response) -> None:
    # Only the page that displayed the notice consumes it: a poll from another page
    # landing in between must not swallow it.
    if getattr(request.state, "flash_shown", False):
        response.delete_cookie(FLASH_COOKIE, samesite="strict")
