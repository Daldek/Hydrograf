"""
The pages of the public service and GET /api/v1/terms (api/endpoints/site.py; ADR-084),
whose provider lines the welcome window shows on every deployment, with or without an
operator.

A page of the front end is sent by nginx from the file the API names in
`X-Accel-Redirect`; the regulamin is the filled page of the deployment, or a 404 with
no link to it when the deployment names no operator (Nogat DEV-15.7).
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

import api.endpoints.site
from api.main import app
from core.attribution import PMAXTP, SOILGRIDS_SOURCE
from core.database import get_db
from core.terms import Terms

TERMS = Terms(
    page="<!doctype html><h1>Regulamin</h1>",
    operator_email="op@example.pl",
    version="1.1",
)


def _gugik(products: str) -> str:
    """G of the products, without an instance.json that dates them."""
    return (
        f"Źródło: Główny Urząd Geodezji i Kartografii – GUGiK, {products} "
        "(wytworzono b.d., pozyskano b.d.); dane przetworzone"
    )


# Every line of the service: PMAXTP's, then G and SG of a catchment (DEV-20.4), and
# the lines of each kind of the map's layers
LINES = {
    "attribution": [*PMAXTP.attribution, _gugik("NMT, BDOT10k"), SOILGRIDS_SOURCE],
    "terms_notice": list(PMAXTP.terms_notice),
    "layers": {
        "elevation": {"attribution": [_gugik("NMT")], "terms_notice": []},
        "drainage": {"attribution": [_gugik("NMT, BDOT10k")], "terms_notice": []},
        "topography": {"attribution": [_gugik("BDOT10k")], "terms_notice": []},
        "soils": {
            "attribution": [_gugik("BDOT10k"), SOILGRIDS_SOURCE],
            "terms_notice": [],
        },
    },
}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def terms(monkeypatch):
    """Serve the deployment's regulamin as given (None: no operator)."""

    def serve(value: Terms | None) -> None:
        monkeypatch.setattr(api.endpoints.site, "current_terms", lambda: value)

    return serve


@pytest.fixture
def pmaxtp():
    """Answer whether `precipitation_data` has rows; None: the database fails."""

    def held(rows: bool | None) -> None:
        session = MagicMock()
        if rows is None:
            session.execute.side_effect = OperationalError("SELECT", {}, Exception())
        else:
            session.execute.return_value.scalar.return_value = rows
        app.dependency_overrides[get_db] = lambda: session

    yield held
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize(
    "page", ["index.html", "admin/index.html", "instrukcja/index.html"]
)
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_nginx_sends_the_file_of_a_page(client, page, method):
    response = client.request(method, f"/{page}")

    assert response.status_code == 200
    assert response.headers["X-Accel-Redirect"] == f"/_site/{page}"
    assert response.content == b""


@pytest.mark.parametrize("page", ["/other.html", "/admin.html"])
def test_an_unknown_page_is_not_found(client, page):
    assert client.get(page).status_code == 404


def test_regulamin_of_a_public_deployment(client, terms, pmaxtp):
    terms(TERMS)
    pmaxtp(True)

    response = client.get("/regulamin.html")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["cache-control"] == "no-cache"
    assert response.text == TERMS.page
    assert client.get("/api/v1/terms").json() == {
        "url": "/regulamin.html",
        "operator_email": "op@example.pl",
        **LINES,
    }


def test_without_an_operator_there_is_no_regulamin(client, terms, pmaxtp):
    terms(None)
    pmaxtp(True)

    response = client.get("/regulamin.html")

    assert response.status_code == 404
    assert response.json()["details"]["reason"] == "terms_not_configured"
    assert client.get("/api/v1/terms").json() == {
        "url": None,
        "operator_email": None,
        **LINES,
    }


def test_an_instance_without_pmaxtp_names_no_pmaxtp_line(client, terms, pmaxtp):
    # Bootstrapped with --skip-precipitation: no design storm, no product of PMAXTP
    terms(TERMS)
    pmaxtp(False)

    info = client.get("/api/v1/terms").json()

    assert info["attribution"] == [_gugik("NMT, BDOT10k"), SOILGRIDS_SOURCE]
    assert info["terms_notice"] == []
    assert info["layers"] == LINES["layers"]


def test_the_pmaxtp_lines_stay_when_the_database_cannot_tell(client, terms, pmaxtp):
    terms(TERMS)
    pmaxtp(None)

    info = client.get("/api/v1/terms").json()

    assert info["attribution"] == LINES["attribution"]
    assert info["terms_notice"] == LINES["terms_notice"]
