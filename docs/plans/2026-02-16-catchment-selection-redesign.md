# Redesign selekcji zlewni cząstkowych

**Data:** 2026-02-16
**Status:** Zatwierdzony

## Kontekst

Obecna selekcja zlewni opiera się na snap-to-stream: kliknięcie → szukanie najbliższego cieku → szukanie zlewni pod snapniętym punktem. Powoduje to błędne przypisanie kliknięcia do sąsiedniej zlewni, gdy ciek z niej płynie blisko granicy.

Dodatkowo: próg 100 m² generuje 105 492 zlewni cząstkowych bez praktycznego zastosowania, a geometria poligonów jest pikselowa (schodkowe krawędzie z rastra).

## Zmiany

### 1. Selekcja oparta o poligon zlewni

- Kliknięcie → bezpośrednio `ST_Contains` na `stream_catchments` → BFS z wyniku.
- Eliminacja `find_nearest_stream_segment()` i `find_stream_catchment_at_point()` (snap-to-stream) z flow selekcji.
- Informacja o cieku (rząd Strahlera, długość) wyciągana po fakcie z `stream_network` po `segment_idx`.

### 2. Usunięcie progu 100 m² ze zlewni cząstkowych

- Pipeline nie generuje zlewni cząstkowych dla progu 100 m².
- Cieki (stream_network) dla 100 m² zostają — widoczne na mapie jako MVT.
- `stream_catchments` zawiera 3 progi: 1000, 10000, 100000 (~12k rekordów zamiast 117k).
- CatchmentGraph: ~12k węzłów, <1 MB RAM.
- Domyślny próg API: 100 → 1000 m².
- ADR-024 (fine-threshold BFS na progu 100) staje się nieaktualny.
- Logika kaskady progów (fine→coarse, `use_fine_bfs`) upraszcza się.

### 3. Uproszczenie geometrii poligonów

- W pipeline, po polygonizacji, przed INSERT: `ST_Simplify(geom, 1.0)` (tolerancja 1m = rozdzielczość DEM).
- Poligony tracą schodkowe krawędzie, stają się gładsze.
- Mniejszy rozmiar geometrii → szybsze MVT, szybsze ST_UnaryUnion, naturalniejsza granica.

## Efekty

| Metryka | Przed | Po |
|---------|-------|-----|
| stream_catchments | 117 228 | ~12 000 |
| CatchmentGraph RAM | ~5 MB | <1 MB |
| Najdrobniejszy BFS | 100 m² | 1000 m² |
| Snap-to-stream | tak | nie |
| Geometria poligonów | pikselowa | uproszczona 1m |

Wymaga re-run pipeline.
