# PROGRESS — Hydrograf

## Status projektu

| Element | Status | Uwagi |
|---------|--------|-------|
| API (FastAPI + PostGIS) | ✅ Gotowy | 6 endpointow (+ tiles DEM/MVT streams): delineate, hydrograph, scenarios, profile, depressions, health |
| Wyznaczanie zlewni | ✅ Gotowy | traverse_upstream, concave hull |
| Parametry morfometryczne | ✅ Gotowy | area, slope, length, CN + 11 nowych wskaznikow |
| Generowanie hydrogramu | ✅ Gotowy | SCS-CN, 42 scenariusze |
| Preprocessing NMT | ✅ Gotowy | pyflwdir + COPY (3.8 min/arkusz), stream burning |
| Integracja Hydrolog | ✅ Gotowy | v0.5.2 |
| Integracja Kartograf | ✅ Gotowy | v0.4.1 (NMT, NMPT, Orto, Land Cover, HSG, BDOT10k hydro) |
| Integracja IMGWTools | ✅ Gotowy | v2.1.0 (opady projektowe) |
| CN calculation | ✅ Gotowy | cn_tables + cn_calculator + determine_cn() |
| Frontend | 🔶 Faza 3 gotowa | CP4 — wektorowe cieki MVT, hillshade, zaglebieniaprzed procesowanie |
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

**Data:** 2026-02-12

### Co zrobiono
- **Naprawa ADR-016 — przepisanie `delineate_subcatchments()` na pyflwdir:**
  - `delineate_subcatchments()` — zastapienie podwojnej petli Pythonowej przez `pyflwdir.FlwdirRaster.basins()` (O(n), C/Numba)
  - Obiekt `FlwdirRaster` tworzony raz w `process_dem()` i reuzywany (zamiast tworzenia lokalnie w kazdej funkcji)
  - Call site zaktualizowany: `fdir` → `flw`
  - ADR-016: status Oczekuje → Przyjeta (opcja B)
  - Dokumentacja: COMPUTATION_PIPELINE.md (sekcja 1.7, tabela algorytmow), PROGRESS.md

### Znane problemy
- **Baza danych — niekompletne dane:** `stream_network` ma dane tylko dla progu 100 m² (397 seg.), `stream_catchments` = 0 rekordow, `depressions` = 0. Pliki posrednie GeoTIFF (10 plikow, 356 MB) zapisane poprawnie.
- Warstwa catchments i streams — wymagaja weryfikacji e2e z pelnym zestawem progow
- Frontend wymaga dalszego audytu jakosci kodu

### Nastepne kroki
1. **Uruchomic pelny pipeline obliczeniowy:**
   ```bash
   docker compose up -d db
   cd backend && .venv/bin/python -m scripts.process_dem \
     --input ../data/e2e_test/dem_mosaic.vrt \
     --burn-streams ../data/e2e_test/hydro/bdot10k_hydro_godlo_N_33_131_C_b_2.gpkg \
     --burn-depth 5.0 \
     --thresholds "100,1000,10000,100000" \
     --save-intermediates \
     --output-dir ../data/e2e_test/intermediates \
     --clear-existing
   ```
2. Zweryfikowac baze: `stream_network` (4 progi), `stream_catchments` (>0), pliki posrednie
3. Uruchomic `generate_depressions.py` + `export_pipeline_gpkg.py`
4. Testy integracyjne e2e nowych endpointow (streams MVT, catchments MVT, thresholds, profile, depressions)
5. Dlug techniczny: constants.py, hardcoded secrets
6. CP5: MVP — pelna integracja, deploy

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
