# Raport sesji: Kartograf v0.4.0 → v0.4.1

**Data sesji:** 2026-02-08
**Domkniecie dokumentacji:** 2026-02-09
**Branch:** `develop`

---

## 1. Podsumowanie

Sesja zrealizowala upgrade Kartograf z v0.4.0 do v0.4.1 oraz integracje 3 nowych funkcjonalnosci w pipeline Hydrograf. Wykonano 6 commitow (Tasks 1–8 z planu). Test E2E (Task 9) zakonczyl sie awaria z powodu wyczerpania zasobow przy `traverse_upstream()` na outlecie z flow_accumulation = 1.76M komorek.

**Wynik:** 8/9 taskow ukonczone. Task 9 (E2E watershed delineation) wymaga naprawy przed ponownym uruchomieniem.

---

## 2. Commity

| # | Hash | Opis | Pliki |
|---|------|------|-------|
| 1 | `a046400` | `feat(core): upgrade Kartograf v0.4.0 → v0.4.1` | requirements.txt |
| 2 | `f003699` | `feat(core): add --category hydro support to download_landcover` | download_landcover.py |
| 3 | `5a26feb` | `feat(core): add --geometry support to download_dem` | download_dem.py |
| 4 | `51b830e` | `feat(core): add --with-hydro stream burning to prepare_area` | prepare_area.py |
| 5 | `d0fff0e` | `docs: update Kartograf version references v0.4.0 → v0.4.1` | 4 pliki docs |
| 6 | `6582be4` | `style(scripts): fix E501 line-too-long` | 3 skrypty |

---

## 3. Wyniki E2E

Dane testowe w `data/e2e_test/`:

### 3.1 NMT (1m)

4 sub-sheets pobrane przez Kartograf v0.4.1:

| Arkusz | Rozmiar |
|--------|---------|
| N-33-131-C-b-2-1.asc | 34 MB |
| N-33-131-C-b-2-2.asc | 33 MB |
| N-33-131-C-b-2-3.asc | 31 MB |
| N-33-131-C-b-2-4.asc | 32 MB |

Lokalizacja: `nmt_1m/N-33/131/C/b/2/*/`

### 3.2 Dane hydrograficzne

- Plik: `hydro/bdot10k_hydro_godlo_N_33_131_C_b_2.gpkg`
- Rozmiar: 8.1 MB
- Warstwy: SWRS, SWKN, SWRM, PTWP (cieki, kanaly, rowniki, wody powierzchniowe)

### 3.3 Rastery posrednie

20 rasterow w `intermediates/` (~444 MB), 2 serie:

**Seria 1: dem_mosaic (mozaika 4 tiles)**

| Warstwa | Rozmiar |
|---------|---------|
| 01_dem.tif | 40 MB |
| 02a_burned.tif | 40 MB |
| 02_filled.tif | 36 MB |
| 03_flowdir.tif | 6.9 MB |
| 04_flowacc.tif | 21 MB |
| 05_slope.tif | 66 MB |
| 06_streams.tif | 770 KB |
| 07_stream_order.tif | 806 KB |
| 08_twi.tif | 77 MB |
| 09_aspect.tif | 67 MB |

**Seria 2: N-33-131-C-b-2-3 (1 arkusz)**

| Warstwa | Rozmiar |
|---------|---------|
| 01_dem.tif | 11 MB |
| 02a_burned.tif | 11 MB |
| 02_filled.tif | 9.6 MB |
| 03_flowdir.tif | 2.0 MB |
| 04_flowacc.tif | 5.1 MB |
| 05_slope.tif | 17 MB |
| 06_streams.tif | 164 KB |
| 07_stream_order.tif | 171 KB |
| 08_twi.tif | 20 MB |
| 09_aspect.tif | 18 MB |

VRT mosaic: `dem_mosaic.vrt` (2.1 KB)

---

## 4. Analiza awarii Task 9

### 4.1 Objawy

- `traverse_upstream()` uruchomiony na outlecie z `flow_accumulation = 1,760,000`
- PostgreSQL przestal odpowiadac — TCP connection established, brak wymiany banera serwera (PostgreSQL nie wyslal "R" — server ready)
- Python zablokowany na oczekiwaniu na odpowiedz bazy danych
- Sesja wymagala twardego przerwania

### 4.2 Root cause — wielopoziomowy

Awaria wynikla z kombinacji problemow w kodzie i potencjalnych ograniczen zasobow srodowiska Docker.

#### Poziom 1: Brak zabezpieczen w kodzie

**`backend/core/watershed.py:184-222` — recursive CTE bez LIMIT:**

```sql
WITH RECURSIVE upstream AS (
    SELECT ... FROM flow_network WHERE id = :outlet_id
    UNION ALL
    SELECT ... FROM flow_network f
    INNER JOIN upstream u ON f.downstream_id = u.id
    WHERE u.depth < :max_depth
)
SELECT ... FROM upstream
```

CTE rozszerza sie rekurencyjnie na wszystkie komorki upstream. Przy outlecie z acc=1.76M oznacza to materializacje ~1.76M wierszy w pamieci PostgreSQL, bez zadnego limitu na rozmiar wyniku.

**`backend/core/watershed.py:224-227` — `.fetchall()` przed sprawdzeniem rozmiaru:**

```python
results = db.execute(query, {...}).fetchall()

if len(results) > max_cells:  # linia 229 — za pozno!
```

Nawet gdyby CTE sie zakonczyl, `.fetchall()` laduje caly wynik do pamieci Python zanim nastapi sprawdzenie `max_cells`. Przy 1.76M wierszach × ~10 kolumn to potencjalnie setki MB RAM.

**`backend/core/database.py:27-35` — brak `statement_timeout`:**

```python
return create_engine(
    settings.database_url,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=5,
    pool_timeout=30,     # timeout na pobranie polaczenia z puli
    pool_recycle=3600,
    echo=settings.log_level == "DEBUG",
)
```

Brak `connect_args={"options": "-c statement_timeout=120000"}` — zapytanie SQL moze dzialac bez limitu czasu.

#### Poziom 2: Ograniczenia zasobow Docker

Srodowisko PostgreSQL dzialalo w kontenerze Docker (`docker compose up -d db`), ktory domyslnie nie ma ograniczen pamieci ani CPU. Jednak przy intensywnym uzyciu zasobow przez recursive CTE na 1.76M komorek:

- **Pamiec:** PostgreSQL potrzebowal znacznej ilosci pamieci roboczej (`work_mem`) na materializacje CTE. Domyslny `work_mem=4MB` w PostgreSQL moze byc niewystarczajacy, wymuszajac zapis na dysk, co drastycznie spowalnia operacje.
- **Shared buffers:** Domyslna konfiguracja PostgreSQL (`shared_buffers=128MB`) moze byc za mala dla takiego obciazenia.
- **Docker memory limits:** Jesli kontener Docker ma narzucone limity pamieci (np. przez konfiguracje systemu lub Docker Desktop), PostgreSQL moze zostac zabity przez OOM killer bez wyraznego bledu — jedynym objawem bedzie brak odpowiedzi na polaczenie TCP.
- **I/O:** Intensywne operacje dyskowe w kontenerze moga byc wolniejsze niz na natywnym systemie plikow.

#### Kaskada zdarzen

1. `traverse_upstream()` wysyla recursive CTE na outlet z acc=1.76M
2. PostgreSQL rozpoczyna ekspansje CTE — materializuje miliony wierszy
3. `work_mem` (4 MB) nie wystarcza → PostgreSQL zaczyna zapisywac na dysk
4. Pamiec kontenera Docker rosnie → mozliwy OOM lub degradacja wydajnosci
5. PostgreSQL przestaje odpowiadac na nowe polaczenia (brak banera serwera)
6. Python czeka na odpowiedz → deadlock na poziomie I/O

---

## 5. Zapobieganie

### 5.1 Natychmiastowe (przed nastepnym E2E)

**(A) `statement_timeout` w konfiguracji polaczenia (`database.py`):**

```python
return create_engine(
    settings.database_url,
    connect_args={"options": "-c statement_timeout=120000"},  # 120s
    ...
)
```

Zapobiega nieskonczonemu dzialaniu zapytan SQL.

**(B) Pre-flight check w `traverse_upstream()` (`watershed.py`):**

```python
# PRZED uruchomieniem CTE
acc = db.execute(text(
    "SELECT flow_accumulation FROM flow_network WHERE id = :id"
), {"id": outlet_id}).scalar()
if acc > max_cells:
    raise ValueError(f"Outlet too large: acc={acc:,} > {max_cells:,}")
```

Szybkie sprawdzenie zanim uruchomimy kosztowne zapytanie.

**(C) LIMIT w CTE (`watershed.py`):**

Dodanie `LIMIT :max_cells + 1` do koncowego SELECT:

```sql
SELECT ... FROM upstream LIMIT :max_cells_plus_one
```

Ogranicza rozmiar wyniku nawet jesli CTE sie rozrasta.

**(D) Konfiguracja zasobow PostgreSQL w Docker (`docker-compose.yml`):**

```yaml
services:
  db:
    ...
    deploy:
      resources:
        limits:
          memory: 2G
    environment:
      - POSTGRES_SHARED_BUFFERS=256MB
    command: >
      postgres
      -c shared_buffers=256MB
      -c work_mem=64MB
      -c maintenance_work_mem=256MB
      -c max_connections=20
```

Jawne ustawienie limitow pamieci i konfiguracji PostgreSQL.

### 5.2 Krotkoterminowe

**(E) Server-side cursor zamiast `.fetchall()`:**

```python
# Zamiast results = db.execute(query).fetchall()
result = db.execute(query)
cells = []
for row in result:
    cells.append(row)
    if len(cells) > max_cells:
        raise ValueError(...)
```

Iteracyjne pobieranie wynikow z natychmiastowym przerwaniem po przekroczeniu limitu.

**(F) Testy E2E na sub-sheet z filtrem acc:**

Wybieranie outletu o umiarkowanym acc (50k–250k) zamiast outletu glownego z acc=1.76M. Realistyczne dla zlewni <= 250 km² (ograniczenie metody SCS-CN).

### 5.3 Dlugoterminowe

**(G) Endpoint `/api/estimate-watershed-size`:**

Szybkie zapytanie zwracajace szacowany rozmiar zlewni (na podstawie acc) przed uruchomieniem pelnego delineation. Frontend moze ostrzec uzytkownika.

**(H) Multi-resolution fallback:**

Automatyczne przelaczanie na NMT 5m lub 10m dla duzych zlewni. Redukuje liczbe komorek ~25x lub ~100x.

---

## 6. Nastepne kroki

1. **Fix traverse_upstream** — wdrozyc zabezpieczenia A–D (natychmiastowe), w tym konfiguracje zasobow Docker
2. **Powtorzyc Task 9** — E2E delineation z mniejszym outletem (acc 50k–250k)
3. **CP4 — Frontend** — mapa Leaflet.js z interaktywnym wyborem punktu zlewni
4. **Dlug techniczny** — constants.py, hardcoded secrets, CI/CD
