# PROGRESS — Hydrograf

## Status projektu

| Element | Status | Uwagi |
|---------|--------|-------|
| API (FastAPI + PostGIS) | ✅ Gotowy | 6 endpointow (+ tiles MVT streams/catchments): delineate, hydrograph, scenarios, profile, depressions, health. 464 testow. |
| Wyznaczanie zlewni | ✅ Gotowy | traverse_upstream, concave hull |
| Parametry morfometryczne | ✅ Gotowy | area, slope, length, CN + 11 nowych wskaznikow |
| Generowanie hydrogramu | ✅ Gotowy | SCS-CN, 42 scenariusze |
| Preprocessing NMT | ✅ Gotowy | pyflwdir + COPY (3.8 min/arkusz), stream burning |
| Integracja Hydrolog | ✅ Gotowy | v0.5.2 |
| Integracja Kartograf | ✅ Gotowy | v0.4.1 (NMT, NMPT, Orto, Land Cover, HSG, BDOT10k hydro) |
| Integracja IMGWTools | ✅ Gotowy | v2.1.0 (opady projektowe) |
| CN calculation | ✅ Gotowy | cn_tables + cn_calculator + determine_cn() |
| Frontend | 🔶 Faza 3 gotowa | CP4 — wektorowe cieki MVT, hillshade, zaglbienia preprocessing |
| Testy scripts/ | ⏳ W trakcie | 46 testow process_dem (burn, fill, sinks, pyflwdir, aspect, TWI, Strahler) |
| Dokumentacja | ✅ Gotowy | Standaryzacja wg shared/standards (2026-02-07) |

## Checkpointy

### CP1 — Health endpoint ✅
- **Data:** 2026-01-15
- **Wersja:** v0.1.0
- **Zakres:** Setup, Docker Compose, GET /health, migracje Alembic

### CP2 — Wyznaczanie zlewni ✅
- **Data:** 2026-01-18
- **Wersja:** v0.2.0
- **Zakres:** POST /delineate-watershed, traverse_upstream, build_boundary, integracja Hydrolog

### CP3 — Generowanie hydrogramu ✅
- **Data:** 2026-01-21
- **Wersja:** v0.3.0
- **Zakres:** POST /generate-hydrograph, SCS-CN, 42 scenariusze, COPY 27x, reverse trace 330x, Land Cover, IMGWTools

### CP4 — Frontend z mapa ⏳
- **Wersja:** v0.4.0 (planowana)
- **Zakres:** Leaflet.js, Chart.js, interaktywna mapa, panel parametrow

### CP5 — MVP ⏳
- **Wersja:** v1.0.0 (planowana)
- **Zakres:** Pelna integracja frontend+backend, deploy produkcyjny

## Ostatnia sesja

**Data:** 2026-02-12 (sesja 6)

### Co zrobiono

- **Testy integracyjne e2e dla 3 nowych endpointow (51 testow):**
  - `test_profile.py` (13 testow): `POST /api/terrain-profile` — struktura odpowiedzi, walidacja geometry, n_samples limits, pusty wynik 404, multi-point LineString
  - `test_depressions.py` (17 testow): `GET /api/depressions` — GeoJSON FeatureCollection, properties, filtry (volume/area/bbox), walidacja 422, zaokraglenia, sortowanie
  - `test_tiles.py` (21 testow): streams/catchments MVT + thresholds — content-type protobuf, cache headers, puste tile, threshold walidacja, zoom levels, graceful fallback

- **Naprawa kontenera API (OOM):**
  - Kontener API mial limit pamieci 1 GiB zamiast 3 GiB (stary kontener, `deploy.resources.limits` nie zastosowany)
  - Flow graph (938 MB) + Python + uvicorn reload nie miescily sie w 1 GiB → OOM → API nie odpowiadalo (504 Gateway Timeout)
  - Naprawiono: `docker compose up -d --force-recreate api` — poprawny limit 3 GiB, startup 85s

- **Laczny wynik:** 464 testow (413 + 51 nowych), wszystkie przechodza

### Stan bazy danych
| Tabela | Rekordy | Uwagi |
|--------|---------|-------|
| flow_network | 19,667,699 | 4 progi FA |
| stream_network | 82,624 | **2257 segmentow utraconych** — naprawa wymaga re-run pipeline |
| stream_catchments | 84,881 | 100: 76596, 1000: 7427, 10000: 779, 100000: 79 |
| depressions | 560,198 | vol=4.6M m³, max_depth=7.01 m |

### Znane problemy
- Frontend wymaga dalszego audytu jakosci kodu
- ~~stream_network ma mniej segmentow niz catchments (82624 vs 84881)~~ — **naprawione ADR-019**: migracja 010. Wymaga `alembic upgrade head` + re-run pipeline z `--clear-existing`
- `generate_tiles.py` wymaga tippecanoe (nie jest w pip, trzeba zainstalowac systemowo)
- Flow graph: `downstream_id` nie jest przechowywany w pamięci (zwracany jako None) — nie uzywany przez callery
- Migracja 009, 010 jeszcze nie uruchomione (`alembic upgrade head`)

### Nastepne kroki
1. `alembic upgrade head` (migracje 009 + 010)
2. Re-run pipeline z `--clear-existing` i weryfikacja: stream_count == catchment_count per threshold
3. Instalacja tippecanoe i uruchomienie `generate_tiles.py` na danych produkcyjnych
4. Benchmark `traverse_upstream`: in-memory vs SQL na 3 rozmiarach zlewni
5. Benchmark pipeline po optymalizacji (~22 min → szacowane ~6-8 min)
6. ~~Testy integracyjne e2e endpointow~~ — **zrobione**: 51 testow (profile, depressions, tiles)
7. Dlug techniczny: constants.py, hardcoded secrets
8. CP5: MVP — pelna integracja, deploy

## Backlog

- [x] Fix traverse_upstream resource exhaustion (ADR-015: pre-flight check, CTE LIMIT, statement_timeout, Docker limits)
- [x] CP4 Faza 1: Frontend — mapa + zlewnia + parametry (Leaflet.js, Bootstrap 5)
- [x] CP4: Warstwa NMT — naprawiona (L.imageOverlay zamiast L.tileLayer)
- [x] CP4: Warstwa ciekow (Strahler) — L.imageOverlay z dylatacja morfologiczna → zamieniona na MVT
- [x] CP4 Faza 2: Redesign glassmorphism + Chart.js + hydrogram + profil + zaglebie
- [x] CP4 Faza 3: Wektoryzacja ciekow MVT, multi-prog FA, hillshade, zaglbienia preprocessing
- [ ] CP5: MVP — pelna integracja, deploy
- [ ] Testy scripts/ (process_dem.py, import_landcover.py — 0% coverage)
- [ ] Utworzenie backend/core/constants.py (M_PER_KM, M2_PER_KM2, CRS_*)
- [ ] Usuniecie hardcoded secrets z config.py i migrations/env.py
- [ ] Problem jezior bezodplywowych (endorheic basins) — komorki bez odplywu moga powodowac niepoprawne wyznaczanie zlewni
- [ ] CI/CD pipeline (GitHub Actions)
