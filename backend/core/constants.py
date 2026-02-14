"""
Project-wide constants.

Centralizes magic numbers and coordinate reference system identifiers
used across modules.
"""

# Coordinate Reference Systems
CRS_PL1992 = "EPSG:2180"
CRS_WGS84 = "EPSG:4326"
CRS_WEBMERCATOR = "EPSG:3857"

# Unit conversions
M_PER_KM = 1000.0
M2_PER_KM2 = 1_000_000.0

# Hydrological defaults
DEFAULT_CN = 75
HYDROGRAPH_AREA_LIMIT_KM2 = 250.0

# Flow graph safety limit (~200 km² @ 1m resolution)
MAX_WATERSHED_CELLS = 2_000_000
MAX_STREAM_DISTANCE_M = 1000.0

# Default flow accumulation threshold (finest resolution)
DEFAULT_THRESHOLD_M2 = 100
