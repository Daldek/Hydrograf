"""
The hand-off of a watershed or a network to Hydrolog's GUI (ADR-068, ADR-080).

``nogat-handoff/1`` is Nogat's envelope of the data handed between the GUIs of the
ecosystem (``schemas/nogat/handoff-1.schema.json``, a verbatim copy); its payload is
Hydrolog's ``hydrolog-network/1``. A watershed is one ``subcatchment`` (``Z1``) with its
``watershed`` in the keys of Hydrolog's ``WatershedParameters``, flowing to the outlet
``OUT``: the network that Hydrolog's „Hydrogram zlewni” writes and opens. The design
hydrograph of POST /api/generate-hydrograph adds the runoff and the rainfall the
computation used and its result, which Hydrolog recomputes and shows beside its own.
The values are the computation's own, never rounded, so the same version of Hydrolog
gives the same result; the provenance names where the inputs came from.

A network of POST /api/delineate-network (``build_network_handoff``) is its
subcatchments, reaches, junctions and outlet in one payload, without rainfall, time
step, result and the sections of the reaches, which the person gives in Hydrolog's
„Sieć i trasowanie”; ``node_provenance`` gives the origin of every node but the outlet.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from importlib.metadata import version
from typing import TYPE_CHECKING, Any, Final, Literal

from core.version import get_version

if TYPE_CHECKING:
    from core.network_delineation import (
        Network,
        NetworkJunction,
        NetworkReach,
        NetworkSubcatchment,
    )

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

# Hydrograf's morphometry, with the coefficients of the tc method (FAA's C, Kerby's N)
# and Lutz's Manning's n that the hydrograph adds -> the keys of Hydrolog's
# WatershedParameters, in their order. `source` and `crs` stay out: the provenance
# names the source.
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
    "runoff_coeff": "runoff_coeff",
    "retardance": "retardance",
    "overland_length_km": "overland_length_km",
    "overland_slope_m_per_m": "overland_slope_m_per_m",
    "length_to_centroid_km": "Lc_km",
    "manning_n": "manning_n",
    "urban_pct": "urban_pct",
    "forest_pct": "forest_pct",
    "flow_path_length_km": "flow_path_length_km",
    "flow_path_slope_m_per_m": "flow_path_slope_m_per_m",
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
        ``runoff_coeff`` or ``retardance`` when the method of tc used them and
        ``manning_n`` when Lutz's method estimated Nash's n and K.
    name : str
        Name of the watershed.
    cn : float, optional
        The CN the computation used in place of the morphometry's (the default CN of a
        watershed without land cover).

    Returns
    -------
    dict[str, Any]
        ``name`` and the known values of ``WatershedParameters``, among them the
        longest flow path and its slope and the overland segment (the inputs of tc);
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
    tc_method: str | None = None,
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
    tc_method : str, optional
        Method of the time of concentration of the ``scs`` model: Hydrolog computes
        tc from the watershed, so the runoff carries no ``tc_min``.
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
    if tc_method is not None:
        runoff["tc_method"] = tc_method
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


# The longest description of a node or a network that Hydrolog takes
# (hydrolog-network/1, $defs/description)
DESCRIPTION_MAX_CHARS: Final = 500
# How the length of a reach is measured: the difference of the flow distances of its
# ends (ADR-080, D10)
REACH_LENGTH_METHOD: Final = "flow_distance"
# The lines of the check length of a reach (bdot_streams)
REACH_VECTOR_SOURCE: Final = "bdot10k"
# A reach without a section is routed by Muskingum-Cunge once the person gives one
REACH_METHOD: Final = "muskingum-cunge"
# A reach of the minimum slope is a lag instead (ADR-080, D10a): Muskingum-Cunge
# finds no division of a flat reach that keeps its weights non-negative. The wave
# travels it at this celerity [m/s]
FLAT_REACH_METHOD: Final = "lag"
FLAT_REACH_CELERITY_M_PER_S: Final = 0.5
_SLOPE_WORDS: Final = {"nmt": "NMT", "minimum": "minimalny"}


def flat_reach_lag_min(length_km: float) -> int:
    """Return the lag of a flat reach: its length at 0.5 m/s, 1 min at least."""
    return max(1, round(length_km * 1000 / FLAT_REACH_CELERITY_M_PER_S / 60))


def build_network_handoff(
    network: "Network",
    names: Mapping[str, str],
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Return the hand-off ``nogat-handoff/1`` of a network (ADR-080, D14).

    Parameters
    ----------
    network : Network
        The delineated network (``core.network_delineation.delineate_network``).
    names : Mapping[str, str]
        The names of the points that have one, by the id of the point.
    created_at : datetime, optional
        When the hand-off is written (now).

    Returns
    -------
    dict[str, Any]
        The document: the payload ``hydrolog-network/1`` with every node in the order
        of the network (each after the nodes it receives) and a Polish description
        of each; subcatchments with the ``watershed`` of their morphometry (the area
        exact to the cell) and the ``curve-number`` runoff with Hydrolog's defaults,
        Muskingum-Cunge reaches with a length and a slope and no section (a reach of
        the minimum slope a lag of FLAT_REACH_CELERITY_M_PER_S), junctions
        and the outlet ``OUT``; no rainfall, time step or result. ``provenance``
        names A's snapped place, ``node_provenance`` the origin of every
        subcatchment, reach and junction.
    """
    moment = created_at or datetime.now(UTC)
    outlet = network.points[0]
    subcatchments = {item.subcatchment.id: item for item in network.subcatchments}
    reaches = {item.reach.id: item for item in network.reaches}
    junctions = {item.junction.id: item for item in network.junctions}
    (outlet_junction,) = [
        item.junction.id for item in network.junctions if item.junction.kind == "outlet"
    ]
    name = names.get(outlet.point_id) or watershed_name(
        outlet.latitude, outlet.longitude
    )
    # „Kaczawa, sieć (3 zlewnie)”: the count in parentheses reads as Polish, and the
    # subject names the hand-off's file, where a colon is not allowed
    subject = (
        f"{name}, sieć ({_count(len(subcatchments), 'zlewnia', 'zlewnie', 'zlewni')})"
    )
    nodes: list[dict[str, Any]] = []
    node_provenance: dict[str, dict[str, Any]] = {}
    for node_id in network.order:
        if node_id in subcatchments:
            nodes.append(_subcatchment_node(subcatchments[node_id], names))
            node_provenance[node_id] = {
                "watershed": _subcatchment_origin(subcatchments[node_id])
            }
        elif node_id in reaches:
            nodes.append(_reach_node(reaches[node_id]))
            node_provenance[node_id] = {"node": _reach_origin(reaches[node_id])}
        elif node_id in junctions:
            nodes.append(
                _junction_node(junctions[node_id], names, subcatchments, reaches)
            )
            node_provenance[node_id] = {"node": _junction_origin(junctions[node_id])}
        else:
            nodes.append({"id": node_id, "type": "outlet", "from": [outlet_junction]})
    description = (
        "Sieć zlewni do przekroju zamykającego "
        f"{_point_label(outlet.point_id, names)}, wyznaczona w Hydrografie: "
        f"{_count(len(subcatchments), 'zlewnia', 'zlewnie', 'zlewni')}, "
        f"{_count(len(reaches), 'odcinek', 'odcinki', 'odcinków')}, "
        f"{_count(len(junctions), 'węzeł', 'węzły', 'węzłów')}. Opad sieci i przekroje "
        "odcinków (n Manninga, szerokość) podaje się w Hydrologu."
    )
    return {
        "schema": HANDOFF_SCHEMA,
        "created_at": moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "producer": {"tool": PRODUCER, "version": get_version()},
        "subject": subject,
        "provenance": {
            "watershed": {
                "source": PRODUCER,
                "point": outlet.point_id,
                "latitude": outlet.latitude,
                "longitude": outlet.longitude,
                "threshold_m2": network.threshold_m2,
            }
        },
        "node_provenance": node_provenance,
        "payload": {
            "schema": PAYLOAD_SCHEMA,
            "name": subject,
            "description": _description(description),
            "nodes": nodes,
        },
    }


def _subcatchment_node(
    element: "NetworkSubcatchment", names: Mapping[str, str]
) -> dict[str, Any]:
    """Return a subcatchment of the payload: its watershed, the runoff and a text."""
    morphometry = element.watershed.morphometry
    title = _element_title(element, names)
    watershed = watershed_parameters(
        morphometry.model_dump(exclude_none=True) if morphometry is not None else {},
        title,
    )
    # Exact to the cell, so the subcatchments add up to A in Hydrolog too
    watershed["area_km2"] = element.area_km2
    return {
        "id": element.subcatchment.id,
        "type": "subcatchment",
        "watershed": watershed,
        "runoff": {"model": "curve-number"},
        "description": _description(f"{title}: {_area(element.area_km2)}"),
    }


def _element_title(element: "NetworkSubcatchment", names: Mapping[str, str]) -> str:
    """Say what an element is, in Polish: „Dopływ do ujścia przy P1 (Kamiennik)”.

    A headwater is named as a tributary: which branch of a confluence goes on as the
    main river follows the larger upstream area, not the river a person knows, and it
    changes nothing in the computation.
    """
    item = element.subcatchment
    if item.kind == "intermediate":
        return f"Przyrzecze odcinka {item.reach}"
    if item.point is None:
        return f"Dopływ powyżej {item.to}"
    point = _point_label(item.point, names)
    if item.at_mouth:
        return f"Dopływ do ujścia przy {point}"
    return f"Dopływ do punktu {point}"


def _subcatchment_origin(element: "NetworkSubcatchment") -> dict[str, Any]:
    """Where a subcatchment comes from: its kind, its point and reach, its outlet."""
    item = element.subcatchment
    origin: dict[str, Any] = {"source": PRODUCER, "element": item.kind}
    if item.point is not None:
        origin["point"] = item.point
    if item.reach is not None:
        origin["reach"] = item.reach
    if item.at_mouth:
        origin["at_mouth"] = True
    origin["latitude"] = element.watershed.outlet.latitude
    origin["longitude"] = element.watershed.outlet.longitude
    return origin


def _reach_node(item: "NetworkReach") -> dict[str, Any]:
    """Return a reach of the payload: its length and slope, no section, a text.

    A reach of the minimum slope is a lag of its length at
    FLAT_REACH_CELERITY_M_PER_S: Muskingum-Cunge cannot route a flat reach.
    """
    reach = item.reach
    text = (
        f"Odcinek od {reach.from_node} do {reach.to}: "
        f"{_decimal(item.length_km, 2)} km, spadek "
        f"{_decimal(item.slope_m_per_m * 1000, 2)} ‰ "
        f"({_SLOPE_WORDS[item.slope_method]})"
    )
    if item.slope_method == "minimum":
        lag_min = flat_reach_lag_min(item.length_km)
        return {
            "id": reach.id,
            "type": "reach",
            "method": FLAT_REACH_METHOD,
            "from": [reach.from_node],
            "lag_min": lag_min,
            "description": _description(
                f"{text}. Opóźnienie {lag_min} min (długość przy "
                f"{_decimal(FLAT_REACH_CELERITY_M_PER_S, 1)} m/s) zamiast "
                "Muskingum-Cunge, który nie trasuje odcinka bez spadku"
            ),
        }
    return {
        "id": reach.id,
        "type": "reach",
        "method": REACH_METHOD,
        "from": [reach.from_node],
        "length_km": item.length_km,
        "slope_m_per_m": item.slope_m_per_m,
        "description": _description(text),
    }


def _reach_origin(item: "NetworkReach") -> dict[str, Any]:
    """Where a reach's length and slope come from, with the NMT and the check length.

    A reach of the minimum slope says why it is a lag (``method_reason`` ``flat``)
    and at what celerity.
    """
    origin: dict[str, Any] = {
        "source": PRODUCER,
        "element": "reach",
        "length": REACH_LENGTH_METHOD,
        "slope": item.slope_method,
    }
    if item.slope_method == "minimum":
        origin["length_km"] = item.length_km
        origin["slope_m_per_m"] = item.slope_m_per_m
        origin["method"] = FLAT_REACH_METHOD
        origin["method_reason"] = "flat"
        origin["lag_celerity_m_per_s"] = FLAT_REACH_CELERITY_M_PER_S
    if item.upstream_elevation_m is not None:
        origin["upstream_elevation_m"] = item.upstream_elevation_m
    if item.downstream_elevation_m is not None:
        origin["downstream_elevation_m"] = item.downstream_elevation_m
    if item.vector_length_km is not None:
        origin["vector_length_km"] = item.vector_length_km
        origin["vector_source"] = REACH_VECTOR_SOURCE
    return origin


def _junction_node(
    item: "NetworkJunction",
    names: Mapping[str, str],
    subcatchments: Mapping[str, "NetworkSubcatchment"],
    reaches: Mapping[str, "NetworkReach"],
) -> dict[str, Any]:
    """Return a junction of the payload: its inflows and a text.

    A confluence names the points of the tributaries that enter it, the point of a
    headwater included, directly or by its reach: that is a tributary to the person too
    (_element_title).
    """
    junction = item.junction
    if junction.kind == "outlet":
        text = f"Przekrój zamykający {_point_label(junction.point or '', names)}"
    elif junction.kind == "point":
        text = f"Punkt {_point_label(junction.point or '', names)}"
    else:
        headwater_points = [
            point
            for node in junction.inflows
            if (point := _headwater_point(node, subcatchments, reaches)) is not None
        ]
        text = "Zbieg: " + ", ".join(
            f"dopływ {_point_label(point, names)}"
            for point in [*headwater_points, *junction.tributaries]
        )
    return {
        "id": junction.id,
        "type": "junction",
        "from": list(junction.inflows),
        "description": _description(text),
    }


def _headwater_point(
    node: str,
    subcatchments: Mapping[str, "NetworkSubcatchment"],
    reaches: Mapping[str, "NetworkReach"],
) -> str | None:
    """Return the point of a headwater an inflow of a junction brings, or None."""
    if node in reaches:
        node = reaches[node].reach.from_node
    element = subcatchments.get(node)
    if element is None or element.subcatchment.kind != "headwater":
        return None
    return element.subcatchment.point


def _junction_origin(item: "NetworkJunction") -> dict[str, Any]:
    """Where a junction comes from: its kind, its point and its place."""
    junction = item.junction
    origin: dict[str, Any] = {"source": PRODUCER, "element": junction.kind}
    if junction.point is not None:
        origin["point"] = junction.point
    origin["latitude"] = item.latitude
    origin["longitude"] = item.longitude
    return origin


def _point_label(point_id: str, names: Mapping[str, str]) -> str:
    """Name a point by its id and, when it has one, its name: „P1 (Kamiennik)”."""
    name = names.get(point_id)
    return f"{point_id} ({name})" if name else point_id


def _decimal(value: float, decimals: int) -> str:
    """Write a number with a decimal comma, as the interface does."""
    return f"{value:.{decimals}f}".replace(".", ",")


def _area(area_km2: float) -> str:
    """Write an area in km², with 4 decimals below 0.1 km² so that it is not 0."""
    return f"{_decimal(area_km2, 2 if area_km2 >= 0.1 else 4)} km²"


def _count(count: int, one: str, few: str, many: str) -> str:
    """Write a count with the Polish plural: 1 zlewnia, 3 zlewnie, 5 zlewni."""
    if count == 1:
        return f"{count} {one}"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return f"{count} {few}"
    return f"{count} {many}"


# Characters a description of Hydrolog refuses: the control characters but line feed
_CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]")


def _description(text: str) -> str:
    """Make a text one Hydrolog takes: no control character, at most 500 characters."""
    text = _CONTROL.sub(" ", text)
    if len(text) <= DESCRIPTION_MAX_CHARS:
        return text
    return text[: DESCRIPTION_MAX_CHARS - 1] + "…"
