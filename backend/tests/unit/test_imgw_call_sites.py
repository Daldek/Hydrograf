"""The two IMGWTools call sites of Hydrograf, through the real library, offline.

``fetch_pmaxtp`` documents three errors (server, response, point outside the PMAXTP
grid). The call sites report those as "no precipitation data"; every other exception is
a bug or a change of IMGWTools and has to reach the caller.
"""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from scripts.analyze_watershed import AnalysisConfig, fetch_precipitation_imgw
from scripts.preprocess_precipitation import (
    DURATION_MINUTES,
    DURATIONS,
    PROBABILITIES,
    fetch_pmaxtp_for_point,
)

Serve = Callable[[Callable[[httpx.Request], httpx.Response]], None]
Body = Callable[..., dict[str, Any]]

# What each documented error of fetch_pmaxtp looks like on the wire.
IMGW_FAILURES = {
    "connection": httpx.Response(503, text="maintenance"),
    "data": httpx.Response(200, text="<html>not json</html>"),
    "validation": httpx.Response(
        200, json={"data": {}, "error": "Brak pliku, pradopodobnie poza obszarem PL"}
    ),
}


def _answer(response: httpx.Response) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: response


def _boom(request: httpx.Request) -> httpx.Response:
    raise RuntimeError("not an IMGWTools error")


@pytest.fixture
def config(tmp_path) -> AnalysisConfig:
    return AnalysisConfig(
        latitude=52.4,
        longitude=17.3,
        duration_min=100,
        probability=1.0,
        output_dir=tmp_path / "results",
        data_dir=tmp_path / "data",
    )


class TestAnalyzeWatershedPrecipitation:
    def test_reads_the_nearest_duration(
        self, serve_imgw: Serve, pmaxtp_body: Body, config: AnalysisConfig
    ) -> None:
        serve_imgw(
            _answer(httpx.Response(200, json=pmaxtp_body(DURATION_MINUTES, [1, 2])))
        )

        result = fetch_precipitation_imgw(config)

        assert result is not None
        assert result["duration_min"] == 90  # 100 min is not offered; 90 is the nearest
        assert result["probability_percent"] == 1
        assert result["precipitation_mm"] == pytest.approx(
            9.01
        )  # ks of 90 min, p = 1 %
        assert result["precipitation_sg_mm"] == pytest.approx(10.01)
        assert result["precipitation_rb_mm"] == 0.5

    def test_falls_back_to_the_nearest_probability(
        self, serve_imgw: Serve, pmaxtp_body: Body, config: AnalysisConfig
    ) -> None:
        serve_imgw(_answer(httpx.Response(200, json=pmaxtp_body([90], [2, 5]))))
        config.probability = 3.0

        result = fetch_precipitation_imgw(config)

        assert result is not None
        assert result["probability_percent"] == 2

    @pytest.mark.parametrize("failure", IMGW_FAILURES)
    def test_documented_imgw_errors_mean_no_precipitation(
        self, serve_imgw: Serve, config: AnalysisConfig, failure: str
    ) -> None:
        serve_imgw(_answer(IMGW_FAILURES[failure]))

        assert fetch_precipitation_imgw(config) is None

    def test_any_other_error_surfaces(
        self, serve_imgw: Serve, config: AnalysisConfig
    ) -> None:
        serve_imgw(_boom)

        with pytest.raises(RuntimeError, match="not an IMGWTools error"):
            fetch_precipitation_imgw(config)

    def test_a_changed_imgwtools_signature_surfaces(
        self, monkeypatch: pytest.MonkeyPatch, config: AnalysisConfig
    ) -> None:
        def fetch_pmaxtp(lat: float, lon: float) -> None:
            raise AssertionError("unreachable: the call must fail on the keywords")

        monkeypatch.setattr("imgwtools.fetch_pmaxtp", fetch_pmaxtp)

        with pytest.raises(TypeError, match="latitude"):
            fetch_precipitation_imgw(config)


class TestPreprocessPrecipitation:
    async def test_reads_every_scenario(
        self, serve_imgw: Serve, pmaxtp_body: Body
    ) -> None:
        serve_imgw(
            _answer(
                httpx.Response(200, json=pmaxtp_body(DURATION_MINUTES, PROBABILITIES))
            )
        )

        scenarios = await fetch_pmaxtp_for_point(52.4, 17.3, delay_s=0)

        assert len(scenarios) == len(DURATIONS) * len(PROBABILITIES) == 432
        assert scenarios[("1h", 1)] == pytest.approx(6.01)
        assert scenarios[("72h", 98.5)] == pytest.approx(432.985)

    @pytest.mark.parametrize("failure", IMGW_FAILURES)
    async def test_documented_imgw_errors_skip_the_point(
        self, serve_imgw: Serve, failure: str
    ) -> None:
        serve_imgw(_answer(IMGW_FAILURES[failure]))

        assert await fetch_pmaxtp_for_point(52.4, 17.3, delay_s=0) == {}

    async def test_any_other_error_surfaces(self, serve_imgw: Serve) -> None:
        serve_imgw(_boom)

        with pytest.raises(RuntimeError, match="not an IMGWTools error"):
            await fetch_pmaxtp_for_point(52.4, 17.3, delay_s=0)

    async def test_a_changed_imgwtools_signature_surfaces(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fetch_pmaxtp(lat: float, lon: float) -> None:
            raise AssertionError("unreachable: the call must fail on the keywords")

        monkeypatch.setattr("imgwtools.fetch_pmaxtp", fetch_pmaxtp)

        with pytest.raises(TypeError, match="latitude"):
            await fetch_pmaxtp_for_point(52.4, 17.3, delay_s=0)
