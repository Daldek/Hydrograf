# Changelog

All notable changes to Hydrograf will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- CI/CD pipeline with GitHub Actions (lint, test, coverage)
- Rate limiting in Nginx (10 req/s for API, 30 req/s general)
- `GET /api/scenarios` endpoint for listing valid hydrograph options
- `CHANGELOG.md` following Keep a Changelog format
- `TECHNICAL_DEBT.md` documenting known issues
- `pyproject.toml` with tool configurations (black, flake8, mypy, pytest)
- `.pre-commit-config.yaml` for automated code quality checks
- CHECK constraint for `land_cover.category` column
- UNIQUE index for `stream_network` (name + geohash)

### Changed
- CORS configuration now uses environment variable `CORS_ORIGINS`
- Limited CORS methods to GET, POST, OPTIONS
- Disabled CORS credentials for security
- Migrated Pydantic settings from `class Config` to `model_config = SettingsConfigDict`
- Updated `black` to 26.1.0

### Fixed
- 16 flake8 errors (unused imports, line length, spacing)
- 17 files reformatted with black

### Security
- Fixed critical CORS vulnerability (`allow_origins=["*"]` with `allow_credentials=True`)

## [0.3.0] - 2026-01-20

### Added
- Multi-tile DEM mosaic support for large watersheds
- Reverse trace optimization for `find_main_stream` (330x faster)
- COPY-based bulk insert for DEM import (27x faster)

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

[Unreleased]: https://github.com/user/hydrograf/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/user/hydrograf/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/user/hydrograf/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/user/hydrograf/releases/tag/v0.1.0
