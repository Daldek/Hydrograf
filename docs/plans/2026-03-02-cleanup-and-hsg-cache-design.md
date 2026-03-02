# Design: Cleanup rozszerzenie + HSG cache dla calej Polski

**Data:** 2026-03-02
**Status:** Zatwierdzony

## Kontekst

Trzy powiazane problemy:
1. Panel admina nie usuwa plikow `.geojson` z `frontend/data/` (wzorzec `overlays` ma tylko `*.png` i `*.json`)
2. Panel admina nie usuwa przetworzonych plikow `.tif` z `data/nmt/` i `data/hydro/`
3. `cache/soil_hsg/hsg.tif` nadpisywany przy kazdym uruchomieniu — brak reuse

## Decyzje projektowe

### HSG — jednorazowe pobranie dla calej Polski

**Uzasadnienie:** Raster HSG dla calej Polski to ~11M pikseli (4400×2500 px) przy 250m rozdzielczosci SoilGrids = ~2-5 MB z kompresja. Jednorazowe pobranie eliminuje cala zlozonosc cachowania (kafelki, overlap detection, merge).

**Flow:**
1. Plik: `cache/soil_hsg/hsg_poland.tif` (uint8, EPSG:4326)
2. Bbox Polski: ~14.07-24.15°E × 49.00-54.84°N
3. Skip logic: jesli plik istnieje → skip download
4. Processing: clip do bbox projektu → `rasterio.warp` do EPSG:2180 (nearest neighbor) → polygonizacja → import do DB
5. DB import: `DELETE FROM soil_hsg WHERE ST_Intersects(geom, bbox)` zamiast `DELETE FROM soil_hsg` (zachowuje dane z innych obszarow)

**Cache w oryginalnym CRS (EPSG:4326):**
- Brak strat jakosci z reproj
- Jeden resampling przy processingu (oryg → NMT grid)
- Spojne z filozofia ADR-037 (cache = surowe dane)

### Cleanup — rozszerzenie targetow

**Overlays:** Dodanie `*.geojson` do wzorcow glob (obok `*.png`, `*.json`).

**Processed data:** Nowy target `processed_data` (typ `dir`) obejmujacy:
- `data/nmt/` — przetworzone rastry DEM (filled, flowdir, flowacc, slope, etc.)
- `data/hydro/` — merged BDOT10k GeoPackage

Wlaczony w `ALL_CLEANUP_TARGETS` (dane przetworzone sa tanie do regeneracji z cache).

## Pliki do zmiany

- `backend/scripts/bootstrap.py` — step_soil_hsg(): nowy flow z hsg_poland.tif
- `backend/api/endpoints/admin.py` — CLEANUP_TARGETS: nowy target + wzorzec geojson
- `backend/tests/unit/test_admin_cleanup.py` — testy nowych targetow
- Testy step_soil_hsg (jesli istnieja)
