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
    Compute hillshade from DEM using Lambertian reflectance.

    Parameters
    ----------
    dem : np.ndarray
        DEM array (in metric CRS for correct gradients)
    cellsize : float
        Cell size in meters
    azimuth : float
        Light source azimuth in degrees (default: 315 = NW)
    altitude : float
        Light source altitude in degrees (default: 45)

    Returns
    -------
    np.ndarray
        Hillshade array, values 0–1 (float64)
    """
    dx = np.gradient(dem, cellsize, axis=1)  # dz/dx
    dy = np.gradient(dem, cellsize, axis=0)  # dz/dy
    slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
    aspect_rad = np.arctan2(-dy, dx)

    az_rad = np.radians(azimuth)
    alt_rad = np.radians(altitude)

    hillshade = np.sin(alt_rad) * np.cos(slope_rad) + np.cos(alt_rad) * np.sin(
        slope_rad
    ) * np.cos(az_rad - aspect_rad)
    return np.clip(hillshade, 0, 1)
