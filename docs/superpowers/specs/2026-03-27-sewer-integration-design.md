---
title: Integracja kanalizacji deszczowej z analiza splywu powierzchniowego
date: 2026-03-27
status: draft
---

# Integracja kanalizacji deszczowej z analiza splywu powierzchniowego

## 1. Problem

Standardowe algorytmy flow direction i flow accumulation opieraja sie wylacznie na grawitacyjnym splywie po powierzchni terenu (DEM). W srodowisku miejskim system kanalizacji deszczowej calkowicie zmienia reguly gry — woda przechwycona przez wpust moze wyplynac w miejscu topograficznie wyzej polozonym lub w zupelnie innej zlewni powierzchniowej, niz wskazuje DEM.

## 2. Podejscie

Modified inlet burning + routing przez graf sieci + propagacja FA downstream. Trzy etapy wbudowane w istniejacy offline pipeline `process_dem.py`.

Inspirowane podejsciem inlet burning z Si et al. (2024) i USGS StreamStats, ale z autorskim grafowym transferem FA zamiast wypalania trasy kolektora w DEM. Kluczowa roznica: brak sztucznych kanalow morfologicznych na powierzchni DEM — FA jest transferowane bezposrednio przez graf sieci kanalizacyjnej od wpustow do wylotow.

Podejscia odrzucone:
- **Conditioned DEM** (wypalenie sieci kanalizacyjnej jako sztuczna dolina) — bledne koncepcyjnie, tworzy nieistniejace kanaly morfologiczne
- **Dual-drainage** (dwie niezalezne warstwy polaczone w punktach wymiany) — poprawne fizycznie, ale wymaga pelnych danych o sieci z rzednymi
- **Biblioteka stormcatchments** — GPL-3.0 (licencja wirusowa), pysheds zamiast pyflwdir, networkx zamiast scipy sparse, brak FA propagation downstream

## 3. Architektura modulow

### 3.1 Nowe pliki

```
backend/
├── core/
│   └── sewer_service.py          # Logika: parsowanie, graf, burning, routing, propagacja
├── scripts/
│   └── download_sewer.py         # Pozyskiwanie danych: file/WFS/DB/URL
├── api/endpoints/
│   └── (rozszerzenie admin.py)   # Upload + podglad w admin panelu
└── migrations/versions/
    └── XXX_create_sewer_tables.py  # numer wg aktualnego Alembic head
```

### 3.2 Modul `core/sewer_service.py`

Odpowiedzialnosci:

1. **Parsowanie danych** — `parse_sewer_input(path, attr_mapping)` — linie / punkty / oba → ujednolicona struktura wewnetrzna
2. **Budowa grafu** — `build_sewer_graph(lines, points, snap_m)` — snap endpoints, identyfikacja wpustow/wylotow, ustalenie kierunku (kaskada), scipy sparse matrix
3. **Inlet burning** — `burn_inlets(dem, inlets, depth_m, cfg)` — walidacja rzednych vs DEM, obnizenie DEM + wstrzykniecie drain_points
4. **Odtworzenie FA wpustow** — `reconstruct_inlet_fa(fa, fdir, inlets)` — obliczenie FA dla komorek nodata (drain_points) z sasiadow
5. **Sewer routing** — `route_fa_through_sewer(graph, fa_raster)` — BFS od lisci do korzenia, suma FA z wpustow per wylot
6. **FA propagation** — `propagate_fa_downstream(fa, fdir, outlets)` — wstrzykniecie FA do komorek wylotow + globalny recompute downstream
7. **DB insert** — `insert_sewer_data(network, nodes, db)` — zapis do PostGIS

### 3.3 Modul `scripts/download_sewer.py`

Zrodla danych (jedno per run):

- `load_from_file(path)` → GeoDataFrame
- `load_from_wfs(url, layer)` → GeoDataFrame
- `load_from_database(conn, table)` → GeoDataFrame
- `load_from_url(url)` → GeoDataFrame
- `load_sewer_data(config)` → dispatch wg config.sewer.source.type → reprojekcja EPSG:2180 → walidacja geometrii

Walidacja CRS: jesli dane nie maja CRS → ERROR z komunikatem. Opcjonalnie: `sewer.source.assumed_crs` w YAML pozwala na reczne wskazanie CRS.

### 3.4 Integracja z `process_dem.py`

```python
# ~40 linii w process_dem.py

if cfg.sewer.enabled:
    sewer_data = load_sewer_data(cfg)  # ERROR jesli brak danych
    graph, nodes = build_sewer_graph(
        sewer_data, snap_tolerance_m=cfg.sewer.snap_tolerance_m
    )
    dem, drain_points_sewer = burn_inlets(dem, nodes, cfg.sewer.inlet_burn_depth_m)
    drain_points.extend(drain_points_sewer)

# ... existing: fill sinks (z drain_points) → fdir → FA ...

if cfg.sewer.enabled:
    reconstruct_inlet_fa(fa, fdir, nodes)  # P1 fix: odtworzenie FA z sasiadow
    fa = route_fa_through_sewer(graph, fa, nodes)
    fa = propagate_fa_downstream(fa, fdir, nodes)  # globalny recompute

# ... existing: stream extraction → subcatchments → DB ...

if cfg.sewer.enabled:
    insert_sewer_data(graph, nodes, db)
```

## 4. Algorytm

### 4.1 Pozycja w pipeline

```
1.  Read DEM
2.  Building raising (+5m BUBD)
3.  Stream burning (BDOT10k rivers)
3b. ★ Inlet burning + drain_points injection
4.  Fill sinks → fdir → FA (drain_points przekazane do pyflwdir)
4a. ★ Odtworzenie FA wpustow (z sasiadow w fdir)
4b. ★ Sewer routing (BFS po grafie → suma FA na wylotach)
4c. ★ FA propagation downstream od wylotow (globalny recompute)
5.  Stream extraction (z "wzbogaconym" FA)
6.  Subcatchment delineation
7.  Polygonization + stats
8.  DB insert (+ sewer_network, sewer_nodes)
```

Kroki 4a-4c musza byc wstawione PO `process_hydrology_pyflwdir()` a PRZED `compute_strahler_from_fdir()` — miedzy liniami 572 a 681 w obecnym `process_dem.py`.

### 4.2 Krok 3b — Inlet burning + drain_points injection

```
INPUT:  dem (np.ndarray), sewer_nodes (lista wpustow), config
OUTPUT: dem (zmodyfikowany), drain_points (lista (row, col))

1. Dla kazdego wezla typu 'inlet':
   a. (x, y) → (row, col) via inverse rasterio transform (int() truncation)
   b. WALIDACJA: jesli row/col poza zakresem rastra → WARNING, skip, diagnostics++
   c. dem_elev = dem[row, col]
   d. Ustal burn_depth:
      - Jesli user podal invert_elev_m → depth = dem_elev - invert_elev_m
      - Jesli user podal depth_m → depth = depth_m
      - Fallback → depth = config.sewer.inlet_burn_depth_m (YAML)
   e. WALIDACJA: jesli depth <= 0 → WARNING (wpust "wystaje" nad teren), skip
   f. DEDUPLICATION: jesli (row, col) juz w drain_points (inny wpust w tej samej komorce):
      → uzyj max(depth) z obu wpustow
      → FA bedzie wspoldzielone (jeden odczyt per komorka, nie podwojony)
   g. dem[row, col] -= depth
   h. drain_points.append((row, col))
   i. Zapisz: node.dem_elev_m = dem_elev, node.burn_elev_m = dem_elev - depth
```

KRYTYCZNE: Wpusty musza byc dodane do `drain_points` przekazywanych do `process_hydrology_pyflwdir()`. Mechanizm `drain_points` juz istnieje dla jezior bezodplywowych — pyflwdir traktuje je jako outlety/pity i NIE zasypuje ich podczas fill sinks (Wang & Liu). Komorki drain_points sa ustawiane na nodata w DEM (hydrology.py:1277-1281), wiec po pipeline FA w tych komorkach = 0.

### 4.3 Krok 4a — Odtworzenie FA wpustow (FIX dla drain_points/nodata)

```
INPUT:  fa_raster, fdir_raster, sewer_nodes (wpusty z (row, col))
OUTPUT: nodes z odtworzonym fa_value

Mechanizm drain_points ustawia komorke DEM na nodata. pyflwdir WYKLUCZA
ja z FA — komorka wpustu ma FA = 0. Ale woda z sasiadow poprawnie splywu
KU wpustowi (fdir sasiadow wskazuje na komorke wpustu). Odtwarzamy FA
wpustu jako sume FA z sasiadow, ktorych fdir wskazuje na te komorke.

1. Dla kazdego wezla typu 'inlet':
   a. (row, col) — juz obliczone w kroku 3b
   b. reconstructed_fa = 0
   c. Dla kazdego z 8 sasiadow (dr, dc) w D8:
      - neighbor = (row + dr, col + dc)
      - jesli fdir[neighbor] wskazuje na (row, col):
        - reconstructed_fa += fa[neighbor]
   d. node.fa_value = reconstructed_fa
   e. UWAGA: jesli dwa wpusty w tej samej komorce — FA dzielone
      proporcjonalnie (50/50) lub przypisane do jednego (merge)
```

### 4.4 Krok 4b — Sewer routing

```
INPUT:  sewer_graph (scipy sparse), sewer_nodes (z fa_value z kroku 4a)
OUTPUT: nodes z total_upstream_fa

1. Dla kazdego wezla typu 'outlet':
   a. BFS upstream po grafie → zbierz wszystkie inlet nodes
   b. total_fa = sum(inlet.fa_value for inlet in upstream_inlets)
   c. node.total_upstream_fa = total_fa
```

### 4.5 Krok 4c — FA propagation downstream (globalny recompute)

```
INPUT:  fa_raster, fdir_raster, outlets
OUTPUT: fa_raster (zmodyfikowany)

Zamiast iteracyjnego BFS per wylot (ryzyko podwojenia surplus na
wspolnych sciezkach), stosujemy dwuetapowe podejscie:

1. Wstrzykniecie surplusow do komorek wylotow:
   a. Dla kazdego wylotu:
      - (x, y) → (row, col)
      - WALIDACJA: jesli fa[row, col] == nodata → ERROR (wylot w nodata DEM)
        → snap do najblizszej komorki non-nodata w promieniu cellsize
      - fa_raster[row, col] += outlet.total_upstream_fa

2. Globalny recompute FA downstream od wylotow:
   - Zbierz wszystkie komorki wylotow jako seed points
   - BFS downstream po fdir od kazdego seeda:
     - visited = set()
     - queue = deque(seed_cells)
     - while queue:
       - current = queue.popleft()
       - if current in visited: continue
       - visited.add(current)
       - next = follow fdir[current]
       - if next is valid (in bounds, not nodata, not in visited):
         - Przelicz fa[next] = suma FA z WSZYSTKICH sasiadow
           ktorych fdir wskazuje na next (nie tylko surplus)
         - queue.append(next)

   Alternatywnie: uzyj pyflwdir upstream_area() na zmodyfikowanym
   rastrze (prostsze, ale przelicza CALY raster — wolniejsze).
   Rekomendacja: lokalny BFS od wylotow dla wydajnosci.
```

### 4.6 Kaskada kierunku przeplywu

```
INPUT:  sewer_lines, sewer_points (opcjonalne), config
OUTPUT: directed graph (scipy sparse)

1. Zbuduj nieskierowany graf z topologii linii
   - Snap endpoints w promieniu effective_snap = max(snap_tolerance_m, cellsize)
   - Kazdy unikalny endpoint → wezel
   - Kazda linia → krawedz

2. Jesli user podal punkty → snap do najblizszych wezlow
   - Oznacz node_type z atrybutu (inlet/outlet/junction)

3. Ustal kierunek krawedzi — kaskada:
   a. ATRYBUT: jesli jest kolumna flow_direction/from_node/to_node → uzyj
   b. RZEDNE: jesli invert_elev na obu koncach → kierunek z wyzszej do nizszej
   c. TOPOLOGIA DRZEWIASTA:
      - Znajdz wyloty (user-defined lub auto-detect z topologii)
      - BFS od wylotow "w gore" — krawedzie nieodwiedzone kieruj ku wylotowi
      - Liscie (stopien=1, nie-wyloty) → oznacz jako inlet

4. Identyfikacja wylotow (jesli user nie podal):
   - Wezly bez krawedzi wychodzacych (sink w grafie / korzen drzewa)
   - Dodatkowa walidacja: wylot powinien lezec blisko cieku wodnego lub krawedzi DEM

5. Walidacja:
   - Czy graf jest spojny? Jesli nie → WARNING per komponent
   - Czy kazdy komponent ma dokladnie jeden outlet? Jesli nie → WARNING
   - Komponent bez wylotu → POMIJANY (brak inlet burning, brak FA routing) + WARNING
   - Cykle? → WARNING (ale nie blokuj — ignorujemy, transferujemy FA do wylotu niezaleznie od sciezki)
```

## 5. Model danych (PostGIS)

### 5.1 Tabela `sewer_nodes`

| Kolumna | Typ | Nullable | Opis |
|---------|-----|----------|------|
| `id` | SERIAL PK | NO | |
| `geom` | Point 2180 | NO | Lokalizacja |
| `node_type` | VARCHAR(20) | NO | 'inlet' / 'outlet' / 'junction' |
| `component_id` | INTEGER | YES | Numer spojnej skladowej grafu |
| `depth_m` | FLOAT | YES | Glebokosc wpustu |
| `invert_elev_m` | FLOAT | YES | Rzedna dna |
| `dem_elev_m` | FLOAT | YES | Rzedna DEM (wypelniana przez pipeline) |
| `burn_elev_m` | FLOAT | YES | Rzedna po wypaleniu (DEM - depth) |
| `fa_value` | INT | YES | FA w komorce (odtworzone z sasiadow dla wpustow) |
| `total_upstream_fa` | INT | YES | Suma FA z upstream wpustow (tylko wyloty) |
| `root_outlet_id` | INT FK → self | YES | Do ktorego wylotu trafia (NULL dla wylotow) |
| `nearest_stream_segment_idx` | INT | YES | Snap do stream_network (tylko wyloty) |
| `source_type` | VARCHAR(20) | NO | 'user_defined' / 'topology_generated' |
| `rim_elev_m` | FLOAT | YES | Rzedna wlazu/terenu (HEC-RAS/SWMM) |
| `max_depth_m` | FLOAT | YES | Max glebokosc studzienki (HEC-RAS/SWMM) |
| `ponded_area_m2` | FLOAT | YES | Powierzchnia zalewania (HEC-RAS/SWMM) |
| `outfall_type` | VARCHAR(20) | YES | 'free'/'normal'/'fixed'/'tidal' (HEC-RAS/SWMM) |
| `updated_at` | TIMESTAMP | YES | DEFAULT CURRENT_TIMESTAMP |

Indeksy: GIST(geom), B-tree(node_type), composite(root_outlet_id, node_type).
Constraint: CHECK(root_outlet_id != id).

### 5.2 Tabela `sewer_network`

| Kolumna | Typ | Nullable | Opis |
|---------|-----|----------|------|
| `id` | SERIAL PK | NO | |
| `geom` | LineString 2180 | NO | Linia kolektora |
| `node_from_id` | INT FK → sewer_nodes | NO | Wezel poczatkowy |
| `node_to_id` | INT FK → sewer_nodes | NO | Wezel koncowy |
| `diameter_mm` | INT | YES | Srednica |
| `width_mm` | INT | YES | Szerokosc (non-circular) |
| `height_mm` | INT | YES | Wysokosc (non-circular) |
| `cross_section_shape` | VARCHAR(20) | YES | 'circular'/'rectangular'/'egg'/'arch' |
| `invert_elev_start_m` | FLOAT | YES | Rzedna dna — start |
| `invert_elev_end_m` | FLOAT | YES | Rzedna dna — koniec |
| `material` | VARCHAR(50) | YES | Material |
| `manning_n` | FLOAT | YES | Wspolczynnik szorstkosci (HEC-RAS/SWMM) |
| `length_m` | FLOAT | NO | Dlugosc (obliczona z geom) |
| `slope_percent` | FLOAT | YES | Spadek (z rzednych lub DEM) |
| `source` | VARCHAR(50) | NO | Pochodzenie danych |
| `updated_at` | TIMESTAMP | YES | DEFAULT CURRENT_TIMESTAMP |

Indeksy: GIST(geom), B-tree(node_from_id), B-tree(node_to_id).

### 5.3 Rozszerzenie `stream_network`

Nowa kolumna (nullable):
- `is_sewer_augmented` BOOLEAN DEFAULT FALSE — flaga dla segmentow downstream od wylotow kanalizacji, ktorych `upstream_area_km2` uwzglednia FA z kanalizacji

## 6. Dane wejsciowe

### 6.1 Minimum wejsciowe

Jedna warstwa liniowa (LineString) z geometria kolektorow. Wszystko inne jest opcjonalne — wezly generowane automatycznie z endpointow linii, kierunek z topologii drzewiastej.

Trzy warianty wejscia (kazdy samodzielnie wystarczajacy):
1. **Tylko linie** — wezly auto-generowane z endpointow. Liscie = wpusty, korzen = wylot.
2. **Tylko punkty** (z atrybutem `next_node_id`) — linie interpolowane miedzy kolejnymi punktami.
3. **Linie + punkty** — pelne dane, punkty snap-owane do najblizszych wezlow sieci.

### 6.2 Zrodla danych (jedno per run)

- **Plik lokalny** — SHP/GPKG/GeoJSON w katalogu `/data/sewer/`
- **Upload przez admin panel** — endpoint POST + GUI
- **WFS** — zdalny serwis GIS
- **Baza danych** — zewnetrzna PostGIS
- **URL** — bezposredni link do pliku

### 6.3 Atrybuty opcjonalne

Wszystkie kolumny poza geometria sa opcjonalne. Domyslne wartosci:
- `inlet_burn_depth_m` — z YAML config (default: 0.5m)
- `cross_section_shape` — 'circular'
- `node_type` — auto-detect z topologii
- `flow_direction` — auto-detect kaskada (atrybut → rzedne → topologia)

### 6.4 Walidacja i snap

- Snap endpoints w promieniu `effective_snap = max(snap_tolerance_m, cellsize)` — zapobiega sytuacji gdy snap < cellsize rastra
- WARNING jesli snap > tolerancji
- WARNING jesli graf niespojny (wiele komponentow)
- Komponent bez wylotu → POMIJANY + WARNING
- WARNING jesli rzedna wpustu >= DEM (wpust "wystaje" nad teren)
- ERROR jesli dane nie maja CRS (opcja: `assumed_crs` w YAML)
- WARNING jesli wpust poza zakresem rastra DEM → skip + diagnostics
- ERROR jesli wylot w komorce nodata DEM → snap do najblizszej valid cell
- WARNING jesli dwa wpusty w tej samej komorce rastra → merge (max depth, shared FA)

## 7. Konfiguracja YAML

```yaml
sewer:
  enabled: false
  inlet_burn_depth_m: 0.5
  snap_tolerance_m: 2.0

  source:
    type: file                          # file | wfs | database | url
    path: /data/sewer/network.gpkg      # dla type: file
    # url: https://gis.miasto.pl/wfs    # dla type: wfs | url
    # layer: sewer_lines                # dla type: wfs
    # connection: postgresql://...       # dla type: database
    # table: sewer_network              # dla type: database
    lines_layer: null                   # nazwa warstwy linii w GPKG (null = auto-detect)
    points_layer: null                  # nazwa warstwy punktow w GPKG (null = brak)
    assumed_crs: null                   # reczne CRS jesli brak w danych (np. "EPSG:4326")

  attribute_mapping:
    diameter: null
    width: null
    height: null
    cross_section: null
    invert_start: null
    invert_end: null
    depth: null
    material: null
    manning: null
    flow_direction: null
    node_type: null
    rim_elevation: null
    max_depth: null
    ponded_area: null
    outfall_type: null
```

Sekcja `sewer` musi byc dodana do `_DEFAULT_CONFIG` w `config.py` z domyslnymi wartosciami jak powyzej.

### 7.1 Zachowanie error handling

- `sewer.enabled=true` + brak danych (plik nie istnieje, WFS timeout, pusta tabela) → **ERROR**, pipeline przerwany. Uzytkownik swiadomie wlaczyl kanalizacje — brak danych to blad konfiguracji, nie graceful degradation.
- `sewer.enabled=false` → kroki 3b, 4a-4c sa calkowicie pomijane. Pipeline dziala jak dotad.

## 8. API i admin panel

### 8.1 Nowe endpointy

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/api/admin/sewer/upload` | POST | Upload pliku z siecia kanalizacyjna |
| `/api/admin/sewer/status` | GET | Status danych (wezly, krawedzie, warnings) |
| `/api/admin/sewer/delete` | DELETE | Usuniecie danych kanalizacyjnych |
| `/api/tiles/sewer/{z}/{x}/{y}.pbf` | GET | MVT tiles sieci kanalizacyjnej |

### 8.2 Admin panel

Nowa zakladka "Sewer" w `/admin`:
- Status danych (zaladowano / brak)
- Statystyki (wezly, krawedzie, typy, komponenty)
- Upload / podglad na mapie / usuwanie
- WARNING jesli pipeline jest "dirty" (dane zmienione od ostatniego runu)

### 8.3 Frontend

Nowa warstwa overlay w `layers.js`:
- Linie kolektorow — kolor wg srednicy lub node_type
- Punkty wpustow (niebieskie) / wylotow (czerwone) / junction (szare)
- Tooltip z atrybutami

### 8.4 Re-run workflow

Po zmianie danych kanalizacji (upload / delete) → pelny re-run pipeline jest WYMAGANY:
1. `DELETE /api/admin/sewer/delete` → TRUNCATE sewer_*, oznacz pipeline jako "dirty"
2. `POST /api/admin/sewer/upload` → zapis pliku, oznacz pipeline jako "dirty"
3. Admin panel wyswietla warning: "Dane kanalizacji zmienione — wymagany re-run pipeline"
4. Re-run pipeline: `process_dem.py` przetwarza od nowa z nowymi danymi kanalizacji (FA raster, stream_network, stream_catchments sa przeliczane)

## 9. Znane ograniczenia

### 9.1 Precise delineation (ADR-050) nie uwzglednia kanalizacji

RasterCache (tryb precise, bez threshold) uzywa fdir z dysku. Komorki wpustow w fdir sa pitami (fdir=0/nodata) — woda doplywajaca do wpustu ZATRZYMUJE SIE tam. Precise delineation nie wie o routingu kanalizacyjnym. To jest ograniczenie trybu precise — wyniki precomputed (z threshold) uwzgledniaja kanalizacje (zmodyfikowany FA → stream_network → CatchmentGraph).

### 9.2 drain_point/nodata przerywa sciezki splywu przez komorke wpustu

Ustawienie komorki wpustu na nodata blokuje WSZYSTKIE sciezki splywu przechodzace przez te komorke — nie tylko wode przechwycona przez kanalizacje. Przy rastrze 5m (komorka 25m²) efekt jest akceptowalny (micro-zlewnia wpustu i tak odpowiada fizycznej zlewni wpustu ulicznego). Dla rastrow 1m efekt jest minimalny.

### 9.3 upstream_area_km2 downstream od wylotow

Segmenty stream_network downstream od wylotow kanalizacji maja zawyzone `upstream_area_km2` (uwzglednia FA z kanalizacji). `CatchmentGraph.aggregate_stats["area_km2"]` (suma poligonow) jest poprawne topograficznie. Flaga `is_sewer_augmented` w stream_network umozliwia rozroznienie.

### 9.4 stream_distance z drain_points

`flw.stream_distance()` traktuje wpusty jako outlety — komorki upstream od wpustu maja stream_distance do WPUSTU (nie do globalnego outletu). To zmienia `max_flow_dist_m` i `hydraulic_length_km` w stream_catchments zawierajacych wpusty.

## 10. Dokumentacja

### 10.1 Pliki do aktualizacji

| Plik | Zmiana |
|------|--------|
| `docs/SCOPE.md` | Przeniesienie kanalizacji z "out of scope" do "in scope" |
| `docs/ARCHITECTURE.md` | Nowe moduly, tabele, endpointy, diagram pipeline |
| `docs/DATA_MODEL.md` | Tabele `sewer_network`, `sewer_nodes`, kolumna `is_sewer_augmented` |
| `docs/DECISIONS.md` | ADR-051: Integracja kanalizacji deszczowej |
| `docs/CHANGELOG.md` | Wpis o nowej funkcjonalnosci |
| `docs/PROGRESS.md` | Aktualizacja statusu |
| `docs/CROSS_PROJECT_ANALYSIS.md` | Wplyw na zaleznosci |

### 10.2 ADR-051 — kluczowe decyzje

1. Podejscie: modified inlet burning + routing grafowy + FA propagation (autorski hybrid)
2. Dane: upload uzytkownika (file/WFS/DB/URL), nie publiczne API
3. Graf: scipy sparse, spojne z CatchmentGraph
4. stormcatchments odrzucony (GPL-3.0, pysheds, brak FA propagation)
5. Drain points injection — rozwiazanie fill sinks vs inlet burning + odtworzenie FA z sasiadow
6. Globalny recompute FA downstream zamiast iteracyjnego BFS per wylot
7. Jedno zrodlo danych per run, brak wariantowosci
8. Schemat DB z kolumnami HEC-RAS/SWMM (nullable, future-proof)
9. Zero nowych zaleznosci

## 11. Zaleznosci

Zero nowych zaleznosci. Wszystkie potrzebne biblioteki juz w `requirements.txt`:
- `geopandas`, `fiona` — czytanie SHP/GPKG/GeoJSON, WFS
- `shapely` — geometrie, snap, distance
- `scipy` — sparse matrix, BFS
- `numpy` — operacje rastrowe
- `rasterio` — raster I/O, transform
- `pyproj` — reprojekcja CRS
- `sqlalchemy` — polaczenie z zewnetrzna DB

## 12. Testowanie

### 12.1 Unit testy (`tests/unit/test_sewer_service.py`)

Minimum 20 testow dla kazdej funkcji w `sewer_service.py`:

**Parsowanie:**
- parse_sewer_input z plikiem liniowym (SHP, GPKG, GeoJSON)
- parse_sewer_input z plikiem punktowym
- parse_sewer_input z obydwoma warstwami
- attribute_mapping — reczne i auto-detect
- brak CRS → ERROR
- pusta geometria → ERROR

**Budowa grafu:**
- build_sewer_graph z prostego drzewa (3 wpusty, 1 wylot)
- snap_tolerance — merge bliskich endpointow
- kaskada kierunku: atrybut, rzedne, topologia
- auto-detect wylotow z topologii
- graf rozlaczny → wiele komponentow + WARNING
- komponent bez wylotu → POMIJANY + WARNING
- cykle w grafie → WARNING, routing dziala

**Inlet burning:**
- burn_inlets — obnizenie DEM, generacja drain_points
- walidacja: depth <= 0 → WARNING, skip
- walidacja: wpust poza DEM → WARNING, skip
- deduplication: dwa wpusty w jednej komorce → merge

**Odtworzenie FA:**
- reconstruct_inlet_fa — poprawna suma z 8 sasiadow
- komorka na krawedzi rastra (mniej niz 8 sasiadow)
- dwa wpusty w jednej komorce — dzielone FA

**Routing:**
- route_fa_through_sewer — prosta siec (2 wpusty → 1 wylot)
- siec z junction (rozgalezienie)
- wiele komponentow (niezalezne wyloty)

**Propagacja FA:**
- propagate_fa_downstream — wstrzykniecie + recompute
- wylot w komorce nodata → ERROR / snap
- wylot na cieku (stream cell) — FA dodane poprawnie

### 12.2 Integration testy

1. **Regression** — pipeline z `sewer.enabled=false` → identyczne wyniki jak dotychczas
2. **Prosta siec** — syntetyczny DEM 50x50, 3 wpusty, 1 wylot → weryfikacja FA downstream
3. **Kompleksowa siec** — 2 rozlaczne komponenty, jeden bez wylotu → WARNING, poprawne FA

### 12.3 Test fixtures

- Syntetyczny DEM 50x50 z plaskim terenem i lekkim spadkiem
- Prosta siec kanalizacyjna (3 linie, 4 wezly) jako GeoJSON
- Zlozony fixture z wieloma komponentami i brakujacymi atrybutami

## 13. Literatura

- Si et al. (2024), *Discover Water*, Springer — porownanie trzech metod GIS integracji sieci kanalizacyjnej z delineacja zlewni miejskich. DSC = 0.80. Nasze podejscie jest inspirowane metoda inlet burning, ale zamiast wypalania trasy kolektora w DEM stosuje autorski grafowy transfer FA — eliminujac sztuczne koryta na powierzchni.
- USGS StreamStats (zlewnia Mystic River, Massachusetts) — operacyjne wdrozenie inlet burning + siec rurociagów w DEM. Roznica: USGS wypala cala trase podziemna, my transferujemy FA grafem.
- Biblioteka `stormcatchments` (Python/GitHub) — referencyjna implementacja koncepcji (graf NetworkX + pysheds). Odrzucona z powodu GPL-3.0, redundantnych zaleznosci, braku FA propagation.
- Water NZ — ostrzezenie: metoda rastrowa dziala dobrze dla sieci burzowej, gorzej dla sanitarnej (prowadzonej celowo z dala od najnizszych partii terenu).
