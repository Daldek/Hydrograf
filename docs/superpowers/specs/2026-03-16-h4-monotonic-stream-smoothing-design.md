# H4 — Monotoniczne wygładzanie cieków (Monotonic Stream Smoothing)

**Data:** 2026-03-16
**Status:** Zatwierdzony
**Priorytet:** Niski (backlog)

## Problem

Obecne wypalanie cieków (`burn_streams_into_dem`) obniża NMT o stałą wartość (`burn_depth_m`) wzdłuż geometrii cieku. To powoduje dwa problemy:

1. **Niedostateczne wypalanie przy przeszkodach** — mosty, wiadukty, nasypy mogą nie zostać wystarczająco obniżone nawet przy dużej głębokości wypalania.
2. **Nadmierne wypalanie na normalnych odcinkach** — stałe obniżenie tworzy sztuczne zagłębienia, które wymagają dużego fill sinks i mogą zalewać okoliczne komórki.

## Rozwiązanie

Dwuetapowe przetwarzanie:

1. **Stałe wypalanie** (etap 1) — obecna funkcja `burn_streams_into_dem()` ze zmniejszoną domyślną głębokością (2m zamiast 10/5m). Daje wstępne przybliżenie.
2. **Monotoniczne wygładzanie** (etap 2) — nowa funkcja `smooth_streams_monotonic()` koryguje profil elevacji wzdłuż cieków tak, aby wysokości monotonicznie malały od źródła do ujścia.

## Decyzje projektowe

| Element | Decyzja | Uzasadnienie |
|---------|---------|--------------|
| Tryb | Dwuetapowy (wypalanie + wygładzanie) | Wypalanie daje przybliżenie, wygładzanie koryguje |
| Kierunek | Tylko downstream (running minimum) | Prosty, wystarczający — obniżamy przeszkody, nie podnosimy dna |
| Źródło elevacji | Z wypalonego DEM (po etapie 1) | Wygładzanie jako korekta, nie zamiennik |
| Rasteryzacja profilu | Bresenham po geometrii wektorowej | Niezależne od pyflwdir, zachowuje kolejność pikseli |
| Ustalanie kierunku | Topologia sieci (BFS od ujścia) | Odporne na płaskie tereny i szum DEM |
| Zakres | Komórki pod geometrią BDOT10k | Spójne z obecnym wypalaniem |
| Włączanie | Automatyczne gdy `burn_streams_path` podany | Brak osobnego flaga — wypalanie i wygładzanie to jeden mechanizm |
| `burn_depth_m` | Domyślne zmniejszone do 2m | Łagodniejsze wypalanie, wygładzanie przejmuje główną rolę |

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

### Nowa funkcja: `smooth_streams_monotonic()`

**Lokalizacja:** `backend/core/hydrology.py`

```python
def smooth_streams_monotonic(
    dem: np.ndarray,
    transform: Affine,
    streams_path: Path | str,
    nodata: float = -9999.0,
) -> tuple[np.ndarray, dict]:
```

**Algorytm:**

1. Wczytaj geometrie cieków z BDOT10k (SWRS, SWKN, SWRM) — ta sama logika co `burn_streams_into_dem`.
2. Zbuduj graf topologii sieci z geometrii wektorowych.
3. Znajdź ujście (węzeł o stopniu 1 z najniższą elevacją lub na krawędzi rastra).
4. BFS od ujścia — ustala kierunek każdego segmentu i kolejność przetwarzania.
5. Przetwarzaj segmenty w odwrotnej kolejności BFS (od źródeł ku ujściu):
   - Rasteryzuj segment do uporządkowanej sekwencji komórek (Bresenham).
   - Pobierz profil elevacji z DEM.
   - Running minimum: `profile[i] = min(profile[i], profile[i-1])`.
   - Na confluencji: start = `min(elevation, last_value_dopływów)`.
   - Zapisz wygładzone wartości do DEM.
6. Zwróć zmodyfikowany DEM + diagnostykę.

### Funkcja pomocnicza: `_rasterize_line_ordered()`

```python
def _rasterize_line_ordered(
    line: LineString | MultiLineString,
    transform: Affine,
) -> list[tuple[int, int]]:
```

- Iteruje po parach kolejnych wierzchołków LineString.
- `skimage.draw.line(r0, c0, r1, c1)` → uporządkowane piksele segmentu.
- Deduplikacja na złączeniach (ostatni piksel segmentu = pierwszy następnego).
- Dla MultiLineString — każda składowa osobno.

### Budowa grafu topologii: `_build_stream_network_graph()`

```python
def _build_stream_network_graph(
    geometries: list[LineString],
    dem: np.ndarray,
    transform: Affine,
    snap_tolerance_px: int = 1,
) -> tuple[dict, int]:
```

- Buduje graf z endpointów geometrii (węzły w obrębie tolerancji snapping = ten sam węzeł).
- Zwraca graf adjacency + indeks węzła-ujścia.
- Ujście: węzeł o stopniu 1 z najniższą elevacją DEM, lub na krawędzi rastra.
- Dla rozłącznych komponentów — każdy ma osobne ujście.

### Obsługa confluencji

Kolejność przetwarzania z BFS gwarantuje, że dopływy są przetworzone przed ciekiem poniżej confluencji:

```
Dopływ A: [150, 148, 145] → last = 145
Dopływ B: [160, 155, 147] → last = 147
Ciek poniżej: [149, 144, 140]
  → first = min(149, 145, 147) = 145
  → running minimum: [145, 144, 140]
```

## Zmienione pliki

| Plik | Zmiana |
|------|--------|
| `core/hydrology.py` | +`smooth_streams_monotonic()`, +`_rasterize_line_ordered()`, +`_build_stream_network_graph()` |
| `scripts/process_dem.py` | Wywołanie wygładzania po wypalaniu, zmiana default `burn_depth_m` → 2.0 |
| `scripts/bootstrap.py` | Zmiana default `burn_depth_m` w `_DEFAULT_CONFIG["dem"]` i CLI |
| `scripts/prepare_area.py` | Zmiana default `burn_depth_m` w CLI |
| `scripts/README.md` | Aktualizacja dokumentacji domyślnych wartości |
| `tests/unit/test_monotonic_smoothing.py` | Nowy plik z testami |
| `docs/DECISIONS.md` | Nowy ADR |

## Testy

Nowy plik `tests/unit/test_monotonic_smoothing.py` — 9 testów:

1. **Prosty przypadek** — jedna linia, profil z "górką" (mostem) → po wygładzeniu monotoniczny.
2. **Płaski teren** — profil stały → bez zmian.
3. **Już monotoniczny** — profil malejący → 0 skorygowanych komórek.
4. **Confluencja** — dwa dopływy + ciek poniżej → poprawna wartość startowa.
5. **Odwrócona geometria** — LineString ujście→źródło → topologia poprawnie odwraca.
6. **MultiLineString** — kilka segmentów w jednej geometrii.
7. **Komórki NoData** — pomijane, nie psują running minimum.
8. **Rozłączna sieć** — dwa niezależne komponenty → osobne ujścia.
9. **`_rasterize_line_ordered`** — deduplikacja, poprawna kolejność pikseli.

## Diagnostyka

```python
{
    "segments_processed": 42,
    "cells_smoothed": 1234,
    "cells_unchanged": 5678,
    "max_correction_m": 3.2,
    "mean_correction_m": 0.4,
    "disconnected_components": 1,
}
```

Logowane na poziomie `INFO` po zakończeniu kroku.
