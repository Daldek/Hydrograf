"""
The hand-off of a watershed to Hydrolog's GUI (ADR-068).

``nogat-handoff/1`` is Nogat's envelope of the data handed between the GUIs of the
ecosystem (``schemas/nogat/handoff-1.schema.json``, a verbatim copy); its payload is
Hydrolog's ``hydrolog-network/1``. A watershed is one ``subcatchment`` (``Z1``) with its
``watershed`` in the keys of Hydrolog's ``WatershedParameters``, flowing to the outlet
``OUT``: the network that Hydrolog's „Hydrogram zlewni” writes and opens. The design
hydrograph of POST /api/generate-hydrograph adds the runoff and the rainfall the
computation used and its result, which Hydrolog recomputes and shows beside its own.
The values are the computation's own, never rounded, so the same version of Hydrolog
gives the same result; the provenance names where the inputs came from.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from importlib.metadata import version
from typing import Any, Final, Literal

from core.version import get_version

HANDOFF_SCHEMA: Final = "nogat-handoff/1"
PAYLOAD_SCHEMA: Final = "hydrolog-network/1"
PRODUCER: Final = "hydrograf"

# The ids of Hydrogram zlewni's subcatchment and outlet in Hydrolog's own hand-offs
SUBCATCHMENT_ID: Final = "Z1"
OUTLET_ID: Final = "OUT"

# What computes the result of a hand-off (`result.command`)
HYDROGRAPH_COMMAND: Final = "POST /api/generate-hydrograph"

# The method of fetch_pmaxtp (its default) that filled precipitation_data
PMAXTP_METHOD: Final = "POT"

# Hydrograf's morphometry, with Lutz's Manning's n that the hydrograph adds -> the keys
# of Hydrolog's WatershedParameters, in their order. `source` and `crs` stay out: the
# provenance names the source.
_WATERSHED_KEYS: Final = {
    "area_km2": "area_km2",
    "perimeter_km": "perimeter_km",
    "length_km": "length_km",
    "elevation_min_m": "elevation_min_m",
    "elevation_max_m": "elevation_max_m",
    "elevation_mean_m": "elevation_mean_m",
    "mean_slope_m_per_m": "mean_slope_m_per_m",
    "channel_length_km": "channel_length_km",
    "channel_slope_m_per_m": "channel_slope_m_per_m",
    "cn": "cn",
    "length_to_centroid_km": "Lc_km",
    "manning_n": "manning_n",
    "urban_pct": "urban_pct",
    "forest_pct": "forest_pct",
}


@cache
def hydrolog_version() -> str:
    """Return the version of the installed Hydrolog, which computes the hydrographs.

    Returns
    -------
    str
        The PEP 440 version of the distribution ``hydrolog``.
    """
    return version("hydrolog")


def watershed_name(latitude: float, longitude: float) -> str:
    """Return the name of a watershed after its outlet, as the hand-off gives it.

    Parameters
    ----------
    latitude, longitude : float
        Outlet in WGS84 [°].

    Returns
    -------
    str
        For example ``"Zlewnia 51,01679° N, 15,88923° E"``: five decimals (about a
        metre) and a decimal comma, like the coordinates of the interface.
    """

    def degrees(value: float, positive: str, negative: str) -> str:
        hemisphere = positive if value >= 0 else negative
        return f"{abs(value):.5f}".replace(".", ",") + f"° {hemisphere}"

    return f"Zlewnia {degrees(latitude, 'N', 'S')}, {degrees(longitude, 'E', 'W')}"


def watershed_parameters(
    morphometry: Mapping[str, Any], name: str, cn: float | None = None
) -> dict[str, Any]:
    """Return the ``watershed`` of the subcatchment: the morphometry in Hydrolog's keys.

    Parameters
    ----------
    morphometry : Mapping[str, Any]
        Hydrograf's morphometry (the fields of ``MorphometricParameters``), with
        ``manning_n`` when Lutz's method estimated Nash's n and K.
    name : str
        Name of the watershed.
    cn : float, optional
        The CN the computation used in place of the morphometry's (the default CN of a
        watershed without land cover).

    Returns
    -------
    dict[str, Any]
        ``name`` and the known values of ``WatershedParameters``;
        ``length_to_centroid_km`` becomes ``Lc_km``. The other fields of the
        morphometry (shape and relief indices, the hydraulic length, the
        imperviousness) have no key in Hydrolog's watershed, and ``source`` and
        ``crs`` are left to the provenance.
    """
    parameters: dict[str, Any] = {"name": name}
    for key, target in _WATERSHED_KEYS.items():
        value = cn if key == "cn" and cn is not None else morphometry.get(key)
        if value is not None:
            parameters[target] = value
    return parameters


def delineated_origin(
    latitude: float, longitude: float, changed: Sequence[str] = ()
) -> dict[str, Any]:
    """Return the provenance of a watershed Hydrograf delineated.

    Parameters
    ----------
    latitude, longitude : float
        Outlet of the watershed in WGS84 [°].
    changed : Sequence[str], optional
        Fields of the morphometry the person changed after the delineation (the
        advanced mode).

    Returns
    -------
    dict[str, Any]
        ``source`` ``"hydrograf"``, the outlet and, when the person changed fields,
        ``changed``: their keys in the watershed of the hand-off.
    """
    origin: dict[str, Any] = {
        "source": PRODUCER,
        "latitude": latitude,
        "longitude": longitude,
    }
    if changed:
        origin["changed"] = [_WATERSHED_KEYS.get(name, name) for name in changed]
    return origin


def given_origin() -> dict[str, Any]:
    """Return the provenance of a morphometry a request gave without its delineation.

    Returns
    -------
    dict[str, Any]
        ``{"source": "user"}``: the values of the person or program that sent them.
    """
    return {"source": "user"}


def design_storm(
    hietogram_type: str,
    total_mm: float,
    duration_min: float,
    *,
    alpha: float | None = None,
    beta: float | None = None,
    peak_position: float | None = None,
) -> dict[str, Any]:
    """Return the ``rainfall`` of a design storm: a depth in the shape of a hyetograph.

    Parameters
    ----------
    hietogram_type : str
        ``"beta"``, ``"block"`` or ``"euler_ii"``.
    total_mm : float
        Depth [mm].
    duration_min : float
        Duration [min].
    alpha, beta : float, optional
        Parameters of the Beta hyetograph.
    peak_position : float, optional
        Relative position of the peak of the Euler II hyetograph.

    Returns
    -------
    dict[str, Any]
        The rainfall of kind ``design``, with the shape parameters that are given.
    """
    rainfall: dict[str, Any] = {
        "kind": "design",
        "hietogram_type": hietogram_type,
        "total_mm": float(total_mm),
        "duration_min": float(duration_min),
    }
    shape = {"alpha": alpha, "beta": beta, "peak_position": peak_position}
    rainfall.update({key: value for key, value in shape.items() if value is not None})
    return rainfall


def rainfall_series(depths_mm: Sequence[float], timestep_min: float) -> dict[str, Any]:
    """Return the ``rainfall`` of a series: the depth of every time step.

    Parameters
    ----------
    depths_mm : Sequence[float]
        Depth of each step [mm].
    timestep_min : float
        Length of a step [min].

    Returns
    -------
    dict[str, Any]
        The rainfall of kind ``series``.
    """
    return {
        "kind": "series",
        "depths_mm": [float(depth) for depth in depths_mm],
        "timestep_min": float(timestep_min),
    }


def pmaxtp_origin(
    probability_percent: float,
    duration_min: float,
    latitude: float,
    longitude: float,
    interpolation: Literal["thiessen", "idw"],
    areal_reduction_factor: float | None = None,
) -> dict[str, Any]:
    """Return the provenance of a PMAXTP depth Hydrograf took from its grid.

    Parameters
    ----------
    probability_percent : float
        Exceedance probability [%].
    duration_min : float
        Duration [min].
    latitude, longitude : float
        The point of the request in WGS84 [°] (the click).
    interpolation : {"thiessen", "idw"}
        ``"thiessen"``: the depth is the watershed mean over the Thiessen polygons of
        the points of the grid of ``precipitation_data`` (ADR-069); ``"idw"``: the
        inverse distance weighting at the point of its four nearest points.
    areal_reduction_factor : float or None, optional
        The user's areal reduction factor the depth was multiplied by; None when the
        depth was not reduced.

    Returns
    -------
    dict[str, Any]
        ``source`` ``"pmaxtp"`` with its method, probability, duration, point and
        interpolation, and ``areal_reduction_factor`` when the user gave one (the
        rainfall's ``total_mm`` is then the reduced depth).
    """
    origin: dict[str, Any] = {
        "source": "pmaxtp",
        "method": PMAXTP_METHOD,
        "probability_percent": probability_percent,
        "duration_min": duration_min,
        "latitude": latitude,
        "longitude": longitude,
        "interpolation": interpolation,
    }
    if areal_reduction_factor is not None:
        origin["areal_reduction_factor"] = areal_reduction_factor
    return origin


def curve_number_runoff(
    uh_model: str,
    amc: str,
    *,
    tc_min: float | None = None,
    nash_n: float | None = None,
    nash_k_min: float | None = None,
    snyder_length_km: float | None = None,
    snyder_centroid_length_km: float | None = None,
    snyder_ct: float | None = None,
    snyder_cp: float | None = None,
) -> dict[str, Any]:
    """Return the ``runoff`` of the subcatchment: SCS-CN and a unit hydrograph.

    Parameters
    ----------
    uh_model : str
        ``"scs"``, ``"nash"`` or ``"snyder"``.
    amc : str
        Antecedent moisture condition, ``"I"``, ``"II"`` or ``"III"``.
    tc_min : float, optional
        Time of concentration [min] of the ``scs`` model.
    nash_n, nash_k_min : float, optional
        Nash's n and K [min].
    snyder_length_km, snyder_centroid_length_km, snyder_ct, snyder_cp : float, optional
        Snyder's L and Lc [km], Ct and Cp.

    Returns
    -------
    dict[str, Any]
        The options of ``hydrograph generate`` in Hydrolog's order; the default initial
        abstraction ratio (0.2) is left out.
    """
    runoff: dict[str, Any] = {"model": "curve-number"}
    if tc_min is not None:
        runoff["tc_min"] = float(tc_min)
    runoff["amc"] = amc
    runoff["uh_model"] = uh_model
    options = {
        "nash_n": nash_n,
        "nash_k_min": nash_k_min,
        "snyder_length_km": snyder_length_km,
        "snyder_centroid_length_km": snyder_centroid_length_km,
        "snyder_ct": snyder_ct,
        "snyder_cp": snyder_cp,
    }
    runoff.update(
        {key: float(value) for key, value in options.items() if value is not None}
    )
    return runoff


def hydrograph_result(
    peak_discharge_m3s: float, time_to_peak_min: float, total_volume_m3: float
) -> dict[str, Any]:
    """Return the ``result`` of a hand-off: Hydrograf's hydrograph, for comparison.

    Parameters
    ----------
    peak_discharge_m3s : float
        Peak discharge [m3/s].
    time_to_peak_min : float
        Time to the peak [min].
    total_volume_m3 : float
        Volume of the hydrograph [m3].

    Returns
    -------
    dict[str, Any]
        The endpoint that computed it, Hydrolog and its version, and the three values.
    """
    return {
        "command": HYDROGRAPH_COMMAND,
        "computed_with": {"tool": "hydrolog", "version": hydrolog_version()},
        "peak_discharge_m3s": float(peak_discharge_m3s),
        "time_to_peak_min": float(time_to_peak_min),
        "total_volume_m3": float(total_volume_m3),
    }


@dataclass(frozen=True)
class DesignHydrograph:
    """What the design hydrograph of a watershed adds to its hand-off.

    Attributes
    ----------
    timestep_min : float
        Time step of the computation [min], the ``timestep_min`` of the network.
    runoff : dict[str, Any]
        The runoff of the subcatchment (``curve_number_runoff``).
    rainfall : dict[str, Any]
        The rainfall of the subcatchment (``design_storm`` or ``rainfall_series``).
    provenance : dict[str, dict[str, Any]]
        Where the rainfall and the derived runoff parameters came from (``rainfall``,
        ``runoff``).
    result : dict[str, Any]
        Hydrograf's result (``hydrograph_result``).
    """

    timestep_min: float
    runoff: dict[str, Any]
    rainfall: dict[str, Any]
    provenance: dict[str, dict[str, Any]]
    result: dict[str, Any]


def build_handoff(
    *,
    name: str,
    watershed: dict[str, Any],
    watershed_origin: dict[str, Any],
    hydrograph: DesignHydrograph | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Return the hand-off ``nogat-handoff/1`` of a watershed.

    Parameters
    ----------
    name : str
        Name of the watershed: the subject and the name of the network.
    watershed : dict[str, Any]
        The watershed of the subcatchment (``watershed_parameters``).
    watershed_origin : dict[str, Any]
        Its provenance (``delineated_origin`` or ``given_origin``).
    hydrograph : DesignHydrograph, optional
        The design hydrograph computed for the watershed. Without it the subcatchment
        has the SCS-CN runoff with Hydrolog's defaults and no rainfall, and the
        hand-off has no result.
    created_at : datetime, optional
        When the hand-off is written (now).

    Returns
    -------
    dict[str, Any]
        The document: Hydrograf and its version as the producer, the payload
        ``hydrolog-network/1`` of the subcatchment and its outlet, the provenance and,
        with the hydrograph, its result.
    """
    moment = created_at or datetime.now(UTC)
    subcatchment: dict[str, Any] = {
        "id": SUBCATCHMENT_ID,
        "type": "subcatchment",
        "watershed": watershed,
        "runoff": hydrograph.runoff if hydrograph else {"model": "curve-number"},
    }
    payload: dict[str, Any] = {"schema": PAYLOAD_SCHEMA, "name": name}
    provenance: dict[str, dict[str, Any]] = {"watershed": watershed_origin}
    if hydrograph:
        subcatchment["rainfall"] = hydrograph.rainfall
        payload["timestep_min"] = float(hydrograph.timestep_min)
        provenance.update(hydrograph.provenance)
    payload["nodes"] = [
        subcatchment,
        {"id": OUTLET_ID, "type": "outlet", "from": [SUBCATCHMENT_ID]},
    ]
    document: dict[str, Any] = {
        "schema": HANDOFF_SCHEMA,
        "created_at": moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "producer": {"tool": PRODUCER, "version": get_version()},
        "subject": name,
        "provenance": provenance,
        "payload": payload,
    }
    if hydrograph:
        document["result"] = hydrograph.result
    return document
