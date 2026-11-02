"""
Morphometric calculations for watershed analysis.

Provides the shape indices of a watershed, compatible with Hydrolog's
WatershedParameters. The rest of the morphometry of the API is computed from the
catchment graph in ``core.watershed_service.build_morph_dict_from_graph``.
"""

from typing import Any

import numpy as np


def calculate_shape_indices(
    area_km2: float,
    perimeter_km: float,
    length_km: float,
) -> dict[str, Any]:
    """
    Calculate watershed shape indices.

    Parameters
    ----------
    area_km2 : float
        Watershed area [km2]
    perimeter_km : float
        Watershed perimeter [km]
    length_km : float
        Watershed length (max distance from outlet) [km]

    Returns
    -------
    dict
        Dictionary with keys:
        - compactness_coefficient: Gravelius compactness Kc = P / (2*sqrt(pi*A))
        - circularity_ratio: Miller circularity Rc = 4*pi*A / P^2
        - elongation_ratio: Schumm elongation Re = (2/L)*sqrt(A/pi)
        - form_factor: Horton form factor Ff = A / L^2
        - lemniscate_ratio: Chorley lemniscate Cl = 0.5 * L / A
        - mean_width_km: mean width W = A / L [km]
    """
    result = {}

    if area_km2 <= 0 or perimeter_km <= 0 or length_km <= 0:
        return {
            "compactness_coefficient": None,
            "circularity_ratio": None,
            "elongation_ratio": None,
            "form_factor": None,
            "lemniscate_ratio": None,
            "mean_width_km": None,
        }

    # Kc — Gravelius compactness coefficient
    # Kc = P / (2 * sqrt(pi * A)), Kc=1 for circle
    result["compactness_coefficient"] = round(
        perimeter_km / (2 * np.sqrt(np.pi * area_km2)), 4
    )

    # Rc — Miller circularity ratio
    # Rc = 4 * pi * A / P^2, Rc=1 for circle
    result["circularity_ratio"] = round(4 * np.pi * area_km2 / (perimeter_km**2), 4)

    # Re — Schumm elongation ratio
    # Re = (2/L) * sqrt(A/pi), Re=1 for circle
    result["elongation_ratio"] = round((2 / length_km) * np.sqrt(area_km2 / np.pi), 4)

    # Ff — Horton form factor
    # Ff = A / L^2
    result["form_factor"] = round(area_km2 / (length_km**2), 4)

    # Cl — Chorley lemniscate ratio
    # Cl = π * L² / (4 * A)
    result["lemniscate_ratio"] = round(np.pi * length_km**2 / (4 * area_km2), 4)

    # W — mean width
    # W = A / L [km]
    result["mean_width_km"] = round(area_km2 / length_km, 4)

    return result
