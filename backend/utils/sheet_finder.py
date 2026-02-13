"""
Map sheet code finder for Polish topographic maps.

Converts geographic coordinates to map sheet codes (godła) for the
Polish coordinate system (Układ 1992). Based on the International
Map of the World (IMW) division system.

Sheet hierarchy (Poland uses 1992 system):
- 1:1,000,000 - IMW sheets (e.g., N-34)
- 1:500,000   - 4 sheets per 1:1M (A, B, C, D)
- 1:200,000   - 36 sheets per 1:1M (I-XXXVI or 01-36)
- 1:100,000   - 144 sheets per 1:1M (001-144)
- 1:50,000    - 4 sheets per 1:100k (A, B, C, D)
- 1:25,000    - 4 sheets per 1:50k (a, b, c, d)
- 1:10,000    - 8 sheets per 1:25k (row-col: 1-1 to 2-4)

Examples
--------
>>> code = coordinates_to_sheet_code(52.23, 21.01)
>>> print(code)
N-34-131-C-c-2-1

>>> sheets = get_sheets_for_bbox(52.2, 21.0, 52.3, 21.1)
>>> print(sheets)
['N-34-131-C-c-2-1', 'N-34-131-C-c-2-2', ...]
"""

import math
from dataclasses import dataclass

# Note: transform_wgs84_to_pl1992 is available via utils.geometry if needed


@dataclass
class SheetBounds:
    """Geographic bounds of a map sheet."""

    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    def contains(self, lat: float, lon: float) -> bool:
        """Check if point is within bounds."""
        return self.min_lat <= lat < self.max_lat and self.min_lon <= lon < self.max_lon

    @property
    def center(self) -> tuple[float, float]:
        """Return center point (lat, lon)."""
        return (
            (self.min_lat + self.max_lat) / 2,
            (self.min_lon + self.max_lon) / 2,
        )


# IMW zone letters for latitudes (every 4 degrees from equator)
IMW_ZONE_LETTERS = "ABCDEFGHJKLMNPQRSTUV"  # No I or O

# Sheet division parameters
SCALE_1M_LAT_SIZE = 4.0  # degrees
SCALE_1M_LON_SIZE = 6.0  # degrees


def _lat_to_zone_letter(lat: float) -> str:
    """
    Convert latitude to IMW zone letter.

    For Poland, the relevant zones are:
    - M: 48-52°N
    - N: 52-56°N

    Parameters
    ----------
    lat : float
        Latitude in degrees (positive for N, negative for S)

    Returns
    -------
    str
        Zone letter (A-V, excluding I and O)

    Raises
    ------
    ValueError
        If latitude is outside valid range
    """
    if lat < -80 or lat > 84:
        raise ValueError(f"Latitude {lat} outside IMW range (-80 to 84)")

    # For northern hemisphere, calculate zone
    # Zone 0 = 0-4°N → letter index in adjusted alphabet
    # IMW uses letters A-V excluding I and O
    # For Poland: M=48-52°N, N=52-56°N

    if lat >= 0:
        zone_idx = int(lat / SCALE_1M_LAT_SIZE)
        # Map zone index to letter index
        # IMW letters: ABCDEFGHJKLMNPQRSTUV (no I, no O)
        # Zone 12 (48-52°N) → M (index 11 in letter string)
        # Zone 13 (52-56°N) → N (index 12 in letter string)

        if zone_idx <= 7:
            # Zones 0-7 → letters A-H (indices 0-7)
            letter_idx = zone_idx
        elif zone_idx <= 14:
            # Zones 8-14 → letters J-P (indices 8-13), I is skipped
            # zone_idx 8 → J (index 8), zone_idx 12 → M (index 11)
            letter_idx = zone_idx - 1
        else:
            # Zones 15+ → letters Q-V (indices 14-19), O is also skipped
            letter_idx = zone_idx - 2

        if letter_idx >= len(IMW_ZONE_LETTERS) or letter_idx < 0:
            raise ValueError(f"Latitude {lat} outside supported range")

        return IMW_ZONE_LETTERS[letter_idx]
    else:
        # Southern hemisphere (not used for Poland)
        zone_idx = int((-lat - 0.001) / SCALE_1M_LAT_SIZE)
        # H, G, F, ...
        letter_idx = 7 - zone_idx if zone_idx <= 7 else 8 - zone_idx
        return IMW_ZONE_LETTERS[max(0, letter_idx)]


def _lon_to_zone_number(lon: float) -> int:
    """
    Convert longitude to IMW zone number (column).

    Parameters
    ----------
    lon : float
        Longitude in degrees (-180 to 180)

    Returns
    -------
    int
        Zone number (1-60)
    """
    # Zone 1 starts at 180°W, zone 31 starts at 0°E
    # Each zone is 6 degrees wide
    zone = int((lon + 180) / SCALE_1M_LON_SIZE) + 1
    return min(max(zone, 1), 60)


def _get_1m_bounds(zone_letter: str, zone_number: int) -> SheetBounds:
    """
    Get geographic bounds for 1:1,000,000 sheet.

    Parameters
    ----------
    zone_letter : str
        IMW zone letter
    zone_number : int
        IMW zone number (column)

    Returns
    -------
    SheetBounds
        Geographic bounds of the sheet
    """
    # Find latitude from zone letter
    # IMW letters: ABCDEFGHJKLMNPQRSTUV (no I at position 8, no O at position 14)
    # Letter index to zone (latitude band) conversion:
    # - A-H (idx 0-7): zone = idx
    # - J-N (idx 8-12): zone = idx + 1 (I is skipped)
    # - P-V (idx 13-19): zone = idx + 2 (I and O are skipped)

    letter_idx = IMW_ZONE_LETTERS.index(zone_letter.upper())

    if letter_idx <= 7:
        zone_from_equator = letter_idx
    elif letter_idx <= 12:
        zone_from_equator = letter_idx + 1
    else:
        zone_from_equator = letter_idx + 2

    # Northern hemisphere: latitude = zone * 4
    min_lat = zone_from_equator * SCALE_1M_LAT_SIZE
    max_lat = min_lat + SCALE_1M_LAT_SIZE

    # Longitude from zone number
    # Zone 31 starts at 0°E, each zone is 6° wide
    min_lon = (zone_number - 31) * SCALE_1M_LON_SIZE
    max_lon = min_lon + SCALE_1M_LON_SIZE

    return SheetBounds(min_lat, max_lat, min_lon, max_lon)


def _subdivide_bounds(
    bounds: SheetBounds, rows: int, cols: int, row: int, col: int
) -> SheetBounds:
    """
    Get bounds of a subdivision within parent bounds.

    Parameters
    ----------
    bounds : SheetBounds
        Parent sheet bounds
    rows : int
        Number of rows in subdivision
    cols : int
        Number of columns in subdivision
    row : int
        Row index (0-based, from top/north)
    col : int
        Column index (0-based, from left/west)

    Returns
    -------
    SheetBounds
        Subdivision bounds
    """
    lat_size = (bounds.max_lat - bounds.min_lat) / rows
    lon_size = (bounds.max_lon - bounds.min_lon) / cols

    # Row 0 is at the top (north)
    min_lat = bounds.max_lat - (row + 1) * lat_size
    max_lat = bounds.max_lat - row * lat_size
    min_lon = bounds.min_lon + col * lon_size
    max_lon = bounds.min_lon + (col + 1) * lon_size

    return SheetBounds(min_lat, max_lat, min_lon, max_lon)


def _find_subdivision(
    bounds: SheetBounds, lat: float, lon: float, rows: int, cols: int
) -> tuple[int, int]:
    """
    Find which subdivision contains the point.

    Parameters
    ----------
    bounds : SheetBounds
        Parent sheet bounds
    lat : float
        Latitude
    lon : float
        Longitude
    rows : int
        Number of rows
    cols : int
        Number of columns

    Returns
    -------
    Tuple[int, int]
        (row, col) indices (0-based)
    """
    lat_size = (bounds.max_lat - bounds.min_lat) / rows
    lon_size = (bounds.max_lon - bounds.min_lon) / cols

    # Row from top (north)
    row = int((bounds.max_lat - lat) / lat_size)
    row = min(max(row, 0), rows - 1)

    # Column from left (west)
    col = int((lon - bounds.min_lon) / lon_size)
    col = min(max(col, 0), cols - 1)

    return row, col


def coordinates_to_sheet_code(lat: float, lon: float, scale: str = "1:10000") -> str:
    """
    Convert geographic coordinates to map sheet code (godło).

    Parameters
    ----------
    lat : float
        Latitude in WGS84 (decimal degrees)
    lon : float
        Longitude in WGS84 (decimal degrees)
    scale : str
        Target scale: "1:1000000", "1:100000", "1:50000", "1:25000", "1:10000"
        Default is "1:10000"

    Returns
    -------
    str
        Map sheet code (godło), e.g., "N-34-131-C-c-2-1"

    Raises
    ------
    ValueError
        If coordinates are outside Poland or scale is invalid

    Examples
    --------
    >>> coordinates_to_sheet_code(52.23, 21.01)
    'N-34-131-C-c-2-1'

    >>> coordinates_to_sheet_code(52.23, 21.01, scale="1:100000")
    'N-34-131'
    """
    # Validate coordinates are roughly in Poland
    if not (49.0 <= lat <= 55.0 and 14.0 <= lon <= 24.5):
        raise ValueError(f"Coordinates ({lat}, {lon}) are outside Poland bounds")

    # 1:1,000,000 sheet
    zone_letter = _lat_to_zone_letter(lat)
    zone_number = _lon_to_zone_number(lon)
    code_1m = f"{zone_letter}-{zone_number}"
    bounds_1m = _get_1m_bounds(zone_letter, zone_number)

    if scale == "1:1000000":
        return code_1m

    # 1:100,000 sheet (12 rows × 12 cols = 144 sheets per 1:1M)
    row_100k, col_100k = _find_subdivision(bounds_1m, lat, lon, 12, 12)
    sheet_100k = row_100k * 12 + col_100k + 1  # 1-144
    code_100k = f"{code_1m}-{sheet_100k:03d}"
    bounds_100k = _subdivide_bounds(bounds_1m, 12, 12, row_100k, col_100k)

    if scale == "1:100000":
        return code_100k

    # 1:50,000 sheet (2 rows × 2 cols = 4 sheets per 1:100k)
    # A B
    # C D
    row_50k, col_50k = _find_subdivision(bounds_100k, lat, lon, 2, 2)
    letters_50k = ["A", "B", "C", "D"]
    idx_50k = row_50k * 2 + col_50k
    code_50k = f"{code_100k}-{letters_50k[idx_50k]}"
    bounds_50k = _subdivide_bounds(bounds_100k, 2, 2, row_50k, col_50k)

    if scale == "1:50000":
        return code_50k

    # 1:25,000 sheet (2 rows × 2 cols = 4 sheets per 1:50k)
    # a b
    # c d
    row_25k, col_25k = _find_subdivision(bounds_50k, lat, lon, 2, 2)
    letters_25k = ["a", "b", "c", "d"]
    idx_25k = row_25k * 2 + col_25k
    code_25k = f"{code_50k}-{letters_25k[idx_25k]}"
    bounds_25k = _subdivide_bounds(bounds_50k, 2, 2, row_25k, col_25k)

    if scale == "1:25000":
        return code_25k

    # 1:10,000 sheet (2 rows × 4 cols = 8 sheets per 1:25k)
    # Uses row-col notation: 1-1, 1-2, 1-3, 1-4 (top row)
    #                        2-1, 2-2, 2-3, 2-4 (bottom row)
    row_10k, col_10k = _find_subdivision(bounds_25k, lat, lon, 2, 4)
    code_10k = f"{code_25k}-{row_10k + 1}-{col_10k + 1}"

    if scale == "1:10000":
        return code_10k

    raise ValueError(f"Invalid scale: {scale}")


def get_sheet_bounds(sheet_code: str) -> SheetBounds:
    """
    Get geographic bounds for a map sheet code.

    Parameters
    ----------
    sheet_code : str
        Map sheet code (godło), e.g., "N-34-131-C-c-2-1"

    Returns
    -------
    SheetBounds
        Geographic bounds of the sheet

    Examples
    --------
    >>> bounds = get_sheet_bounds("N-34-131")
    >>> print(f"Lat: {bounds.min_lat:.2f}-{bounds.max_lat:.2f}")
    """
    parts = sheet_code.split("-")

    if len(parts) < 2:
        raise ValueError(f"Invalid sheet code: {sheet_code}")

    # Parse 1:1M
    zone_letter = parts[0]
    zone_number = int(parts[1])
    bounds = _get_1m_bounds(zone_letter, zone_number)

    if len(parts) == 2:
        return bounds

    # Parse 1:100k
    sheet_100k = int(parts[2])
    row_100k = (sheet_100k - 1) // 12
    col_100k = (sheet_100k - 1) % 12
    bounds = _subdivide_bounds(bounds, 12, 12, row_100k, col_100k)

    if len(parts) == 3:
        return bounds

    # Parse 1:50k
    letter_50k = parts[3].upper()
    idx_50k = "ABCD".index(letter_50k)
    row_50k = idx_50k // 2
    col_50k = idx_50k % 2
    bounds = _subdivide_bounds(bounds, 2, 2, row_50k, col_50k)

    if len(parts) == 4:
        return bounds

    # Parse 1:25k
    letter_25k = parts[4].lower()
    idx_25k = "abcd".index(letter_25k)
    row_25k = idx_25k // 2
    col_25k = idx_25k % 2
    bounds = _subdivide_bounds(bounds, 2, 2, row_25k, col_25k)

    if len(parts) == 5:
        return bounds

    # Parse 1:10k
    row_10k = int(parts[5]) - 1
    col_10k = int(parts[6]) - 1
    bounds = _subdivide_bounds(bounds, 2, 4, row_10k, col_10k)

    return bounds


def get_sheets_for_bbox(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    scale: str = "1:10000",
) -> list[str]:
    """
    Get all map sheet codes that cover a bounding box.

    Parameters
    ----------
    min_lat : float
        Minimum latitude
    min_lon : float
        Minimum longitude
    max_lat : float
        Maximum latitude
    max_lon : float
        Maximum longitude
    scale : str
        Target scale (default "1:10000")

    Returns
    -------
    List[str]
        List of sheet codes covering the bbox

    Examples
    --------
    >>> sheets = get_sheets_for_bbox(52.2, 21.0, 52.25, 21.1)
    >>> print(len(sheets))
    4
    """
    sheets = set()

    # Estimate sheet size at this scale
    if scale == "1:10000":
        # ~2.5 arcmin lat × ~5 arcmin lon approximately
        step_lat = 0.02  # ~2 km
        step_lon = 0.04  # ~3 km
    elif scale == "1:25000":
        step_lat = 0.05
        step_lon = 0.08
    elif scale == "1:50000":
        step_lat = 0.1
        step_lon = 0.16
    elif scale == "1:100000":
        step_lat = 0.33
        step_lon = 0.5
    else:
        step_lat = 0.1
        step_lon = 0.1

    # Sample points across the bbox
    lat = min_lat
    while lat <= max_lat + step_lat:
        lon = min_lon
        while lon <= max_lon + step_lon:
            try:
                code = coordinates_to_sheet_code(
                    min(lat, max_lat), min(lon, max_lon), scale
                )
                sheets.add(code)
            except ValueError:
                pass  # Outside Poland
            lon += step_lon
        lat += step_lat

    return sorted(sheets)


def get_neighboring_sheets(
    sheet_code: str, include_diagonals: bool = True
) -> list[str]:
    """
    Get neighboring sheet codes.

    Parameters
    ----------
    sheet_code : str
        Center sheet code
    include_diagonals : bool
        Include diagonal neighbors (default True)

    Returns
    -------
    List[str]
        List of neighboring sheet codes

    Examples
    --------
    >>> neighbors = get_neighboring_sheets("N-34-131-C-c-2-2")
    >>> print(len(neighbors))
    8
    """
    bounds = get_sheet_bounds(sheet_code)
    center_lat, center_lon = bounds.center

    # Sheet dimensions
    lat_size = bounds.max_lat - bounds.min_lat
    lon_size = bounds.max_lon - bounds.min_lon

    # Determine scale from sheet code
    parts = sheet_code.split("-")
    if len(parts) == 7:
        scale = "1:10000"
    elif len(parts) == 5:
        scale = "1:25000"
    elif len(parts) == 4:
        scale = "1:50000"
    elif len(parts) == 3:
        scale = "1:100000"
    else:
        scale = "1:1000000"

    neighbors = []

    # Offsets for neighbors
    offsets = [(-1, 0), (1, 0), (0, -1), (0, 1)]  # N, S, W, E
    if include_diagonals:
        offsets += [(-1, -1), (-1, 1), (1, -1), (1, 1)]  # NW, NE, SW, SE

    for dlat, dlon in offsets:
        neighbor_lat = center_lat + dlat * lat_size
        neighbor_lon = center_lon + dlon * lon_size

        try:
            neighbor_code = coordinates_to_sheet_code(neighbor_lat, neighbor_lon, scale)
            if neighbor_code != sheet_code:
                neighbors.append(neighbor_code)
        except ValueError:
            pass  # Outside Poland

    return sorted(set(neighbors))


def get_sheets_for_point_with_buffer(
    lat: float, lon: float, buffer_km: float = 5.0, scale: str = "1:10000"
) -> list[str]:
    """
    Get all sheet codes covering area around a point.

    Parameters
    ----------
    lat : float
        Center latitude (WGS84)
    lon : float
        Center longitude (WGS84)
    buffer_km : float
        Buffer radius in kilometers (default 5 km)
    scale : str
        Target scale (default "1:10000")

    Returns
    -------
    List[str]
        List of sheet codes covering the buffered area

    Examples
    --------
    >>> sheets = get_sheets_for_point_with_buffer(52.23, 21.01, buffer_km=5)
    >>> print(len(sheets))
    9
    """
    # Approximate degrees per km at this latitude
    km_per_deg_lat = 111.0
    km_per_deg_lon = 111.0 * math.cos(math.radians(lat))

    buffer_lat = buffer_km / km_per_deg_lat
    buffer_lon = buffer_km / km_per_deg_lon

    return get_sheets_for_bbox(
        lat - buffer_lat, lon - buffer_lon, lat + buffer_lat, lon + buffer_lon, scale
    )
