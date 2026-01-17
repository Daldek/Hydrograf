# Skrypty preprocessingu

Skrypty do jednorazowego przetwarzania danych wejściowych przed uruchomieniem systemu.

## Wymagania

- Python 3.12+ ze środowiskiem wirtualnym (`backend/.venv`)
- Uruchomiona baza PostgreSQL/PostGIS
- Wykonane migracje Alembic

## Dostępne skrypty

### `process_dem.py` - Przetwarzanie NMT

Przetwarza plik NMT (Numeryczny Model Terenu) z formatu ASCII GRID i ładuje dane do tabeli `flow_network`.

**Etapy przetwarzania:**
1. Odczyt pliku ASCII GRID (.asc)
2. Wypełnienie zagłębień (sink filling)
3. Obliczenie kierunku przepływu (D8)
4. Obliczenie akumulacji przepływu
5. Obliczenie spadku terenu
6. Identyfikacja strumieni
7. Import do bazy PostgreSQL/PostGIS

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

**Pliki pośrednie (GeoTIFF):**

Opcja `--save-intermediates` generuje pliki do weryfikacji obliczeń w oprogramowaniu GIS (np. QGIS):

| Plik | Opis | Typ danych |
|------|------|------------|
| `*_01_dem.tif` | Oryginalny NMT | float32 |
| `*_02_filled.tif` | NMT po wypełnieniu zagłębień | float32 |
| `*_03_flowdir.tif` | Kierunek przepływu (D8 encoding) | int16 |
| `*_04_flowacc.tif` | Akumulacja przepływu (liczba komórek upstream) | int32 |
| `*_05_slope.tif` | Spadek terenu [%] | float32 |
| `*_06_streams.tif` | Maska strumieni (0/1) | uint8 |

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
