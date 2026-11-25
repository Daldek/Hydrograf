"""Browser tests of the view's context in „Zgłoś uwagę” (js/feedback.js, DEV-15.12).

Nogat's plan 2026-11-24-hydrograf-maplibre, step 1, the bullet „feedback's context
(feedback.js:55-62, DEV-15.12): params.map holds the map's centre and the base map,
and zoom is a number (its value changes in step 2, which the changelog says)”. A
report is sent through the dialog and the body of POST /api/v1/feedback is read as the
page sent it: ``context.parameters.map`` holds the centre of
``Hydrograf.map.describe()`` and the name of the chosen base map, its ``zoom`` is a
number whose value the tests leave alone, and the API answers that the report is
saved. The second test moves the view and chooses „bez podkładu” first.
"""

import math
from typing import Any

import pytest
from playwright.sync_api import Page, Response, expect

from tests.e2e.browser import Tab, open_map, wait_view

# The centre the report holds is the map's own [°]
CENTRE_TOLERANCE_DEG = 1e-6
DIALOG = "Zgłoś uwagę"
SAVED = "Dziękujemy! Zgłoszenie zostało zapisane."


def is_feedback(response: Response) -> bool:
    return response.request.method == "POST" and response.url.endswith(
        "/api/v1/feedback"
    )


def send_report(page: Page, message: str) -> dict[str, Any]:
    """Send a report through „Zgłoś uwagę”; the ``map`` of the context it sent."""
    page.get_by_role("button", name=DIALOG, exact=True).click()
    dialog = page.get_by_role("dialog", name=DIALOG, exact=True)
    dialog.get_by_label("Wiadomość", exact=True).fill(message)
    with page.expect_response(is_feedback) as answered:
        dialog.get_by_role("button", name="Wyślij", exact=True).click()
    response = answered.value
    assert response.ok, f"feedback failed: {response.status} {response.text()}"
    assert response.json()["status"] == "ok"
    # The dialog closes itself 2 s after the message: its text, not its visibility
    expect(page.get_by_text(SAVED, exact=True)).to_be_attached()
    body = response.request.post_data_json
    assert isinstance(body, dict), body
    assert body["message"] == message
    sent: dict[str, Any] = body["context"]["parameters"]["map"]
    return sent


def assert_view(sent: dict[str, Any], described: dict[str, Any]) -> None:
    """The context holds the map's centre and a zoom that is a number."""
    lng, lat = described["center"]
    centre = (sent["center"]["lng"], sent["center"]["lat"])
    assert centre == pytest.approx((lng, lat), abs=CENTRE_TOLERANCE_DEG), sent
    zoom = sent["zoom"]
    assert isinstance(zoom, int | float) and not isinstance(zoom, bool), sent
    assert math.isfinite(zoom), sent


def test_feedback_context_holds_the_centre_and_the_default_base_map(tab: Tab) -> None:
    page = tab.page
    described = open_map(tab)

    sent = send_report(page, "Test e2e: kontekst widoku mapy")

    assert_view(sent, described)
    assert sent["baseLayer"] == "openfreemap", sent


def test_feedback_context_follows_the_view_and_the_chosen_base_map(tab: Tab) -> None:
    page = tab.page
    opened = open_map(tab)
    base_maps = page.get_by_role(
        "radiogroup", name="Podkład kartograficzny", exact=True
    )
    base_maps.get_by_role("radio", name="bez podkładu", exact=True).check()
    # The view moves by a drag of the map
    box = page.locator("#map").bounding_box()
    assert box is not None
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x - 240, y + 120, steps=8)
    page.mouse.up()
    tab.settle()
    described = wait_view(page)
    assert described["center"] != pytest.approx(opened["center"], abs=1e-4)

    sent = send_report(page, "Test e2e: widok po przesunięciu, bez podkładu")

    assert_view(sent, described)
    assert sent["baseLayer"] == "none", sent
