# Integracja z Kartografem

**Wersja:** 5.0
**Data:** 2026-03-02
**Status:** Aktywna

---

## 1. Przegląd

Hydrograf wykorzystuje [Kartograf](https://github.com/Daldek/Kartograf) (v0.6.1) do automatycznego pobierania danych przestrzennych z polskich i europejskich zasobów:

- **NMT** - Numeryczny Model Terenu z GUGiK (rozdzielczość 5m)
- **NMPT** - Numeryczny Model Pokrycia Terenu z GUGiK (nowy w v0.4.0)
- **Ortofotomapa** - Ortofotomapy z GUGiK (nowy w v0.4.0)
- **BDOT10k** - Dane o pokryciu terenu z GUGiK (15 warstw — 12 PT + 3 SW w jednym GPKG od v0.5.0)
- **BDOT10k BUBD** - Budynki z GUGiK (do building raising w NMT, ADR-033)
- **CORINE** - Europejska klasyfikacja pokrycia terenu z Copernicus (44 klasy)
- **SoilGrids HSG** - Grupy hydrologiczne gleby (przez HSGCalculator)

### 1.1 Co to jest Kartograf?

Kartograf to narzędzie Python do:
- **Parsowania godeł** arkuszy map topograficznych (układ 1992 i 2000)
- **Pobierania danych NMT/NMPT** z GUGiK przez OpenData/WCS API
- **Pobierania ortofotomap** z GUGiK (nowy w v0.4.0)
- **Pobierania danych o pokryciu terenu** z BDOT10k i CORINE
- **Obliczania HSG** z SoilGrids (HSGCalculator)
- **Zarządzania hierarchią arkuszy** (od 1:1M do 1:10k)
- **Auto-ekspansji godeł** — automatyczne rozwijanie godeł grubszych skal do arkuszy 1:10000 (nowy w v0.4.0)
- **Filtrowania po geometrii** — ograniczanie danych do zadanego zasięgu (nowy w v0.4.1)
- **Pobierania wszystkich 15 warstw BDOT10k** (12 PT + 3 SW) w jednym GPKG (nowy w v0.5.0)
- **Batch download** z retry logic i progress tracking

### 1.2 Dlaczego integracja?

| Problem | Rozwiązanie |
|---------|-------------|
| Ręczne pobieranie NMT z Geoportalu | Automatyczne pobieranie przez Kartograf |
| Użytkownik musi znać godła arkuszy | Konwersja współrzędnych → godło |
| Wiele arkuszy dla dużych zlewni | Automatyczne pobieranie sąsiednich arkuszy |
| Brak spójności formatów | Jednolity format AAIGrid (.asc) / GeoPackage (.gpkg) |
| Brak danych CN dla hydrogramów | Automatyczne pobieranie BDOT10k z wartościami CN |
| Brak danych HSG | HSGCalculator z SoilGrids |
| Budynki zaburzają kierunki spływu | Building raising +5m z BUBD (ADR-033) |

---

## 2. Architektura Integracji

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PRZEPŁYW DANYCH                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Użytkownik / Panel Admin                                           │
│      │                                                              │
│      │ (bbox WGS84 / sheets / --dry-run)                            │
│      ▼                                                              │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    bootstrap.py                              │   │
│  │  (Orchestrator: 9 kroków, subprocess, SSE streaming)        │   │
│  └─────────────────┬───────────────────────────────────────────┘   │
│                    │                                                │
│      ┌─────────────┼─────────────┬─────────────┐                   │
│      │             │             │             │                   │
│      ▼             ▼             ▼             ▼                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐          │
│  │download  │ │download  │ │ HSG      │ │ BDOT10k      │          │
│  │_dem.py   │ │_landcover│ │ (Soil-   │ │ BUBD         │          │
│  │          │ │.py       │ │ Grids)   │ │ (budynki)    │          │
│  │Kartograf │ │Kartograf │ │Kartograf │ │Kartograf     │          │
│  │GugikProv.│ │LandCover │ │HSGCalc.  │ │Bdot10kProv.  │          │
│  │Download  │ │Manager   │ │          │ │              │          │
│  │Manager   │ │          │ │          │ │              │          │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘          │
│       │             │            │              │                   │
│       │ .asc files  │ .gpkg      │ .tif (HSG)   │ .gpkg (BUBD)    │
│       └──────┬──────┴────────────┴──────────────┘                  │
│              │                                                      │
│              ▼                                                      │
│      ┌──────────────────┐                                           │
│      │  process_dem.py  │                                           │
│      │                  │                                           │
│      │  VRT mosaic →    │                                           │
│      │  building raise  │                                           │
│      │  stream burn →   │                                           │
│      │  pyflwdir →      │                                           │
│      │  stream_network  │                                           │
│      │  + catchments    │                                           │
│      └────────┬─────────┘                                           │
│               │                                                     │
│               ▼                                                     │
│      ┌──────────────────┐                                           │
│      │   PostgreSQL     │                                           │
│      │   + PostGIS      │                                           │
│      │                  │                                           │
│      │  stream_network  │                                           │
│      │  stream_catchments│                                          │
│      │  land_cover      │                                           │
│      │  soil_hsg        │                                           │
│      │  depressions     │                                           │
│      └──────────────────┘                                           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Komponenty

### 3.1 `utils/sheet_finder.py`

Moduł do konwersji współrzędnych geograficznych na godła arkuszy map.

**Funkcje:**

| Funkcja | Opis |
|---------|------|
| `coordinates_to_sheet_code(lat, lon, scale)` | Współrzędne → godło |
| `get_sheet_bounds(sheet_code)` | Godło → granice geograficzne |
| `get_sheets_for_bbox(min_lat, min_lon, max_lat, max_lon)` | BBox → lista godeł |
| `get_neighboring_sheets(sheet_code)` | Godło → sąsiednie arkusze |
| `get_sheets_for_point_with_buffer(lat, lon, buffer_km)` | Punkt + bufor → lista godeł |

**Przykład:**

```python
from utils.sheet_finder import coordinates_to_sheet_code, get_sheets_for_point_with_buffer

# Pojedyncze godło
code = coordinates_to_sheet_code(52.23, 21.01)
# → "N-34-131-C-c-2-1"

# Arkusze dla obszaru 5km wokół punktu
sheets = get_sheets_for_point_with_buffer(52.23, 21.01, buffer_km=5)
# → ["N-34-131-C-c-1-4", "N-34-131-C-c-2-1", "N-34-131-C-c-2-2", ...]
```

### 3.2 `scripts/download_dem.py`

Skrypt do pobierania danych NMT z GUGiK.

**Użycie:**

```bash
# Pobieranie dla punktu z buforem
python -m scripts.download_dem \
    --lat 52.23 --lon 21.01 \
    --buffer 5 \
    --output ../data/nmt/

# Pobieranie konkretnych arkuszy
python -m scripts.download_dem \
    --sheets N-34-131-C-c-2-1 N-34-131-C-c-2-2 \
    --output ../data/nmt/

# Pobieranie arkuszy pokrywających plik geometrii
python -m scripts.download_dem \
    --geometry ../data/boundary.gpkg \
    --output ../data/nmt/
```

**Parametry:**

| Parametr | Opis | Domyślnie |
|----------|------|-----------|
| `--lat`, `--lon` | Współrzędne centrum (WGS84) | - |
| `--buffer` | Promień bufora [km] | 5 |
| `--sheets` | Lista godeł do pobrania | - |
| `--geometry` | Plik geometrii (SHP/GPKG) do selekcji arkuszy | - |
| `--output`, `-o` | Katalog wyjściowy | `../data/nmt/` |
| `--format` | Format (AAIGrid, GTiff) | AAIGrid |
| `--scale` | Skala arkuszy | 1:10000 |

**Klasy Kartografa:**
```python
from kartograf import DownloadManager, GugikProvider
from kartograf import find_sheets_for_geometry  # selekcja po geometrii
```

### 3.3 `scripts/download_landcover.py`

Skrypt do pobierania danych pokrycia terenu.

**Użycie:**

```bash
# BDOT10k dla punktu z buforem (v0.5.0: pobiera wszystkie 15 warstw)
python -m scripts.download_landcover \
    --lat 52.23 --lon 21.01 \
    --buffer 5

# BDOT10k po kodzie TERYT (powiat)
python -m scripts.download_landcover \
    --teryt 1465

# CORINE Land Cover
python -m scripts.download_landcover \
    --lat 52.23 --lon 21.01 \
    --provider corine \
    --year 2018
```

**Klasy Kartografa:**
```python
from kartograf.landcover import LandCoverManager
from kartograf.providers.bdot10k import Bdot10kProvider
from kartograf import BBox
```

**Funkcja `discover_teryts_for_bbox()`** — automatyczne wykrywanie kodów TERYT powiatów w zadanym bounding boxie. Domyślnie wysyła pojedyncze zapytanie WFS GetFeature do PRG GUGiK (`A02_Granice_powiatow`, pole `JPT_KOD_JE`), żądając wyłącznie atrybutów (bez geometrii) dla szybkości. Jeśli WFS jest niedostępny, fallback na starą metodę grid-sampling (`_discover_teryts_grid()` — siatka punktów 25×25 przez `Bdot10kProvider._get_teryt_for_point()`). Parsowanie odpowiedzi GML w `_parse_teryts_from_gml()`. Szczegóły decyzji: ADR-045.

### 3.4 `scripts/bootstrap.py`

One-command orchestrator do pełnego preprocessingu.

**Użycie Kartografa:**

```python
from kartograf import SheetParser       # parsowanie godeł → BBox
from kartograf import HSGCalculator     # obliczanie HSG z SoilGrids
from kartograf import BBox              # obiekt bounding box
```

**Kroki z Kartografem:**
1. `SheetParser(godlo).get_bbox()` — obliczenie bbox z godeł
2. `download_dem.py` — pobieranie NMT (GugikProvider + DownloadManager)
3. `download_landcover.py` — pobieranie BDOT10k (LandCoverManager)
4. `HSGCalculator().calculate_hsg_by_bbox()` — pobieranie HSG z SoilGrids
5. `discover_asc_files()` — skanowanie pobranych plików .asc (bbox overlap check)

### 3.5 `scripts/prepare_area.py`

Pipeline łączący pobieranie i przetwarzanie.

**Użycie:**

```bash
# Pełny pipeline
python -m scripts.prepare_area \
    --lat 52.23 --lon 21.01 \
    --buffer 5

# Z land cover
python -m scripts.prepare_area \
    --lat 52.23 --lon 21.01 \
    --buffer 5 \
    --with-landcover

# Z danymi hydro
python -m scripts.prepare_area \
    --lat 52.23 --lon 21.01 \
    --buffer 5 \
    --with-hydro
```

**Klasa Kartografa:**
```python
from kartograf import SheetParser
```

### 3.6 `core/cn_calculator.py`

Kalkulator CN z wykorzystaniem danych z Kartografa.

**Klasy Kartografa:**
```python
from kartograf import BBox, LandCoverManager
from kartograf.hydrology import HSGCalculator
```

**Funkcje:**
- `check_kartograf_available()` — weryfikacja dostępności Kartografa
- `convert_boundary_to_bbox()` — konwersja granicy WGS84 → BBox EPSG:2180
- `get_hsg_from_soilgrids(bbox)` — HSG z SoilGrids przez HSGCalculator
- `get_land_cover_stats(bbox, data_dir)` — pokrycie terenu z LandCoverManager
- `calculate_cn_from_kartograf(boundary, data_dir)` — pełne obliczenie CN

### 3.7 `utils/raster_utils.py`

Narzędzia rastrowe.

**Funkcja:** `discover_asc_files(nmt_dir, bbox_2180)` — skanuje katalog NMT i filtruje pliki .asc po nakładaniu się z bbox (rozwiązuje problem VRT mosaic gaps).

---

## 4. Moduły Hydrografa korzystające z Kartografa

| Moduł | Importy z Kartografa | Zastosowanie |
|-------|---------------------|--------------|
| `scripts/download_dem.py` | `DownloadManager`, `GugikProvider`, `find_sheets_for_geometry` | Pobieranie NMT z GUGiK |
| `scripts/download_landcover.py` | `LandCoverManager`, `BBox`, `Bdot10kProvider` | Pobieranie BDOT10k/CORINE |
| `scripts/bootstrap.py` | `SheetParser`, `HSGCalculator`, `BBox` | Orchestrator preprocessingu |
| `scripts/prepare_area.py` | `SheetParser` | Pipeline przygotowania obszaru |
| `core/cn_calculator.py` | `BBox`, `HSGCalculator`, `LandCoverManager` | Obliczanie CN |
| `utils/raster_utils.py` | (pośrednio, operuje na plikach .asc) | Skanowanie plików NMT |

---

## 5. System Godeł Arkuszy Map

### 5.1 Hierarchia

```
1:1 000 000  │  N-34                    │  4° × 6°
1:500 000    │  N-34-A                  │  2° × 3°
1:200 000    │  N-34-XXIII              │  40' × 1°
1:100 000    │  N-34-131                │  20' × 30'
1:50 000     │  N-34-131-C              │  10' × 15'
1:25 000     │  N-34-131-C-c            │  5' × 7'30"
1:10 000     │  N-34-131-C-c-2-1        │  2'30" × 3'45"
```

**Uwaga:** Godła 1:25k automatycznie rozwijają się do 4x arkuszy 1:10k (auto-ekspansja).

### 5.2 Podział arkuszy

**1:100 000** - 144 arkuszy na 1:1M (12 x 12)
```
┌───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐
│001│002│003│004│005│006│007│008│009│010│011│012│
├───┼───┼───┼───┼───┼───┼───┼───┼───┼───┼───┼───┤
│013│014│...│                               │024│
├───┼───┼───┼───┼───┼───┼───┼───┼───┼───┼───┼───┤
│...│   │                                   │...│
├───┼───┼───┼───┼───┼───┼───┼───┼───┼───┼───┼───┤
│133│134│135│136│137│138│139│140│141│142│143│144│
└───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┘
```

**1:50 000** - 4 arkusze na 1:100k (A, B, C, D)
```
┌───┬───┐
│ A │ B │
├───┼───┤
│ C │ D │
└───┴───┘
```

**1:25 000** - 4 arkusze na 1:50k (a, b, c, d)
```
┌───┬───┐
│ a │ b │
├───┼───┤
│ c │ d │
└───┴───┘
```

**1:10 000** - 8 arkuszy na 1:25k (wiersz-kolumna)
```
┌─────┬─────┬─────┬─────┐
│ 1-1 │ 1-2 │ 1-3 │ 1-4 │
├─────┼─────┼─────┼─────┤
│ 2-1 │ 2-2 │ 2-3 │ 2-4 │
└─────┴─────┴─────┴─────┘
```

---

## 6. GUGiK WCS API

### 6.1 Endpoint

```
https://mapy.geoportal.gov.pl/wss/service/PZGIK/NMT/WCS/DigitalTerrainModelFormatTIFF
```

### 6.2 Parametry żądania

| Parametr | Wartość |
|----------|---------|
| SERVICE | WCS |
| VERSION | 2.0.1 |
| REQUEST | GetCoverage |
| COVERAGEID | `<godło>` (np. N-34-131-C-c-2-1) |
| FORMAT | image/tiff, application/x-ogc-aaigrid, text/plain |

### 6.3 Formaty

| Format | MIME Type | Rozszerzenie |
|--------|-----------|--------------|
| GeoTIFF | image/tiff | .tif |
| AAIGrid | application/x-ogc-aaigrid | .asc |
| XYZ | text/plain | .xyz |

---

## 7. Obsługa Błędów

### 7.1 Błędy pobierania

| Kod | Przyczyna | Rozwiązanie |
|-----|-----------|-------------|
| 404 | Arkusz nie istnieje | Sprawdź godło |
| 503 | Serwer GUGiK niedostępny | Retry z backoff |
| Timeout | Wolne połączenie | Zwiększ timeout |

### 7.2 Retry Logic

Kartograf implementuje automatyczne ponawianie:
- Max 3 próby
- Exponential backoff (2^n sekund)
- Atomic file writes (temp → rename)

---

## 8. Przykłady Użycia

### 8.1 Przygotowanie danych dla nowego obszaru

```bash
# 1. Sprawdź jakie arkusze są potrzebne
cd backend
python -c "
from utils.sheet_finder import get_sheets_for_point_with_buffer
sheets = get_sheets_for_point_with_buffer(52.23, 21.01, buffer_km=5)
print(f'Arkusze do pobrania: {len(sheets)}')
for s in sheets:
    print(f'  {s}')
"

# 2. Pobierz i przetwórz
.venv/bin/python -m scripts.prepare_area \
    --lat 52.23 --lon 21.01 \
    --buffer 5
```

### 8.2 Pełny bootstrap z panelu admin

```bash
# One-command bootstrap (wszystkie kroki)
.venv/bin/python -m scripts.bootstrap \
    --bbox "20.8,52.1,21.2,52.4"

# Dry run (pokaż plan bez wykonywania)
.venv/bin/python -m scripts.bootstrap \
    --bbox "20.8,52.1,21.2,52.4" --dry-run

# Bootstrap z pominięciem kroków
.venv/bin/python -m scripts.bootstrap \
    --bbox "20.8,52.1,21.2,52.4" \
    --skip-precipitation --skip-tiles
```

### 8.3 Pobieranie konkretnego regionu

```bash
# Pobierz wszystkie arkusze 1:10k dla arkusza 1:100k
.venv/bin/python -m scripts.download_dem \
    --sheets N-34-131-A-a-1-1 N-34-131-A-a-1-2 N-34-131-A-a-1-3 N-34-131-A-a-1-4 \
            N-34-131-A-a-2-1 N-34-131-A-a-2-2 N-34-131-A-a-2-3 N-34-131-A-a-2-4 \
    --output ../data/nmt/
```

### 8.4 Użycie w kodzie Python

```python
from utils.sheet_finder import (
    coordinates_to_sheet_code,
    get_sheets_for_point_with_buffer
)
from kartograf import GugikProvider, DownloadManager

# Znajdź arkusze
sheets = get_sheets_for_point_with_buffer(52.23, 21.01, buffer_km=5)

# Pobierz dane
provider = GugikProvider(resolution="5m")
manager = DownloadManager(output_dir="./data/nmt/", provider=provider)

for sheet in sheets:
    # download_sheet() zwraca Path do pobranego pliku
    path = manager.download_sheet(sheet, skip_existing=True)
    print(f"Pobrano: {path}")
```

---

## 9. Testy

### 9.1 Testy jednostkowe

```bash
# Testy sheet_finder
pytest tests/unit/test_sheet_finder.py -v

# Testy download_landcover (mocked Bdot10kProvider)
pytest tests/unit/test_download_landcover.py -v

# Testy cn_calculator
pytest tests/unit/test_cn_calculator.py -v

# Testy land_cover (spatial intersection CN)
pytest tests/unit/test_land_cover.py -v

# Testy cn_tables (tablice CN dla BDOT10k + BUBD)
pytest tests/unit/test_cn_tables.py -v

# Testy building raising
pytest tests/unit/test_building_raising.py -v

# Testy discover_asc_files
pytest tests/unit/test_discover_asc.py -v

# Testy tiles landcover (MVT)
pytest tests/unit/test_tiles_landcover.py -v
```

### 9.2 Testy integracyjne (wymagają połączenia z GUGiK)

```bash
pytest tests/integration/test_download_dem.py -v --run-network
```

---

## 10. Land Cover (Kartograf 0.6.1)

### 10.1 Dostępne źródła danych

| Źródło | Opis | Skala/Rozdzielczość |
|--------|------|---------------------|
| **BDOT10k** | Baza Danych Obiektów Topograficznych (GUGiK) | 1:10 000 |
| **CORINE** | European Land Cover (Copernicus) | 100m raster |

### 10.2 Warstwy BDOT10k

Od Kartograf v0.5.0+ wszystkie 15 warstw (12 PT + 3 SW) pobierane są w jednym GPKG. Filtrowanie warstw hydro (SWRS, SWKN, SWRM) odbywa się w Hydrograf na etapie merge za pomocą stałej `HYDRO_LAYER_PREFIXES`.

| Kod | Opis | → Hydrograf category | CN |
|-----|------|---------------------|-----|
| PTLZ | Tereny leśne | `las` | 60 |
| PTTR | Tereny rolne | `grunt_orny` | 78 |
| PTUT | Uprawy trwałe | `grunt_orny` | 78 |
| PTWP | Wody powierzchniowe | `woda` | 100 |
| PTWZ | Tereny zabagnione | `łąka` | 70 |
| PTRK | Roślinność krzewiasta | `łąka` | 70 |
| PTZB | Tereny zabudowane | `zabudowa_mieszkaniowa` | 85 |
| PTKM | Tereny komunikacyjne | `droga` | 98 |
| PTPL | Place | `droga` | 98 |
| PTGN | Grunty nieużytkowe | `inny` | 75 |
| PTNZ | Tereny niezabudowane | `inny` | 75 |
| PTSO | Składowiska | `inny` | 75 |
| **BUBD** | **Budynki** | (building raising) | 85-92 (wg HSG) |
| SWRS | Rzeki i strumienie | (hydro — stream burning) | — |
| SWKN | Kanały | (hydro — stream burning) | — |
| SWRM | Rowy melioracyjne | (hydro — stream burning) | — |

### 10.3 Land Cover MVT (Vector Tiles)

Endpoint `/api/tiles/landcover/{z}/{x}/{y}.pbf` serwuje dane land cover jako Mapbox Vector Tiles. Generowane dynamicznie z tabeli `land_cover` (PostGIS `ST_AsMVTGeom`). Atrybuty w tile: `category`, `cn_value`, `bdot_class`.

### 10.4 Import do bazy danych

```bash
.venv/bin/python -m scripts.import_landcover \
    --input ../data/landcover/bdot10k_teryt_1465.gpkg
```

### 10.5 Pełny pipeline z land cover

```bash
.venv/bin/python -m scripts.prepare_area \
    --lat 52.23 --lon 21.01 \
    --buffer 5 \
    --with-landcover
```

### 10.6 API Python

```python
from kartograf.landcover import LandCoverManager
from kartograf import BBox

# Inicjalizacja (domyślnie BDOT10k)
manager = LandCoverManager(output_dir="./data/landcover")

# Pobieranie przez godło arkusza
gpkg_path = manager.download_by_godlo("N-34-131-C-c-2-1")

# Pobieranie przez bounding box (EPSG:2180)
bbox = BBox(450000, 550000, 460000, 560000, "EPSG:2180")
gpkg_path = manager.download_by_bbox(bbox)

# Pobieranie przez TERYT powiatu
gpkg_path = manager.download_by_teryt("1465")

# Zmiana na CORINE Land Cover
manager = LandCoverManager(output_dir="./data/landcover", provider="corine")
gpkg_path = manager.download_by_godlo("N-34-130-D", year=2018)
```

---

## 11. BDOT10k Hydro (Kartograf 0.6.1)

### 11.1 Warstwy hydrograficzne

Od Kartograf v0.5.0+ wszystkie 15 warstw BDOT10k (12 PT + 3 SW) pobierane są w jednym GPKG. Filtrowanie warstw hydrograficznych odbywa się w Hydrograf na etapie merge za pomocą stałej `HYDRO_LAYER_PREFIXES`.

| Kod BDOT10k | Opis | Typ geometrii |
|-------------|------|---------------|
| **SWRS** | Rzeki i strumienie | LineString |
| **SWKN** | Kanały | LineString |
| **SWRM** | Rowy melioracyjne | LineString |
| **PTWP** | Wody powierzchniowe (jeziora, stawy) | Polygon |

### 11.2 Filtrowanie warstw hydro

W Kartograf v0.5.0+ nie ma parametru `category` — wszystkie warstwy pobierane są razem. Filtrowanie warstw hydro (SWRS, SWKN, SWRM, PTWP) odbywa się w `merge_hydro_gpkgs()` za pomocą stałej `HYDRO_LAYER_PREFIXES`:

```python
HYDRO_LAYER_PREFIXES = ("SWRS", "SWKN", "SWRM", "PTWP")
```

### 11.3 Zastosowanie w Hydrograf

Dane hydrograficzne z BDOT10k służą do:
- **Stream burning** — wypalanie cieków w NMT dla lepszego odwzorowania kierunków przepływu (`core/hydrology.py: burn_streams_into_dem()`)
- **Walidacja sieci rzecznej** — porównanie wygenerowanej sieci z danymi referencyjnymi BDOT10k
- **Uzupełnienie informacji** — nazwy cieków, klasyfikacja (rzeka/kanał/rów)

---

## 12. Building Raising (ADR-033)

### 12.1 Problem

Budynki w NMT nie są wystarczająco "podwyższone" — woda w modelu przepływa przez budynki, co daje nierealistyczne kierunki spływu.

### 12.2 Rozwiązanie

Funkcja `raise_buildings_in_dem()` w `core/hydrology.py`:
- Pobiera footprinty budynków z BUBD (BDOT10k, GeoPackage)
- Rasteryzuje geometrie na siatkę DEM
- Podnosi wartości DEM pod budynkami o +5m

```python
from core.hydrology import raise_buildings_in_dem

dem = raise_buildings_in_dem(
    dem=dem_array,
    transform=rasterio_transform,
    crs_epsg=2180,
    building_gpkg="data/landcover/bubd.gpkg",
    building_raise_m=5.0,
)
```

### 12.3 Pipeline

Building raising jest zintegrowany w `process_dem.py` — wykonuje się automatycznie po załadowaniu NMT, przed obliczaniem kierunków przepływu.

---

## 13. HSG — Grupy Hydrologiczne Gleby

### 13.1 Przegląd

HSGCalculator z Kartografa pobiera dane z SoilGrids (globalny dataset gleb) i klasyfikuje je do grup hydrologicznych (A, B, C, D).

### 13.2 Użycie w Hydrograf

Dwa punkty integracji:
1. **`bootstrap.py` krok 5** — masowe pobieranie HSG dla całego bbox, polygonizacja i import do tabeli `soil_hsg`
2. **`cn_calculator.py`** — obliczanie CN na żądanie (online) dla konkretnej zlewni

### 13.3 Tabela `soil_hsg`

| Kolumna | Typ | Opis |
|---------|-----|------|
| id | SERIAL | PK |
| hsg_group | VARCHAR(2) | Grupa HSG (A, B, C, D) |
| geom | GEOMETRY(MultiPolygon, 2180) | Geometria |

Dane z tabeli `soil_hsg` używane w `core/soil_hsg.py: get_hsg_for_boundary()` — spatial intersection z granicą zlewni do obliczenia dominującej grupy HSG.

---

## 14. Filtrowanie po geometrii

Kartograf umożliwia ograniczenie pobieranych danych do zadanego zasięgu przestrzennego:

```python
from kartograf import find_sheets_for_geometry

# Selekcja arkuszy pokrywających plik geometrii
sheets = find_sheets_for_geometry("boundary.gpkg", target_scale="1:10000")
```

```bash
# Pobieranie NMT dla pliku geometrii
python -m scripts.download_dem \
    --geometry ../data/watershed_boundary.geojson \
    --output ../data/nmt/
```

---

## 15. Przyszłe Rozszerzenia

- [x] **Land Cover** - pobieranie BDOT10k i CORINE (Kartograf 0.3.0)
- [x] **Auto-ekspansja godeł** - automatyczne rozwijanie godeł grubszych skal (Kartograf 0.4.0)
- [x] **Progress callback** - `on_progress` w `download_sheet()` (Kartograf 0.4.0)
- [x] **BDOT10k hydro** - kategorie hydrograficzne SWRS, SWKN, SWRM, PTWP (Kartograf 0.4.1)
- [x] **Geometry file selection** - filtrowanie danych po pliku geometrii (Kartograf 0.4.1)
- [x] **HSG Calculator** - grupy hydrologiczne gleby z SoilGrids (Kartograf 0.4.1)
- [x] **Building raising** - BUBD footprints z BDOT10k → +5m w DEM (ADR-033)
- [x] **Land cover MVT** - endpoint `/api/tiles/landcover/{z}/{x}/{y}.pbf` (CP4)
- [x] **CN calculation** - cn_calculator + cn_tables z danymi Kartografa
- [ ] **NMPT integration** - wykorzystanie NMPT w analizach (dostępny od Kartograf 0.4.0)
- [x] **Cache lokalny** - separacja cache/data, unikanie ponownego pobierania (ADR-037, Kartograf 0.5.0)
- [ ] **Parallel download** - równoległe pobieranie wielu arkuszy

---

**Wersja dokumentu:** 5.0
**Ostatnia aktualizacja:** 2026-03-02
