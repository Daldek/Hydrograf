# Integracja Hydrograf ↔ Hydrolog

**Data utworzenia:** 2026-01-20
**Ostatnia aktualizacja:** 2026-11-11 (the network hand-off with every control point a node, `J…` at a confluence and `P…` elsewhere, numbered from the closing section upward, the outlet `O` and the names and `node_provenance` of plan `2026-11-11-network-nodes`; Hydroni and kaczawa2 run `930915d` with `develop` `a46adb4`; the names of the network hand-off after the two kinds of ADR-080, and Hydrolog's `3aab136`; 2026-11-10: the hand-off of a network, ADR-080; Hydrolog `930915d` of `develop`, the release set candidate-3 of Nogat; was `759d7ef` of candidate-2, before it `4fad769`, the TR-55 rows of Hydrograf's covers and water at CN 98, which production still runs)
**Status:** ✅ Zaimplementowane (CP3+)

---

## Cel

Umożliwić łatwą wymianę danych między Hydrografem (analizy przestrzenne GIS) a Hydrologiem (obliczenia hydrologiczne), z możliwością integracji z innymi systemami.

---

## Podział odpowiedzialności

```
┌─────────────────────────────────────────────────────────────────┐
│                         HYDROGRAF                               │
│  Odpowiedzialność: ANALIZY PRZESTRZENNE (GIS)                   │
│                                                                 │
│  - Wyznaczanie zlewni z NMT (CatchmentGraph BFS)                │
│  - Obliczanie parametrów geometrycznych z boundary/cells        │
│  - Obliczanie statystyk wysokości z DEM (zonal_stats)           │
│  - Obliczanie CN z pokrycia terenu (cn_calculator + cn_tables)  │
│  - Interpolacja opadów (IDW/Thiessen, Obserwator PMAXTP)        │
│  - Śledzenie głównego cieku (trace_main_channel)                │
│                                                                 │
│  OUTPUT: JSON zgodny ze schematem WatershedParameters           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │  STANDARYZOWANY FORMAT JSON   │
              │  (WatershedParameters schema) │
              └───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         HYDROLOG                                │
│  Odpowiedzialność: OBLICZENIA HYDROLOGICZNE                     │
│                                                                 │
│  - Czas koncentracji (Kirpich, NRCS, Giandotti,                 │
│      FAA, Kerby, Kerby-Kirpich)                                 │
│  - Hydrogramy jednostkowe (SCS, Nash, Clark, Snyder)            │
│  - Transformacja opad→odpływ (splot)                            │
│  - Wskaźniki kształtu zlewni                                    │
│  - Krzywa hipsograficzna                                        │
│  - Hietogramy (Beta, Block, Euler II)                           │
│                                                                 │
│  INPUT: WatershedParameters.from_dict(json_data)                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Format wymiany danych

### JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "WatershedParameters",
  "description": "Standaryzowany format parametrów zlewni dla integracji GIS ↔ Hydrolog",
  "type": "object",
  "required": ["area_km2", "perimeter_km", "length_km", "elevation_min_m", "elevation_max_m"],
  "properties": {
    "name": {"type": "string", "description": "Nazwa zlewni"},
    "area_km2": {"type": "number", "minimum": 0, "description": "Powierzchnia [km²]"},
    "perimeter_km": {"type": "number", "minimum": 0, "description": "Obwód [km]"},
    "length_km": {"type": "number", "minimum": 0, "description": "Długość zlewni [km]"},
    "elevation_min_m": {"type": "number", "description": "Min wysokość [m n.p.m.]"},
    "elevation_max_m": {"type": "number", "description": "Max wysokość [m n.p.m.]"},
    "elevation_mean_m": {"type": "number", "description": "Średnia wysokość [m n.p.m.]"},
    "mean_slope_m_per_m": {"type": "number", "minimum": 0, "description": "Średni spadek [m/m]"},
    "channel_length_km": {"type": "number", "minimum": 0, "description": "Długość cieku [km]"},
    "channel_slope_m_per_m": {"type": "number", "minimum": 0, "description": "Spadek cieku [m/m]"},
    "longest_flow_path_km": {"type": "number", "minimum": 0, "description": "Najdłuższa ścieżka spływu [km]"},
    "divide_flow_path_km": {"type": "number", "minimum": 0, "description": "Droga spływu z działu wodnego [km]"},
    "centroid_flow_path_km": {"type": "number", "minimum": 0, "description": "Droga spływu z centroidu [km] (dla modeli izochron)"},
    "cn": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Curve Number"},
    "source": {"type": "string", "description": "Źródło danych"},
    "crs": {"type": "string", "description": "Układ współrzędnych"}
  }
}
```

### Przykład JSON (output z Hydrografa)

```json
{
  "name": "Zlewnia potoku X",
  "area_km2": 45.3,
  "perimeter_km": 32.1,
  "length_km": 12.5,
  "elevation_min_m": 150.0,
  "elevation_max_m": 520.0,
  "elevation_mean_m": 340.0,
  "mean_slope_m_per_m": 0.025,
  "channel_length_km": 8.2,
  "channel_slope_m_per_m": 0.045,
  "longest_flow_path_km": 14.2,
  "divide_flow_path_km": 13.8,
  "centroid_flow_path_km": 9.1,
  "cn": 72,
  "source": "Hydrograf",
  "crs": "EPSG:2180"
}
```

---

## Przekazanie do GUI Hydrologa (`nogat-handoff/1`, ADR-068)

GUI Hydrologa („Wczytaj z Hydrografa” w „Hydrogramie zlewni”) czyta kopertę Nogata
`nogat-handoff/1` (kopia: `schemas/nogat/handoff-1.schema.json`) z dokumentem
`hydrolog-network/1`: jedna zlewnia cząstkowa `Z1` (pola `WatershedParameters`,
`length_to_centroid_km` jako `Lc_km`) i wylot `OUT`. Buduje je `backend/core/handoff.py`:

- `POST /api/delineate-watershed` → `handoff`: sama zlewnia, bez opadu i wyniku;
- `POST /api/generate-hydrograph` → `handoff`: zlewnia z `runoff` (SCS-CN z użytym
  `tc_min`, n i K Nasha albo L, Lc, Ct, Cp Snydera; AMC), `rainfall` (opad projektowy
  PMAXTP z kształtem hietogramu albo własny szereg), `timestep_min` i `result` (Qmax,
  czas do szczytu, objętość, `computed_with` z wersją Hydrologa). Wartości są te, których
  użyło obliczenie, bez zaokrągleń: `hydrograph generate` Hydrologa daje z nich ten sam
  wynik (`backend/tests/unit/test_handoff.py`).

Pochodzenie (`provenance`): zlewnia z Hydrografa z ujściem i polami zmienionymi w trybie
zaawansowanym (pole żądania `morphometry_origin`; bez niego `user`), opad `pmaxtp`
(POT, prawdopodobieństwo, czas trwania, punkt żądania, `interpolation: idw`) albo `user`,
parametry odpływu (metoda tc, estymacja Nasha). W interfejsie: „Kopiuj do Hydrologa” i
„Plik przekazania” pod sekcjami panelu „Zlewnia” (`frontend/js/handoff.js`).

Nash by Lutz travels as Lutz (ADR-068, erratum 2026-11-05): the watershed carries Lutz's
inputs `manning_n` (0.035), `forest_pct` and `urban_pct` (the land cover shares the
computation used) and the provenance of `runoff` is Hydrolog's own record `{"source":
"hydrograf", "method": "lutz"}`, so Hydrolog opens Nash in Lutz mode and its `uh nash`
gives Hydrograf's n and K; `runoff` keeps them for the recomputation.

The hand-off of a hydrograph with a PMAXTP rainfall, or with an own series copied from one
(`custom_precipitation.derived_from`), carries the top-level `attribution` and
`terms_notice` of Nogat DEV-20.6 and DEV-20.7 (ADR-083; the copy of the schema from Nogat
`bbb58a8`): the lines the PMAXTP terms require, which Hydrolog shows with the loaded data and
carries into its own products. The hand-offs of a delineation and of a network hold no
PMAXTP value and have neither field.

---

## The hand-off of a network (`POST /api/delineate-network`, ADR-080)

`POST /api/delineate-network` returns in `handoff` one `nogat-handoff/1` around one
`hydrolog-network/1` holding the whole network, for Hydrolog's „Sieć i trasowanie”
(`build_network_handoff` in `backend/core/handoff.py`; plans
`docs/plans/2026-11-10-network-delineation.md`, D14 and D15, and
`docs/plans/2026-11-11-network-nodes.md`, N1, N7 and N8). The envelope is the copy of
Nogat `8848c26` with the optional `node_provenance` (`schemas/nogat/README.md`).

Every control point is a node of the network, the closing section included: `J<n>` at a
confluence (a point drawn to one within 50 m, or a junction the network makes) and `P<n>`
elsewhere. The ids are the network's, numbered by a walk from the closing section upward,
each kind on its own (the closing section is `J1` or `P1`); the request's ids are only the
client's handles and never reach the hand-off.

- **Envelope:** `schema`, `created_at`, `producer` (`hydrograf` and its version),
  `subject` = the closing section's `name`, else `watershed_name` of its place, then „, sieć”
  and the number of subcatchments in parentheses („Kaczawa, sieć (3 zlewnie)”, „…, sieć
  (5 zlewni)”); `provenance.watershed` = `{source: "hydrograf", point: <the closing
  section's node id, J1 or P1>, latitude, longitude, threshold_m2}`, its snapped place and
  the network the points snapped to.
- **Payload:** `name` (= `subject`), `description` („Sieć zlewni do przekroju zamykającego
  J1 (Kaczawa), wyznaczona w Hydrografie: …”: the counts of subcatchments, reaches and
  junctions, and that the rainfall and the reach sections are given in Hydrolog) and
  `nodes`. Each node comes after every node it receives: at each node the trunk (the main
  river, the larger upstream area) first, then the branches by accumulation. For the closing
  section alone at a confluence: `Z1` (headwater, the main river), `Z2` (headwater), `J1`,
  `O`. For the closing section mid-river with a point up a tributary: the main river's
  headwater above the tributary's mouth, the headwater above the point, the point's `P2`,
  `R2` and its przyrzecze, `J1` (the mouth, a junction of the network), `R1` and its
  przyrzecze, `P1` (the closing section), `O`.
- **Subcatchment** (`Z…`): `watershed` in the keys of `WatershedParameters`
  (`watershed_parameters` of its morphometry), with `area_km2` exact to the cell
  (6 decimals), so the subcatchments sum to the closing section's catchment in Hydrolog too;
  `runoff` `{"model": "curve-number"}` with Hydrolog's defaults.
- **Reach** (`R…`): `method` `muskingum-cunge`, `from` (one node), `length_km` (the
  difference of the flow distances of its ends), `slope_m_per_m` (the NMT at its ends);
  no section. A reach whose NMT does not fall (slope 0.0001, „minimum”) is `method`
  `lag`, `from`, `lag_min` = max(1, round(1000 · `length_km` / 0.5 / 60)) instead (ADR-080
  D10a): the pinned Hydrolog's Muskingum-Cunge refuses a flat reach at any time step
  (`unstable_timestep`). Hydrolog's `develop` since `3aab136` (its ADR-0026) routes a reach
  that Muskingum-Cunge cannot grid as linear reservoirs with the warning
  `diffusion_dominated` instead; the pin `930915d` predates it.
- **Junction** (`J…` and `P…`, one per node): `from`, its inflows, the trunk first.
  **Outlet** `O` (was `OUT`): `from` the closing section's node. Hydrolog finds the outlet by
  its type and labels the nodes by their ids, so its canvas shows `J…`, `P…` and `O`.
- **Descriptions** (Polish, at most 500 characters; control characters but the line feed
  become spaces): a headwater „Dopływ do J4 (ciek główny)” (the main river into a node),
  „Dopływ do J4” (another branch) or „Dopływ do P3” (above a `P`), by the node's id only (the
  name of the node's point is the node's own description); przyrzecze „Przyrzecze odcinka R4”,
  each followed by its area; reach „Odcinek od
  J1 do J2: 5,07 km, spadek 0,98 ‰ (NMT)” or „(minimalny)”, a lag followed by „Opóźnienie
  2 min (długość przy 0,5 m/s) zamiast Muskingum-Cunge, …”; a node „Zbieg: Paszówka” (a point
  drawn to a confluence; „Zbieg” without a name or made by the network), „Punkt: Nysa Mała”
  (a `P`; „Punkt” without a name) or „Przekrój zamykający: Kaczawa” (the closing section, at a
  confluence or not; „Przekrój zamykający” without a name).

`node_provenance` has an entry for every subcatchment, reach and junction and none for
`O`; `source` is `"hydrograf"` in each. Hydrolog's GUI reads `element`, `point` and `reach`
(`handoff/mapping.js`) and ignores the other keys:

| Node | Input | Origin parameters |
|---|---|---|
| subcatchment | `watershed` | `element` (`headwater`, `intermediate`), `point` (when it enters the node of a person's point: that node's id, which Hydrolog shows for a headwater as „dopływ do punktu J4”), `reach` (of a przyrzecze), `latitude`, `longitude` (its outlet) |
| reach | `node` | `element` `"reach"`, `length` `"flow_distance"`, `slope` `"nmt"` or `"minimum"`, `upstream_elevation_m` and `downstream_elevation_m` (the NMT at its ends, when known), `vector_length_km` with `vector_source` `"bdot10k"` (when the reach has a BDOT10k check length); a lag (slope `"minimum"`) also `length_km`, `slope_m_per_m`, `method` `"lag"`, `method_reason` `"flat"` and `lag_celerity_m_per_s` 0.5 |
| junction | `node` | `element` (`confluence` for one the network made, `point` for a person's point, `J` or `P`, `outlet` for the closing section), `name` (its point's, when it has one), `at_node` (only when true: the point was drawn to the node), `latitude`, `longitude` |

The hand-off carries no `rainfall`, `timestep_min`, `result`, reach section or `position`.
In Sieć the person sets the rainfall of the network (step „Sieć”) and gives each
Muskingum-Cunge reach its section (Manning's n, width) before the network is routed; Sieć
lays the network out from its structure. The hand-offs of `delineate-watershed` and
`generate-hydrograph` do not change: one subcatchment `Z1` into the outlet `OUT`.

The pin: Hydrolog `930915d` (Nogat's release set candidate-3, `b0ac85b`) has the
`description` (and `position`) of every node in `hydrolog-network/1`, which a network's
hand-off needs (Hydrolog `46c743f` or later). The pinned Hydrolog reads the envelope copy of
Nogat `8727f6e` and takes `node_provenance` as an unknown field; its step 3 of the Nogat plan
`2026-11-10-node-provenance-in-handoff` (`cead00a`, in Hydrolog's `develop` after `930915d`)
copies `8848c26`.
`backend/tests/unit/test_network_endpoint.py` and
`backend/tests/integration/test_network_delineation_db.py` validate the hand-off against
the envelope copy and the pinned Hydrolog's `hydrolog-network/1`.

---

## Zaimplementowane komponenty

### 1. Moduł: `backend/core/morphometry.py`

**Status:** ✅ Zaimplementowane

Funkcje:
- `calculate_shape_indices(area_km2, perimeter_km, length_km)` - wskaźniki kształtu (Kc, Rc, Re, Ff, Cl, W)

Pozostałe parametry (powierzchnia, obwód, długość, wysokości, spadek, ciek główny, wskaźniki rzeźby i drenażu) liczy `build_morph_dict_from_graph()` w `core/watershed_service.py` z grafu zlewni cząstkowych; ciek główny wyznacza `CatchmentGraph.trace_main_channel()`.

### 2. Moduł: `backend/core/morphometry_raster.py`

**Status:** ✅ Zaimplementowane (CP4+)

Obliczenia rastrowe na numpy arrays:
- `compute_slope(dem, cellsize, nodata)` - spadek terenu (Sobel)
- `compute_aspect(dem, cellsize, nodata)` - ekspozycja
- `compute_twi(dem, fac, cellsize, nodata)` - Topographic Wetness Index
- `compute_strahler_order(fdir, fac, threshold)` - rząd Strahlera

### 3. Moduł: `backend/core/catchment_graph.py`

**Status:** ✅ Zaimplementowane (CP4+)

In-memory graf zlewni (~44k nodes, ~0.5 MB):
- `traverse_upstream(node_idx)` - BFS w górę sieci
- `aggregate_stats(indices)` - agregacja parametrów (area, elevation, slope)
- `trace_main_channel(segment_idx, threshold)` - śledzenie głównego cieku (do channel_slope)
- `find_catchment_at_point(x, y, threshold, db)` - lokalizacja zlewni cząstkowej (ST_Contains)

### 4. Moduł: `backend/core/watershed_service.py`

**Status:** ✅ Zaimplementowane (CP4+)

Wspólna logika serwisowa:
- `build_morph_dict_from_graph(cg, indices, boundary, ...)` - buduje dict morfometryczny z CatchmentGraph
- `get_stream_info_by_segment_idx(segment_idx, threshold, db)` - info o segmencie po indeksie (ADR-026)
- `merge_catchment_boundaries(segment_idxs, threshold, db)` - łączenie granic z wygładzaniem (Chaikin, ADR-032)

### 5. Schematy Pydantic: `backend/models/schemas.py`

**Status:** ✅ Zaimplementowane

Dodane klasy:
- `MorphometricParameters` - parametry morfometryczne zgodne z Hydrolog
- `HydrographRequest` - request do generowania hydrogramu
- `HydrographResponse` - pełna odpowiedź z hydrogramem
- `PrecipitationInfo` - informacje o opadzie i hietogramie
- `HydrographInfo` - dane hydrogramu (times, discharge, peak, volume)
- `WaterBalance` - bilans wodny (CN, retention, effective rainfall)
- `HydrographMetadata` - metadane obliczeń (tc, metoda, model UH)

### 6. Endpoint: `POST /api/generate-hydrograph`

**Status:** ✅ Zaimplementowane

**Plik:** `backend/api/endpoints/hydrograph.py`

**Importy Hydrologa:**
```python
from hydrolog.morphometry import WatershedParameters
from hydrolog.precipitation import BetaHietogram, BlockHietogram, EulerIIHietogram
from hydrolog.runoff import HydrographGenerator, NashIUH
from hydrolog.time.concentration import ConcentrationTime
```

**Przepływ danych:**
1. Walidacja parametrów (duration, probability)
2. Transformacja współrzędnych WGS84 → PL-1992
3. Lokalizacja zlewni cząstkowej (CatchmentGraph + ST_Contains)
4. BFS w górę sieci (traverse_upstream)
5. Agregacja statystyk + sprawdzenie limitu 250 km²
6. Budowa granicy zlewni (merge + Chaikin smoothing)
7. Obliczenie CN z pokrycia terenu (land_cover + cn_tables)
8. Budowa dict morfometrycznego (build_morph_dict_from_graph)
9. Pobranie opadu: the watershed mean of `precipitation_data` by Thiessen polygons (**Hydrolog:** `thiessen_polygons`, ADR-069); without a boundary IDW at the point (**Hydrolog:** `inverse_distance_weighting`)
10. **Hydrolog:** `WatershedParameters.from_dict()` → `calculate_tc()`
11. **Hydrolog:** Hietogram (Beta/Block/Euler II) → `generate()`
12. **Hydrolog:** `HydrographGenerator` → `generate()`
13. Budowa odpowiedzi JSON

**Parametry wejściowe:**
- `latitude`, `longitude` - współrzędne WGS84
- `duration` - czas trwania opadu: 5min, 10min, 15min, 30min, 45min, 1h, 1.5h, 2h, 3h, 6h, 12h, 18h, 24h, 36h, 48h, 72h
- `probability` - prawdopodobieństwo: 1%, 2%, 5%, 10%, 20%, 50%
- `timestep_min` - krok czasowy (default: 5 min)
- `tc_method` - metoda tc: kirpich, nrcs, giandotti, faa, kerby, kerby_kirpich
- `hietogram_type` - typ hietogramu: beta, block, euler_ii
- `uh_model` - model hydrogramu jednostkowego: scs, snyder, nash
- `nash_estimation` - metoda estymacji Nash IUH: from_lutz, from_urban_regression
- `snyder_ct` - współczynnik opóźnienia Snydera (default: 1.5)
- `snyder_cp` - współczynnik szczytu Snydera (default: 0.6)
- `tc_runoff_coeff` - współczynnik spływu C metody FAA (0 < C ≤ 1, z tab. I FAA 1970, AC 150/5320-5B); wymagany dla `faa`, nigdy nie liczony z CN
- `tc_retardance` - współczynnik oporu N Kerby'ego (0,02–0,8, tabela Kerby'ego / TxDOT HDM); wymagany dla `kerby` i `kerby_kirpich`, bez wartości domyślnej
- `morphometry` - morfometria (tryb zaawansowany), w tym `flow_path_length_km`, `flow_path_slope_m_per_m`, `overland_length_km`, `overland_slope_m_per_m`

**Ograniczenia:**
- Maksymalna powierzchnia zlewni: 250 km² (limit metody SCS-CN)

### 7. Endpoint: `GET /api/scenarios`

**Status:** ✅ Zaimplementowane

Zwraca dostępne kombinacje parametrów hydrogramu (durations, probabilities, tc_methods, hietogram_types, area_limit_km2).

### 8. Rozszerzenie endpointu watershed

**Status:** ✅ Zaimplementowane

Endpoint `/api/delineate-watershed` zwraca teraz `morphometry` w odpowiedzi.

### 9. Skrypt: `scripts/analyze_watershed.py`

**Status:** ✅ Zaimplementowane

Skrypt CLI do pełnej analizy zlewni (offline). Używa rozszerzonych importów Hydrologa:
```python
from hydrolog.morphometry import WatershedParameters
from hydrolog.precipitation import BetaHietogram
from hydrolog.runoff import SCSCN, HydrographGenerator, SCSUnitHydrograph
```

---

## Moduły Hydrografa korzystające z Hydrologa

| Moduł | Importy z Hydrologa | Zastosowanie |
|-------|---------------------|--------------|
| `api/endpoints/hydrograph.py` | `WatershedParameters`, `BetaHietogram`, `BlockHietogram`, `EulerIIHietogram`, `HydrographGenerator`, `NashIUH`, `ConcentrationTime` | Endpoint API generowania hydrogramu |
| `core/precipitation.py` | `Station`, `thiessen_polygons`, `inverse_distance_weighting` | The PMAXTP design depth: the watershed mean, IDW at a point (ADR-069) |
| `scripts/analyze_watershed.py` | `WatershedParameters`, `BetaHietogram`, `SCSCN`, `HydrographGenerator`, `SCSUnitHydrograph` | Skrypt CLI pełnej analizy |
| `core/morphometry.py` | `WatershedParameters` (w docstring/example) | Dokumentacja formatu wymiany |

---

## Lista zmian - podsumowanie

### Hydrograf (CP3+)

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/pyproject.toml` | + hydrolog (commit `930915d`, 1.0.0.dev0; was v0.6.3, ADR-060) | ✅ |
| `backend/core/morphometry.py` | `calculate_shape_indices` (wskaźniki kształtu) | ✅ |
| `backend/core/morphometry_raster.py` | Obliczenia rastrowe (slope, aspect, TWI, Strahler) | ✅ |
| `backend/core/catchment_graph.py` | In-memory graf, BFS, trace_main_channel | ✅ |
| `backend/core/watershed_service.py` | build_morph_dict_from_graph, boundary smoothing | ✅ |
| `backend/core/cn_calculator.py` | Obliczanie CN z Kartografa (HSG + land cover) | ✅ |
| `backend/core/cn_tables.py` | Tablice CN dla BDOT10k + BUBD | ✅ |
| `backend/core/land_cover.py` | CN z tabeli land_cover (spatial intersection) | ✅ |
| `backend/models/schemas.py` | 7 klas Pydantic (MorphometricParameters, etc.) | ✅ |
| `backend/api/endpoints/watershed.py` | Unified endpoint — tryb precomputed (snap-to-stream + BFS) i precise (pyflwdir on-the-fly), morphometry w response (ADR-050) | ✅ |
| `backend/api/endpoints/hydrograph.py` | Endpoint hydrogramu (CatchmentGraph BFS) | ✅ |
| `backend/api/main.py` | + router hydrograph | ✅ |
| `backend/api/endpoints/network.py`, `backend/core/handoff.py` | `POST /api/delineate-network` and `build_network_handoff`: the hand-off of a network (ADR-080) | ✅ |
| `backend/scripts/analyze_watershed.py` | Skrypt CLI pełnej analizy z Hydrologiem | ✅ |
| `backend/tests/unit/test_morphometry.py` | Testy wskaźników kształtu | ✅ |
| `backend/tests/integration/test_hydrograph.py` | 16 testów integracyjnych | ✅ |

### Hydrolog

| Plik | Zmiana | Status |
|------|--------|--------|
| `hydrolog/morphometry/watershed_params.py` | WatershedParameters | ✅ |
| `hydrolog/morphometry/geometric.py` | + `from_dict()` | ✅ |
| `hydrolog/morphometry/terrain.py` | + `from_dict()` | ✅ |

---

## Uwaga: channel_slope vs stream_length vs flow_path

Od ADR-029 rozróżniamy dwa pomiary długości cieków:

- **`aggregate_stats()["stream_length_km"]`** = suma długości CAŁEJ sieci cieków (do drainage density)
- **`trace_main_channel()`** = długość GŁÓWNEGO cieku (do channel_slope i tc)

Różnica może wynosić 2-10x. Channel slope MUSI być obliczany z głównego cieku.

### Ścieżki spływu (flow path tracing)

Od migracji 023 dostępne są dodatkowe parametry długościowe oparte na ścieżkach spływu:

- **`longest_flow_path_km`** — najdłuższa ścieżka spływu w zlewni (hydraulic length). Agregacja `max_flow_dist_m` z subcatchments przez CatchmentGraph. Geometria dostępna jako `longest_flow_path_geojson`
- **`divide_flow_path_km`** — najdłuższa droga spływu od granicy zlewni do ujścia: największa odległość spływu (`stream_distance.tif`) w komórkach granicy zlewni (komórki jej zlewni cząstkowych z rastra `dem_mosaic_10_subcatchments_<próg>.tif` z sąsiadem poza zlewnią) minus baza ujścia jak dla `longest_flow_path_km`, więc nigdy od niej dłuższa (`core/divide_flow_path.py`). `null`, gdy zaczyna się w komórce początkowej najdłuższej drogi spływu (to ta sama droga). Geometria `divide_flow_path_geojson` po kierunkach spływu D8 tylko do pierwszej komórki wspólnej z najdłuższą drogą spływu (dalej drogi D8 się pokrywają); właściwości `length_km` (cała droga) i `own_length_km` (pokazany odcinek). Nie wchodzi do Tc
- **`centroid_flow_path_km`** — odległość spływu z centroidu zlewni do ujścia. Point sampling `stream_distance.tif` na centroidzie. Dostępny dla modeli izochron (wewnętrzny, ukryty w GUI)

---

## Metody czasu koncentracji (Tc)

Tc liczy wyłącznie Hydrolog: `_calculate_tc` (`api/endpoints/hydrograph.py`) buduje `WatershedParameters.from_dict` z morfometrii (obszar użyty w obliczeniu, CN użyty w obliczeniu) i współczynnika metody z żądania i woła `calculate_tc(tc_method)` (Nogat plan `2026-11-05-official-tc-inputs`, D5). Każda metoda bierze pola, które definiuje jej źródło, bez zastępników:

| Metoda | Klucz API | Pola zlewni (Hydrolog) | Z żądania | Źródło |
|--------|-----------|------------------------|-----------|--------|
| Kirpich | `kirpich` | `flow_path_length_km`, `flow_path_slope_m_per_m` | — | Kirpich 1940 (za Fang i in. 2005) |
| NRCS (lag) | `nrcs` | `flow_path_length_km`, `mean_slope_m_per_m`, `cn` | — | NEH 630 rozdz. 15 |
| Giandotti | `giandotti` | `channel_length_km`, `elevation_min_m`, `elevation_mean_m`, `area_km2` | — | Giandotti 1934 (za Grimaldi i in. 2012) |
| FAA | `faa` | `overland_length_km`, `overland_slope_m_per_m`, `runoff_coeff` | `tc_runoff_coeff` → `runoff_coeff` | FAA 1970, AC 150/5320-5B, rys. 7 i tab. I |
| Kerby | `kerby` | `overland_length_km`, `overland_slope_m_per_m`, `retardance` | `tc_retardance` → `retardance` | Kerby 1959; TxDOT HDM |
| Kerby-Kirpich | `kerby_kirpich` | `retardance`, `overland_*`, `flow_path_*` (koryto = `flow_path_length_km − overland_length_km`) | `tc_retardance` → `retardance` | Roussel i in. 2005; Cleveland i in. 2012 (TxDOT 0-6382-P1) |

**Pola zlewni** mierzy preprocessing (ADR-070): `flow_path_length_km` (= `hydraulic_length_km`, najdłuższa droga spływu od punktu zlewni najdalszego hydraulicznie – zwykle na dziale wodnym, ale może leżeć na grzbiecie wewnątrz zlewni – do ujścia), `flow_path_slope_m_per_m` ((wysokość jej początku − wysokość ujścia) / długość), `overland_length_km` i `overland_slope_m_per_m` (odcinek od jej początku do pierwszej komórki sieci cieków progu wyznaczenia). Pole, którego nie da się zmierzyć, jest puste, nie 0 ani wartością domyślną; tryb zaawansowany może je podać.

**Brak danych:** Hydrologowy `InvalidParameterError` z `details.reason` `missing_field` staje się 400 `validation_error` z `details` `{"reason": "missing_field", "method": …, "missing": […]}` (nazwy pól morfometrii albo opcji żądania `tc_runoff_coeff`, `tc_retardance`) i komunikatem „Czas koncentracji metodą … wymaga: …” (`tc_inputs_missing`). Usunięte: wybór pól po stronie Hydrografu (długość hydrauliczna podstawiana pod `length_km`, spadek cieku dla Kirpicha, średni spadek terenu dla FAA i Kerby'ego, C z CN, N 0,4, długość BDOT10k i „L_max − L_k” w Kerby-Kirpich) oraz opcja żądania `tc_overland_length_km` (odcinek powierzchniowy podaje się razem ze spadkiem w `morphometry`).

**Przekazanie (ADR-068):** zlewnia niesie `flow_path_*` i `overland_*` (gdy niepuste) oraz `runoff_coeff`/`retardance` metody, która ich użyła; `runoff` niesie `tc_method` bez `tc_min`, więc Hydrolog liczy tc ponownie; `provenance.runoff.tc_min` zostaje do porównania.

---

## Typy hietogramów

| Typ | Klucz API | Parametry | Opis |
|-----|-----------|-----------|------|
| Beta | `beta` | `alpha` (default: 2.0), `beta` (default: 5.0) | Rozkład beta — elastyczny kształt, peak zależny od alpha/beta |
| Block | `block` | brak | Opad jednostajny (stała intensywność) |
| Euler II | `euler_ii` | `peak_position=0.33` (hardcoded) | Rozkład Euler typu II — peak w 1/3 czasu trwania |

---

## Estymacja parametrów Nash IUH

| Metoda | Klucz API | Parametry wymagane | Uwagi |
|--------|-----------|---------------------|-------|
| Lutz (domyślna) | `from_lutz` | `channel_length_km`, `length_to_centroid_km`, `channel_slope_m_per_m`; `forest_pct`, `urban_pct` | Lutz (1984) after KZGW 2017, eq. 6.17: Manning's n 0.035 (`LUTZ_MANNING_N`), W = share of forest (`las`), U = share of urbanised land (`zabudowa_mieszkaniowa`, `zabudowa_przemysłowa`, `droga`) from the land cover of the delineation, 0 without it; `area_km2` passed too. The hand-off carries `manning_n`, `forest_pct` and `urban_pct` in the watershed and `{"source": "hydrograf", "method": "lutz"}` as the provenance of `runoff`, so Hydrolog reopens Nash by Lutz (ADR-068, erratum 2026-11-05) |
| Regresja zurbanizowana | `from_urban_regression` | `nash_urban_fraction` | Rao et al. (1972), wymaga wskaźnika urbanizacji |

**Removed 2026-11-05:** the estimation from the time of concentration (`nash_estimation: "from_tc"`, `NashIUH.from_tc()`, deprecated in Hydrolog since 0.6.2 and announced for removal in 1.0.0) and the request field `nash_n` it used. The relation $t_{lag} = 0.6·T_c$ of the SCS hydrograph has no ground in the Nash cascade, so Hydrograf no longer offers it: a request with `from_tc` gets 400 `validation_error` at `/body/nash_estimation` with the allowed values, `GET /api/scenarios` lists only `from_lutz` and `from_urban_regression`, and no Nash estimation computes Tc.

---

## Snyder Unit Hydrograph

**Model:** `uh_model: 'snyder'`

**Parametry:**
- `snyder_ct` — współczynnik opóźnienia (default: 1.5). Zależy od charakterystyki retencji zlewni
- `snyder_cp` — współczynnik szczytu (default: 0.6). Wpływa na wysokość szczytu hydrogramu

**Wymagane dane morfometryczne (z `morph_dict`):**
- `channel_length_km` — długość głównego cieku
- `length_to_centroid_km` — odległość od ujścia do centroidu zlewni wzdłuż cieku

**Implementacja:** `backend/api/endpoints/hydrograph.py`

**Hydrolog 1.0.0.dev0 (ADR-060):** `HydrographGenerator` builds the Snyder unit hydrograph for a duration equal to the time step (the duration correction of Snyder: `tLR = tL + 0.25 (D - tD)`, `tpR = tLR + D/2`, `qpR = qp tL / tLR`), not for the standard duration `tD = tL/5.5` as 0.6.3 did. Measured on the endpoint at a time step of 5 minutes (three catchments, six concentration-time methods, three hyetograph types): the peak is 11 to 12% higher, comes 25 to 70 minutes earlier, and the volume is the same. The SCS and Nash unit hydrographs give the numbers they gave before.

**Dostępne modele hydrogramu jednostkowego:**
- `scs` — SCS Unit Hydrograph (domyślny)
- `snyder` — Snyder Unit Hydrograph
- `nash` — Nash IUH (Instantaneous Unit Hydrograph)

---

## TODO / Przyszłe rozszerzenia

1. ~~Obliczanie CN z pokrycia terenu~~ ✅ Zaimplementowane (cn_tables + cn_calculator + land_cover)

2. ~~Dodatkowe metody tc~~ ✅ Zaimplementowane (FAA, Kerby, Kerby-Kirpich — Hydrolog v0.6.3)

3. **Eksport wyników** - eksport hydrogramu do CSV/Excel

4. **Podwójna analiza NMT** - analiza z/bez obszarów bezodpływowych (backlog)

---

## Przykład użycia API

### Generowanie hydrogramu

```bash
curl -X POST http://localhost:8000/api/generate-hydrograph \
  -H "Content-Type: application/json" \
  -d '{
    "latitude": 52.23,
    "longitude": 21.01,
    "duration": "1h",
    "probability": 10,
    "tc_method": "kirpich",
    "hietogram_type": "beta"
  }'
```

### Przykładowa odpowiedź

```json
{
  "watershed": {
    "boundary_geojson": {...},
    "outlet": {"latitude": 52.23, "longitude": 21.01, "elevation_m": 150.0},
    "area_km2": 45.3,
    "hydrograph_available": true,
    "morphometry": {
      "area_km2": 45.3,
      "perimeter_km": 32.1,
      "length_km": 12.5,
      "elevation_min_m": 150.0,
      "elevation_max_m": 520.0,
      "elevation_mean_m": 340.0,
      "mean_slope_m_per_m": 0.025,
      "channel_length_km": 8.2,
      "channel_slope_m_per_m": 0.045,
      "longest_flow_path_km": 14.2,
      "divide_flow_path_km": 13.8,
      "centroid_flow_path_km": 9.1,
      "cn": 72,
      "source": "Hydrograf",
      "crs": "EPSG:2180"
    },
    "longest_flow_path_geojson": {"type": "Feature", "geometry": {"type": "LineString", "coordinates": ["..."]}}
  },
  "precipitation": {
    "total_mm": 45.0,
    "duration_min": 60.0,
    "probability_percent": 10,
    "timestep_min": 5.0,
    "times_min": [0, 5, 10, "..."],
    "intensities_mm": [0.5, 1.2, 2.1, "..."]
  },
  "hydrograph": {
    "times_min": [0, 5, 10, "..."],
    "discharge_m3s": [0, 0.1, 0.5, "..."],
    "peak_discharge_m3s": 12.5,
    "time_to_peak_min": 45.0,
    "total_volume_m3": 125000
  },
  "water_balance": {
    "total_precip_mm": 45.0,
    "total_effective_mm": 28.5,
    "runoff_coefficient": 0.63,
    "cn_used": 72,
    "retention_mm": 84.7,
    "initial_abstraction_mm": 16.9
  },
  "metadata": {
    "tc_min": 32.5,
    "tc_method": "kirpich",
    "hietogram_type": "beta",
    "uh_model": "scs"
  }
}
```

---

## Repozytorium Hydrologa

- **GitHub:** https://github.com/Daldek/Hydrolog.git
- **Branch:** `develop` (on GitHub)
- **Wersja:** 1.0.0.dev0, commit `930915d5eee94ece17682e288fbab64c7f7cc5c1` (`develop` of Nogat's release set candidate-3, with the stages W1 and W2 of Hydrolog's network wizard; was `759d7ef` of candidate-2, before it `4fad769`, which added the TR-55 rows that `core/cn_tables.py` uses: water at 98, paved roads with open ditches, residential 1/4 acre, woods–grass; ADR-075 amendment 2026-11-09). Against `759d7ef` the modules Hydrograf calls change only by additions: `WatershedParameters` gains `nash_parameters` (`NASH_INPUTS` in `_ranges.py`) and the `uh_params` of `HydrographGenerator` an optional `estimated` (default False); `time/concentration.py` and `runoff/cn_lookup.py` are unchanged. Against `4fad769` only the descriptions of `residential_low` and `residential_medium` in `runoff/cn_lookup.py` change; against `1ffcd6b` only `runoff/cn_lookup.py` changes the results of the modules Hydrograf calls
- **Dokumentacja:** `docs/INTEGRATION.md`
- **Instalacja:** zaleznosc w `backend/pyproject.toml` (`[tool.uv.sources]`: `hydrolog = { git = "https://github.com/Daldek/Hydrolog.git", rev = "930915d5eee94ece17682e288fbab64c7f7cc5c1" }`), instalowana przez `uv sync --locked`; the commit is on GitHub, so every machine resolves it; the release replaces it with a tag (REL-5.3)

---

**Ostatnia aktualizacja:** 2026-11-11
