# Integracja Hydrograf ↔ Hydrolog

**Data utworzenia:** 2026-01-20
**Ostatnia aktualizacja:** 2026-11-21 (the pin `dbbbdb5`, Hydrolog 0.9.0.dev5, the development pin of the release round of 2026-11-21, Nogat plan `2026-11-19-hydrolog-0.9.0-consumers`, step 2; Hydrograf 0.5.0 to 0.5.2 pinned Hydrolog's tags, 0.5.2 `v0.8.1` of Nogat's release set candidate-10: the equal-area slope `flow_path_equal_area_slope_m_per_m` handed over and read by Lutz as Jg with L the longest flow path, Snyder's L the longest flow path, Euler II from the PMAXTP depth-duration curve without `peak_position`, the whole-step checks of a design storm, Hydrolog's refusals and notices, `formula_versions` and `hydrolog_version`, the constants of 0.9.0, the envelope copy of Nogat `2bbb507`). 2026-11-15 (the pin `3ce7ee8` of Nogat's release set candidate-5, was `e5df06d`: of the modules Hydrograf calls only a docstring of `routing/network.py` changes, and the envelope copy is the same). 2026-11-15 (the pin `e5df06d` of Hydrolog's `develop`, 0.8.0.dev0 as the author set it on 2026-11-14, after `9e2cb61` of Nogat's release set candidate-4: of the modules Hydrograf calls only two docstrings change). 2026-11-14 (the pin `9e2cb61` of Nogat's release set candidate-4, was `930915d`: the modules Hydrograf calls are unchanged; it reads the same envelope copy as Hydrograf and routes a flat reach as linear reservoirs). 2026-11-14 (audit against the code of 2026-11-14: the exchange format is Hydrograf's `MorphometricParameters` handed in the keys of Hydrolog's `WatershedParameters`; the provider lines of every hand-off (PMAXTP, G, SG) and the envelope copy of Nogat `b29eada`; the interpolation of the PMAXTP provenance; tc through `WatershedParameters.calculate_tc`, no `ConcentrationTime`; the Hydrolog imports of every module; the 27 probabilities; the inputs of the urban regression; `trace_main_channel`). 2026-11-11: the network hand-off with every control point a node, `J…` at a confluence and `P…` elsewhere, numbered from the closing section upward, the outlet `O` and the names and `node_provenance` of plan `2026-11-11-network-nodes`; Hydroni and kaczawa2 run `930915d` with `develop` `a46adb4`; the names of the network hand-off after the two kinds of ADR-080, and Hydrolog's `3aab136`; 2026-11-10: the hand-off of a network, ADR-080; Hydrolog `930915d` of `develop`, the release set candidate-3 of Nogat; was `759d7ef` of candidate-2, before it `4fad769`, the TR-55 rows of Hydrograf's covers and water at CN 98, which production then still ran
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

### The morphometry and Hydrolog's `WatershedParameters`

Hydrograf gives the morphometry of a watershed as `MorphometricParameters`
(`backend/models/schemas.py`; `morphometry` of `POST /api/delineate-watershed`; required
`area_km2`, `perimeter_km`, `length_km`, `elevation_min_m`, `elevation_max_m`). Hydrolog's
`WatershedParameters` (0.9.0.dev5) requires only `area_km2`; each method checks the fields it
needs (the Tc table below; Lutz's estimation `flow_path_length_km`, `Lc_km`,
`flow_path_equal_area_slope_m_per_m` and `manning_n`). `watershed_parameters()`
(`backend/core/handoff.py`) hands over the values Hydrolog has a key for: `area_km2`,
`perimeter_km`, `length_km`, the elevations, `mean_slope_m_per_m`, `channel_length_km`,
`channel_slope_m_per_m`, `cn`, `runoff_coeff`, `retardance`, `overland_length_km`,
`overland_slope_m_per_m`, `length_to_centroid_km` as `Lc_km`, `manning_n`, `urban_pct`,
`forest_pct`, `flow_path_length_km`, `flow_path_slope_m_per_m` and
`flow_path_equal_area_slope_m_per_m`. The other fields (the shape and relief indices,
`longest_flow_path_km`, `divide_flow_path_km`, `centroid_flow_path_km`, the hydraulic length,
the imperviousness) have no key in Hydrolog, and `source` and `crs` are left to the provenance.

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
  `tc_min`, n i K Nasha albo L, Lc, Ct, Cp Snydera, L being `flow_path_length_km`; AMC),
  `rainfall` (opad projektowy PMAXTP z kształtem hietogramu: `alpha` and `beta` of Beta,
  the depth-duration curve `depth_duration_mm` of Euler II, no `peak_position`; albo własny
  szereg), `timestep_min` i `result` (Qmax, czas do szczytu, objętość, `computed_with` with
  Hydrolog's `version` and the `formula_versions` of the response). Wartości są te, których
  użyło obliczenie, bez zaokrągleń: `hydrograph generate` Hydrologa daje z nich ten sam
  wynik (`backend/tests/unit/test_handoff.py`).

Pochodzenie (`provenance`): zlewnia z Hydrografa z ujściem i polami zmienionymi w trybie
zaawansowanym (pole żądania `morphometry_origin`; bez niego `user`), the rainfall `pmaxtp`
(POT, the probability, the duration, the request's point, `interpolation` `thiessen` for the
watershed mean or `idw` at a point without a boundary, and `areal_reduction_factor` when the user
gave one) or `user`,
parametry odpływu (metoda tc, estymacja Nasha). W interfejsie: „Kopiuj do Hydrologa” i
„Plik przekazania” pod sekcjami panelu „Zlewnia” (`frontend/js/handoff.js`).

Nash by Lutz travels as Lutz (ADR-068, erratum 2026-11-05): the watershed carries Lutz's
inputs `flow_path_length_km` (L), `Lc_km`, `flow_path_equal_area_slope_m_per_m` (Jg),
`manning_n` (0.035), `forest_pct` and `urban_pct` (the land cover shares the computation
used) and the provenance of `runoff` is Hydrolog's own record `{"source": "hydrograf",
"method": "lutz"}`, so Hydrolog opens Nash in Lutz mode and its `uh nash` gives Hydrograf's
n and K; `runoff` keeps them for the recomputation.

Every hand-off carries the top-level `attribution` and `terms_notice` of Nogat DEV-20.6 and
DEV-20.7 (ADR-083, ADR-085; the envelope copy of Nogat `2bbb507`): the lines the terms of the
providers of its data require (`backend/core/attribution.py`), left out when there are none.
A hydrograph with a PMAXTP rainfall, or with an own series copied from one
(`custom_precipitation.derived_from`), carries the PMAXTP source, the processing note and the
monograph in `attribution` and the link to the PMAXTP terms in `terms_notice`; a watershed of
Hydrograf's data adds G (GUGiK: NMT, BDOT10k, with the dates of `instance.json` `sources`) and,
with soil groups, SG (SoilGrids) to `attribution`. The hand-offs of a delineation and of a
network carry G (and SG) and no `terms_notice`. Hydrolog shows the lines with the loaded data
and carries them into its own products (since `9537463`, in the pinned `dbbbdb5`).

---

## The hand-off of a network (`POST /api/delineate-network`, ADR-080)

`POST /api/delineate-network` returns in `handoff` one `nogat-handoff/1` around one
`hydrolog-network/1` holding the whole network, for Hydrolog's „Sieć i trasowanie”
(`build_network_handoff` in `backend/core/handoff.py`; plans
`docs/plans/2026-11-10-network-delineation.md`, D14 and D15, and
`docs/plans/2026-11-11-network-nodes.md`, N1, N7 and N8). The envelope is the copy of
Nogat `2bbb507`, with the optional `node_provenance` (`schemas/nogat/README.md`).

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
  D10a): Hydrolog `930915d` (candidate-3) refused a flat reach at any time step
  (`unstable_timestep`). The pinned `dbbbdb5` (since `3aab136`, its ADR-0026) routes a reach
  that Muskingum-Cunge cannot grid as linear reservoirs with the warning
  `diffusion_dominated` instead; the hand-off still writes the lag.
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

The pin: Hydrolog `dbbbdb5` (0.9.0.dev5, the development pin of the release round of
2026-11-21; Hydrograf 0.5.2 pinned `v0.8.1`) has the `description` (and `position`) of every
node in `hydrolog-network/1`, which a network's hand-off needs (Hydrolog `46c743f` or later),
and reads the envelope copy of Nogat `2bbb507`, the same file as
`schemas/nogat/handoff-1.schema.json` here (the same SHA-256), with `node_provenance`,
`attribution` and `terms_notice` (its step 3 of the Nogat plan
`2026-11-10-node-provenance-in-handoff`, `cead00a`).
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
- `gradient_strips`, `compute_slope_from_gradients`, `compute_aspect_from_gradients` - slope
  (Sobel) and aspect of the DEM, strip by strip
- `compute_twi(acc, slope, cellsize)` - Topographic Wetness Index
- `compute_strahler_from_fdir(flw, acc, threshold)` - Strahler order on the flow
  directions of the run

### 3. Moduł: `backend/core/catchment_graph.py`

**Status:** ✅ Zaimplementowane (CP4+)

In-memory graf zlewni (~44k nodes, ~0.5 MB):
- `traverse_upstream(node_idx)` - BFS w górę sieci
- `aggregate_stats(indices)` - agregacja parametrów (area, elevation, slope)
- `trace_main_channel(outlet_idx, upstream_indices)` - śledzenie głównego cieku (do channel_slope)
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
from hydrolog.exceptions import InvalidParameterError
from hydrolog.morphometry import WatershedParameters
from hydrolog.precipitation import (
    BetaHietogram,
    BlockHietogram,
    EulerIIHietogram,
    Hietogram,
    HietogramResult,
)
from hydrolog.runoff import AMC, SCSCN, HydrographGenerator, NashIUH
```

**Przepływ danych:**
1. Walidacja parametrów (duration, probability) and of the design storm before anything is computed (`_design_storm`): the duration must be a whole number of steps of `timestep_min` (to 1e-9 of it), else 400 `storm_not_whole_steps` (reason `not_multiple`); Euler II needs a step of at least 5 min, the first PMAXTP duration (`EULER_II_SHORTEST_MIN`), else 400 `euler_ii_step_below_curve` (reason `not_covered`) (Hydrolog ADR-0046, ADR-0042)
2. Transformacja współrzędnych WGS84 → PL-1992
3. Lokalizacja zlewni cząstkowej (CatchmentGraph + ST_Contains)
4. BFS w górę sieci (traverse_upstream)
5. Agregacja statystyk + sprawdzenie limitu 250 km²
6. Budowa granicy zlewni (merge + Chaikin smoothing)
7. Obliczenie CN z pokrycia terenu (land_cover + cn_tables)
8. Budowa dict morfometrycznego (build_morph_dict_from_graph)
9. Pobranie opadu: the watershed mean of `precipitation_data` by Thiessen polygons (**Hydrolog:** `thiessen_polygons`, ADR-069); without a boundary IDW at the point (**Hydrolog:** `inverse_distance_weighting`)
10. **Hydrolog:** `WatershedParameters.from_dict()` → `calculate_tc()`
11. **Hydrolog:** Hietogram (`_hietogram`: Beta of the request's α and β, Block, or Euler II of the curve `_depth_duration_mm`) → `generate()`
12. **Hydrolog:** `HydrographGenerator` → `generate()`
13. Budowa odpowiedzi JSON, with `hydrolog_version` and `formula_versions` (`core/formula_versions.py`)

A refusal of Hydrolog (`InvalidParameterError`) becomes a problem document through `refusal()` of `core/hydrolog_refusals.py` (below).

**Parametry wejściowe:**
- `latitude`, `longitude` - współrzędne WGS84
- `duration` - czas trwania opadu: 5min, 10min, 15min, 30min, 45min, 1h, 1.5h, 2h, 3h, 6h, 12h, 18h, 24h, 36h, 48h, 72h
- `probability` - the exceedance probability [%], one of the 27 PMAXTP values (0.01 to 99.9; `GET /api/scenarios`)
- `timestep_min` - krok czasowy (default: 5 min, 1–60): the duration of a PMAXTP storm must be a whole number of steps, and Euler II's step at least 5 min (the GUI sends none: 5 min divides every PMAXTP duration)
- `tc_method` - metoda tc: kirpich, nrcs, giandotti, faa, kerby, kerby_kirpich
- `hietogram_type` - typ hietogramu: beta, block, euler_ii
- `uh_model` - model hydrogramu jednostkowego: scs, snyder, nash
- `nash_estimation` - metoda estymacji Nash IUH: from_lutz, from_urban_regression
- `snyder_ct` - współczynnik opóźnienia Snydera (default: 1.5)
- `snyder_cp` - współczynnik szczytu Snydera (default: 0.6)
- `tc_runoff_coeff` - współczynnik spływu C metody FAA (0 < C ≤ 1, z tab. I FAA 1970, AC 150/5320-5B); wymagany dla `faa`, nigdy nie liczony z CN
- `tc_retardance` - współczynnik oporu N Kerby'ego (0,02–0,8, tabela Kerby'ego / TxDOT HDM); wymagany dla `kerby` i `kerby_kirpich`, bez wartości domyślnej
- `morphometry` - morfometria (tryb zaawansowany), w tym `flow_path_length_km`, `flow_path_slope_m_per_m`, `flow_path_equal_area_slope_m_per_m`, `overland_length_km`, `overland_slope_m_per_m`

**Ograniczenia:**
- Maksymalna powierzchnia zlewni: 250 km² (limit metody SCS-CN)

### 7. Endpoint: `GET /api/scenarios`

**Status:** ✅ Zaimplementowane

Zwraca dostępne kombinacje parametrów hydrogramu (`durations`, `probabilities`, `tc_methods`, `hietogram_types`, `uh_models`, `snyder_defaults`, `nash_estimation_methods`, `amc`, `custom_precipitation_max_steps`, `area_limit_km2`); the route is in `api/endpoints/hydrograph.py`.

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
| `api/endpoints/hydrograph.py` | `InvalidParameterError`, `WatershedParameters`, `BetaHietogram`, `BlockHietogram`, `EulerIIHietogram`, `Hietogram`, `HietogramResult`, `AMC`, `SCSCN`, `HydrographGenerator`, `NashIUH` | Endpoint API generowania hydrogramu; tc through `WatershedParameters.calculate_tc` |
| `core/hydrolog_notices.py` | `NOTICES` (`hydrolog.catalog`) | Hydrolog's warnings of a hydrograph as the `notices` of its response, in Polish (E5b-06): a warning of Hydrolog is a `Warning` with `code()` and `details` whose code `NOTICES` lists, since its class `HydrologWarning` is only in the private `hydrolog._warnings` |
| `core/hydrolog_refusals.py` | `InvalidParameterError` | Hydrolog's refusals of a formula's inputs as problem documents by the standard's reasons (`refusal`) |
| `core/formula_versions.py` | `FormulaSpec` (`hydrolog.nogat_formulas`), the specs of `hietogram`, `interpolation`, `concentration`, `cn_lookup`, `scs_cn`, `unit_hydrograph`, `snyder_uh`, `nash_iuh`, `convolution`, `EQUAL_AREA_SLOPE` (`hydrolog.morphometry.profile`) | The `formula_versions` of a hydrograph, of a delineated watershed and of the hand-off's `result.computed_with` (Nogat CMP-2.8) |
| `core/divide_flow_path.py` | `equal_area_slope` (`hydrolog.morphometry`), `InvalidParameterError` | The equal-area slope of the profile of the longest flow path, Lutz's Jg (`profile_equal_area_slope`) |
| `core/precipitation.py` | `Station`, `thiessen_polygons`, `inverse_distance_weighting` | The PMAXTP design depth: the watershed mean, IDW at a point (ADR-069) |
| `scripts/analyze_watershed.py` | `WatershedParameters`, `BetaHietogram`, `SCSCN`, `HydrographGenerator`, `SCSUnitHydrograph` | Skrypt CLI pełnej analizy |
| `core/cn_tables.py` | `AMC`, `SCSCN`, `HydrologicCondition`, `LandCover`, `get_cn` | The CN of the land cover rows from Hydrolog's TR-55 table, the AMC conversion |
| `core/land_cover.py`, `core/cn_calculator.py` | `calculate_weighted_cn` | The area-weighted CN of a watershed |
| `core/point_info.py` | `AMC`, `SCSCN` | The CN of a point at AMC I and III |
| `scripts/export_catchment_parameters.py` | `AMC` | The export of the catchment parameters |

---

## Lista zmian - podsumowanie

### Hydrograf (CP3+)

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/pyproject.toml` | + hydrolog (commit `dbbbdb5`, 0.9.0.dev5, range `>=0.9.0.dev5,<0.10`; was the tag `v0.8.1` in Hydrograf 0.5.2, v0.6.3 before ADR-060) | ✅ |
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
| `backend/tests/integration/test_hydrograph.py` | Testy integracyjne endpointu | ✅ |

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
- **`flow_path_equal_area_slope_m_per_m`** — the equal-area slope of the longitudinal profile of the same D8 path as `flow_path_length_km` (Lutz's Jg, Hydrolog ADR-0053): `profile_equal_area_slope` (`core/divide_flow_path.py`) takes the path's cells from its end up to its head, each at its flow distance from the end and its elevation on the filled DEM `dem_mosaic_02_filled` that the pipeline saved (read at request time by `compute_flow_paths`, beside the flow-path rasters; `cells.dem` of `core/cell_parameters.py` for a network element and the export), and Hydrolog's `equal_area_slope` gives S = 2A/L², A the trapezoid area of the profile above the elevation of its first point (the end cell below the outlet, or the cell above it when that one has no value), L its flow length; to 6 decimals. `null` without the saved filled DEM (or off the grid of the labels), for a gap in the profile, or for a profile without positive area (Hydrolog's `positive_area`), never 0
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
| Beta | `beta` | `hietogram_alpha` (default: 2.0), `hietogram_beta` (default: 5.0) | Rozkład beta — elastyczny kształt, peak zależny od alpha/beta |
| Block | `block` | brak | Opad jednostajny (stała intensywność) |
| Euler II | `euler_ii` | the PMAXTP depth-duration curve of the probability (`_depth_duration_mm`) | Euler type II of ATV-DVWK-A 118 (Hydrolog ADR-0042): the depth of each of the 16 PMAXTP durations (5 min–72 h) weighed as the design depth (the Thiessen mean over the watershed, IDW at the point without a boundary) and multiplied by the user's `areal_reduction_factor` when given; blocks Δh_j = h(jΔt) − h((j−1)Δt), h(0) = 0; the largest at the block from 0.3·D rounded down to the step (k = floor(0.3·n), n = D/Δt), the next ones before it back to t = 0, the rest after it, in the order of their durations; every m blocks around the peak hold h(mΔt) and the storm h(D); depths between the PMAXTP durations linear in ln D, nothing extrapolated |

Every hyetograph cuts the storm into n = D/Δt whole steps (Hydrolog ADR-0046): Hydrograf refuses a duration that is not a whole number of steps before it computes anything (400 `storm_not_whole_steps`, reason `not_multiple`), and an Euler II step below 5 min, where the curve starts (400 `euler_ii_step_below_curve`, reason `not_covered`). `EulerIIHietogram(depth_duration_mm).generate(total_mm, duration_min, timestep_min)` refuses a `total_mm` other than h(D) by more than 0.005 mm; Hydrograf's total is the curve's own depth of D. Until 0.8.x Euler II took `peak_position=0.33` (alternating blocks of weights r^-0.7, the peak at 1/3 of the duration).

---

## Estymacja parametrów Nash IUH

| Metoda | Klucz API | Parametry wymagane | Uwagi |
|--------|-----------|---------------------|-------|
| Lutz (domyślna) | `from_lutz` | `flow_path_length_km` (L), `length_to_centroid_km` (Lc, along the main channel), `flow_path_equal_area_slope_m_per_m` (Jg); `forest_pct`, `urban_pct` | Lutz (1984) after KZGW 2017, eq. 6.17 (Hydrolog ADR-0053: L the longest flow path to the divide, Jg the equal-area slope of its profile; was `channel_length_km` and `channel_slope_m_per_m` until Hydrolog 0.8.x); missing → 422 `lutz_parameters_missing` (reason `missing_morphometry`). Manning's n 0.035 (`LUTZ_MANNING_N`), W = share of forest (`las`), U = share of urbanised land (`zabudowa_mieszkaniowa`, `zabudowa_przemysłowa`, `droga`) from the land cover of the delineation, 0 without it; `area_km2` passed too. The hand-off carries `manning_n`, `forest_pct` and `urban_pct` in the watershed and `{"source": "hydrograf", "method": "lutz"}` as the provenance of `runoff`, so Hydrolog reopens Nash by Lutz (ADR-068, erratum 2026-11-05) |
| Regresja zurbanizowana | `from_urban_regression` | `area_km2`, the imperviousness of the land cover as `urban_fraction` (0 without it), the effective rainfall and its duration of SCS-CN | Rao et al. (1972); the response gives the values in `nash_urban_fraction`, `nash_effective_precip_mm`, `nash_duration_h` |

**Removed 2026-11-05:** the estimation from the time of concentration (`nash_estimation: "from_tc"`, `NashIUH.from_tc()`, deprecated in Hydrolog since 0.6.2 and announced for removal in 1.0.0) and the request field `nash_n` it used. The relation $t_{lag} = 0.6·T_c$ of the SCS hydrograph has no ground in the Nash cascade, so Hydrograf no longer offers it: a request with `from_tc` gets 400 `validation_error` at `/body/nash_estimation` with the allowed values, `GET /api/scenarios` lists only `from_lutz` and `from_urban_regression`, and no Nash estimation computes Tc.

---

## Snyder Unit Hydrograph

**Model:** `uh_model: 'snyder'`

**Parametry:**
- `snyder_ct` — współczynnik opóźnienia (default: 1.5). Zależy od charakterystyki retencji zlewni
- `snyder_cp` — współczynnik szczytu (default: 0.6). Wpływa na wysokość szczytu hydrogramu

**Wymagane dane morfometryczne (z `morph_dict`):**
- `flow_path_length_km` — L, the longest flow path, to the divide (Hydrolog ADR-0043; `channel_length_km`, the main channel, until Hydrolog 0.8.x)
- `length_to_centroid_km` — odległość od ujścia do centroidu zlewni wzdłuż cieku

Missing → 422 `snyder_parameters_missing` (reason `missing_morphometry`).

**Implementacja:** `backend/api/endpoints/hydrograph.py`

**Hydrolog 0.8.0.dev0 (ADR-060; numbered 1.0.0.dev0 until 2026-11-14):** `HydrographGenerator` builds the Snyder unit hydrograph for a duration equal to the time step (the duration correction of Snyder: `tLR = tL + 0.25 (D - tD)`, `tpR = tLR + D/2`, `qpR = qp tL / tLR`), not for the standard duration `tD = tL/5.5` as 0.6.3 did. Measured on the endpoint at a time step of 5 minutes (three catchments, six concentration-time methods, three hyetograph types): the peak is 11 to 12% higher, comes 25 to 70 minutes earlier, and the volume is the same. The SCS and Nash unit hydrographs give the numbers they gave before.

**Hydrolog 0.9.0.dev5 (`dbbbdb5`):** Snyder's L and Lutz's L and Jg as above; Euler II from the depth-duration curve; Kirpich's metric constant the exact 3.97560 (= 0.0078·(1000/0.3048)^0.77; was 3.981, −0.136 %), NRCS's SI constant 0.0141466 (= 100/7068.86; was 0.01416, −0.095 %); the SCS unit hydrograph's applicability ends at 51.8 km² (20 mi²; was 52).

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
  },
  "hydrolog_version": "0.9.0.dev5",
  "formula_versions": {"beta_hyetograph": 1, "equal_area_slope": 1, "kirpich": 1, "scs": 1, "scs_cn_retention": 1, "scs_cn_runoff": 1, "thiessen_precipitation": 1, "tr55_cn": 1, "uh_convolution": 1}
}
```

The response also carries `handoff` (above) and the provider lines `attribution` and
`terms_notice` (`core/attribution.py`): with a PMAXTP rainfall the PMAXTP lines and the link
to its terms, then G and SG of the watershed's data.

It also carries `notices` (E5b-06): the warnings Hydrolog gave while it computed the
hydrograph (`outside_applicability`, a value outside the applicability range of a formula,
`outside_typical_range` up to Hydrolog 0.8.x, and `outside_unverified_range`, outside a
typical range without a published source), each `level`, `code` and a Polish `message` from
their details, e.g. „Hydrogram jednostkowy SCS: powierzchnia zlewni = 100 km² – powyżej
zakresu stosowania 0–51,8 km². Wynik może być niewiarygodny.” or „…– powyżej typowego
zakresu …, który nie ma opublikowanego źródła i czeka na weryfikację. Wynik może być
niewiarygodny.”. One `warnings.showwarning` hook of the API (`core/hydrolog_notices.py`, put
in by the lifespan after the log starts) collects them into a list of the request's context
and passes every warning on to the log; the hydrograph's Hydrolog computations hold numba's
compiler lock (E5b-08), so a numba compile never takes them away from the hook.

`hydrolog_version` is the version of the installed Hydrolog (`hydrolog_version()` of
`core/handoff.py`), and `formula_versions` the `formula_version` of each of Hydrolog's
formulas the hydrograph depends on, by the name of its spec, sorted (Nogat CMP-2.8;
`formula_versions(hydrograph_specs(...))` of `core/formula_versions.py`): the weighting of
the PMAXTP grid and the hyetograph of a design storm, the SCS-CN retention and runoff, the
AMC conversion for AMC I and III, the time of concentration and the SCS unit hydrograph,
Snyder's lag and curve or Nash's IUH with Lutz's or the urban estimation, and the
convolution; on the full path joined by those of the delineated watershed. A watershed
(`POST /api/delineate-watershed`, `watershed.formula_versions`) carries `tr55_cn` for a CN of
its land cover and `equal_area_slope` for a measured Jg (`watershed_specs`). The hand-off's
`result.computed_with` carries the same `version` and `formula_versions`.

A refusal of Hydrolog, `InvalidParameterError` with `details.reason` of Nogat's computation
standard (CMP-3.1, CMP-3.2), becomes a 400 `validation_error` with the same `reason` and the
`formula`, `constraint` or `option` it names (`refusal()` of `core/hydrolog_refusals.py`):
`outside_physical_range` of an input (`formula_input_outside_physical_range`, its value and
range) or of a physical condition between inputs (`formula_physical_condition`),
`invalid_type` (`formula_input_invalid_type`) and `precondition_failed`
(`formula_precondition_failed`), the two conditions with Hydrolog's statement of them; Lutz's
Lc ≤ L (`lutz_centroid_beyond_length`), U + W ≤ 100 (`lutz_shares_over_area`) and
Kerby–Kirpich's flow path longer than its overland segment
(`kerby_kirpich_overland_not_shorter`) have Polish sentences of their own. Any other refusal
keeps Hydrolog's message as `invalid_parameters`.

---

## Repozytorium Hydrologa

- **GitHub:** https://github.com/Daldek/Hydrolog.git
- **Branch:** `develop` (on GitHub)
- **Wersja:** 0.9.0.dev5 (range `>=0.9.0.dev5,<0.10`), commit `dbbbdb5a6d8d9d4e0125178cb00ce2920709b672` (the head of Hydrolog's `develop` for the release round of 2026-11-21, Nogat plan `2026-11-19-hydrolog-0.9.0-consumers`, step 2: Lutz's Jg as the equal-area slope, ADR-0053; Snyder's L the longest flow path, ADR-0043; Euler II from a depth-duration curve, ADR-0042; hyetographs of whole steps, ADR-0046; formula specs with `formula_version`; the exact Kirpich and NRCS constants; the SCS unit hydrograph to 51.8 km². Hydrograf 0.5.0 pinned `v0.8.0`, 0.5.1 and 0.5.2 `v0.8.1`, the latter of Nogat's release set candidate-10). Before the tags: `3ce7ee8` of Nogat's release set candidate-5, 2026-11-15; against `e5df06d` the modules Hydrograf calls change only in a docstring of `routing/network.py`; `e5df06d` was the version set by the author on 2026-11-14, was 1.0.0.dev0; before: `develop` of Nogat's release set candidate-4: station statistics, the admin panel of its GUI, dead code removed, the logging gaps of Nogat DEV-12.5, DEV-12.7 and DEV-20.10 closed; was `930915d` of candidate-3, with the stages W1 and W2 of Hydrolog's network wizard, before it `759d7ef` of candidate-2 and `4fad769`, which added the TR-55 rows that `core/cn_tables.py` uses: water at 98, paved roads with open ditches, residential 1/4 acre, woods–grass; ADR-075 amendment 2026-11-09). Against `930915d` the modules Hydrograf calls are unchanged (`time/`, `runoff/` but `nash_iuh.py`, `morphometry/watershed_params.py`, `_ranges.py`, `precipitation/`); `nash_iuh.py` loses `LutzCalculationResult.tp_iuh_min` and `morphometry/terrain.py` `TerrainAnalysis.mean_elevation_from_dem`, neither used here, and `routing/document.py` takes `attribution` and `terms_notice` at the top of a network document. Against `759d7ef` the modules Hydrograf calls change only by additions: `WatershedParameters` gains `nash_parameters` (`NASH_INPUTS` in `_ranges.py`) and the `uh_params` of `HydrographGenerator` an optional `estimated` (default False); `time/concentration.py` and `runoff/cn_lookup.py` are unchanged. Against `4fad769` only the descriptions of `residential_low` and `residential_medium` in `runoff/cn_lookup.py` change; against `1ffcd6b` only `runoff/cn_lookup.py` changes the results of the modules Hydrograf calls
- **Dokumentacja:** `docs/INTEGRATION.md`
- **Instalacja:** zaleznosc w `backend/pyproject.toml` (`[tool.uv.sources]`: `hydrolog = { git = "https://github.com/Daldek/Hydrolog.git", rev = "dbbbdb5a6d8d9d4e0125178cb00ce2920709b672" }`), instalowana przez `uv sync --locked`; the commit is on GitHub, so every machine resolves it; the release commit replaces it with the tag of Hydrolog 0.9.0, within the range `hydrolog>=0.9.0.dev5,<0.10` (REL-5.3, REL-5.6)

---

**Ostatnia aktualizacja:** 2026-11-21
