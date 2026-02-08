# Skrypty preprocessingu

Skrypty do jednorazowego przetwarzania danych wejściowych przed uruchomieniem systemu.

## Wymagania

- Python 3.12+ ze środowiskiem wirtualnym (`backend/.venv`)
- Uruchomiona baza PostgreSQL/PostGIS
- Wykonane migracje Alembic
- [Kartograf 0.4.0](https://github.com/Daldek/Kartograf) (automatycznie instalowany z requirements.txt)
  - NMT/NMPT: Dane wysokościowe z GUGiK
  - BDOT10k: Dane o pokryciu terenu z GUGiK (12 warstw)
  - CORINE: Europejska klasyfikacja pokrycia terenu z Copernicus

## Dostępne skrypty

### `prepare_area.py` - Pełny pipeline (ZALECANY)

Pipeline łączący automatyczne pobieranie NMT z GUGiK i przetwarzanie do bazy danych.
**Użyj tego skryptu gdy chcesz przygotować dane dla nowego obszaru.**

**Użycie:**

```bash
cd backend

# Przygotowanie obszaru 5 km wokół punktu (tylko NMT)
.venv/bin/python -m scripts.prepare_area \
    --lat 52.23 --lon 21.01 \
    --buffer 5

# Z danymi o pokryciu terenu (BDOT10k) - wymagane dla hydrogramów!
.venv/bin/python -m scripts.prepare_area \
    --lat 52.23 --lon 21.01 \
    --buffer 5 \
    --with-landcover

# Z niższym progiem strumieni (więcej szczegółów)
.venv/bin/python -m scripts.prepare_area \
    --lat 52.23 --lon 21.01 \
    --buffer 10 \
    --stream-threshold 50

# Dry run - tylko pokaż jakie arkusze byłyby pobrane
.venv/bin/python -m scripts.prepare_area \
    --lat 52.23 --lon 21.01 \
    --dry-run
```

**Parametry:**

| Parametr | Opis | Domyślnie |
|----------|------|-----------|
| `--lat`, `--lon` | Współrzędne centrum obszaru (WGS84) | (wymagane) |
| `--buffer` | Promień bufora w km | 5 |
| `--stream-threshold` | Próg akumulacji dla strumieni | 100 |
| `--scale` | Skala arkuszy (1:10000, 1:25000, 1:50000, 1:100000) | 1:10000 |
| `--with-landcover` | Pobierz też dane o pokryciu terenu (BDOT10k) | false |
| `--landcover-provider` | Źródło danych: bdot10k lub corine | bdot10k |
| `--keep-downloads` | Zachowaj pobrane pliki .asc | true |
| `--save-intermediates` | Zapis plików GeoTIFF | false |
| `--output`, `-o` | Katalog wyjściowy | `../data/nmt/` |
| `--dry-run` | Tylko pokaż co byłoby zrobione | false |

---

### `download_dem.py` - Pobieranie NMT z GUGiK

Pobiera dane NMT z GUGiK używając biblioteki [Kartograf](https://github.com/Daldek/Kartograf) (v0.4.0).
**Użyj gdy chcesz tylko pobrać dane bez przetwarzania.**

> **Uwaga:** Kartograf 0.4.0 pobiera dane przez OpenData API w formacie ASC z auto-ekspansją godeł.
> Format nie jest konfigurowalny przy pobieraniu przez godła arkuszy.

**Użycie:**

```bash
cd backend

# Pobieranie dla punktu z buforem
.venv/bin/python -m scripts.download_dem \
    --lat 52.23 --lon 21.01 \
    --buffer 5 \
    --output ../data/nmt/

# Pobieranie konkretnych arkuszy
.venv/bin/python -m scripts.download_dem \
    --sheets N-34-131-C-c-2-1 N-34-131-C-c-2-2 \
    --output ../data/nmt/

# Dry run - tylko pokaż jakie arkusze byłyby pobrane
.venv/bin/python -m scripts.download_dem \
    --lat 52.23 --lon 21.01 \
    --dry-run
```

**Parametry:**

| Parametr | Opis | Domyślnie |
|----------|------|-----------|
| `--lat`, `--lon` | Współrzędne centrum (WGS84) | - |
| `--buffer` | Promień bufora w km | 5 |
| `--sheets` | Lista godeł arkuszy do pobrania | - |
| `--output`, `-o` | Katalog wyjściowy | `../data/nmt/` |
| `--scale` | Skala arkuszy | 1:10000 |
| `--no-skip-existing` | Pobierz ponownie istniejące pliki | false |
| `--dry-run` | Tylko pokaż co byłoby pobrane | false |

---

### `process_dem.py` - Przetwarzanie NMT

Przetwarza plik NMT (Numeryczny Model Terenu) z formatu ASCII GRID i ładuje dane do tabeli `flow_network`.

**Etapy przetwarzania (używa biblioteki `pyflwdir` — Deltares):**
1. Odczyt pliku rastrowego (.asc, .vrt, .tif)
2. Wypalanie cieków w DEM (opcjonalne, `--burn-streams`)
3. Wypełnienie wewnętrznych dziur nodata
4. Wypełnienie depresji + obliczenie kierunku przepływu D8 (`fill_depressions`)
5. Obliczenie akumulacji przepływu (`upstream_area`)
6. Obliczenie spadku terenu (Sobel)
7. Obliczenie aspektu (ekspozycja stoku, 0-360°)
8. Obliczenie rzędu Strahlera (`flw.stream_order`)
9. Obliczenie TWI (Topographic Wetness Index)
10. Identyfikacja strumieni (próg akumulacji)
11. Wektoryzacja cieków jako LineString (`vectorize_streams`)
12. Import do bazy PostgreSQL/PostGIS (COPY)

**Użycie:**

```bash
cd backend

# Podstawowy import
.venv/bin/python -m scripts.process_dem --input ../data/nmt/plik.asc

# Z zapisem plików pośrednich do weryfikacji w QGIS
.venv/bin/python -m scripts.process_dem \
    --input ../data/nmt/plik.asc \
    --save-intermediates \
    --output-dir ../data/nmt/output

# Tryb testowy (tylko statystyki)
.venv/bin/python -m scripts.process_dem --input ../data/nmt/plik.asc --dry-run
```

**Parametry:**

| Parametr | Skrót | Opis | Domyślnie |
|----------|-------|------|-----------|
| `--input` | `-i` | Ścieżka do pliku .asc (wymagane) | - |
| `--stream-threshold` | - | Próg flow accumulation dla strumieni | 100 |
| `--batch-size` | - | Rozmiar batch przy imporcie do bazy | 10000 |
| `--dry-run` | - | Tylko obliczenia i statystyki, bez importu | false |
| `--save-intermediates` | `-s` | Zapis rastrów pośrednich jako GeoTIFF | false |
| `--output-dir` | `-o` | Katalog dla plików GeoTIFF | (katalog wejściowy) |
| `--clear-existing` | - | Wyczyść istniejące dane (TRUNCATE flow_network) | false |
| `--burn-streams` | - | Ścieżka do GeoPackage/Shapefile z ciekami | - |
| `--burn-depth` | - | Głębokość wypalania [m] | 5.0 |
| `--skip-streams-vectorize` | - | Pomiń wektoryzację cieków | false |

**Pliki pośrednie (GeoTIFF):**

Opcja `--save-intermediates` generuje pliki do weryfikacji obliczeń w oprogramowaniu GIS (np. QGIS):

| Plik | Opis | Typ danych |
|------|------|------------|
| `*_01_dem.tif` | Oryginalny NMT | float32 |
| `*_02a_burned.tif` | NMT po wypaleniu cieków (jeśli `--burn-streams`) | float32 |
| `*_02_filled.tif` | NMT po wypełnieniu zagłębień | float32 |
| `*_03_flowdir.tif` | Kierunek przepływu (D8 encoding) | int16 |
| `*_04_flowacc.tif` | Akumulacja przepływu (liczba komórek upstream) | int32 |
| `*_05_slope.tif` | Spadek terenu [%] | float32 |
| `*_06_streams.tif` | Maska strumieni (0/1) | uint8 |
| `*_07_stream_order.tif` | Rząd Strahlera (1-8+, 0=nie-ciek) | uint8 |
| `*_08_twi.tif` | TWI — Topographic Wetness Index | float32 |
| `*_09_aspect.tif` | Aspekt — ekspozycja stoku (0-360°, N=0) | float32 |

**Kodowanie D8 (flowdir):**

| Wartość | Kierunek |
|---------|----------|
| 1 | E (wschód) |
| 2 | SE (południowy-wschód) |
| 4 | S (południe) |
| 8 | SW (południowy-zachód) |
| 16 | W (zachód) |
| 32 | NW (północny-zachód) |
| 64 | N (północ) |
| 128 | NE (północny-wschód) |

**Przykładowy output:**

```
============================================================
DEM Processing Script
============================================================
Input: ../data/nmt/N-33-131-D-a-3-2.asc
Stream threshold: 100
============================================================
Read DEM: 473x435 cells
Origin: (383202.5, 509297.5)
Cell size: 5.0 m
Filling depressions...
Depression filling completed after 1000 iterations
Computing flow direction (D8)...
Computing flow accumulation...
Computing slope...
Slope computed (range: 0.0% - 73.8%)
Creating flow_network records...
Created 196822 records
Stream cells (acc >= 100): 5734
============================================================
Processing complete!
  Grid size: 435 x 473
  Cell size: 5.0 m
  Total cells: 205,755
  Valid cells: 196,822
  Max accumulation: 3,617
  Mean slope: 10.0%
  Stream cells: 5,734
  Records created: 196,822
  Records inserted: 196,822
  Time elapsed: 264.2s
============================================================
```

---

### `download_landcover.py` - Pobieranie danych o pokryciu terenu

Pobiera dane o pokryciu terenu z BDOT10k (GUGiK) lub CORINE (Copernicus) używając Kartograf 0.4.0.

**Użycie:**

```bash
cd backend

# BDOT10k dla punktu z buforem
.venv/bin/python -m scripts.download_landcover \
    --lat 52.23 --lon 21.01 \
    --buffer 5

# BDOT10k po kodzie TERYT (powiat)
.venv/bin/python -m scripts.download_landcover \
    --teryt 1465

# CORINE Land Cover
.venv/bin/python -m scripts.download_landcover \
    --lat 52.23 --lon 21.01 \
    --provider corine \
    --year 2018
```

**Parametry:**

| Parametr | Opis | Domyślnie |
|----------|------|-----------|
| `--lat`, `--lon` | Współrzędne centrum (WGS84) | - |
| `--buffer` | Promień bufora w km | 5 |
| `--teryt` | Kod TERYT powiatu (4 cyfry) | - |
| `--godlo` | Godło arkusza mapy | - |
| `--provider`, `-p` | Źródło: bdot10k lub corine | bdot10k |
| `--year` | Rok dla CORINE (1990-2018) | 2018 |
| `--output`, `-o` | Katalog wyjściowy | `../data/landcover/` |

**Format wyjściowy:** GeoPackage (.gpkg)

---

### `import_landcover.py` - Import pokrycia terenu do bazy

Importuje dane z GeoPackage do tabeli `land_cover` z przypisaniem wartości CN.

**Użycie:**

```bash
cd backend

# Import danych BDOT10k
.venv/bin/python -m scripts.import_landcover \
    --input ../data/landcover/bdot10k_teryt_1465.gpkg

# Dry run (tylko pokaż co byłoby zaimportowane)
.venv/bin/python -m scripts.import_landcover \
    --input ../data/landcover/bdot10k_teryt_1465.gpkg \
    --dry-run

# Wyczyść istniejące dane przed importem
.venv/bin/python -m scripts.import_landcover \
    --input ../data/landcover/bdot10k_teryt_1465.gpkg \
    --clear-existing
```

**Parametry:**

| Parametr | Opis | Domyślnie |
|----------|------|-----------|
| `--input`, `-i` | Ścieżka do pliku .gpkg (wymagane) | - |
| `--batch-size` | Rekordów na batch | 1000 |
| `--clear-existing` | Wyczyść istniejące dane | false |
| `--dry-run` | Tylko pokaż co byłoby zaimportowane | false |

**Mapowanie BDOT10k → CN:**

| Kod BDOT10k | Kategoria Hydrograf | CN | Imperviousness |
|-------------|--------------------|----|----------------|
| PTLZ | las | 60 | 0.0 |
| PTTR, PTUT | grunt_orny | 78 | 0.1 |
| PTWP | woda | 100 | 1.0 |
| PTWZ, PTRK | łąka | 70 | 0.0 |
| PTZB | zabudowa_mieszkaniowa | 85 | 0.5 |
| PTKM, PTPL | droga | 98 | 0.95 |
| PTGN, PTNZ, PTSO | inny | 75 | 0.2 |

---

### `preprocess_precipitation.py` - Dane opadowe IMGW

Pobiera i przetwarza dane PMAXTP z IMGW do tabeli `precipitation_data`.

**Użycie:**

```bash
cd backend
.venv/bin/python -m scripts.preprocess_precipitation --help
```

---

## Weryfikacja danych

### Sprawdzenie w bazie danych

```bash
# Połączenie z bazą
docker exec -it hydro_db psql -U hydro_user -d hydro_db

# Statystyki flow_network
SELECT
    COUNT(*) as total_cells,
    SUM(CASE WHEN is_stream THEN 1 ELSE 0 END) as stream_cells,
    MIN(elevation) as min_elevation,
    MAX(elevation) as max_elevation,
    AVG(slope)::numeric(6,2) as avg_slope_percent,
    MAX(flow_accumulation) as max_accumulation
FROM flow_network;
```

### Weryfikacja w QGIS

1. Uruchom skrypt z `--save-intermediates`
2. Otwórz wygenerowane pliki GeoTIFF w QGIS
3. Sprawdź:
   - `*_02_filled.tif` - czy zagłębienia zostały wypełnione
   - `*_03_flowdir.tif` - czy kierunki przepływu są sensowne
   - `*_04_flowacc.tif` - czy strumienie są w dolinach
   - `*_06_streams.tif` - czy maska pokrywa się z rzeczywistymi ciekami

---

## Znane ograniczenia

1. **Algorytm fill depressions** - prosta implementacja iteracyjna, może być wolna dla dużych rastrów
2. **Pamięć** - cały raster ładowany do RAM
3. **Układ współrzędnych** - obsługuje tylko EPSG:2180 (PL-1992)
