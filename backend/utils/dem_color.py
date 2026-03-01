"""
Shared DEM visualization utilities: color ramp, colormap builder, hillshade.

Used by scripts/generate_dem_overlay.py and scripts/generate_dem_tiles.py.
"""

import numpy as np

# Hypsometric color ramp: (position, R, G, B)
COLOR_STOPS = [
    (0.0, 56, 128, 60),  # dark green — valleys
    (0.15, 76, 175, 80),  # green
    (0.30, 139, 195, 74),  # light green
    (0.45, 205, 220, 57),  # lime
    (0.60, 255, 193, 7),  # amber
    (0.75, 161, 110, 60),  # brown
    (0.90, 120, 100, 90),  # dark brown/grey
    (1.0, 245, 245, 240),  # near white — peaks
]


def build_colormap(n_steps: int = 256) -> np.ndarray:
    """Build a 256x3 uint8 colormap from color stops."""
    cmap = np.zeros((n_steps, 3), dtype=np.uint8)
    positions = [s[0] for s in COLOR_STOPS]
    colors = np.array([[s[1], s[2], s[3]] for s in COLOR_STOPS], dtype=np.float64)

    for i in range(n_steps):
        t = i / (n_steps - 1)
        # Find interval
        for k in range(len(positions) - 1):
            if positions[k] <= t <= positions[k + 1]:
                local_t = (t - positions[k]) / (positions[k + 1] - positions[k])
                rgb = colors[k] * (1 - local_t) + colors[k + 1] * local_t
                cmap[i] = np.clip(rgb, 0, 255).astype(np.uint8)
                break
    return cmap


def compute_hillshade(
    dem: np.ndarray,
    cellsize: float,
    azimuth: float = 315.0,
    altitude: float = 45.0,
) -> np.ndarray:
    """
    Multi-directional hillshade for natural terrain visualization.

    Uses 4 light directions (NW, NE, SE, SW) averaged with weights.
    NW (315 deg) is dominant (conventional cartographic lighting).
    The ``azimuth`` parameter is kept for backward compatibility but
    is not used — the 4-direction blend replaces single-source lighting.

    Parameters
    ----------
    dem : np.ndarray
        DEM array (in metric CRS for correct gradients)
    cellsize : float
        Cell size in meters
    azimuth : float
        Kept for backward compatibility (ignored in multi-directional mode)
    altitude : float
        Light source altitude in degrees (default: 45)

    Returns
    -------
    np.ndarray
        Hillshade array, values 0–1 (float64)
    """
    azimuths = [315, 45, 135, 225]
    weights = [0.4, 0.2, 0.2, 0.2]

    dzdx = np.gradient(dem, cellsize, axis=1)
    dzdy = np.gradient(dem, cellsize, axis=0)
    slope = np.sqrt(dzdx**2 + dzdy**2)
    slope_rad = np.arctan(slope)
    aspect_rad = np.arctan2(-dzdy, dzdx)

    alt_rad = np.radians(altitude)

    result = np.zeros_like(dem, dtype=np.float64)
    for az, w in zip(azimuths, weights, strict=True):
        az_rad = np.radians(360 - az + 90)
        hs = (
            np.cos(alt_rad) * np.sin(slope_rad) * np.cos(az_rad - aspect_rad)
            + np.sin(alt_rad) * np.cos(slope_rad)
        )
        hs = np.clip(hs, 0, 1)
        result += w * hs

    return np.clip(result, 0, 1)
