# Changelog

All notable changes to Hydrograf will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Frontend CP4 Faza 1 — mapa + wyznaczanie zlewni + parametry:
  - `frontend/index.html` — layout Bootstrap 5 (navbar + mapa + panel boczny)
  - `frontend/css/style.css` — style (crosshair, responsywnosc, tabele parametrow)
  - `frontend/js/api.js` — klient API (delineateWatershed, checkHealth, polskie bledy)
  - `frontend/js/map.js` — modul Leaflet.js (OSM, polygon zlewni, marker ujscia)
  - `frontend/js/app.js` — logika aplikacji (walidacja, wyswietlanie ~20 parametrow)
- CDN: Leaflet 1.9.4, Bootstrap 5.3.3 (z integrity hashes)
- Vanilla JS (ES6+, IIFE modules), bez bundlera
- Panel warstw (lewy, chowany) z przyciskiem toggle (hamburger)
- Panel parametrow domyslnie ukryty — auto-otwiera sie po wyznaczeniu zlewni, zamykany X
- Warstwa NMT (WIP): PostGIS raster + endpoint XYZ tiles + kolorystyka hipsometryczna
  - `scripts/import_dem_raster.py` — import DEM GeoTIFF do PostGIS jako kafelki 256x256
  - `api/endpoints/tiles.py` — `GET /api/tiles/dem/{z}/{x}/{y}.png` z PostGIS raster
  - Rampa kolorow: zielony (doliny) → zolty → brazowy → bialy (szczyty), semi-transparent
  - **Status:** backend dziala (tile PNG z bazy), frontend nie wyswietla (do debugowania)
- `scripts/generate_dem_overlay.py` — skrypt generujacy statyczny PNG z NMT (narzedzie pomocnicze)
- `--max-size` w `generate_dem_overlay.py` — downsampling LANCZOS (domyslnie 1024 px)
- `frontend/data/dem.png` + `dem.json` — pre-generowany overlay NMT z metadanymi WGS84 bounds
- `Pillow>=10.0.0` w requirements.txt (rendering tile PNG)
- Kontrolki warstwy NMT w panelu warstw:
  - Przycisk zoom-to-extent (⌖) — `fitDemBounds()` przybliza mape do zasiegu warstwy
  - Suwak przezroczystosci 0–100% — `setDemOpacity()`, pojawia sie po wlaczeniu warstwy
- Warstwa ciekow (Strahler order) jako `L.imageOverlay`:
  - `scripts/generate_streams_overlay.py` — skrypt generujacy PNG z rzedami Strahlera (dyskretna paleta niebieska 1-8, przezroczyste tlo)
  - `frontend/data/streams.png` + `streams.json` — pre-generowany overlay ciekow (48 KB, max order=5)
  - Dylatacja morfologiczna (`maximum_filter`) — grubosc linii proporcjonalna do rzedu (1→3px, 5→11px)
  - `map.js`: `loadStreamsOverlay()`, `getStreamsLayer()`, `fitStreamsBounds()`, `setStreamsOpacity()`
  - `app.js`: refaktor `initLayersPanel()` — wyodrebniony `addLayerEntry()`, dwa wpisy: NMT (30%) i Cieki (0%)

### Fixed
- Overlay NMT i ciekow przesuniety ~26 m wzgledem OSM — reprojekcja rastra do EPSG:4326:
  - Przyczyna: skrypty transformowaly tylko 2 narozniki (SW/NE), a obraz pozostawal w siatce EPSG:2180 obróconej ~0.63° wzgledem WGS84 (zbieznosc poludnikow PL-2000 strefa 6)
  - `generate_dem_overlay.py`: `rasterio.warp.reproject()` z `Resampling.bilinear` zamiast `pyproj` corner-only transform
  - `generate_streams_overlay.py`: dylatacja w EPSG:2180, nastepnie `reproject()` z `Resampling.nearest` (dane kategoryczne)
  - Bounds obliczane z transformu reprojekcji (nie z naroznikow)
  - Dodano `--source-crs` fallback gdy raster nie ma metadanych CRS
- Warstwa NMT "jezdzila" po mapie i miala artefakty — zamiana `L.tileLayer` na `L.imageOverlay`:
  - Przyczyna: `ST_Clip/ST_Resize` nieodpowiednia dla malego rastra (~2km x 2km); przy niskim zoomie DEM bylo rozciagniete na caly kafelek web
  - `map.js`: async `loadDemOverlay()` — fetch `/data/dem.json` → `L.imageOverlay` z georeferencjonowanymi granicami
  - `app.js`: null-guard w `initLayersPanel()` (layer moze byc null przed zaladowaniem)
- Suwak przezroczystosci odwrocony (0% = pelne krycie, 100% = niewidoczne) — dopasowanie do etykiety "Przezr."
- DEM overlay PNG: alpha 200→255 — przezroczystosc sterowana wylacznie przez Leaflet, nie wbudowana w obraz

### Security
- Naglowki bezpieczenstwa nginx: CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy
- Cache statycznych plikow (7d, immutable)
- Ograniczenie portow API (127.0.0.1:8000) i DB (127.0.0.1:5432) — jedyny punkt wejscia z sieci: nginx:8080
- Frontend: wylacznie `textContent` dla danych dynamicznych (brak innerHTML z danymi)

### Fixed
- Dockerfile: dodano `git` do system dependencies (wymagany przez `git+https://` w requirements.txt)
- docker-compose.yml: `effective_cache_size=1G` → `1GB` (poprawna jednostka PostgreSQL)
- Bootstrap 5.3.3 CSS integrity hash (zly hash blokowal zaladowanie stylow → mapa niewidoczna)
- Nginx: `^~` prefix na `/api/tiles/` (regex `.png` przechwytywal tile requesty jako statyczne pliki)

### Fixed
- Ochrona przed resource exhaustion (OOM) w `traverse_upstream()` (ADR-015):
  - Pre-flight check (`check_watershed_size()`) — odrzuca zlewnie >2M komorek przed CTE (<1ms)
  - LIMIT w rekurencyjnym CTE — ogranicza wyniki SQL jako safety net
  - `statement_timeout=30s` w polaczeniach z baza (30s API, 600s skrypty CLI)
  - Docker resource limits: db=2G, api=1G, PostgreSQL tuning (shared_buffers=512MB)
- `MAX_CELLS_DEFAULT` zmniejszony z 10M do 2M (bezpieczne dla 15 GB RAM)

### Tested
- E2E Task 9 (retry): N-33-131-C-b-2 — 4 testy pass:
  - A: 493k cells (0.49 km², 6.5s, Strahler=4, Dd=15.3 km/km²)
  - B: 1.5M cells (1.50 km², 21s, Strahler=4, Dd=14.7 km/km²)
  - C: Pre-flight reject (limit 100k) — natychmiastowe odrzucenie
  - D: Max outlet (1.76M, CTE=2M+1) — LIMIT safety net poprawnie zlapal nadmiar

### Changed
- Aktualizacja Kartograf v0.4.0 → v0.4.1 (BDOT10k hydro, geometry selection, rtree fix)
- Aktualizacja Kartograf v0.3.1 → v0.4.0 (nowe produkty: NMPT, Ortofotomapa, auto-ekspansja godel)
- `download_dem.py`: obsluga `Path | list[Path]` z `download_sheet()` (auto-ekspansja godel grubszych skal)

### Added (Kartograf v0.4.1)
- `download_landcover.py --category hydro` — pobieranie warstw BDOT10k hydrograficznych (SWRS, SWKN, SWRM, PTWP)
- `download_dem.py --geometry` — precyzyjny wybor arkuszy NMT z pliku SHP/GPKG
- `prepare_area.py --with-hydro` — automatyczne pobieranie danych hydro i stream burning

### Added
- Wypalanie ciekow BDOT10k w DEM (`--burn-streams`) — obnizenie DEM wzdluz znanych ciekow przed analiza hydrologiczna (ADR-013)
- 6 nowych testow jednostkowych dla `burn_streams_into_dem()`
- Nowe warstwy rastrowe w preprocessingu DEM (ADR-014):
  - Aspect (`09_aspect.tif`) — ekspozycja stoku 0-360° (N=0, zgodnie z zegarem)
  - TWI (`08_twi.tif`) — Topographic Wetness Index = ln(SCA / tan(slope))
  - Strahler stream order (`07_stream_order.tif`) — rzad cieku wg Strahlera
- Wektoryzacja ciekow z DEM jako LineString w `stream_network` (source='DEM_DERIVED')
- Migracja 003: `strahler_order` w `flow_network`, `upstream_area_km2` i `mean_slope_percent` w `stream_network`
- Wskazniki ksztaltu zlewni: wspolczynnik zwartosci Kc, kolowosci Rc, wydluzenia Re, ksztaltu Ff, szerokosc srednia
- Wskazniki rzezbowe: wspolczynnik rzezbowy Rh, calka hipsometryczna HI
- Krzywa hipsometryczna (opcjonalna, `include_hypsometric_curve=true`)
- Wskazniki sieci rzecznej: gestosc sieci Dd, czest. ciekow Fs, liczba chropowatosci Rn, max rzad Strahlera
- 11 nowych pol w `MorphometricParameters` (Optional, backward compatible)
- `HypsometricPoint` model i `hypsometric_curve` w `WatershedResponse`
- 38 nowych testow jednostkowych (18 DEM + 21 morfometria)
- Flaga `--skip-streams-vectorize` w CLI process_dem

### Removed
- Warstwa `02b_inflated` — zbedna po migracji na pyflwdir (Wang & Liu 2006 obsluguje plaskowyzyzny wewnetrznie)

### Fixed
- `idx_stream_unique` uzywal `ST_GeoHash(geom, 12)` na geometrii EPSG:2180 — naprawiono na `ST_GeoHash(ST_Transform(geom, 4326), 12)`
- `strahler_order=0` dla komorek z acc>=threshold ale pyflwdir order=0 — clamp do min 1
- Duplikaty geohash przy insercie stream segments — `ON CONFLICT DO NOTHING`
- Cieki konczace sie w srodku rastra — wypelnianie wewnetrznych dziur nodata + naprawa zlewow po pysheds
- Przerwane lancuchy downstream_id w flow_network spowodowane NaN fdir i nodata holes

### Changed
- Migracja z pysheds na pyflwdir (Deltares) — mniej zaleznosci, brak temp file, Wang & Liu 2006
- Migracja na .venv-first development workflow (ADR-011)
- Rozdzielenie deps runtime/dev (requirements.txt + pyproject.toml [dev])
- Usuniecie black/flake8 z requirements.txt, dodanie ruff do [dev]
- Aktualizacja docker-compose → docker compose w dokumentacji
- Restrukturyzacja dokumentacji wg shared/standards/DOCUMENTATION_STANDARDS.md
- CLAUDE.md rozbudowany z 14 do ~185 linii (7 sekcji)
- PROGRESS.md skondensowany z 975 do ~71 linii (4 sekcje)
- DEVELOPMENT_STANDARDS.md przepisany z Ruff (zamiast black+flake8)
- IMPLEMENTATION_PROMPT.md przepisany do stanu v0.3.0
- Migracja z black+flake8 na ruff (E, F, I, UP, B, SIM)
- Przeniesienie 6 plików MD z root do docs/

### Tested
- E2E Kartograf v0.4.1: N-33-131-C-b-2 — NMT download (4 sub-sheets), BDOT10k hydro (8.1 MB GPKG), stream burning, 20 rasterow posrednich (~444 MB); Task 9 FAILED (traverse_upstream resource exhaustion, outlet acc=1.76M, mozliwe ograniczenia zasobow Docker)
- E2E pipeline: N-33-131-C-b-2-3 z warstwami 01-09 — 198s, 4.9M komorek, max_strahler=8, 19,005 segmentow (641.6 km), wyniki w `data/results/`
- E2E pipeline: N-33-131-C-b-2-3 z stream burning — 2,856 cells burned, 55s, wyniki w `data/nmt/`
- E2E pipeline: N-33-131-C-b-2-3 z pyflwdir — broken streams: 233→1, max acc +71%, pipeline 17% szybciej
- E2E pipeline: N-33-131-C-b-2-3 (1:10000, 1 arkusz, 4.9M komorek) — flowacc fix verified
- E2E pipeline: N-33-131-C-b (5 m) — Kartograf download, pysheds processing, IMGW precipitation

### Added
- docs/DECISIONS.md — 10 Architecture Decision Records
- .editorconfig (UTF-8, LF, 4 spacje Python, 2 spacje YAML/MD)

### Fixed
- pyproject.toml: readme path outside package root, flat-layout discovery error (editable install)
- Cross-referencje w README.md (ścieżki do docs/)
- Usunięcie rozwiązanego TD-2 z TECHNICAL_DEBT.md (land_cover.py istnieje)
- Naprawa URL repozytorium w pyproject.toml
- 208 błędów ruff naprawionych (202 auto-fix + 6 ręcznie B904)

---

### Added
- `--use-cached` CLI option for `analyze_watershed.py` - skip delineation/morphometry (200x faster re-runs)
- `--tiles` option for specifying exact NMT sheet codes
- `--teryt` option for BDOT10k county code
- `--save-qgis` option for exporting intermediate layers
- `--max-stream-distance` option for outlet search radius
- `load_cached_results()` function for fast hydrograph recalculation
- `core/cn_tables.py` - centralized CN lookup tables for HSG × land cover combinations
- `core/cn_calculator.py` - Kartograf integration for HSG-based CN calculation
- `determine_cn()` function in `core/land_cover.py` - unified CN hierarchy
- 71 new unit tests for CN modules
- Raster utilities: `resample_raster()`, `polygonize_raster()`

### Changed
- **BREAKING**: Precipitation now uses KS (quantile) instead of SG (upper confidence bound)
- Hydrograph generation uses Beta hyetograph convolution for long-duration events
- Beta distribution parameters changed to (2, 5) for asymmetric rainfall
- Increased `max_cells` limit from 5M to 10M
- Refactored `scripts/analyze_watershed.py` - removed ~260 lines of CN logic
- CN calculation now uses modular approach: config → database → Kartograf → default

### Fixed
- Unrealistic Q results caused by using SG instead of KS for design precipitation
- Instantaneous rainfall assumption for long-duration events (now uses convolution)

## [0.3.0] - 2026-01-21

### Added
- Multi-tile DEM mosaic support for large watersheds
- Reverse trace optimization for `find_main_stream` (330x faster)
- COPY-based bulk insert for DEM import (27x faster)
- Land cover integration with weighted CN calculation
- Direct IMGWTools v2.1.0 dependency
- CI/CD pipeline with GitHub Actions (lint, test, coverage)
- Rate limiting in Nginx (10 req/s for API, 30 req/s general)
- `GET /api/scenarios` endpoint for listing valid hydrograph options
- `TECHNICAL_DEBT.md` documenting known issues
- `.pre-commit-config.yaml` for automated code quality checks
- CHECK constraint for `land_cover.category` column
- UNIQUE index for `stream_network` (name + geohash)

### Changed
- CORS configuration now uses environment variable `CORS_ORIGINS`
- Limited CORS methods to GET, POST, OPTIONS
- Disabled CORS credentials for security
- Migrated Pydantic settings from `class Config` to `model_config = SettingsConfigDict`
- Updated `black` to 26.1.0
- Unified line-length to 88 (was 100) for cross-project consistency

### Fixed
- 16 flake8 errors (unused imports, line length, spacing)
- 35 files reformatted with black (17 initial + 18 for line-length)

### Security
- Fixed critical CORS vulnerability (`allow_origins=["*"]` with `allow_credentials=True`)

### Performance
- DEM import: ~3.8 min (was ~102 min)
- `find_main_stream`: ~0.74s (was ~246s)

## [0.2.0] - 2026-01-18

### Added
- Hydrograph generation endpoint (`POST /api/generate-hydrograph`)
- Integration with Hydrolog library for SCS-CN calculations
- Morphometric parameters calculation (area, perimeter, length, slopes)
- Water balance output in hydrograph response
- Land cover support via Kartograf integration

### Changed
- Renamed project from HydroLOG to Hydrograf

## [0.1.0] - 2026-01-15

### Added
- Initial project setup
- Watershed delineation endpoint (`POST /api/delineate-watershed`)
- Health check endpoint (`GET /health`)
- PostgreSQL + PostGIS database schema
- DEM preprocessing script with pysheds
- IMGW precipitation data integration
- Docker Compose deployment configuration

### Documentation
- SCOPE.md - Project scope and requirements
- ARCHITECTURE.md - System architecture
- DATA_MODEL.md - Database schema
- PRD.md - Product requirements

[Unreleased]: https://github.com/Daldek/Hydrograf/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Daldek/Hydrograf/compare/v0.2.2...v0.3.0
[0.2.0]: https://github.com/Daldek/Hydrograf/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Daldek/Hydrograf/releases/tag/v0.1.0
