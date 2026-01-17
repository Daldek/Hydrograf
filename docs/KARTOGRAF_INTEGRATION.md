# Integracja z Kartografem

**Wersja:** 1.0
**Data:** 2026-01-17
**Status:** W implementacji

---

## 1. Przegląd

HydroLOG wykorzystuje [Kartograf](https://github.com/Daldek/Kartograf) do automatycznego pobierania danych NMT (Numeryczny Model Terenu) z zasobów GUGiK. Eliminuje to konieczność ręcznego pobierania plików z Geoportalu.

### 1.1 Co to jest Kartograf?

Kartograf to narzędzie Python do:
- **Parsowania godeł** arkuszy map topograficznych (układ 1992 i 2000)
- **Pobierania danych NMT** z GUGiK przez WCS API
- **Zarządzania hierarchią arkuszy** (od 1:1M do 1:10k)
- **Batch download** z retry logic i progress tracking

### 1.2 Dlaczego integracja?

| Problem | Rozwiązanie |
|---------|-------------|
| Ręczne pobieranie NMT z Geoportalu | Automatyczne pobieranie przez Kartograf |
| Użytkownik musi znać godła arkuszy | Konwersja współrzędnych → godło |
| Wiele arkuszy dla dużych zlewni | Automatyczne pobieranie sąsiednich arkuszy |
| Brak spójności formatów | Jednolity format AAIGrid (.asc) |

---

## 2. Architektura Integracji

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PRZEPŁYW DANYCH                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Użytkownik                                                         │
│      │                                                              │
│      │ (lat, lon, buffer_km)                                        │
│      ▼                                                              │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                   prepare_area.py                            │   │
│  │  (Pipeline: download + process)                              │   │
│  └─────────────────┬───────────────────────────────────────────┘   │
│                    │                                                │
│      ┌─────────────┴─────────────┐                                 │
│      │                           │                                 │
│      ▼                           ▼                                 │
│  ┌───────────────┐       ┌──────────────────┐                      │
│  │sheet_finder.py│       │  download_dem.py │                      │
│  │               │       │                  │                      │
│  │ lat,lon →     │       │  Kartograf       │                      │
│  │ godła arkuszy │       │  GugikProvider   │                      │
│  └───────┬───────┘       └────────┬─────────┘                      │
│          │                        │                                 │
│          │ Lista godeł            │ Pliki .asc                     │
│          └───────────┬────────────┘                                 │
│                      │                                              │
│                      ▼                                              │
│              ┌──────────────────┐                                   │
│              │  process_dem.py  │                                   │
│              │                  │                                   │
│              │  pysheds →       │                                   │
│              │  flow_network    │                                   │
│              └────────┬─────────┘                                   │
│                       │                                             │
│                       ▼                                             │
│              ┌──────────────────┐                                   │
│              │   PostgreSQL     │                                   │
│              │   + PostGIS      │                                   │
│              │                  │                                   │
│              │  flow_network    │                                   │
│              └──────────────────┘                                   │
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
```

**Parametry:**

| Parametr | Opis | Domyślnie |
|----------|------|-----------|
| `--lat`, `--lon` | Współrzędne centrum (WGS84) | - |
| `--buffer` | Promień bufora [km] | 5 |
| `--sheets` | Lista godeł do pobrania | - |
| `--output`, `-o` | Katalog wyjściowy | `../data/nmt/` |
| `--format` | Format (AAIGrid, GTiff) | AAIGrid |
| `--scale` | Skala arkuszy | 1:10000 |

### 3.3 `scripts/prepare_area.py`

Pipeline łączący pobieranie i przetwarzanie.

**Użycie:**

```bash
# Pełny pipeline
python -m scripts.prepare_area \
    --lat 52.23 --lon 21.01 \
    --buffer 5

# Z dodatkowymi opcjami
python -m scripts.prepare_area \
    --lat 52.23 --lon 21.01 \
    --buffer 10 \
    --stream-threshold 50 \
    --save-intermediates
```

**Parametry:**

| Parametr | Opis | Domyślnie |
|----------|------|-----------|
| `--lat`, `--lon` | Współrzędne centrum (WGS84) | (wymagane) |
| `--buffer` | Promień bufora [km] | 5 |
| `--stream-threshold` | Próg akumulacji dla strumieni | 100 |
| `--save-intermediates` | Zapis plików GeoTIFF | false |
| `--keep-downloads` | Zachowaj pobrane pliki .asc | true |

---

## 4. System Godeł Arkuszy Map

### 4.1 Hierarchia

```
1:1 000 000  │  N-34                    │  4° × 6°
1:500 000    │  N-34-A                  │  2° × 3°
1:200 000    │  N-34-XXIII              │  40' × 1°
1:100 000    │  N-34-131                │  20' × 30'
1:50 000     │  N-34-131-C              │  10' × 15'
1:25 000     │  N-34-131-C-c            │  5' × 7'30"
1:10 000     │  N-34-131-C-c-2-1        │  2'30" × 3'45"
```

### 4.2 Podział arkuszy

**1:100 000** - 144 arkuszy na 1:1M (12 × 12)
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

## 5. GUGiK WCS API

### 5.1 Endpoint

```
https://mapy.geoportal.gov.pl/wss/service/PZGIK/NMT/WCS/DigitalTerrainModelFormatTIFF
```

### 5.2 Parametry żądania

| Parametr | Wartość |
|----------|---------|
| SERVICE | WCS |
| VERSION | 2.0.1 |
| REQUEST | GetCoverage |
| COVERAGEID | `<godło>` (np. N-34-131-C-c-2-1) |
| FORMAT | image/tiff, application/x-ogc-aaigrid, text/plain |

### 5.3 Formaty

| Format | MIME Type | Rozszerzenie |
|--------|-----------|--------------|
| GeoTIFF | image/tiff | .tif |
| AAIGrid | application/x-ogc-aaigrid | .asc |
| XYZ | text/plain | .xyz |

---

## 6. Obsługa Błędów

### 6.1 Błędy pobierania

| Kod | Przyczyna | Rozwiązanie |
|-----|-----------|-------------|
| 404 | Arkusz nie istnieje | Sprawdź godło |
| 503 | Serwer GUGiK niedostępny | Retry z backoff |
| Timeout | Wolne połączenie | Zwiększ timeout |

### 6.2 Retry Logic

Kartograf implementuje automatyczne ponawianie:
- Max 3 próby
- Exponential backoff (2^n sekund)
- Atomic file writes (temp → rename)

---

## 7. Przykłady Użycia

### 7.1 Przygotowanie danych dla nowego obszaru

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

### 7.2 Pobieranie konkretnego regionu

```bash
# Pobierz wszystkie arkusze 1:10k dla arkusza 1:100k
.venv/bin/python -m scripts.download_dem \
    --sheets N-34-131-A-a-1-1 N-34-131-A-a-1-2 N-34-131-A-a-1-3 N-34-131-A-a-1-4 \
            N-34-131-A-a-2-1 N-34-131-A-a-2-2 N-34-131-A-a-2-3 N-34-131-A-a-2-4 \
    --output ../data/nmt/
```

### 7.3 Użycie w kodzie Python

```python
from utils.sheet_finder import (
    coordinates_to_sheet_code,
    get_sheets_for_point_with_buffer
)
from kartograf import GugikProvider, DownloadManager

# Znajdź arkusze
sheets = get_sheets_for_point_with_buffer(52.23, 21.01, buffer_km=5)

# Pobierz dane
provider = GugikProvider()
manager = DownloadManager(provider, output_dir="./data/nmt/")

for sheet in sheets:
    path = manager.download(sheet, format="AAIGrid")
    print(f"Pobrano: {path}")
```

---

## 8. Testy

### 8.1 Testy jednostkowe

```bash
pytest tests/unit/test_sheet_finder.py -v
```

### 8.2 Testy integracyjne (wymagają połączenia z GUGiK)

```bash
pytest tests/integration/test_download_dem.py -v --run-network
```

---

## 9. Rozwiązywanie Problemów

### Problem: "Coordinates outside Poland bounds"

**Przyczyna:** Współrzędne poza granicami Polski (49°-55°N, 14°-24.5°E)

**Rozwiązanie:** Sprawdź poprawność współrzędnych

### Problem: "Connection timeout to GUGiK"

**Przyczyna:** Serwer GUGiK niedostępny lub wolne połączenie

**Rozwiązanie:**
1. Sprawdź połączenie internetowe
2. Poczekaj i spróbuj ponownie
3. Użyj `--retry 5` dla więcej prób

### Problem: "Sheet not found in GUGiK database"

**Przyczyna:** Nie wszystkie arkusze są dostępne (np. tereny przygraniczne)

**Rozwiązanie:** Pomiń brakujące arkusze lub użyj danych z innego źródła

---

## 10. Przyszłe Rozszerzenia

- [ ] **Cache lokalny** - unikanie ponownego pobierania
- [ ] **Progress bar** - wizualizacja postępu pobierania
- [ ] **Parallel download** - równoległe pobieranie wielu arkuszy
- [ ] **API endpoint** - `/api/prepare-area` dla pobierania on-demand
- [ ] **Automatyczne łączenie** - merge wielu arkuszy w jeden raster

---

**Wersja dokumentu:** 1.0
**Ostatnia aktualizacja:** 2026-01-17
