"""The CLI of analyze_watershed refuses a time step that cannot cut the storm.

Hydrolog builds a hyetograph only of whole time steps (ADR-0046): the step must
divide the requested duration (used without PMAXTP data) and the PMAXTP duration
nearest to it (used with them). The script stops before any download, delineation
or PMAXTP call, through argparse (exit 2).
"""

import sys

import pytest

from scripts import analyze_watershed as script


@pytest.fixture
def runs(monkeypatch) -> list[script.AnalysisConfig]:
    """The configs analyze_watershed was called with; nothing is computed."""
    calls: list[script.AnalysisConfig] = []
    monkeypatch.setattr(script, "analyze_watershed", calls.append)
    return calls


def _main(monkeypatch, tmp_path, *options: str) -> None:
    argv = ["analyze_watershed", "--lat", "52.45", "--lon", "17.31"]
    monkeypatch.setattr(sys, "argv", [*argv, "-o", str(tmp_path), *options])
    script.main()


@pytest.mark.parametrize(
    ("options", "used", "suggested"),
    [
        # 7 min does not divide 60 min
        (("--duration", "60", "--timestep", "7"), "60 min", "--timestep 6"),
        # 10 min divides the requested 50 min, not the PMAXTP 45 min nearest to it
        (("--duration", "50", "--timestep", "10"), "45 min", "--timestep 5"),
        # 9 min divides the PMAXTP 45 min, not the requested 50 min
        (("--duration", "50", "--timestep", "9"), "50 min", "--timestep 5"),
        # a step longer than the storm is less than one whole step
        (("--duration", "60", "--timestep", "120"), "60 min", "--timestep 60"),
    ],
)
def test_step_that_does_not_divide_the_duration_is_refused(
    monkeypatch, tmp_path, capsys, runs, options, used, suggested
):
    with pytest.raises(SystemExit) as stop:
        _main(monkeypatch, tmp_path, *options)

    assert stop.value.code == 2
    assert runs == []
    error = capsys.readouterr().err
    assert f"Czas trwania opadu {used}" in error
    assert suggested in error


@pytest.mark.parametrize("timestep", ["0", "-5", "nan"])
def test_step_not_above_zero_is_refused(monkeypatch, tmp_path, runs, timestep):
    with pytest.raises(SystemExit) as stop:
        _main(monkeypatch, tmp_path, "--timestep", timestep)

    assert stop.value.code == 2
    assert runs == []


@pytest.mark.parametrize(
    ("options", "duration", "timestep"),
    [
        ((), 60, 5.0),
        (("--duration", "60", "--timestep", "10"), 60, 10.0),
        (("--duration", "50", "--timestep", "5"), 50, 5.0),
        (("--duration", "90", "--timestep", "7.5"), 90, 7.5),
    ],
)
def test_step_that_divides_the_duration_runs_the_analysis(
    monkeypatch, tmp_path, runs, options, duration, timestep
):
    _main(monkeypatch, tmp_path, *options)

    [config] = runs
    assert config.duration_min == duration
    assert config.timestep_min == timestep
