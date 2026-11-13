"""
The pages of the public service and GET /api/terms (api/endpoints/site.py; ADR-084).

A page of the front end is sent by nginx from the file the API names in
`X-Accel-Redirect`; the regulamin is the filled page of the deployment, or a 404 with
no link to it when the deployment names no operator (Nogat DEV-15.7).
"""

import pytest
from fastapi.testclient import TestClient

import api.endpoints.site
from api.main import app
from core.terms import Terms

TERMS = Terms(page="<!doctype html><h1>Regulamin</h1>", operator_email="op@example.pl")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def terms(monkeypatch):
    """Serve the deployment's regulamin as given (None: no operator)."""

    def serve(value: Terms | None) -> None:
        monkeypatch.setattr(api.endpoints.site, "current_terms", lambda: value)

    return serve


@pytest.mark.parametrize("page", ["index.html", "admin.html", "instrukcja/index.html"])
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_nginx_sends_the_file_of_a_page(client, page, method):
    response = client.request(method, f"/{page}")

    assert response.status_code == 200
    assert response.headers["X-Accel-Redirect"] == f"/_site/{page}"
    assert response.content == b""


def test_an_unknown_page_is_not_found(client):
    assert client.get("/other.html").status_code == 404


def test_regulamin_of_a_public_deployment(client, terms):
    terms(TERMS)

    response = client.get("/regulamin.html")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["cache-control"] == "no-cache"
    assert response.text == TERMS.page
    assert client.get("/api/terms").json() == {
        "url": "/regulamin.html",
        "operator_email": "op@example.pl",
    }


def test_without_an_operator_there_is_no_regulamin(client, terms):
    terms(None)

    response = client.get("/regulamin.html")

    assert response.status_code == 404
    assert response.json()["details"]["reason"] == "terms_not_configured"
    assert client.get("/api/terms").json() == {"url": None, "operator_email": None}
