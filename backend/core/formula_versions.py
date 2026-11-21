"""The versions of Hydrolog's formulas that a result of Hydrograf depends on.

Nogat's computation standard (CMP-2.8): every result a project stores or exports
carries the ``formula_version`` of each Tier A formula it depends on, so that the
results of a formula found defective can be found again. Hydrolog declares each of
its formulas by a spec (``hydrolog.nogat_formulas.FormulaSpec``) with a
``formula_version`` it increments with every change of the formula's results
(Hydrolog ADR-0050), and a library caller reads the version from the spec
(``hydrolog.time.concentration.KIRPICH.formula_version``). Hydrograf computes with
Hydrolog's classes, not its commands, so the specs of each step are named here:
a result carries ``{spec name: formula_version}`` of the steps it ran, the shape
of the ``formula_versions`` of Hydrolog's envelope ``hydrolog-result/1``.
"""

from collections.abc import Iterable, Mapping
from typing import Final

from hydrolog.morphometry.profile import EQUAL_AREA_SLOPE
from hydrolog.nogat_formulas import FormulaSpec
from hydrolog.precipitation import hietogram, interpolation
from hydrolog.runoff import (
    cn_lookup,
    convolution,
    nash_iuh,
    scs_cn,
    snyder_uh,
    unit_hydrograph,
)
from hydrolog.time import concentration

# The design hyetographs by hietogram_type
HYETOGRAPHS: Final[Mapping[str, FormulaSpec]] = {
    "beta": hietogram.BETA,
    "block": hietogram.BLOCK,
    "euler_ii": hietogram.EULER_II,
}

# The weightings of the PMAXTP grid by interpolation (core.precipitation)
AREAL_DEPTHS: Final[Mapping[str, FormulaSpec]] = {
    "thiessen": interpolation.THIESSEN,
    "idw": interpolation.IDW,
}

# The methods of the time of concentration by tc_method
CONCENTRATION_TIMES: Final[Mapping[str, FormulaSpec]] = {
    "kirpich": concentration.KIRPICH,
    "nrcs": concentration.NRCS,
    "giandotti": concentration.GIANDOTTI,
    "faa": concentration.FAA,
    "kerby": concentration.KERBY,
    "kerby_kirpich": concentration.KERBY_KIRPICH,
}

# The CN of a soil-cover complex from the TR-55 table (core.cn_tables)
TR55_CN: Final = cn_lookup.TR55_CN

# The equal-area slope of the profile of the longest flow path (Lutz's Jg)
FLOW_PATH_EQUAL_AREA_SLOPE: Final = EQUAL_AREA_SLOPE


def formula_versions(specs: Iterable[FormulaSpec]) -> dict[str, int]:
    """Return the ``formula_version`` of each spec by its name, sorted by name.

    Parameters
    ----------
    specs : Iterable[FormulaSpec]
        Hydrolog's specs of the formulas a result depends on.

    Returns
    -------
    dict[str, int]
        Spec name to ``formula_version``, as Hydrolog's envelope gives them.
    """
    return dict(sorted((spec.name, spec.formula_version) for spec in specs))


def hydrograph_specs(
    *,
    hietogram_type: str | None,
    interpolation_method: str | None,
    tc_method: str | None,
    uh_model: str,
    nash_estimation: str | None,
    amc: str,
) -> list[FormulaSpec]:
    """Return Hydrolog's specs of the computation of a hydrograph.

    Parameters
    ----------
    hietogram_type : str or None
        The design hyetograph of a PMAXTP storm; None for an own series.
    interpolation_method : str or None
        How the PMAXTP depth came from the grid (``thiessen``, ``idw``); None for an
        own series.
    tc_method : str or None
        The method of the time of concentration of the SCS unit hydrograph; None for
        Snyder and Nash, whose hydrographs do not use it.
    uh_model : str
        ``scs``, ``snyder`` or ``nash``.
    nash_estimation : str or None
        ``from_lutz`` or ``from_urban_regression`` for Nash.
    amc : str
        ``I``, ``II`` or ``III``: the conversion of the CN for AMC I and III.

    Returns
    -------
    list[FormulaSpec]
        The SCS-CN retention and runoff and the convolution of every hydrograph, the
        hyetograph and the weighting of the grid of a PMAXTP storm, the conversion
        of the CN for AMC I and III, and the unit hydrograph: SCS with its time of
        concentration, Snyder's lag and curve, or Nash's IUH with Lutz's estimation
        or the urban regression of its n and K.
    """
    specs = [scs_cn.RETENTION, scs_cn.RUNOFF, convolution.CONVOLUTION]
    if hietogram_type is not None:
        specs.append(HYETOGRAPHS[hietogram_type])
    if interpolation_method is not None:
        specs.append(AREAL_DEPTHS[interpolation_method])
    if amc != "II":
        specs.append(scs_cn.AMC_CONVERSION)
    if uh_model == "scs" and tc_method is not None:
        specs += [CONCENTRATION_TIMES[tc_method], unit_hydrograph.SCS]
    elif uh_model == "snyder":
        specs += [snyder_uh.SNYDER, snyder_uh.SNYDER_SHAPE]
    elif uh_model == "nash":
        specs.append(nash_iuh.NASH_IUH)
        specs.append(
            nash_iuh.LUTZ if nash_estimation == "from_lutz" else nash_iuh.URBAN
        )
    return specs


def watershed_specs(
    *, cn_from_land_cover: bool, equal_area_slope: bool
) -> list[FormulaSpec]:
    """Return Hydrolog's specs of the parameters of a delineated watershed.

    Parameters
    ----------
    cn_from_land_cover : bool
        The CN is the area-weighted CN of the soil-cover complexes of its land cover,
        each from the TR-55 table.
    equal_area_slope : bool
        The equal-area slope of its longest flow path was measured.

    Returns
    -------
    list[FormulaSpec]
        ``tr55_cn`` and ``equal_area_slope`` where they gave a value.
    """
    specs = []
    if cn_from_land_cover:
        specs.append(TR55_CN)
    if equal_area_slope:
        specs.append(FLOW_PATH_EQUAL_AREA_SLOPE)
    return specs
