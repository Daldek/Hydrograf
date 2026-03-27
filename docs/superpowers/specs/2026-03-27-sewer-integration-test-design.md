# Spec: Integration Test — Sewer Pipeline z syntetycznym DEM

**Data:** 2026-03-27
**Autor:** Claude Code (sesja 75)
**Status:** Draft

## Cel

Test integracyjny walidujący pełny pipeline kanalizacji deszczowej: od budowy grafu sewer, przez modyfikację DEM i flow accumulation, po zapis do bazy PostGIS. Bez orchestratora `process_dem.py` — bezpośrednie wywołania funkcji z `sewer_service.py`.

## Zakres

**IN:**
- Syntetyczny DEM 100×100 (5m cellsize, EPSG:2180)
- Syntetyczna sieć kanalizacyjna (Y-junction: 2 inlety → junction → outlet)
- `build_sewer_graph()` — budowa grafu z GeoDataFrame
- `burn_inlets()` — obniżenie DEM w komórkach inletów
- pyflwdir: fill → fdir → acc na zmodyfikowanym DEM
- `reconstruct_inlet_fa()` — odtworzenie FA na inletach
- `route_fa_through_sewer()` — routing FA przez graf
- `propagate_fa_downstream()` — propagacja surplusu za outlet
- `insert_sewer_data()` — zapis do PostGIS + weryfikacja
- Walidacja `is_sewer_augmented` na `stream_network`

**OUT:**
- `download_sewer.py` (ładowanie danych z zewnętrznych źródeł)
- `process_dem.py` orchestrator (testujemy funkcje bezpośrednio)
- Frontend, MVT tiles, admin API
- Edge cases (cykle, rozłączne komponenty, brak outletów) — pokryte w unit testach

## Syntetyczny DEM

**Rozmiar:** 100×100 pikseli, cellsize=5m, EPSG:2180
**Origin:** xllcorner=500000.0, yllcorner=300000.0 (bbox: 500000–500500, 300000–300500)
**Nachylenie:** SE gradient — `elev = 200.0 - row * 1.0 - col * 0.5`
- Najwyższy punkt: (0,0) = 200m
- Najniższy punkt: (99,99) = 200 - 99 - 49.5 = 51.5m
- Naturalny odpływ w kierunku SE (prawy-dolny róg)
- Gradient 1.0/0.5 (nie 1.5/0.5) — łagodniejszy, aby burn 2.0m tworzył lokalne minimum

**Dolinka:** Wzdłuż kolumny 50 dodatkowe obniżenie -5m, tworzy naturalny ciek:
```python
dem[:, 48:53] -= 5.0  # 5-pikselowa dolinka
```

**Nodata:** dem[0, 0] = -9999.0 (narożnik NW)

## Syntetyczna sieć kanalizacyjna

**Topologia Y-junction:**
```
Inlet_A (row=20, col=30)  ──────►  Junction (row=50, col=50)  ──────►  Outlet (row=70, col=50)
Inlet_B (row=20, col=70)  ──────►        ↑
```

**Konwersja raster→geo (Affine transform):**
- x = xllcorner + col * cellsize + cellsize/2
- y = yllcorner + (nrows - row) * cellsize - cellsize/2

**Współrzędne geograficzne (EPSG:2180):**
| Node | Row | Col | X | Y | Elev (przed dolinką) |
|------|-----|-----|---|---|------|
| Inlet_A | 20 | 30 | 500152.5 | 300397.5 | 155.0 |
| Inlet_B | 20 | 70 | 500352.5 | 300397.5 | 135.0 |
| Junction | 50 | 50 | 500252.5 | 300247.5 | 100.0 |
| Outlet | 70 | 50 | 500252.5 | 300147.5 | 70.0 |

**GeoDataFrame — 3 LineStrings:**
1. Inlet_A → Junction (diag NW→SE)
2. Inlet_B → Junction (diag NE→SW)
3. Junction → Outlet (prosto na S)

**Atrybuty:** diameter_mm=300, material="PVC" (brak invert_elev — kierunek z topologii)

## Testy

### Plik: `backend/tests/integration/test_sewer_pipeline.py`

**Markers:** `@pytest.mark.db` na testach wymagających bazy

**Fixtures (scope=module):**
- `synthetic_dem` — numpy 100×100 + rasterio Affine transform
- `sewer_gdf` — GeoDataFrame z 3 LineStrings
- `sewer_graph` — wynik `build_sewer_graph(sewer_gdf)`
- `modified_dem` — DEM po `burn_inlets()`
- `hydro_rasters` — fdir + acc po pyflwdir processing
- `pipeline_state` — dict ze wszystkimi artefaktami (przekazywany między testami)

**Strategia stanów:** Jeden `@pytest.fixture(scope="module")` buduje cały pipeline raz i zwraca dict z wynikami. Poszczególne testy walidują fragmenty.

### Test 1: `test_build_sewer_graph`
- `build_sewer_graph(sewer_gdf, snap_tolerance_m=2.0)` zwraca SewerGraph
- 4 nodes: 2× inlet, 1× junction, 1× outlet
- 3 edges
- 1 komponent (n_components=1)
- adj matrix shape = (4, 4)
- Brak warnings

### Test 2: `test_burn_inlets`
- Mapowanie node (x,y) → (row,col) przez `~transform * (x, y)`
- `burn_inlets(dem_copy, inlets, default_depth_m=2.0)` modyfikuje DEM
- DEM w komórkach inletów obniżony o 2.0m
- `dem_elev_m` i `burn_elev_m` ustawione na node dicts
- `burn_elev_m < dem_elev_m` dla każdego inletu
- Zwraca listę drain_points z 2 elementami

### Test 3: `test_hydrology_processing`
- pyflwdir: `dem_filled = pyflwdir.dem.fill_depressions(dem_modified)`
- fdir via `pyflwdir.from_dem()` → D8 flow direction
- acc via `flw.accuflux()` → flow accumulation
- fdir shape == dem shape
- acc > 0 w większości komórek (poza nodata)
- acc rośnie w kierunku SE (max w prawym-dolnym rogu lub w dolince)

### Test 4: `test_reconstruct_inlet_fa`
- `reconstruct_inlet_fa(acc, fdir, inlets)` ustawia `fa_value`
- `fa_value > 0` dla obu inletów (mają contributing area)
- `fa_value` typu int

### Test 5: `test_route_fa_through_sewer`
- `route_fa_through_sewer(sewer_graph)` ustawia `total_upstream_fa` na outlecie
- outlet.total_upstream_fa == inlet_A.fa_value + inlet_B.fa_value
- junction i inlety mają total_upstream_fa == None

### Test 6: `test_propagate_fa_downstream`
- Kopia acc przed propagacją
- `propagate_fa_downstream(acc, fdir, outlets)` modyfikuje acc
- FA w komórce outletu wzrósł: `acc_after[outlet_row, outlet_col] > acc_before[outlet_row, outlet_col]`
- FA downstream od outletu (wzdłuż fdir) również wzrósł
- Przyrost == outlet.total_upstream_fa

### Test 7: `test_insert_sewer_data` (`@requires_db`)
- `insert_sewer_data(sewer_graph, db_session, source_file="synthetic_test")`
- SELECT COUNT(*) FROM sewer_nodes → 4
- SELECT COUNT(*) FROM sewer_network → 3
- Outlet node: node_type='outlet', total_upstream_fa > 0
- Inlet nodes: node_type='inlet', fa_value > 0
- Edges: length_m > 0, source='synthetic_test'
- Geometrie w SRID 2180

### Test 8: `test_sewer_augmented_flag` (`@requires_db`)
- Wymaga stream_network z segmentami w okolicy outletu
- Wstawienie syntetycznego segmentu stream_network blisko outletu (< 50m)
- Po `insert_sewer_data()`: `is_sewer_augmented = TRUE` na tym segmencie

## Zależności

- `numpy`, `pyflwdir`, `rasterio` (transform), `geopandas`, `shapely`, `scipy`
- `sqlalchemy` (db_session z conftest_db.py)
- Marker `@pytest.mark.db` + `@requires_db` z conftest_db.py

## Konwencje

- Plik: `backend/tests/integration/test_sewer_pipeline.py`
- Fixtures w tym samym pliku (scope=module, specyficzne dla tego testu)
- Nazewnictwo: `area_km2`, `elevation_m`, `depth_m` etc.
- Assertions: `np.testing.assert_*`, standardowe `assert`
