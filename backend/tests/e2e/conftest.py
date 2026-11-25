"""Fixtures of the browser tests (Nogat's plan 2026-11-24-hydrograf-maplibre, step 1).

Every test of this directory is marked ``e2e``: the default run and the gate leave it
out, the ``e2e`` job of CI runs it (``uv run pytest tests/e2e -m e2e``). It needs
PostGIS (``DATABASE_URL``, a role that may create databases, as for the ``db`` tests)
and Playwright's Chromium (``uv run playwright install chromium``); without either the
tests are skipped, but when ``CI`` is set they fail.

* ``site`` (session): the synthetic catchment of ``tests/e2e/site.py`` in a private
  database and a temporary data root, the API under uvicorn and the pages served as
  nginx serves them, with its CSP.
* ``chromium`` (package): one headless Chromium. Playwright's sync API runs an event
  loop in the main thread, so it stops with this directory's last test.
* ``tab``: a recording tab of the site at 1440 px in the system's light theme;
  ``new_tab(width=..., theme=..., welcome=...)`` opens more (``browser.open_tab``).
  At its end a tab fails the test on any CSP violation, page error, console error or
  request outside the recorded answers.
"""

import os
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Error, expect, sync_playwright

from tests.conftest_db import _db_available
from tests.e2e.browser import EXPECT_TIMEOUT_MS, Tab, open_tab
from tests.e2e.site import Site, serve_site

HERE = Path(__file__).resolve().parent


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    for item in items:
        if HERE in Path(str(item.fspath)).resolve().parents:
            item.add_marker(pytest.mark.e2e)


def unavailable(reason: str) -> None:
    """Skip the test for a missing prerequisite; under CI fail it instead."""
    if os.environ.get("CI"):
        pytest.fail(f"{reason}; CI must run the browser tests", pytrace=False)
    pytest.skip(reason)


@pytest.fixture(scope="session")
def site(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Site]:
    """The served site of the synthetic catchment."""
    if not _db_available():
        unavailable("PostGIS is not available (DATABASE_URL)")
    with serve_site(tmp_path_factory.mktemp("e2e")) as served:
        yield served


@pytest.fixture(scope="package")
def chromium() -> Iterator[Browser]:
    """One headless Chromium of Playwright for the package."""
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Error as error:
            unavailable(
                "Chromium does not start; install it with "
                f"`uv run playwright install chromium` ({error})"
            )
            raise
        expect.set_options(timeout=EXPECT_TIMEOUT_MS)
        yield browser
        expect.set_options(timeout=None)
        browser.close()


@pytest.fixture
def new_tab(chromium: Browser, site: Site) -> Iterator[Callable[..., Tab]]:
    """Open recording tabs of the site: ``new_tab(width=1440, theme=None)``."""
    tabs: list[Tab] = []
    with ExitStack() as stack:

        def make(**options: Any) -> Tab:
            tab = stack.enter_context(open_tab(chromium, site, **options))
            tabs.append(tab)
            return tab

        yield make
        problems = [problem for tab in tabs for problem in tab.problems()]
        assert problems == [], problems


@pytest.fixture
def tab(new_tab: Callable[..., Tab]) -> Tab:
    """A recording tab of the site at 1440 px in the system's light theme."""
    return new_tab()
