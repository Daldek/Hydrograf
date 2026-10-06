# Integracja z Kartografem

**Wersja:** 5.2
**Data:** 2026-09-28
**Status:** Aktywna

---

## 1. Przegląd

Hydrograf wykorzystuje [Kartograf](https://github.com/Daldek/Kartograf) (v0.6.1) do automatycznego pobierania danych przestrzennych z polskich i europejskich zasobów:

- **NMT** - Numeryczny Model Terenu z GUGiK
- **NMPT** - Numeryczny Model Pokrycia Terenu z GUGiK
- **Ortofotomapa** - Ortofotomapy z GUGiK
- **BDOT10k** - Dane z GUGiK
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
- **Auto-ekspansji godeł** — automatyczne rozwijanie godeł grubszych skal do arkuszy 1:10000
- **Filtrowania po geometrii** — ograniczanie danych do zadanego zasięgu
- **Pobierania BDOT10k**
- **Batch download** z retry logic i progress tracking

### 1.2 Dlaczego integracja?

| Problem | Rozwiązanie |
|---------|-------------|
| Ręczne pobieranie NMT z Geoportalu | Automatyczne pobieranie przez Kartograf |
| Użytkownik musi znać godła arkuszy | Konwersja współrzędnych -> godło |
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
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    bootstrap.py                             │    │
│  │  (Orchestrator: 10 kroków, subprocess, SSE streaming)       │    │
│  └─────────────────┬───────────────────────────────────────────┘    │
│                    │                                                │
│      ┌─────────────┼─────────────┬─────────────┐                    │
│      │             │             │             │                    │
│      ▼             ▼             ▼             ▼                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐            │
│  │download  │ │download  │ │ HSG      │ │ BDOT10k      │            │
│  │_dem.py   │ │_landcover│ │ (Soil-   │ │ BUBD         │            │
│  │          │ │.py       │ │ Grids)   │ │ (budynki)    │            │
│  │Kartograf │ │Kartograf │ │Kartograf │ │Kartograf     │            │
│  │GugikProv.│ │LandCover │ │HSGCalc.  │ │Bdot10kProv.  │            │
│  │Download  │ │Manager   │ │          │ │              │            │
│  │Manager   │ │          │ │          │ │              │            │
│  └────┬─────┘ └─────┬────┘ └────┬─────┘ └───────┬──────┘            │
│       │             │            │              │                   │
│       │ .asc files  │ .gpkg      │ .tif (HSG)   │ .gpkg (BUBD)      │
│       └──────┬──────┴────────────┴──────────────┘                   │
│              │                                                      │
│              ▼                                                      │
│      ┌──────────────────┐                                           │
│      │  process_dem.py  │                                           │
│      │                  │                                           │
│      │  VRT mosaic ->   │                                           │
│      │  building raise  │                                           │
│      │  stream burn ->  │                                           │
│      │  pyflwdir ->     │                                           │
│      │  stream_network  │                                           │
│      │  + catchments    │                                           │
│      └────────┬─────────┘                                           │
│               │                                                     │
│               ▼                                                     │
│      ┌───────────────────┐                                          │
│      │   PostgreSQL      │                                          │
│      │   + PostGIS       │                                          │
│      │                   │                                          │
│      │  stream_network   │                                          │
│      │  stream_catchments│                                          │
│      │  land_cover       │                                          │
│      │  soil_hsg         │                                          │
│      │  depressions      │                                          │
│      └───────────────────┘                                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Komponenty

### 3.1 `utils/sheet_lookup.py`

Moduł do konwersji punktu + bufora na godła arkuszy map. Od ADR-057 (sesja
2026-09-28) Hydrograf **nie reimplementuje** matematyki godeł — `sheet_lookup.py`
jest cienkim wrapperem delegującym do `kartograf.find_sheets_for_bbox()`
(WGS84 -> EPSG:2180 przez `transform_wgs84_to_pl1992()`, budowa `kartograf.BBox`,
wywołanie Kartografa). Zastąpił usunięty `utils/sheet_finder.py` (~616 linii
własnej logiki godło↔współrzędne), który dzielił arkusz 1:25000 na 1:10000
siatką 2×4 zamiast zagnieżdżonego 2×2 wg GUGiK — dawało to błędne godła bez
pokrycia wspólnego z poprawnym wynikiem Kartografa dla tego samego punktu
i bufora. Szczegóły: ADR-057.

**Funkcje:**

| Funkcja | Opis |
|---------|------|
| `sheets_for_point_buffer(lat, lon, buffer_km, scale="1:10000")` | Punkt + bufor -> posortowana lista godeł (deleguje do `kartograf.find_sheets_for_bbox()`) |

**Przykład:**

```python
from utils.sheet_lookup import sheets_for_point_buffer

# Arkusze dla obszaru 5km wokół punktu
sheets = sheets_for_point_buffer(52.23, 21.01, buffer_km=5)
# -> ["N-34-131-C-c-1-4", "N-34-131-C-c-2-1", "N-34-131-C-c-2-2", ...]
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
| `--layer` | Nazwa warstwy w pliku GPKG | pierwsza warstwa |
| `--output`, `-o` | Katalog wyjściowy | `../data/nmt/` |
| `--scale` | Skala arkuszy (`1:10000`, `1:25000`, `1:50000`, `1:100000` — etykiety Kartografa, patrz §5.1) | 1:10000 |
| `--no-skip-existing` | Pobierz ponownie mimo istniejącego pliku | wyłączone |
| `--dry-run` | Pokaż plan bez pobierania | wyłączone |

Format pliku wyjściowego jest zawsze ASC (ESRI ASCII Grid, OpenData GUGiK) — nie ma parametru `--format`, skrypt zawsze loguje `Format: ASC (OpenData)`.

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
from kartograf.landcover import LandCoverManager  # (lub from kartograf import LandCoverManager — re-export)
from kartograf.providers.bdot10k import Bdot10kProvider
from kartograf import BBox  # (lub from kartograf.core.geometry import BBox)
```

**Funkcja `discover_teryts_for_bbox()`** — automatyczne wykrywanie kodów TERYT powiatów w zadanym bounding boxie. Domyślnie wysyła pojedyncze zapytanie WFS GetFeature do PRG GUGiK (`A02_Granice_powiatow`, pole `JPT_KOD_JE`), żądając wyłącznie atrybutów (bez geometrii) dla szybkości. Jeśli WFS jest niedostępny (błąd sieci lub 0 wyników), fallback na starszą metodę `_discover_teryts_grid()`: próbkowanie punktów siatką o kroku `spacing_m=2000` (co ~2 km, liczba punktów zależy od rozmiaru bboxa — generowana przez `_generate_sample_coords()`) i odpytanie każdego przez `Bdot10kProvider._get_teryt_for_point()`. To **nie** jest stała siatka 25×25 — to podejście pochodzi jeszcze sprzed ADR-045. Ponieważ `_get_teryt_for_point()` jest prywatną metodą Kartografa (brak publicznej alternatywy w 0.6.1), `_discover_teryts_grid()` zaczyna od jawnego guardu (`callable(getattr(Bdot10kProvider, "_get_teryt_for_point", None))`, podnosi `RuntimeError` gdy API zniknie) pilnowanego przez test kontraktowy w `test_download_landcover.py`. Parsowanie odpowiedzi GML w `_parse_teryts_from_gml()`. Szczegóły decyzji: ADR-045.

### 3.4 `scripts/bootstrap.py`

One-command orchestrator do pełnego preprocessingu.

**Użycie Kartografa:**

```python
from kartograf import SheetParser       # parsowanie godeł -> BBox
from kartograf import HSGCalculator     # obliczanie HSG z SoilGrids
from kartograf import BBox              # obiekt bounding box (lub from kartograf.core.geometry import BBox)
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
from kartograf import BBox, LandCoverManager  # (lub kartograf.core.geometry.BBox / kartograf.landcover.LandCoverManager)
from kartograf.hydrology import HSGCalculator
```

**Funkcje:**
- `check_kartograf_available()` — weryfikacja dostępności Kartografa
- `convert_boundary_to_bbox()` — konwersja granicy WGS84 -> BBox EPSG:2180
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
| `utils/sheet_lookup.py` | `BBox`, `find_sheets_for_bbox` | Punkt + bufor -> godła arkuszy (ADR-057), używane przez `download_dem.py --lat/--lon` i `prepare_area.py` |
| `scripts/download_landcover.py` | `LandCoverManager`, `BBox`, `Bdot10kProvider` | Pobieranie BDOT10k/CORINE |
| `scripts/download_landcover.py` | `Bdot10kProvider` (`kartograf.providers.bdot10k`) | Fallback TERYT discovery (`_discover_teryts_grid`) — WMS point query dla kodów TERYT. Korzysta z **prywatnej** metody `_get_teryt_for_point()` (brak publicznej alternatywy w 0.6.1) — zabezpieczone jawnym guardem + testem kontraktowym, udokumentowany wyjątek w ADR-057 |
| `scripts/bootstrap.py` | `SheetParser`, `HSGCalculator`, `BBox` | Orchestrator preprocessingu |
| `scripts/prepare_area.py` | `SheetParser` | Pipeline przygotowania obszaru |
| `core/cn_calculator.py` | `BBox`, `HSGCalculator`, `LandCoverManager` | Obliczanie CN |
| `utils/raster_utils.py` | (pośrednio, operuje na plikach .asc) | Skanowanie plików NMT |

---

## 5. System Godeł Arkuszy Map

### 5.1 Hierarchia

Oficjalna nomenklatura PUWG-1992 (godło -> rozmiar arkusza):

```
1:1 000 000  │  N-34                    │  4° × 6°
1:500 000    │  N-34-A                  │  2° × 3°
1:100 000    │  N-34-131                │  20' × 30'
1:50 000     │  N-34-131-C              │  10' × 15'
1:25 000     │  N-34-131-C-c            │  5' × 7'30"
1:10 000     │  N-34-131-C-c-1          │  2'30" × 3'45"
1:5 000      │  N-34-131-C-c-1-1        │  1'15" × 1'52,5"
```

**Uwaga — przesunięte nazewnictwo skal w Kartografie:** `SheetParser(...).scale` i parametr `target_scale` w `find_sheets_for_bbox()`/`find_sheets_for_geometry()` używają **własnych etykiet Kartografa**, przesuniętych o jeden poziom względem powyższej oficjalnej nomenklatury:

| Wzorzec godła (liczba członów) | `scale` wg Kartografa | Faktyczna oficjalna skala |
|---|---|---|
| `N-34-A` (3, litera A-D) | `"1:500000"` | 1:500 000 (bez przesunięcia) |
| `N-34-131` (3, liczba) | `"1:200000"` | **1:100 000** |
| `N-34-131-C` (4) | `"1:100000"` | **1:50 000** |
| `N-34-131-C-c` (5) | `"1:50000"` | **1:25 000** |
| `N-34-131-C-c-1` (6) | `"1:25000"` | **1:10 000** |
| `N-34-131-C-c-1-1` (7) | `"1:10000"` | **1:5 000** |

Zweryfikowano w `sheet_parser.py` (komentarz „mylące nazewnictwo w COMPONENT_NAMES" przy `arkusz_200k`, ok. :708) oraz empirycznie: `SheetParser("N-34-131").scale == "1:200000"`, `SheetParser("N-34-131-C-c-1-1").scale == "1:10000"`.

W praktyce oznacza to, że wywołanie `find_sheets_for_bbox/geometry(..., target_scale="1:10000")` — którego Hydrograf używa domyślnie (`sheet_lookup.py`, `download_dem.py --scale 1:10000`) — zwraca **7-członowe godła, czyli oficjalnie arkusze 1:5000**. To jest właśnie siatka plików NMT pobieranych z GUGiK OpenData, np. `cache/nmt/nmt_1m/N-34/139/A/c/4/1/N-34-139-A-c-4-1.asc`.

**Auto-ekspansja:** `DownloadManager.download_sheet(godlo)` automatycznie rozwija każde godło grubsze niż etykieta Kartografa `"1:10000"` (czyli oficjalnie grubsze niż 1:5000) do listy wszystkich potomnych arkuszy 1:5000, wywołując `get_all_descendants("1:10000")`. Np. godło oznaczone przez Kartograf jako `"1:25000"` (oficjalnie 1:10 000, 6-członowe) rozwija się do 4 arkuszy 1:5000; godło `"1:50000"` (oficjalnie 1:25 000, 5-członowe) — do 16. Schemat podziału: patrz §5.2.

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

**1:10 000** - 4 arkusze na 1:25k (1, 2, 3, 4)
```
┌─────┬─────┐
│  1  │  2  │
├─────┼─────┤
│  3  │  4  │
└─────┴─────┘
```
(1=NW, 2=NE, 3=SW, 4=SE — `_QUADRANT_POSITIONS` w `sheet_parser.py` ok. :579)

**1:5 000** - 4 arkusze na 1:10k (1, 2, 3, 4), ten sam schemat kodów
```
┌─────┬─────┐
│  1  │  2  │
├─────┼─────┤
│  3  │  4  │
└─────┴─────┘
```

Pełne godło 1:5000 zagnieżdża oba poziomy, np. `N-34-131-C-c-1-1` = `N-34-131-C-c` (1:25k) + `1` (ćwiartka 1:25k->1:10k, NW) + `1` (ćwiartka 1:10k->1:5k, NW).

**Uwaga historyczna:** usunięty moduł `utils/sheet_finder.py` dzielił arkusz 1:25 000 na 1:10 000 błędną siatką 2×4 (wiersz-kolumna) zamiast poprawnego zagnieżdżonego podziału 2×2 pokazanego wyżej — patrz ADR-057.

---

## 6. Pobieranie NMT z GUGiK (OpenData)

### 6.1 Ścieżka wywołań

Hydrograf pobiera NMT wyłącznie przez godła arkuszy (OpenData), nigdy przez WCS/bbox. Pełny łańcuch wywołań:

```
scripts/bootstrap.py / scripts/download_dem.py
    -> kartograf.DownloadManager(output_dir, provider=GugikProvider(...), resolution=...)
        -> DownloadManager.download_sheet(godlo, skip_existing=True)
            (dla godeł grubszych niż etykieta "1:10000" — auto-ekspansja, patrz §5.1/§5.2)
            -> GugikProvider.download(godlo, output_path)
                -> GugikProvider._get_opendata_url(godlo)     # znalezienie URL pliku ASC
                -> GugikProvider._download_with_retry(url, ...) # pobranie z retry
            -> FileStorage.get_path(godlo, ".asc")             # ścieżka docelowa na dysku
```

**Krok 1 — znalezienie URL pliku (`_get_opendata_url`, `kartograf/providers/gugik.py`):**
GUGiK OpenData nie ma prostego mapowania godło->URL, więc Kartograf odpytuje serwis WMS „skorowidzów" (indeksów arkuszy) metodą `GetFeatureInfo` w punkcie centralnym bboxa arkusza (bbox liczony przez `SheetParser(godlo).get_bbox(crs="EPSG:2180")`). Endpoint i warstwy zależą od rozdzielczości i układu wysokościowego:

| Rozdzielczość | Układ wysokościowy | WMS endpoint (skorowidze) | Warstwy (od najnowszej) |
|---|---|---|---|
| 1m | EVRF2007 | `.../NMT/WMS/SkorowidzeUkladEVRF2007` | SkorowidzeNMT2025, 2024, 2023, 2022iStarsze |
| 1m | KRON86 | `.../NMT/WMS/SkorowidzeUkladKRON86` | SkorowidzeNMT2019, 2018, 2017iStarsze |
| 5m | EVRF2007 (jedyny wspierany) | `.../NMT/WMS/SheetsGrid5mEVRF2007` | SkorowidzeNMT2025, 2024, 2023, 2022iStarsze |

Kartograf najpierw próbuje zweryfikować tę zaszytą w kodzie listę warstw przez `GetCapabilities` (per instancja providera, z fallbackiem na wartości zaszyte przy błędzie sieci) i odpytuje kolejne warstwy aż znajdzie URL pasujący wzorcem `url:"(https://opendata[^"]+\.asc)"` w odpowiedzi HTML. Jeśli żadna warstwa nie zwróci pliku — `DownloadError`.

**Krok 2 — pobranie pliku (`_download_with_retry` / `_save_response`):** HTTP GET ze strumieniowaniem, retry `MAX_RETRIES=3` z exponential backoff `2^n` sekund (`RETRY_BACKOFF_BASE=2`), zapis atomowy (plik tymczasowy `.tmp` per proces/wątek -> `rename()`).

**Cache URL-i (`MetadataCache`, `kartograf/cache/metadata.py`):** Kartograf udostępnia opcjonalny SQLite cache (`url_cache`, TTL domyślnie 7 dni) na wyniki `_get_opendata_url()`, przekazywany przez `cache=` do `GugikProvider`. **Hydrograf go obecnie nie podłącza** — `scripts/download_dem.py` tworzy `GugikProvider(resolution=resolution)` bez argumentu `cache`, więc każde pobranie wykonuje świeże zapytanie WMS GetFeatureInfo (zweryfikowane grepem — brak `MetadataCache`/`cache=` w `scripts/`, `core/`, `utils/`).

### 6.2 Parametry używane przez Hydrograf

| Parametr `GugikProvider`/`DownloadManager` | Wartość w Hydrografie | Gdzie ustawiane |
|---|---|---|
| `resolution` | `"5m"` (domyślnie) | `scripts/download_dem.py: download_sheets()`, `scripts/bootstrap.py` (`--resolution`, domyślnie `5m`) |
| `vertical_crs` | `"EVRF2007"` (domyślny w Kartografie, Hydrograf go nie nadpisuje) | — |
| `skip_existing` | `True` domyślnie (CLI: `--no-skip-existing` wyłącza) | `download_sheet(godlo, skip_existing=...)` |
| Format wyjściowy | ASC (ESRI ASCII Grid) | stały dla ścieżki OpenData, `GugikProvider.default_extension == ".asc"` |
| CRS pozioma | EPSG:2180 (PL-1992) | bbox arkuszy liczony przez `SheetParser` |

### 6.3 Układ plików na dysku

`FileStorage` (`kartograf/download/storage.py`) organizuje pliki wg rozdzielczości i członów godła:

```
{output_dir}/nmt_5m/N-34/131/C/c/1/1/N-34-131-C-c-1-1.asc
{output_dir}/nmt_1m/N-34/131/C/c/1/1/N-34-131-C-c-1-1.asc
```

(`nmt_<resolution>/<pas-słup>/<100k>/<50k>/<25k>/<10k_kartografa>/<godło>.asc` — ostatni katalog odpowiada oficjalnej skali 1:5000, patrz §5.1).

### 6.4 Ścieżka WCS (nieużywana przez Hydrograf)

Kartograf udostępnia też `GugikProvider.download_bbox()` / `DownloadManager.download_bbox()` — pobieranie dowolnego bboxa (nie wyrównanego do siatki arkuszy) przez WCS `GetCoverage`. **Hydrograf tego nie wywołuje** (zweryfikowane grepem po `download_bbox` w `scripts/`, `core/`, `utils/` — jedyne wystąpienie to komentarz w docstringu `download_dem.py`). Ograniczenia tej ścieżki:

- dostępna wyłącznie dla rozdzielczości **1m** (`WCS_ENDPOINTS` zawiera `.../NMT/GRID1/WCS/...`, `GRID1` = siatka 1m; dla 5m WCS nie istnieje)
- formaty: tylko `GTiff` (`image/tiff`), `PNG` (`image/png`), `JPEG` (`image/jpeg`) — **brak ASC/AAIGrid przez WCS**
- endpointy (`WCS_ENDPOINTS`, `gugik.py` ok. :81-85), po układzie wysokościowym:
  - `KRON86`: `https://mapy.geoportal.gov.pl/wss/service/PZGIK/NMT/GRID1/WCS/DigitalTerrainModelFormatTIFF`
  - `EVRF2007`: `https://mapy.geoportal.gov.pl/wss/service/PZGIK/NMT/GRID1/WCS/DigitalTerrainModelFormatTIFFEVRF2007`
- `SERVICE=WCS`, `VERSION=2.0.1`, `REQUEST=GetCoverage`, `COVERAGEID` z `COVERAGE_IDS` (`DTM_PL-KRON86-NH_TIFF` / `DTM_PL-EVRF2007-NH_TIFF`), `SUBSET=x(...)`/`SUBSET=y(...)` dla bboxa w EPSG:2180

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
- Atomic file writes (temp -> rename)

---

## 8. Przykłady Użycia

### 8.1 Przygotowanie danych dla nowego obszaru

```bash
# 1. Sprawdź jakie arkusze są potrzebne
cd backend
python -c "
from utils.sheet_lookup import sheets_for_point_buffer
sheets = sheets_for_point_buffer(52.23, 21.01, buffer_km=5)
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
from utils.sheet_lookup import sheets_for_point_buffer
from kartograf import GugikProvider, DownloadManager

# Znajdź arkusze
sheets = sheets_for_point_buffer(52.23, 21.01, buffer_km=5)

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
# Testy sheet_lookup
pytest tests/unit/test_sheet_lookup.py -v

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

### 9.2 Test regresyjny download_dem (mocked, bez sieci)

```bash
pytest tests/unit/test_download_dem.py -v
```

Test pilnuje regresji Path vs `str` przy wywołaniu `find_sheets_for_geometry()` (commit 382c5f3) — w pełni zamockowany, nie wykonuje żadnych połączeń sieciowych. W repozytorium **nie ma obecnie testu integracyjnego z żywym połączeniem do GUGiK** — `tests/integration/` zawiera testy end-to-end na lokalnym stosie (DB/API), nie testy sieciowe Kartografa; `pyproject.toml` definiuje tylko markery `db` i `benchmark`, brak markera sieciowego.

---

## 10. Land Cover (Kartograf 0.6.1)

### 10.1 Dostępne źródła danych

| Źródło | Opis | Skala/Rozdzielczość |
|--------|------|---------------------|
| **BDOT10k** | Baza Danych Obiektów Topograficznych (GUGiK) | 1:10 000 |
| **CORINE** | European Land Cover (Copernicus) | 100m raster |

### 10.2 Warstwy BDOT10k

Od Kartograf v0.5.0+ wszystkie 15 warstw (12 PT + 3 SW) pobierane są w jednym GPKG. Filtrowanie warstw hydro (SWRS, SWKN, SWRM) odbywa się w Hydrograf na etapie merge za pomocą stałej `HYDRO_LAYER_PREFIXES`.

| Kod | Opis | -> Hydrograf category | CN |
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
| **BUBD** | **Budynki** | (building raising) | 77-92 (wg HSG) |
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
from kartograf.landcover import LandCoverManager  # (lub from kartograf import LandCoverManager)
from kartograf import BBox  # (lub from kartograf.core.geometry import BBox)

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
| hsg_group | VARCHAR(1) | Grupa HSG (A, B, C, D) — `CHECK (hsg_group IN ('A','B','C','D'))` |
| area_m2 | DOUBLE PRECISION NOT NULL | Powierzchnia poligonu [m²] |
| geom | GEOMETRY(MultiPolygon, 2180) | Geometria |

Zgodne z `backend/migrations/versions/001_initial_schema.py` (ok. :156-162) i `docs/DATA_MODEL.md` §3.7. Dane z tabeli `soil_hsg` używane w `core/soil_hsg.py: get_hsg_for_boundary()` — spatial intersection z granicą zlewni do obliczenia dominującej grupy HSG.

---

## 14. Filtrowanie po geometrii

Kartograf umożliwia ograniczenie pobieranych danych do zadanego zasięgu przestrzennego:

```python
from pathlib import Path
from kartograf import find_sheets_for_geometry

# Selekcja arkuszy pokrywających plik geometrii
# find_sheets_for_geometry() wymaga pathlib.Path — wywołuje filepath.suffix
# wewnątrz _read_shp_bboxes/_read_gpkg_bboxes; str powoduje AttributeError
# (regresja naprawiona w commit 382c5f3, pilnowana przez tests/unit/test_download_dem.py)
sheets = find_sheets_for_geometry(Path("boundary.gpkg"), target_scale="1:10000")
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
- [x] **Building raising** - BUBD footprints z BDOT10k -> +5m w DEM (ADR-033)
- [x] **Land cover MVT** - endpoint `/api/tiles/landcover/{z}/{x}/{y}.pbf` (CP4)
- [x] **CN calculation** - cn_calculator + cn_tables z danymi Kartografa
- [ ] **NMPT integration** - wykorzystanie NMPT w analizach (dostępny od Kartograf 0.4.0)
- [x] **Cache lokalny** - separacja cache/data, unikanie ponownego pobierania (ADR-037, Kartograf 0.5.0)
- [ ] **Parallel download** - równoległe pobieranie wielu arkuszy

---

**Wersja dokumentu:** 5.2
**Ostatnia aktualizacja:** 2026-09-28 — audyt zgodności z kodem (Hydrograf `backend/` + zainstalowany Kartograf 0.6.1): poprawiono liczbę kroków bootstrapu (10), tabelę parametrów `download_dem.py` (usunięto nieistniejący `--format`, dodano `--layer`), opis fallbacku TERYT (`_discover_teryts_grid` to nie siatka 25×25, tylko próbkowanie co `spacing_m=2000`), pełną hierarchię i podział godeł (przesunięte etykiety skal w Kartografie względem oficjalnej nomenklatury PUWG-1992), przepisano §6 na rzeczywistą ścieżkę pobierania NMT (OpenData przez WMS GetFeatureInfo + retry, WCS jako nieużywana alternatywa), test regresyjny w §9.2, zakres CN dla BUBD (77-92), kolumnę `area_m2`/CHECK w `soil_hsg`, przykład Python z `Path` w §14
