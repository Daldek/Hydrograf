---
title: Integracja kanalizacji deszczowej z analiza splywu powierzchniowego
date: 2026-03-27
status: draft
---

# Integracja kanalizacji deszczowej z analiza splywu powierzchniowego

## 1. Problem

Standardowe algorytmy flow direction i flow accumulation opieraja sie wylacznie na grawitacyjnym splywie po powierzchni terenu (DEM). W srodowisku miejskim system kanalizacji deszczowej calkowicie zmienia reguly gry — woda przechwycona przez wpust moze wyplynac w miejscu topograficznie wyzej polozonym lub w zupelnie innej zlewni powierzchniowej, niz wskazuje DEM.

## 2. Podejscie

Inlet burning + routing przez graf sieci + propagacja FA downstream. Trzy etapy wbudowane w istniejacy offline pipeline `process_dem.py`.

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
    └── 025_create_sewer_tables.py
```

### 3.2 Modul `core/sewer_service.py`

Odpowiedzialnosci:

1. **Parsowanie danych** — `parse_sewer_input(path, attr_mapping)` — linie / punkty / oba → ujednolicona struktura wewnetrzna
2. **Budowa grafu** — `build_sewer_graph(lines, points, snap_m)` — snap endpoints, identyfikacja wpustow/wylotow, ustalenie kierunku (kaskada), scipy sparse matrix
3. **Inlet burning** — `burn_inlets(dem, inlets, depth_m, cfg)` — walidacja rzednych vs DEM, obnizenie DEM + wstrzykniecie drain_points
4. **Sewer routing** — `route_fa_through_sewer(graph, fa_raster)` — BFS od lisci do korzenia, suma FA z wpustow per wylot
5. **FA propagation** — `propagate_fa_downstream(fa, fdir, outlets)` — wstrzykniecie FA do komorek wylotow, BFS downstream po fdir, kolejnosc rosnacego FA
6. **DB insert** — `insert_sewer_data(network, nodes, db)` — zapis do PostGIS

### 3.3 Modul `scripts/download_sewer.py`

Zrodla danych (jedno per run):

- `load_from_file(path)` → GeoDataFrame
- `load_from_wfs(url, layer)` → GeoDataFrame
- `load_from_database(conn, table)` → GeoDataFrame
- `load_from_url(url)` → GeoDataFrame
- `load_sewer_data(config)` → dispatch wg config.sewer.source.type → reprojekcja EPSG:2180 → walidacja geometrii

### 3.4 Integracja z `process_dem.py`

```python
# ~30 linii w process_dem.py

if cfg.sewer.enabled:
    sewer_data = load_sewer_data(cfg)
    graph, nodes = build_sewer_graph(
        sewer_data, snap_tolerance_m=cfg.sewer.snap_tolerance_m
    )
    dem, drain_points_sewer = burn_inlets(dem, nodes, cfg.sewer.inlet_burn_depth_m)
    drain_points.extend(drain_points_sewer)

# ... existing: fill sinks (z drain_points) → fdir → FA ...

if cfg.sewer.enabled:
    fa = route_fa_through_sewer(graph, fa, nodes)
    fa = propagate_fa_downstream(fa, fdir, nodes)

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
4b. ★ Sewer routing (BFS po grafie → suma FA na wylotach)
4c. ★ FA propagation downstream od wylotow
5.  Stream extraction (z "wzbogaconym" FA)
6.  Subcatchment delineation
7.  Polygonization + stats
8.  DB insert (+ sewer_network, sewer_nodes)
```

Kroki 4b i 4c musza byc wstawione PO `process_hydrology_pyflwdir()` a PRZED `compute_strahler_from_fdir()` — miedzy liniami 572 a 681 w obecnym `process_dem.py`.

### 4.2 Krok 3b — Inlet burning + drain_points injection

```
INPUT:  dem (np.ndarray), sewer_nodes (lista wpustow), config
OUTPUT: dem (zmodyfikowany), drain_points (lista (row, col))

1. Dla kazdego wezla typu 'inlet':
   a. (x, y) → (row, col) via inverse rasterio transform (int() truncation)
   b. dem_elev = dem[row, col]
   c. Ustal burn_depth:
      - Jesli user podal invert_elev_m → depth = dem_elev - invert_elev_m
      - Jesli user podal depth_m → depth = depth_m
      - Fallback → depth = config.sewer.inlet_burn_depth_m (YAML)
   d. WALIDACJA: jesli depth <= 0 → WARNING (wpust "wystaje" nad teren), skip
   e. dem[row, col] -= depth
   f. drain_points.append((row, col))
   g. Zapisz: node.dem_elev_m = dem_elev, node.burn_elev_m = dem_elev - depth
```

KRYTYCZNE: Wpusty musza byc dodane do `drain_points` przekazywanych do `process_hydrology_pyflwdir()`. Mechanizm `drain_points` juz istnieje dla jezior bezodplywowych — pyflwdir traktuje je jako outlety/pity i NIE zasypuje ich podczas fill sinks (Wang & Liu).

### 4.3 Krok 4b — Sewer routing

```
INPUT:  sewer_graph (scipy sparse), fa_raster, sewer_nodes
OUTPUT: nodes z total_upstream_fa

1. Dla kazdego wezla typu 'inlet':
   a. (x, y) → (row, col)
   b. node.fa_value = fa_raster[row, col]

2. Dla kazdego wezla typu 'outlet':
   a. BFS upstream po grafie → zbierz wszystkie inlet nodes
   b. total_fa = sum(inlet.fa_value for inlet in upstream_inlets)
   c. node.total_upstream_fa = total_fa
```

### 4.4 Krok 4c — FA propagation downstream

```
INPUT:  fa_raster, fdir_raster, outlets (posortowane rosnaco wg total_fa)
OUTPUT: fa_raster (zmodyfikowany)

1. Posortuj wyloty rosnaco wg total_upstream_fa

2. Dla kazdego wylotu w kolejnosci:
   a. (x, y) → (row, col)
   b. surplus = outlet.total_upstream_fa
   c. fa_raster[row, col] += surplus
   d. BFS downstream po fdir:
      - visited = set()
      - current = (row, col)
      - while current not in visited
            AND current nie jest na krawedzi rastra
            AND fdir[current] != nodata:
        - visited.add(current)
        - next = follow fdir[current] → sasiednia komorka
        - fa_raster[next] += surplus
        - current = next
```

Zabezpieczenie anti-cyklowe: `visited` set + sprawdzenie krawedzi rastra.

### 4.5 Kaskada kierunku przeplywu

```
INPUT:  sewer_lines, sewer_points (opcjonalne), config
OUTPUT: directed graph (scipy sparse)

1. Zbuduj nieskierowany graf z topologii linii
   - Snap endpoints w promieniu snap_tolerance_m
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
   - Cykle? → WARNING (ale nie blokuj — ignorujemy, transferujemy FA do wylotu niezaleznie od sciezki)
```

## 5. Model danych (PostGIS)

### 5.1 Tabela `sewer_nodes`

| Kolumna | Typ | Nullable | Opis |
|---------|-----|----------|------|
| `id` | SERIAL PK | NO | |
| `geom` | Point 2180 | NO | Lokalizacja |
| `node_type` | VARCHAR(20) | NO | 'inlet' / 'outlet' / 'junction' |
| `depth_m` | FLOAT | YES | Glebokosc wpustu |
| `invert_elev_m` | FLOAT | YES | Rzedna dna |
| `dem_elev_m` | FLOAT | YES | Rzedna DEM (wypelniana przez pipeline) |
| `burn_elev_m` | FLOAT | YES | Rzedna po wypaleniu (DEM - depth) |
| `fa_value` | INT | YES | FA w komorce po inlet burning |
| `total_upstream_fa` | INT | YES | Suma FA z upstream wpustow (tylko wyloty) |
| `outlet_id` | INT FK → self | YES | Do ktorego wylotu trafia (NULL dla wylotow) |
| `nearest_stream_segment_idx` | INT | YES | Snap do stream_network (tylko wyloty) |
| `source_type` | VARCHAR(20) | NO | 'user_defined' / 'topology_generated' |
| `rim_elev_m` | FLOAT | YES | Rzedna wlazu/terenu (HEC-RAS/SWMM) |
| `max_depth_m` | FLOAT | YES | Max glebokosc studzienki (HEC-RAS/SWMM) |
| `ponded_area_m2` | FLOAT | YES | Powierzchnia zalewania (HEC-RAS/SWMM) |
| `outfall_type` | VARCHAR(20) | YES | 'free'/'normal'/'fixed'/'tidal' (HEC-RAS/SWMM) |

Indeksy: GIST(geom), B-tree(node_type), B-tree(outlet_id).

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
| `source_file` | VARCHAR(200) | NO | Pochodzenie danych |

Indeksy: GIST(geom), B-tree(node_from_id), B-tree(node_to_id).

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

- Snap endpoints w promieniu `snap_tolerance_m` (YAML, default: 2.0m)
- WARNING jesli snap > tolerancji
- WARNING jesli graf niespojny
- WARNING jesli komponent bez wylotu
- WARNING jesli rzedna wpustu >= DEM (wpust "wystaje")

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
- Statystyki (wezly, krawedzie, typy)
- Upload / podglad na mapie / usuwanie

### 8.3 Frontend

Nowa warstwa overlay w `layers.js`:
- Linie kolektorow — kolor wg srednicy lub node_type
- Punkty wpustow (niebieskie) / wylotow (czerwone) / junction (szare)
- Tooltip z atrybutami

## 9. Dokumentacja

### 9.1 Pliki do aktualizacji

| Plik | Zmiana |
|------|--------|
| `docs/SCOPE.md` | Przeniesienie kanalizacji z "out of scope" do "in scope" |
| `docs/ARCHITECTURE.md` | Nowe moduly, tabele, endpointy, diagram pipeline |
| `docs/DATA_MODEL.md` | Tabele `sewer_network`, `sewer_nodes` |
| `docs/DECISIONS.md` | ADR-051: Integracja kanalizacji deszczowej |
| `docs/CHANGELOG.md` | Wpis o nowej funkcjonalnosci |
| `docs/PROGRESS.md` | Aktualizacja statusu |
| `docs/CROSS_PROJECT_ANALYSIS.md` | Wplyw na zaleznosci |

### 9.2 ADR-051 — kluczowe decyzje

1. Podejscie: inlet burning + routing grafowy + FA propagation
2. Dane: upload uzytkownika (file/WFS/DB/URL), nie publiczne API
3. Graf: scipy sparse, spojne z CatchmentGraph
4. stormcatchments odrzucony (GPL-3.0, pysheds, brak FA propagation)
5. Drain points injection — rozwiazanie fill sinks vs inlet burning
6. Jedno zrodlo danych per run, brak wariantowosci
7. Schemat DB z kolumnami HEC-RAS/SWMM (nullable, future-proof)
8. Zero nowych zaleznosci

## 10. Zaleznosci

Zero nowych zaleznosci. Wszystkie potrzebne biblioteki juz w `requirements.txt`:
- `geopandas`, `fiona` — czytanie SHP/GPKG/GeoJSON, WFS
- `shapely` — geometrie, snap, distance
- `scipy` — sparse matrix, BFS
- `numpy` — operacje rastrowe
- `rasterio` — raster I/O, transform
- `pyproj` — reprojekcja CRS
- `sqlalchemy` — polaczenie z zewnetrzna DB

## 11. Literatura

- Si et al. (2024), *Discover Water*, Springer — porownanie trzech metod GIS integracji sieci kanalizacyjnej z delineacja zlewni miejskich. DSC = 0.80.
- USGS StreamStats (zlwenia Mystic River, Massachusetts) — operacyjne wdrozenie inlet burning + siec rurociagów.
- Biblioteka `stormcatchments` (Python/GitHub) — referencyjna implementacja (odrzucona z powodu GPL-3.0).
- Water NZ — ostrzezenie: metoda rastrowa dziala dobrze dla sieci burzowej, gorzej dla sanitarnej.
