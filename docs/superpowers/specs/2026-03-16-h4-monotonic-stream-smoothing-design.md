# H4 — Monotoniczne wygładzanie cieków (Monotonic Stream Smoothing)

**Data:** 2026-03-16
**Status:** Zatwierdzony
**Priorytet:** Niski (backlog)
**ADR:** ADR-041

## Problem

Obecne wypalanie cieków (`burn_streams_into_dem`) obniża NMT o stałą wartość (`burn_depth_m`) wzdłuż geometrii cieku. To powoduje dwa problemy:

1. **Niedostateczne wypalanie przy przeszkodach** — mosty, wiadukty, nasypy mogą nie zostać wystarczająco obniżone nawet przy dużej głębokości wypalania.
2. **Nadmierne wypalanie na normalnych odcinkach** — stałe obniżenie tworzy sztuczne zagłębienia, które wymagają dużego fill sinks i mogą zalewać okoliczne komórki.

## Rozwiązanie

Dwuetapowe przetwarzanie:

1. **Stałe wypalanie** (etap 1) — obecna funkcja `burn_streams_into_dem()` ze zmniejszoną domyślną głębokością (2m). Daje wstępne przybliżenie.
2. **Monotoniczne wygładzanie** (etap 2) — nowa funkcja `smooth_streams_monotonic()` koryguje profil elevacji wzdłuż cieków tak, aby wysokości monotonicznie malały od źródła do ujścia.

## Decyzje projektowe

| Element | Decyzja | Uzasadnienie |
|---------|---------|--------------|
| Tryb | Dwuetapowy (wypalanie + wygładzanie) | Wypalanie daje przybliżenie, wygładzanie koryguje |
| Kierunek | Tylko downstream (running minimum) | Prosty, wystarczający — obniżamy przeszkody, nie podnosimy dna |
| Źródło elevacji | Z wypalonego DEM (po etapie 1) | Wygładzanie jako korekta, nie zamiennik |
| Rasteryzacja profilu | Bresenham po geometrii wektorowej (czysta implementacja NumPy) | Niezależne od pyflwdir, bez nowych zależności |
| Ustalanie kierunku | Topologia sieci (BFS od ujścia) | Odporne na płaskie tereny i szum DEM |
| Zakres | Komórki pod geometrią BDOT10k | Spójne z obecnym wypalaniem |
| Włączanie | Domyślnie aktywne, wyłączane `--no-smooth-streams` | Możliwość wyłączenia do debugowania/porównań |
| `burn_depth_m` | Domyślne zmniejszone do 2m (wszystkie lokalizacje) | Łagodniejsze wypalanie, wygładzanie przejmuje główną rolę |

## Architektura

### Pipeline po zmianie

```
1. Load DEM
2. Raise buildings (+5m)
3a. Burn streams (constant, 2m)           ← zmniejszona głębokość
3b. Monotonic smoothing (NEW)             ← nowy krok
4. Classify endorheic lakes
5. Depression filling + flow direction
6. Flow accumulation
7. Stream vectorization, etc.
```

Wygładzanie działa **przed** pyflwdir — nie wymaga flow direction ani dwóch przebiegów depression filling.

Przy `save_intermediates=True` zapisywany jest plik `02b_smoothed.tif` (obok istniejącego `02a_burned.tif`).

### Nowa funkcja: `smooth_streams_monotonic()`

**Lokalizacja:** `backend/core/hydrology.py`

```python
def smooth_streams_monotonic(
    dem: np.ndarray,
    transform,
    streams_path: Path | str,
    nodata: float = -9999.0,
) -> tuple[np.ndarray, dict]:
```

Sygnatura zgodna ze stylem `burn_streams_into_dem` (brak type hint na `transform`).

**Algorytm:**

1. Wczytaj geometrie cieków z BDOT10k (SWRS, SWKN, SWRM) — ta sama logika ładowania co `burn_streams_into_dem` (GeoDataFrame, CRS, clipping do zasięgu DEM). Rozłóż MultiLineString na składowe LineString.
2. Odfiltruj geometrie puste lub całkowicie poza zasięgiem rastra.
3. Zbuduj graf topologii sieci z geometrii wektorowych (`_build_stream_network_graph`).
4. Dla każdego rozłącznego komponentu znajdź ujście (BFS).
5. Przetwarzaj segmenty w odwrotnej kolejności BFS (od źródeł ku ujściu):
   - Rasteryzuj segment do uporządkowanej sekwencji komórek (Bresenham). Kierunek rasteryzacji: od węzła dalszego od ujścia do bliższego (upstream → downstream), wynikający z BFS.
   - Pobierz profil elevacji z DEM.
   - Running minimum: `profile[i] = min(profile[i], profile[i-1])`.
   - Na confluencji: start = `min(elevation, last_value_dopływów)`.
   - Zapisz wygładzone wartości do DEM.
6. Zwróć zmodyfikowany DEM + diagnostykę.

### Funkcja pomocnicza: `_rasterize_line_ordered()`

```python
def _rasterize_line_ordered(
    line: LineString,
    transform,
) -> list[tuple[int, int]]:
```

- Przyjmuje LineString (nie MultiLineString — dekompozycja wcześniej).
- Iteruje po parach kolejnych wierzchołków.
- Czysta implementacja Bresenham w NumPy (~10 linii) — bez zależności od `scikit-image`.
- Deduplikacja na złączeniach (ostatni piksel segmentu = pierwszy następnego).

### Budowa grafu topologii: `_build_stream_network_graph()`

```python
def _build_stream_network_graph(
    geometries: list[LineString],
    dem: np.ndarray,
    transform,
    snap_tolerance_px: int = 1,
) -> tuple[dict[int, list[tuple[int, int]]], list[int]]:
```

**Struktura grafu:**
- Węzły identyfikowane sekwencyjnymi int ID.
- Endpointy geometrii zaokrąglane do pikseli rastra → snapping wg tolerancji.
- Adjacency dict: `{node_id: [(neighbor_node_id, segment_index), ...]}` — krawędzie przechowują indeks oryginalnej geometrii.
- Zwraca graf + listę indeksów węzłów-ujść (jeden na komponent).

**Identyfikacja ujścia (priorytet):**
1. Węzły o stopniu 1 (liście grafu) na krawędzi zasięgu rastra.
2. Jeśli brak — węzeł o stopniu 1 z najniższą elevacją DEM.
3. Dla rozłącznych komponentów — każdy ma osobne ujście wg tych reguł.

**Przypadki brzegowe:**
- Bardzo krótkie segmenty (oba endpointy w tym samym pikselu) — pomijane.
- Pętle (rzeki roztokowe) — BFS naturalnie je obsługuje (visited set).
- Nakładające się geometrie na tych samych pikselach — running minimum bierze niższą wartość.

### Obsługa confluencji

Kolejność przetwarzania z BFS gwarantuje, że dopływy są przetworzone przed ciekiem poniżej confluencji:

```
Dopływ A: [150, 148, 145] → last = 145
Dopływ B: [160, 155, 147] → last = 147
Ciek poniżej: [149, 144, 140]
  → first = min(149, 145, 147) = 145
  → running minimum: [145, 144, 140]
```

## Zmiana `burn_depth_m` — wszystkie lokalizacje

Ujednolicenie domyślnej wartości na 2.0m we wszystkich miejscach:

| Plik | Linia | Było | Będzie |
|------|-------|------|--------|
| `core/hydrology.py` | 164 | `10.0` | `2.0` |
| `core/config.py` | 124 | `10.0` | `2.0` |
| `scripts/process_dem.py` | 132 | `5.0` | `2.0` |
| `scripts/prepare_area.py` | 89 | `5.0` | `2.0` |
| `config.yaml.example` | 16 | `10.0` | `2.0` |
| CLI help texts | — | `Default: 5.0` / `10.0` | `Default: 2.0` |

## Zmienione pliki

| Plik | Zmiana |
|------|--------|
| `core/hydrology.py` | +`smooth_streams_monotonic()`, +`_rasterize_line_ordered()`, +`_build_stream_network_graph()`, +`_bresenham()`, zmiana default `burn_depth_m` |
| `core/config.py` | Zmiana `burn_depth_m` w `_DEFAULT_CONFIG` |
| `scripts/process_dem.py` | Wywołanie wygładzania po wypalaniu, `--no-smooth-streams` flag, `save_intermediates` → `02b_smoothed.tif`, zmiana default `burn_depth_m` |
| `scripts/bootstrap.py` | Przekazanie `smooth_streams` do `process_dem`, zmiana default `burn_depth_m` |
| `scripts/prepare_area.py` | Zmiana default `burn_depth_m` |
| `scripts/README.md` | Aktualizacja dokumentacji |
| `config.yaml.example` | Zmiana `burn_depth_m` |
| `tests/unit/test_monotonic_smoothing.py` | Nowy plik z testami |
| `docs/DECISIONS.md` | ADR-041 |

## Testy

Nowy plik `tests/unit/test_monotonic_smoothing.py`:

1. **Prosty przypadek** — jedna linia, profil z "górką" (mostem) → po wygładzeniu monotoniczny.
2. **Płaski teren** — profil stały → bez zmian.
3. **Już monotoniczny** — profil malejący → 0 skorygowanych komórek.
4. **Confluencja** — dwa dopływy + ciek poniżej → poprawna wartość startowa.
5. **Odwrócona geometria** — LineString ujście→źródło → topologia poprawnie odwraca.
6. **MultiLineString** — dekompozycja na składowe, każda wygładzona.
7. **Komórki NoData** — pomijane, nie psują running minimum.
8. **Rozłączna sieć** — dwa niezależne komponenty → osobne ujścia.
9. **`_rasterize_line_ordered`** — deduplikacja, poprawna kolejność pikseli.
10. **`_bresenham`** — poprawność rasteryzacji linii (horyzontalnej, wertykalnej, diagonalnej).
11. **Nakładające się geometrie** — dwa segmenty na tych samych pikselach → minimum wygrywa.
12. **Krótki segment** (1-2 piksele) — poprawne przetworzenie lub pominięcie.
13. **Segment poza zasięgiem DEM** — odfiltrowany, nie wpływa na przetwarzanie.

## Diagnostyka

```python
{
    "segments_processed": 42,
    "segments_skipped": 3,        # poza zasięgiem / za krótkie
    "cells_smoothed": 1234,       # ile komórek skorygowano (obniżono)
    "cells_unchanged": 5678,      # ile już było monotonicznych
    "max_correction_m": 3.2,      # największa korekta (most/nasyp)
    "mean_correction_m": 0.4,
    "disconnected_components": 1,  # ile rozłącznych podsieci
}
```

Logowane na poziomie `INFO` po zakończeniu kroku.
