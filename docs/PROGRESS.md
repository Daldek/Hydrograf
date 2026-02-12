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
| Frontend | 🔶 Faza 3 gotowa | CP4 — wektorowe cieki MVT, BDOT10k zbiorniki+cieki, hillshade, zaglbienia preprocessing |
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

**Data:** 2026-02-12 (sesja 8)

### Co zrobiono

- **Klastrowanie zbiornikow w `classify_endorheic_lakes()`:**
  - Bufor 20m + `unary_union` — stykajace sie jeziora/mokradla sa lączone w klastry
  - Jezeli dowolny element klastra ma odplyw → caly klaster jest przeplywowy
  - Naprawia blad: male jeziorka polaczone przez szuwary z duzym jeziorem przeplywowym byly blednie klasyfikowane jako bezodplywowe
  - 4 nowe testy klastrowania w `test_lake_drain.py` (laczenie, propagacja, odleglosc, lancuch)
  - Diagnostyka rozszerzona o `clusters` count

- **Frontend — warstwy BDOT10k:**
  - Zbiorniki wodne (OT_PTWP_A) jako warstwa GeoJSON z checkbox + suwak przezroczystosci
  - Cieki BDOT10k (OT_SWRS_L/SWKN_L/SWRM_L) jako warstwa GeoJSON, kolorowanie wg typu cieku
  - Eksport `bdot_lakes.geojson` (68 features, 107 KB) + `bdot_streams.geojson` (92 features, 67 KB)
  - Nowa funkcja `addBdotOverlayEntry()` w `layers.js` — async loading GeoJSON

- **Frontend — wylaczanie podkladu:**
  - Opcja "Brak" w podkladach kartograficznych — calkowite wylaczenie warstwy podkladowej
  - `setBaseLayer('none')` bezpiecznie usuwa biezacy podklad

- **nginx:** obsluga `.geojson`, kompresja `application/geo+json`

- **Zmiana domyslnej glebokosci wypalania ciekow:** `burn_depth_m` 5m → 10m w `burn_streams_into_dem()`

- **Laczny wynik:** 484 testy, wszystkie przechodza

### Stan bazy danych
| Tabela | Rekordy | Uwagi |
|--------|---------|-------|
| flow_network | 19,667,650 | 4 progi FA, re-run z endorheic lakes |
| stream_network | 86,789 | 100: 78101, 1000: 7784, 10000: 812, 100000: 92 (17 geohash collisions) |
| stream_catchments | 86,806 | 100: 78113, 1000: 7788, 10000: 813, 100000: 92 |
| depressions | 581,553 | vol=1.16M m³, max_depth=7.01 m |

### Znane problemy
- Frontend wymaga dalszego audytu jakosci kodu
- `generate_tiles.py` wymaga tippecanoe (nie jest w pip, trzeba zainstalowac systemowo)
- Flow graph: `downstream_id` nie jest przechowywany w pamięci (zwracany jako None) — nie uzywany przez callery
- 17 segmentow stream_network (prog 100 m²) odrzuconych przez geohash collision — marginalny problem
- Pliki `bdot_*.geojson` sa statyczne — po re-run pipeline wymagaja ponownego eksportu

### Nastepne kroki
1. Re-run pipeline z klastrowaniem zbiornikow (weryfikacja wynikow)
2. Instalacja tippecanoe i uruchomienie `generate_tiles.py` na danych produkcyjnych
3. Benchmark `traverse_upstream`: in-memory vs SQL na 3 rozmiarach zlewni
4. Dlug techniczny: constants.py, hardcoded secrets
5. CP5: MVP — pelna integracja, deploy

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
- [x] Problem jezior bezodplywowych (endorheic basins) — ADR-020: klasyfikacja + drain points
- [ ] CI/CD pipeline (GitHub Actions)
