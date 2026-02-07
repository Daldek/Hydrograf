# Changelog

All notable changes to Hydrograf will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
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
