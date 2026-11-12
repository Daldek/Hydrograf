"""
The GUIs of the ecosystem that this deployment runs (ADR-082).

The app menu of the top bar (Nogat's `<nogat-app-menu>`, DEV-15.4, loaded by
`frontend/js/nogat.js`) lists them; the hand-off links to Hydrolog through them.
"""

from fastapi import APIRouter

from core.config import get_settings, gui_table

router = APIRouter()


@router.get("/gui")
def gui_addresses() -> dict[str, str]:
    """
    Return the table `gui` of the deployment: registry name -> address.

    The value of HYDROGRAF_GUI (the table `gui` of `[nogat]` in `nogat.toml`,
    DEV-18.1), e.g. `{"hydrolog": "http://127.0.0.1:8070/"}`; `{}` without it, and
    the menu is then not drawn.
    """
    return gui_table(get_settings().hydrograf_gui)
