# Przebudowa topologii sieci kanalizacyjnej

**Data:** 2026-03-27
**Status:** Zatwierdzony
**ADR:** ADR-051 (rozszerzenie)
**Gałąź:** fix/sewer-topology-rebuild

## 1. Problem

Obecna implementacja topologii sieci kanalizacyjnej (`sewer_service.py`) automatycznie wykrywa wpusty, wyloty i relacje między węzłami z geometrii linii. Stosuje snapping endpoints (greedy clustering), kaskadę kierunków (atrybut → rzędne → topologia drzewiasta) i heurystyczną detekcję outletów (najniższe Y). Podejście jest kruche, niejednoznaczne w płaskim terenie i podatne na cichą utratę danych (komponenty bez wykrytych outletów pomijane).

## 2. Rozwiązanie

Jawna topologia definiowana przez użytkownika. Wymagane wskazanie wpustów, wylotów i wzajemnych powiązań (downstream). Backend waliduje spójność danych (strict z raportem błędów) zamiast zgadywać topologię.

## 3. Formaty danych wejściowych

### 3.1 Format A — Jedna warstwa punktowa

Użytkownik dostarcza punkty z kolumnami określającymi role i relacje downstream.

| Kolumna | Typ | Wymagana | Opis |
|---------|-----|----------|------|
| `geometry` | Point | tak | lokalizacja węzła |
| `id` | string/int | tak | unikalny identyfikator |
| `role` | string | tak | `inlet` / `outlet` / `junction` / `storage` |
| `downstream_id` | string/int | tak* | ID następnego węzła downstream. NULL tylko dla `outlet`. Wymagane dla inlet, junction i storage |

\+ opcjonalne atrybuty fizyczne (core i extended — patrz §5).

Backend auto-generuje linie topologiczne (`LINESTRING(x1 y1, x2 y2)`) dla każdej relacji downstream_id. Linie trafiają do `sewer_network` i MVT tiles (wizualizacja, debugowanie). Mają `source='auto_generated'`, brak atrybutów fizycznych.

### 3.2 Format B — Dwie warstwy (punktowa + liniowa)

**Warstwa punktowa:**

| Kolumna | Typ | Wymagana | Opis |
|---------|-----|----------|------|
| `geometry` | Point | tak | lokalizacja |
| `id` | string/int | tak | unikalny identyfikator |
| `role` | string | tak | `inlet` / `outlet` / `junction` / `storage` |

**Warstwa liniowa:**

| Kolumna | Typ | Wymagana | Opis |
|---------|-----|----------|------|
| `geometry` | LineString | tak | geometria rury |
| `from_node` | string/int | tak | ID węzła początkowego (upstream) |
| `to_node` | string/int | tak | ID węzła końcowego (downstream) |

\+ opcjonalne atrybuty fizyczne na obu warstwach.

### 3.3 Obsługiwane pliki

- **GPKG** z 2 warstwami (punkty + linie) — format B
- **GPKG** z 1 warstwą punktową — format A
- **ZIP** z 2 SHP (points + lines) — format B
- **SHP/GeoJSON** pojedynczy punktowy — format A

### 3.4 Auto-detekcja formatu

Backend analizuje zawartość pliku:
- GPKG: `fiona.listlayers()` → 1 warstwa punktowa = format A, 2 warstwy (punkt+linia) = format B
- ZIP: rozpakowanie, analiza SHP
- Pojedynczy plik: typ geometrii (Point = format A)

Użytkownik może wymusić format w config (`format: "points_only" | "points_and_lines" | "auto"`).

## 4. Role węzłów

4 role kompatybilne z SWMM/HEC-RAS:

| Rola | SWMM equivalent | Zachowanie w Hydrografie |
|------|-----------------|--------------------------|
| `inlet` | Subcatchment connection | Wpust — przechwycenie wody z powierzchni (burn DEM, rekonstrukcja FA) |
| `junction` | Junction/Manhole | Studzienka pośrednia — łączy rury, brak interakcji z DEM |
| `outlet` | Outfall | Wylot do cieku — wstrzyknięcie FA, propagacja downstream |
| `storage` | Storage unit | Funkcjonalnie = junction. Istnieje dla kompatybilności SWMM/HEC-RAS. Brak spalania, brak rekonstrukcji FA |

`inlet` i `outlet` wymagane (min. 1 każdego na komponent). `junction` i `storage` opcjonalne.

## 5. Mapowanie atrybutów

### 5.1 Konfiguracja YAML

```yaml
sewer:
  enabled: false
  inlet_burn_depth_m: 0.5
  snap_tolerance_m: 2.0          # tylko do mapowania node→DEM cell

  source:
    type: "file"                  # file | wfs | database | url
    path: null
    format: "auto"                # auto | points_only | points_and_lines
    points_layer: null            # nazwa warstwy punktowej (GPKG)
    lines_layer: null             # nazwa warstwy liniowej (GPKG)
    assumed_crs: null

  field_mapping:
    # Wymagane — identyfikacja topologii
    node_id: "id"
    node_role: "role"
    downstream_id: "downstream_id"   # format A
    edge_from: "from_node"           # format B
    edge_to: "to_node"              # format B

    # Opcjonalne — core (wpływ na hydrologię)
    invert_elev: null               # rzędna dna [m n.p.m.]
    depth: null                     # głębokość wpustu [m]
    diameter: null                  # średnica rury [mm]

    # Opcjonalne — extended (SWMM/HEC-RAS, przechowywane bez walidacji)
    rim_elevation: null
    max_depth: null
    ponded_area: null
    outfall_type: null
    manning: null
    material: null
    cross_section: null
    width: null
    height: null

  role_mapping:                    # mapowanie wartości ról w danych
    inlet: "inlet"
    outlet: "outlet"
    junction: "junction"
    storage: "storage"
```

### 5.2 Backward compatibility

Jeśli config zawiera starą sekcję `attribute_mapping` zamiast `field_mapping`, traktuj ją jako `field_mapping` (fallback).

## 6. Architektura modułów

### 6.1 Podział odpowiedzialności

```
download_sewer.py          → wczytanie pliku/WFS/DB/URL, reprojekcja CRS, auto-detekcja formatu
sewer_topology.py (NOWY)   → parsowanie, walidacja strict, generowanie linii (format A)
sewer_service.py           → budowa grafu (z gotowej topologii), raster ops, DB insert
```

### 6.2 Nowy moduł: `backend/core/sewer_topology.py`

```python
@dataclass
class ParsedTopology:
    """Zunifikowany wynik parsowania obu formatów."""
    nodes: list[dict]       # id, role, x, y, + atrybuty core/extended
    edges: list[dict]       # from_id, to_id, geometry (LineString), + atrybuty
    warnings: list[str]     # non-critical notices
    source_format: str      # "points_only" | "points_and_lines"

class TopologyValidationError(Exception):
    """Structured validation report."""
    errors: list[dict]      # [{type, node_id, message}, ...]

def parse_sewer_topology(
    points_gdf: gpd.GeoDataFrame,
    lines_gdf: gpd.GeoDataFrame | None,
    field_mapping: dict,
    role_mapping: dict,
) -> ParsedTopology:
    """
    Parse and validate sewer topology from user data.

    Format A (lines_gdf=None): points with downstream_id, auto-generate lines.
    Format B (lines_gdf given): points + lines with from_node/to_node.

    Raises TopologyValidationError with structured report on invalid data.
    """

def validate_against_fdir(
    topology: ParsedTopology,
    fdir: np.ndarray,
    transform: Affine,
) -> list[dict]:
    """
    Check for feedback loops after phase 1 hydrology.

    For each outlet: trace fdir downstream on clean fdir (no sewer pits).
    If path reaches inlet's capture zone (cell + 8-neighbors with fdir→inlet)
    of the same component → error.

    Returns list of errors (empty = OK).
    """
```

### 6.3 Walidacja strict — reguły

| Reguła | Typ błędu | Faza | Przykład komunikatu |
|--------|-----------|------|---------------------|
| Unikalne ID węzłów | `duplicate_id` | parse | `Node id=42 appears 3 times` |
| Rola z dozwolonych wartości | `invalid_role` | parse | `Node id=7: role 'pump' not in {inlet,outlet,junction,storage}` |
| downstream_id wskazuje na istniejący węzeł | `missing_target` | parse | `Node id=5: downstream_id=99 not found` |
| Outlet ma downstream_id=NULL | `outlet_has_downstream` | parse | `Outlet id=3 has downstream_id=7` |
| Non-outlet ma downstream_id (nie NULL) | `missing_downstream` | parse | `Inlet id=12 has no downstream_id` |
| Brak cykli | `cycle_detected` | parse | `Cycle: 5 → 8 → 12 → 5` |
| Każdy komponent ma min. 1 outlet | `no_outlet` | parse | `Component {3,7,8} has no outlet` |
| Każdy komponent ma min. 1 inlet | `no_inlet` | parse | `Component {1,2} has no inlet` |
| Format B: from_node/to_node istnieją w punktach | `orphan_edge` | parse | `Edge from_node=99: no matching point` |
| Format B: kierunek linii spójny z rolami | `direction_mismatch` | parse | `Edge 5→3: node 3 is inlet (should be downstream)` |
| Outlet nie w zlewni inletu (pętla fdir) | `feedback_loop` | fdir | `Outlet id=3 drains to inlet id=7 capture zone` |

## 7. Pipeline dwufazowy

### 7.1 Nowy pipeline w `process_dem.py`

```
FAZA 1 — Czysty fdir (bez sewer)
  1. Read DEM
  2. Building raising (+5m BUBD)
  3. Stream burning (BDOT10k)
  4. Fill sinks → fdir                    ← BEZ drain_points sewer
     (FA i cieki NIE potrzebne w tej fazie)

FAZA 1b — Walidacja sewer vs teren
  5. Parse topology (sewer_topology.py)
  6. Map nodes na DEM (row, col)
  7. WALIDACJA PĘTLI:
     - Trace fdir downstream z każdego outletu (czysty fdir, bez pitów)
     - Jeśli ścieżka trafia w komórkę inletu lub jego 8-sąsiedztwo
       (komórki z fdir wskazującym na inlet) tego samego komponentu → BŁĄD, STOP
  8. Jeśli OK → kontynuuj

FAZA 2 — Hydrologia z sewer
  9.  Burn inlets w DEM
  10. Re-fill sinks (z drain_points) → re-fdir → FA
  11. Reconstruct inlet FA
  12. Route FA through sewer
  13. Propagate FA downstream
  14. Ekstrakcja cieków (z wzbogaconym FA)
  15. Subcatchments, stats, DB insert
```

### 7.2 Koszt

- Faza 1: fill + fdir (~30s na 54M komórek). Bez FA — tylko `resolve_flats()` + `flowdir()`.
- Faza 2: pełny pipeline jak dotychczas.
- Narzut: ~30s na pipeline 45 min = +1%.
- Jeśli sewer wyłączony → faza 1 pomijana, pipeline jednorazowy jak dotychczas.

## 8. Zmiany w istniejących modułach

### 8.1 `sewer_service.py`

**Usuwane (~250 linii):**
- `_snap_endpoints()` — jawna topologia zamiast snappingu
- `_detect_outlets()` — outlety oznaczone przez użytkownika
- `_assign_directions_by_topology()` — kierunek z from/to
- Kaskada kierunków w `build_sewer_graph()`
- Klasyfikacja node_type z topologii grafu

**Zmieniony interfejs:**
```python
# Stary:
def build_sewer_graph(gdf, snap_tolerance_m, attr_mapping, user_outlets) -> SewerGraph

# Nowy:
def build_sewer_graph(topology: ParsedTopology) -> SewerGraph
```

Uproszczony — przyjmuje gotową, zwalidowaną topologię. Buduje adj matrix i przypisuje atrybuty.

**Bez zmian:**
- `burn_inlets()`, `reconstruct_inlet_fa()`, `route_fa_through_sewer()`, `propagate_fa_downstream()`, `insert_sewer_data()`
- `SewerGraph` (adj matrix, get_nodes_by_type, get_upstream_inlets)

### 8.2 `download_sewer.py`

**Zmieniony interfejs:**
```python
# Stary:
def load_sewer_data(config) -> gpd.GeoDataFrame

# Nowy:
def load_sewer_data(config) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame | None]
#                                     points            lines (or None = format A)
```

**Nowe:**
- Obsługa ZIP (rozpakowanie, detekcja SHP)
- Auto-detekcja formatu (1 vs 2 warstwy)

### 8.3 `config.py`

- Zamiana `attribute_mapping` → `field_mapping` + `role_mapping` w `_DEFAULT_CONFIG`
- Backward compat: `attribute_mapping` jako fallback dla `field_mapping`
- Dodanie `format: "auto"` w sekcji `source`

### 8.4 `process_dem.py`

- Pipeline dwufazowy (§7)
- Faza 1: fill+fdir przed sewer
- Walidacja pętli między fazami
- Faza 2: burn + re-fill + fdir + FA z sewer

### 8.5 `admin.py`

- Upload: auto-detekcja formatu, response z `detected_format`, `layers`
- Config: rozszerzenie `SewerConfigUpdate` o `field_mapping`, `role_mapping`
- Bez zmian: status, delete

### 8.6 Frontend `admin-sewer.js`

- Wyświetlanie `detected_format` po upload
- Kolor `storage` w MVT tiles
- Usunięcie referencji do `isolated`

## 9. Zmiany w bazie danych

### 9.1 Migracja 027

Jedyna zmiana schematu — CHECK constraint na `node_type`:

```sql
ALTER TABLE sewer_nodes DROP CONSTRAINT chk_node_type;
ALTER TABLE sewer_nodes ADD CONSTRAINT chk_node_type
  CHECK (node_type IN ('inlet', 'outlet', 'junction', 'storage'));
UPDATE sewer_nodes SET node_type = 'junction' WHERE node_type = 'isolated';
```

Reszta schematu bez zmian — `sewer_network.node_from_id`/`node_to_id` już reprezentuje jawną topologię (tyle że teraz pochodzi z danych użytkownika zamiast z heurystyki). Spójne z SWMM CONDUITS (from_node, to_node) i HEC-RAS connections.

## 10. Testy

- **Nowe unit testy:** `test_sewer_topology.py` — parser (format A i B), walidator (wszystkie reguły z §6.3), generowanie linii, walidacja pętli fdir
- **Update:** `test_sewer_service.py` — nowy interfejs `build_sewer_graph(ParsedTopology)`
- **Update:** `test_sewer_pipeline.py` — integracyjne z dwufazowym pipeline
- **Update:** `test_download_sewer.py` — ZIP, auto-detekcja, tuple return
- **Update:** `test_config_sewer.py` — field_mapping, role_mapping, backward compat

## 11. Kompatybilność z modelami hydraulicznymi

Design jest spójny z SWMM i HEC-RAS:
- `sewer_nodes` → SWMM JUNCTIONS/OUTFALLS/STORAGE
- `sewer_network` (node_from_id, node_to_id) → SWMM CONDUITS (from_node, to_node)
- 4 role węzłów mapowalne 1:1 na typy SWMM
- Atrybuty extended (manning, material, ponded_area, outfall_type) przechowywane dla przyszłego eksportu
