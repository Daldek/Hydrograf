"""The real Kartograf, offline: only what would leave the machine is replaced.

The tests that need Kartograf run Kartograf itself, in this process: it plans,
downloads and writes a real store (marker, versions, sidecars, links) or plain files
into a folder of the test, so the reports and the files are those of the pinned
version. What would use the network is replaced by stubs of the public provider
classes (the pattern of the Retman tests, DEV-10.6): the GUGiK sheet index answers
``resolve_campaigns`` and writes a sheet in ``download_record`` (:class:`GugikIndex`),
BDOT10k answers ``teryts_for_area`` and ``download_package`` from a list of counties
(:class:`Counties`), SoilGrids answers ``edition`` and ``download_by_bbox`` with
rasters (:class:`SoilRasters`). The fixture ``offline`` fails any call that reaches a
socket anyway. The stores that a test only reads are built by ``kartograf.testing``.
"""

import shutil
import socket
import threading
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zipfile import ZipFile

import kartograf
import numpy as np
import pytest
import rasterio
import requests
from kartograf.providers.pl.skorowidz import SkorowidzRecord
from kartograf.sources.edition import Edition
from rasterio.transform import from_bounds

# What a GeoPackage starts with (a stand-in where no test reads the layers)
GPKG = b"SQLite format 3\x00" + bytes(100)
# Where GUGiK publishes the sheets of the tests
NMT_URL = (
    "https://opendata.geoportal.gov.pl/NumDaneWys/NMT/{ident}/{ident}_1_{sheet}.asc"
)


def asc(sheet: str, seed: int = 0) -> bytes:
    """Build a 2 x 2 ESRI ASCII grid of the frame of ``sheet`` (PL-1992).

    The four values follow ``seed``, so that two flights have different content.
    """
    frame = kartograf.SheetParser(sheet).get_bbox()
    cell = min(frame.max_x - frame.min_x, frame.max_y - frame.min_y) / 2
    return (
        f"ncols 2\nnrows 2\nxllcorner {frame.min_x}\nyllcorner {frame.min_y}\n"
        f"cellsize {cell}\nnodata_value -9999\n"
        f"{seed} {seed + 1}\n{seed + 2} {seed + 3}\n"
    ).encode()


def flight(
    sheet: str, date: str, ident: str, *, full: bool = True, resolution_m: float = 5.0
) -> SkorowidzRecord:
    """Build a record of the GUGiK sheet index: flight ``ident`` on ``sheet``."""
    return SkorowidzRecord(
        url=NMT_URL.format(ident=ident, sheet=sheet),
        sheet=sheet,
        aktualnosc=date,
        dt_pzgik=None,
        layer="c14",
        system="1992",
        zone=None,
        resolution_m=resolution_m,
        full_sheet=full,
        raw={"format": "ARC/INFO ASCII GRID", "aktualnoscRok": date[:4]},
    )


class GugikIndex:
    """What the stubbed GUGiK sheet index knows, and what was asked of it.

    ``flights`` are the records of the index (the newest flight of a sheet is the one a
    request gets); a sheet without one has no coverage. A download of a URL in
    ``failing`` is a ``DownloadError``. ``resolved`` lists the sheets asked for and
    ``downloaded`` the URLs transferred.
    """

    def __init__(
        self,
        flights: Iterable[SkorowidzRecord] = (),
        *,
        failing: Iterable[str] = (),
    ) -> None:
        self.flights: dict[str, list[SkorowidzRecord]] = {}
        for record in sorted(flights, key=lambda item: item.aktualnosc, reverse=True):
            self.flights.setdefault(record.sheet, []).append(record)
        self.failing = set(failing)
        self.resolved: list[str] = []
        self.downloaded: list[str] = []
        self._lock = threading.Lock()

    def resolve(
        self,
        sheet: str,
        *,
        all_campaigns: bool = False,
        min_year: int | None = None,
        max_year: int | None = None,
        timeout: int | None = None,
    ) -> list[SkorowidzRecord]:
        """Return the newest flight of ``sheet`` (all of them: ``all_campaigns``)."""
        with self._lock:
            self.resolved.append(sheet)
        found = self.flights.get(sheet)
        if not found:
            raise kartograf.NoCoverageError(f"no flight over {sheet}", sheet=sheet)
        return list(found) if all_campaigns else found[:1]

    def download(
        self, record: SkorowidzRecord, path: Path, timeout: int | None = None
    ) -> Path:
        """Write the sheet of ``record``: an ASCII grid."""
        if record.url in self.failing:
            raise kartograf.DownloadError(f"{record.url}: HTTP 500", sheet=record.sheet)
        with self._lock:
            self.downloaded.append(record.url)
        path.parent.mkdir(parents=True, exist_ok=True)
        name = record.url.rsplit("/", 1)[-1]
        path.write_bytes(asc(record.sheet, int(name.split("_")[0])))
        return path

    def length(self, record: SkorowidzRecord) -> int | None:
        """Say that the size of a file is unknown (the real call asks the server)."""
        return None


@contextmanager
def gugik_index(index: GugikIndex) -> Iterator[GugikIndex]:
    """Answer the GUGiK sheet index and the sheet files of the NMT provider."""
    with ExitStack() as stack:
        for name, stub in (
            ("resolve_campaigns", index.resolve),
            ("download_record", index.download),
            ("record_length", index.length),
        ):
            stack.enter_context(patch.object(kartograf.GugikProvider, name, stub))
        yield index


class Counties:
    """The stubbed BDOT10k service: the counties of an area and their packages.

    ``teryts`` are the counties an area intersects (PRG); a package of one in
    ``failing`` is a ``DownloadError``. The GeoPackage of a county is the file
    ``geopackages[teryt]`` when the test gives one, else a stand-in. ``areas`` lists the
    areas asked for and ``packages`` the counties transferred.
    """

    def __init__(
        self,
        teryts: Sequence[str],
        *,
        failing: Iterable[str] = (),
        geopackages: Mapping[str, Path] | None = None,
    ) -> None:
        self.teryts = list(teryts)
        self.failing = set(failing)
        self.geopackages = dict(geopackages or {})
        self.areas: list[Any] = []
        self.packages: list[str] = []

    def counties(self, bbox: Any, timeout: int = 30) -> list[str]:
        """Return the counties of the area."""
        self.areas.append(bbox)
        return list(self.teryts)

    def package(
        self,
        code: str,
        output_path: Path,
        *,
        format: str = "GPKG",
        layers: Sequence[str] | None = None,
        keep_raw: bool = False,
        raw_path: Path | None = None,
        timeout: int | None = None,
    ) -> kartograf.Bdot10kPackage:
        """Write the package of county ``code``."""
        if code in self.failing:
            raise kartograf.DownloadError(f"BDOT10k TERYT {code}: HTTP 500")
        self.packages.append(code)
        path = output_path.with_suffix(".zip") if format == "SHP" else output_path
        if format == "SHP":
            with ZipFile(path, "w") as archive:
                archive.writestr("roads.shp", bytes(100))
        elif code in self.geopackages:
            shutil.copyfile(self.geopackages[code], path)
        else:
            path.write_bytes(GPKG)
        return kartograf.Bdot10kPackage(
            path=path,
            teryt=code,
            url=f"https://opendata.geoportal.gov.pl/bdot10k/{code}_{format}.zip",
            format=format,
            http={
                "etag": None,
                "last_modified": None,
                "content_length": path.stat().st_size,
            },
        )


def _head(self: requests.Session, url: str, **kwargs: Any) -> requests.Response:
    """Answer a ``HEAD`` of a package size: the server sends no ``Content-Length``."""
    response = requests.Response()
    response.status_code = 200
    response.url = url
    return response


@contextmanager
def bdot10k_counties(counties: Counties) -> Iterator[Counties]:
    """Answer BDOT10k (PRG counties, packages and their sizes) from ``counties``."""
    with (
        patch.object(kartograf.Bdot10kProvider, "teryts_for_area", counties.counties),
        patch.object(kartograf.Bdot10kProvider, "download_package", counties.package),
        patch.object(requests.Session, "head", _head),
    ):
        yield counties


# 20% clay, 40% sand, 40% silt (g/kg): loam, hydrologic soil group B
LOAM = {"clay": 200.0, "sand": 400.0, "silt": 400.0}
# 10% clay, 85% sand, 5% silt: loamy sand, hydrologic soil group A
SANDY = {"clay": 100.0, "sand": 850.0, "silt": 50.0}


class SoilRasters:
    """The stubbed SoilGrids service: one raster per property for any bbox.

    ``values[property]`` is the value (g/kg) of every cell, or an exception to raise;
    ``cells`` is the number of cells along a side of a raster. ``downloads`` lists the
    properties transferred.
    """

    def __init__(
        self, values: Mapping[str, float | Exception] | None = None, cells: int = 4
    ) -> None:
        self.values: dict[str, float | Exception] = dict(values or LOAM)
        self.cells = cells
        self.downloads: list[str] = []

    def edition(self, property: str, timeout: int = 120) -> Edition:
        """Return the edition of the source (the same for every property)."""
        return Edition("2.0", f"https://example.test/{property}")

    def download_by_bbox(
        self,
        bbox: Any,
        output_path: Path,
        timeout: int = 120,
        *,
        property: str,
        **kwargs: Any,
    ) -> Path:
        """Write the raster of ``bbox`` for ``property`` in EPSG:4326, like WCS does."""
        self.downloads.append(property)
        value = self.values[property]
        if isinstance(value, Exception):
            raise value
        west, south, east, north = _lon_lat(bbox)
        data = np.full((self.cells, self.cells), value, dtype=np.float32)
        target = Path(output_path).with_suffix(".tif")
        with rasterio.open(
            target,
            "w",
            driver="GTiff",
            width=self.cells,
            height=self.cells,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_bounds(west, south, east, north, self.cells, self.cells),
            nodata=0,
        ) as dst:
            dst.write(data, 1)
        return target


def _lon_lat(bbox: Any) -> tuple[float, float, float, float]:
    """Return ``bbox`` as (west, south, east, north) in EPSG:4326."""
    return tuple(kartograf.transform_bbox(bbox, "EPSG:4326")[:4])  # type: ignore[return-value]


@contextmanager
def soil_rasters(soil: SoilRasters) -> Iterator[SoilRasters]:
    """Answer SoilGrids (the edition and the rasters of a bbox) from ``soil``."""
    with (
        patch.object(kartograf.SoilGridsProvider, "edition", soil.edition),
        patch.object(
            kartograf.SoilGridsProvider, "download_by_bbox", soil.download_by_bbox
        ),
    ):
        yield soil


def _is_loopback(address: Any) -> bool:
    """Say whether a socket address is the local machine."""
    if not (isinstance(address, tuple) and address):
        return True  # AF_UNIX sockets and other local transports
    return address[0] in ("localhost", "127.0.0.1", "::1")


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any connection to another machine, so a call that is not stubbed shows."""
    original = socket.socket.connect

    def guarded(self: socket.socket, address: Any) -> Any:
        if not _is_loopback(address):
            raise RuntimeError(f"Network access in an offline test: {address!r}")
        return original(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
