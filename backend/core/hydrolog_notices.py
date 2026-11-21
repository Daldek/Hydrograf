"""Hydrolog's warnings of a hydrograph as the notices of its response (E5b-06).

Hydrolog reports an observation of a computation, such as a value outside the typical
range of a method, with ``warnings.warn``, which reached only the server log.
:func:`install` puts one hook in front of ``warnings.showwarning`` for the process: it
appends each warning of Hydrolog to the list of the context that issues it, when
:func:`collect` gave the context one, and passes every warning on to the hook it
replaced, so the log keeps them. FastAPI runs a sync endpoint in its threadpool in a
copy of the request's context, so requests computed at the same time collect into
lists of their own. :func:`notices` words the collected warnings in Polish.

Hydrolog's warning class lives in its private module ``hydrolog._warnings``, and
Hydrograf uses Hydrolog only through its public API, so a warning of Hydrolog is told
by its traits: a ``Warning`` with ``details`` and a ``code()`` that the public registry
``hydrolog.catalog.NOTICES`` lists.
"""

import math
import warnings
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Final, TextIO

from hydrolog.catalog import NOTICES

from models.schemas import HydrographNotice

type ShowWarning = Callable[
    [Warning | str, type[Warning], str, int, TextIO | None, str | None], None
]

# The warnings of Hydrolog with their codes that the context collects; None outside
# the computation of a hydrograph
_COLLECTED: ContextVar[list[tuple[str, Warning]] | None] = ContextVar(
    "hydrolog_warnings", default=None
)

# The methods and models whose typical ranges a hydrograph checks (details.method), as
# the panel's sections „Hietogram” and „Hydrogram” name them
_METHODS: Final[Mapping[str, str]] = {
    "kirpich": "Czas koncentracji (Kirpich)",
    "nrcs": "Czas koncentracji (NRCS)",
    "giandotti": "Czas koncentracji (Giandotti)",
    "faa": "Czas koncentracji (FAA)",
    "kerby": "Czas koncentracji (Kerby)",
    "kerby_kirpich": "Czas koncentracji (Kerby-Kirpich)",
    "scs_cn_amc": "Przeliczenie CN na AMC I lub III",
    "scs_cn_runoff": "Opad efektywny SCS-CN",
    "scs": "Hydrogram jednostkowy SCS",
    "snyder": "Hydrogram jednostkowy Snydera",
    "nash": "Hydrogram jednostkowy Nasha",
    "lutz": "Estymacja Nasha metodą Lutza",
    "nash_urban_regression": "Estymacja Nasha regresją urbanizacyjną",
}

# The inputs the checked values come from (details.field): the name, the unit and the
# factor from Hydrolog's unit to it (slopes in % as the panel shows them)
_INPUTS: Final[Mapping[str, tuple[str, str, float]]] = {
    "area_km2": ("powierzchnia zlewni", "km²", 1.0),
    "cn": ("CN (AMC II)", "", 1.0),
    "flow_path_length_km": ("najdłuższa droga spływu", "km", 1.0),
    "flow_path_slope_m_per_m": ("spadek najdłuższej drogi spływu", "%", 100.0),
    "flow_path_equal_area_slope_m_per_m": (
        "spadek wyrównany najdłuższej drogi spływu",
        "%",
        100.0,
    ),
    "overland_length_km": ("długość spływu powierzchniowego", "km", 1.0),
    "overland_slope_m_per_m": ("spadek spływu powierzchniowego", "%", 100.0),
    "runoff_coeff": ("współczynnik spływu C", "", 1.0),
    "retardance": ("współczynnik oporu N", "", 1.0),
    "n": ("liczba zbiorników N", "", 1.0),
    "k_min": ("stała K", "min", 1.0),
    "ct": ("współczynnik Ct", "", 1.0),
    "cp": ("współczynnik Cp", "", 1.0),
    "timestep_min": ("krok czasowy Δt", "min", 1.0),
    "urban_fraction": ("wskaźnik urbanizacji U", "%", 100.0),
}

# An input a method checks other than the value _INPUTS names: the runoff of SCS-CN
# takes the CN after the AMC conversion, the CN used in the computation
_METHOD_INPUTS: Final[Mapping[tuple[str, str], tuple[str, str, float]]] = {
    ("scs_cn_runoff", "cn"): ("CN użyty w obliczeniu", "", 1.0),
}

# The range each code of a value outside a range names and the end of its Polish text,
# after „{method}: {input} = {value} – powyżej/poniżej {range} {bounds}”, as Hydrolog's
# English templates of the codes say it: `outside_applicability` (Nogat CMP-3.3,
# Hydrolog ADR-0070, `outside_typical_range` up to Hydrolog 0.8.x) for the
# applicability range of a formula, `outside_unverified_range` for a typical range
# without a published source
_RANGE_CODES: Final[Mapping[str, tuple[str, str]]] = {
    "outside_applicability": (
        "zakresu stosowania",
        ". Wynik może być niewiarygodny.",
    ),
    "outside_unverified_range": (
        "typowego zakresu",
        ", który nie ma opublikowanego źródła i czeka na weryfikację. Wynik może być "
        "niewiarygodny.",
    ),
}


class _Hook:
    """The ``warnings.showwarning`` of the process that collects Hydrolog's warnings.

    Parameters
    ----------
    passed_to : ShowWarning
        The ``warnings.showwarning`` it replaced, which every warning still reaches.
    """

    def __init__(self, passed_to: ShowWarning) -> None:
        self.passed_to = passed_to

    def __call__(
        self,
        message: Warning | str,
        category: type[Warning],
        filename: str,
        lineno: int,
        file: TextIO | None = None,
        line: str | None = None,
    ) -> None:
        """Append a warning of Hydrolog to the context's list, then pass it on."""
        collected = _COLLECTED.get()
        if collected is not None and isinstance(message, Warning):
            code = _hydrolog_code(message)
            if code is not None:
                collected.append((code, message))
        self.passed_to(message, category, filename, lineno, file, line)


def install() -> None:
    """Collect Hydrolog's warnings from now on; call it after the log has started.

    The log's ``logging.captureWarnings`` replaces ``warnings.showwarning`` without
    calling the one it found, so the hook goes in front of it. Every ``UserWarning``,
    which Hydrolog's warnings are, then reaches the hook each time it is issued: by
    default a warning is shown only the first time at its place, so a request that
    computes what an earlier one did would get no notice. A call while the hook is in
    place only sets the filter again.
    """
    warnings.simplefilter("always", UserWarning)
    if not isinstance(warnings.showwarning, _Hook):
        warnings.showwarning = _Hook(warnings.showwarning)


@contextmanager
def collect() -> Iterator[list[tuple[str, Warning]]]:
    """Collect the warnings of Hydrolog that this context issues inside the block.

    Yields
    ------
    list of (str, Warning)
        Each warning with its code, in the order of issue, filled while the block runs.
    """
    collected: list[tuple[str, Warning]] = []
    token = _COLLECTED.set(collected)
    try:
        yield collected
    finally:
        _COLLECTED.reset(token)


def notices(collected: Iterable[tuple[str, Warning]]) -> list[HydrographNotice]:
    """Return the notices of collected warnings of Hydrolog, identical ones once.

    Parameters
    ----------
    collected : iterable of (str, Warning)
        The warnings with their codes, as :func:`collect` yields them.

    Returns
    -------
    list of HydrographNotice
        The level of the code in ``NOTICES``, the code and Hydrograf's Polish text of
        the code filled from the warning's details; Hydrolog's English message where
        Hydrograf has no text for the code or cannot fill it.
    """
    worded: dict[tuple[str, str], HydrographNotice] = {}
    for code, warning in collected:
        details = getattr(warning, "details", {})
        message = _polish(code, details) or str(warning)
        worded.setdefault(
            (code, message),
            HydrographNotice(level=NOTICES[code].level, code=code, message=message),
        )
    return list(worded.values())


def _hydrolog_code(warning: Warning) -> str | None:
    """Return the notice code of a warning of Hydrolog, None for any other warning."""
    code = getattr(warning, "code", None)
    if not callable(code) or not isinstance(getattr(warning, "details", None), Mapping):
        return None
    try:
        value = code()
    # Another library's warning may have a code() of its own: never fail its issuer
    except Exception:
        return None
    return value if isinstance(value, str) and value in NOTICES else None


def _polish(code: str, details: Mapping[str, Any]) -> str | None:
    """Return the Polish text of a notice, None without one for its code or details."""
    if code == "uh_substeps":
        return _substeps(details)
    worded = _RANGE_CODES.get(code)
    method, field = str(details.get("method")), str(details.get("field"))
    subject = _METHODS.get(method)
    named = _METHOD_INPUTS.get((method, field)) or _INPUTS.get(field)
    numbers = [
        float(x)
        for x in (details.get("value"), details.get("minimum"), details.get("maximum"))
        if isinstance(x, int | float) and math.isfinite(x)
    ]
    if worded is None or subject is None or named is None or len(numbers) != 3:
        return None
    range_name, tail = worded
    name, unit, factor = named
    value, minimum, maximum = (x * factor for x in numbers)
    if value > maximum:
        where, crossed = "powyżej", maximum
    elif value < minimum:
        where, crossed = "poniżej", minimum
    else:
        return None
    units = f"\u00a0{unit}" if unit else ""
    return (
        f"{subject}: {name} = {_value(value, crossed)}{units} – {where} {range_name} "
        f"{_number(minimum)}–{_number(maximum)}{units}{tail}"
    )


def _substeps(details: Mapping[str, Any]) -> str | None:
    """Return the Polish text of ``uh_substeps``, None without its details.

    Hydrolog 0.8.1 computes the SCS unit hydrograph of a step beyond its typical range
    on sub-steps inside it, so that it keeps its volume (Hydrolog's E5b-07).
    """
    numbers = [
        float(x)
        for x in (
            details.get(key) for key in ("timestep_min", "maximum_min", "substep_min")
        )
        if isinstance(x, int | float) and math.isfinite(x)
    ]
    substeps = details.get("substeps")
    if not isinstance(substeps, int) or len(numbers) != 3:
        return None
    step, maximum, substep = numbers
    return (
        f"{_METHODS['scs']}: krok czasowy Δt = {_number(step)}\u00a0min jest dłuższy "
        f"niż typowy zakres 0–{_number(maximum)}\u00a0min, więc hydrogram policzono na "
        f"{substeps} krokach pośrednich po {_number(substep)}\u00a0min, z opadem "
        "każdego kroku rozłożonym na nie równo, i odczytano w chwilach kroków: "
        "zachowuje objętość."
    )


def _value(value: float, crossed: float) -> str:
    """Write a value with the digits it takes to differ from the bound it crosses."""
    for digits in range(4, 16):
        text = _number(value, digits)
        if text != _number(crossed, digits):
            break
    return text


def _number(value: float, digits: int = 4) -> str:
    """Write a number as Polish text does, rounded to ``digits`` significant digits.

    No trailing zeros, a decimal comma and, from 10 000 up, a no-break space between
    the thousands.
    """
    if value == 0:
        return "0"
    decimals = max(0, digits - 1 - math.floor(math.log10(abs(value))))
    text = f"{value:,.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    whole, _, fraction = text.partition(".")
    whole = whole.replace(",", "\u00a0" if abs(value) >= 10_000 else "")
    return f"{whole},{fraction}" if fraction else whole
