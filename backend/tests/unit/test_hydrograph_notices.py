"""Hydrolog's warnings of a hydrograph in its response, in Polish (E5b-06).

Hydrolog warns of a value outside the typical range of a method with
``warnings.warn``. The client runs the application's lifespan, which installs the
hook that collects these warnings after the log starts, as the server does.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import api.endpoints.hydrograph
from api.main import app
from core.database import get_db

URL = "/api/generate-hydrograph"


def _request(
    area_km2: float, timestep_min: float, depths_mm: list[float]
) -> dict[str, Any]:
    """A hydrograph of the SCS unit hydrograph with NRCS's tc on given morphometry."""
    return {
        "latitude": 51.0,
        "longitude": 16.05,
        "custom_precipitation": {"timestep_min": timestep_min, "depths_mm": depths_mm},
        "morphometry": {
            "area_km2": area_km2,
            "perimeter_km": 50.0,
            "length_km": 15.0,
            "elevation_min_m": 120.0,
            "elevation_max_m": 190.0,
            "elevation_mean_m": 155.0,
            "mean_slope_m_per_m": 0.04,
            "channel_length_km": 16.5,
            "channel_slope_m_per_m": 0.0108,
            "flow_path_length_km": 17.0,
            "flow_path_slope_m_per_m": 0.01,
            "length_to_centroid_km": 8.5,
            "cn": 72.0,
        },
    }


# 100 km² is above the typical range of the SCS unit hydrograph (to 52 km²) and of
# NRCS's lag equation (to 24 km²)
LARGE = _request(100.0, 10.0, [5.0, 20.0, 10.0, 5.0])
# A daily step is longer than a quarter of the time to peak of the unit hydrograph:
# Hydrolog computes it on sub-steps (info) and still warns of the step (warning)
DAILY = _request(10.0, 1440.0, [10.0, 60.0, 5.0])

SCS_AREA = (
    "Hydrogram jednostkowy SCS: powierzchnia zlewni = 100\u00a0km² – powyżej "
    "typowego zakresu 0–52\u00a0km². Wynik może być niewiarygodny."
)
NRCS_AREA = (
    "Czas koncentracji (NRCS): powierzchnia zlewni = 100\u00a0km² – powyżej "
    "typowego zakresu 0,005–24\u00a0km². Wynik może być niewiarygodny."
)
DAILY_STEP = (
    "Hydrogram jednostkowy SCS: krok czasowy Δt = 1440\u00a0min – powyżej typowego "
    "zakresu 0–255,2\u00a0min. Wynik może być niewiarygodny."
)
DAILY_SUBSTEPS = (
    "Hydrogram jednostkowy SCS: krok czasowy Δt = 1440\u00a0min jest dłuższy niż "
    "typowy zakres 0–255,2\u00a0min, więc hydrogram policzono na 17 krokach "
    "pośrednich po 84,71\u00a0min, z opadem każdego kroku rozłożonym na nie równo, "
    "i odczytano w chwilach kroków: zachowuje objętość."
)


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _messages(response: Any) -> list[str]:
    assert response.status_code == 200, response.text
    return [notice["message"] for notice in response.json()["notices"]]


def test_a_catchment_above_the_scs_area_range_gets_the_notice_in_polish(
    log_records, client
):
    first = client.post(URL, json=LARGE)
    # The same computation again: a warning is not shown only once at its place
    again = client.post(URL, json=LARGE)

    for response in (first, again):
        assert response.status_code == 200
        assert {
            "level": "warning",
            "code": "outside_typical_range",
            "message": SCS_AREA,
        } in response.json()["notices"]
    # The server log keeps Hydrolog's warning, in English
    logged = [
        record["message"]
        for record in log_records()
        if record["kind"] == "app" and record["event"] == "py.warnings"
    ]
    scs = "scs: area_km2=100.0 is outside typical range [0.0, 52.0]"
    assert sum(scs in message for message in logged) == 2


def test_two_requests_at_once_keep_their_own_notices(client, monkeypatch):
    # Each request waits for the other at each of numba's compiler locks it enters,
    # so both collect while the other computes; the lock still serialises them
    meeting = threading.Barrier(2, timeout=30)
    lock = api.endpoints.hydrograph.global_compiler_lock

    class MeetingLock:
        def __enter__(self) -> None:
            meeting.wait()
            lock.__enter__()

        def __exit__(self, *exc_info: object) -> None:
            lock.__exit__(*exc_info)

    monkeypatch.setattr(api.endpoints.hydrograph, "global_compiler_lock", MeetingLock())

    def post(body: dict[str, Any]) -> Any:
        return client.post(URL, json=body)

    with ThreadPoolExecutor(max_workers=2) as pool:
        large, daily = pool.map(post, [LARGE, DAILY])

    assert _messages(large) == [NRCS_AREA, SCS_AREA]
    assert _messages(daily) == [DAILY_SUBSTEPS, DAILY_STEP]
    assert [notice["level"] for notice in daily.json()["notices"]] == [
        "info",
        "warning",
    ]
