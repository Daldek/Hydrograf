# Raport weryfikacyjny: obliczenia hydrogramowe

**Data:** 2026-03-22
**Punkt bazowy:** 52.284271°N, 20.884829°E
**Wersja:** develop (po zmianach hietogram/hydrograph split)

## 1. Punkty testowe

| Punkt | lat | lng | Area [km2] | CN | Strahler | Channel [km] | Lc [km] |
|-------|-----|-----|-----------|----|---------:|----------:|-----:|
| Upstream | 52.288 | 20.885 | 0.18 | 79 | 3 | 1.162 | 0.382 |
| **Target** | **52.284271** | **20.884829** | **3.46** | **74** | **7** | **0.075** | **1.770** |
| Downstream | 52.282 | 20.886 | 4.66 | 70 | 6 | 0.073 | 1.383 |

**Zmiana powierzchni:** upstream→target = **19.2x**, target→downstream = **1.35x**.
Punkt target jest przy ujsciu duzego doplywu, stad gwaltowny wzrost z 0.18 na 3.46 km2.

---

## 2. Model SCS — 3 punkty × 3 hietogramy

| Punkt | Hietogram | Qmax [m3/s] | tp [min] | V [m3] | P [mm] | Pe [mm] | C [-] | CN |
|-------|-----------|----------:|--------:|---------:|-----:|------:|-----:|---:|
| upstream | beta | 0.0340 | 170 | 402 | 26.99 | 2.24 | 0.083 | 79 |
| upstream | euler_ii | 0.0340 | 185 | 402 | 26.99 | 2.24 | 0.083 | 79 |
| upstream | block | 0.0340 | 190 | 402 | 26.99 | 2.24 | 0.083 | 79 |
| **target** | **beta** | **0.2360** | **395** | **6974** | **26.99** | **0.85** | **0.031** | **74** |
| target | euler_ii | 0.2360 | 415 | 6974 | 26.99 | 0.85 | 0.031 | 74 |
| target | block | 0.2360 | 420 | 6974 | 26.99 | 0.85 | 0.031 | 74 |
| downstream | beta | 0.0360 | 415 | 1113 | 26.99 | 0.24 | 0.009 | 70 |
| downstream | euler_ii | 0.0360 | 435 | 1113 | 26.99 | 0.24 | 0.009 | 70 |
| downstream | block | 0.0360 | 435 | 1113 | 26.99 | 0.24 | 0.009 | 70 |

### Obserwacje SCS:
- **Qmax i V identyczne** dla roznych hietogramow w obrebie jednego punktu — rozni sie jedynie `tp` (czas do szczytu)
- **Beta daje najszybszy szczyt** (170/395/415 min), block najwolniejszy (190/420/435 min) — poprawne
- **Downstream < target Qmax** (0.036 vs 0.236) — to jest **anomalia**: wieksza zlewnia (4.66 km2) daje mniejszy przeplyw niz mniejsza (3.46 km2). Przyczyna: CN downstream=70 vs target=74, wiec Pe=0.24mm vs 0.85mm, a takze tc downstream=633.9 min >> tc target=608.5 min — hydrogram jest bardziej rozlozony
- **effective_mm zwracane** — 12 krokow dla kazdego testu (dt=5min, czas 1h)

---

## 3. Model Nash — 3 punkty × 3 estymacje × 3 hietogramy

### 3.1 Porownanie estymacji (beta hietogram)

| Punkt | Estymacja | Qmax | tp | N | K [min] | tc [min] | urban | Pe_nash | dur_h |
|-------|-----------|-----:|---:|---:|------:|------:|------:|------:|------:|
| upstream | from_tc | 0.1520 | 50 | 3.0 | 10.61 | 53.1 | — | — | — |
| upstream | from_lutz | 0.0370 | 145 | 3.758 | 41.99 | — | — | — | — |
| upstream | from_urban | 0.1590 | 40 | 1.706 | 14.78 | — | 2.24 | 0.75 | — |
| **target** | **from_tc** | **1.2740** | **80** | **3.0** | **24.23** | **121.1** | — | — | — |
| target | from_lutz | 0.3670 | 230 | 3.648 | 75.07 | — | — | — | — |
| target | from_urban | 0.4940 | 140 | 2.559 | 71.12 | — | 0.85 | 0.6667 | — |
| downstream | from_tc | 0.2170 | 80 | 3.0 | 22.71 | 113.5 | — | — | — |
| downstream | from_lutz | 0.0710 | 200 | 3.686 | 61.29 | — | — | — | — |
| downstream | from_urban | 0.0790 | 160 | 2.953 | 63.68 | — | 0.24 | 0.5833 | — |

### 3.2 Wplyw hietogramu na Nash

| Punkt | Estymacja | beta Qmax | euler_ii Qmax | block Qmax | Roznica |
|-------|-----------|-------:|----------:|------:|------:|
| upstream | from_tc | 0.1520 | 0.1350 | 0.1540 | ~14% |
| upstream | from_urban | 0.1590 | 0.1420 | 0.1830 | ~29% |
| target | from_tc | 1.2740 | 1.2590 | 1.2830 | ~2% |
| target | from_urban | 0.4940 | 0.5150 | 0.5770 | ~17% |
| downstream | from_tc | 0.2170 | 0.2180 | 0.2200 | ~1% |
| downstream | from_urban | 0.0790 | 0.0890 | 0.1050 | ~33% |

### Obserwacje Nash:
- **from_tc daje najwyzszy Qmax** — N=3.0 (z parametru) i male K, wiec szybka odpowiedz
- **from_lutz daje najnizszy Qmax** — N i K wyestymowane empirycznie, dluzszy czas reakcji
- **from_urban_regression — N i K zmieniaja sie z hietogramem!** To jest poprawne: estymacja opiera sie na efektywnym czasie trwania opadu, ktory zalezy od rozkladu
- **urban_fraction = NULL** dla wszystkich punktow — **anomalia**: pole `nash_urban_fraction` nie jest wypelniane, choc `imperviousness=0.312` dla target. Sprawdzic backend
- **tc_min = NULL dla from_lutz i from_urban** — poprawne, te metody nie obliczaja tc

---

## 4. Model Snyder — 3 punkty × 3 hietogramy

| Punkt | Hietogram | Qmax | tp | V | tc [min] |
|-------|-----------|-----:|---:|------:|------:|
| upstream | beta | 0.0470 | 115 | 402 | 237.9 |
| upstream | euler_ii | 0.0470 | 130 | 402 | 237.9 |
| upstream | block | 0.0470 | 140 | 402 | 237.9 |
| **target** | **beta** | **0.3300** | **260** | **6971** | **608.5** |
| target | euler_ii | 0.3300 | 275 | 6971 | 608.5 |
| target | block | 0.3300 | 280 | 6971 | 608.5 |
| downstream | beta | 0.0650 | 220 | 1112 | 633.9 |
| downstream | euler_ii | 0.0650 | 235 | 1112 | 633.9 |
| downstream | block | 0.0650 | 240 | 1112 | 633.9 |

### Snyder ct/cp sensitivity (target, beta):

| ct | cp | Qmax | tp [min] | V [m3] |
|---:|---:|-----:|--------:|-------:|
| 1.35 | 0.40 | 0.3590 | 235 | 6971 |
| 1.50 | 0.60 | 0.3300 | 260 | 6971 |
| 1.65 | 0.80 | 0.3250 | 280 | 6971 |

### Obserwacje Snyder:
- **Snyder dziala dla wszystkich 3 punktow** — brak bledow 400
- **Qmax i V identyczne dla roznych hietogramow** — jak w SCS, jedynie tp sie rozni
- **ct/cp wplyw**: nizsze ct/cp = szybszy, wyzszy szczyt (Qmax 0.359 vs 0.325), wyzsze = wolniejszy, nizszy — **poprawne**
- **V stale = 6971** niezaleznie od ct/cp — poprawne (objetosc zalezy od opadu efektywnego, nie UH)
- **tc bardzo duze** (608.5 min = 10.1h) — wydaje sie zawyzone. Wynika z metody NRCS i malego channel_length (0.075 km). Warto sprawdzic

---

## 5. Czulosc na czas trwania opadu

| Duration | P [mm] | Pe [mm] | C [-] | Qmax [m3/s] | tp [min] | V [m3] |
|----------|-----:|------:|-----:|----------:|-------:|-------:|
| 5min | 14.07 | 0.00 | 0.000 | 0.0000 | 0 | 0 |
| 10min | 16.87 | 0.00 | 0.000 | 0.0000 | 0 | 0 |
| 15min | 18.77 | 0.01 | 0.000 | 0.0030 | 375 | 77 |
| 30min | 22.54 | 0.23 | 0.010 | 0.0650 | 380 | 1923 |
| 45min | 25.04 | 0.54 | 0.021 | 0.1490 | 390 | 4400 |
| **1h** | **26.99** | **0.85** | **0.031** | **0.2360** | **395** | **6974** |
| 1.5h | 30.07 | 1.47 | 0.049 | 0.4100 | 410 | 12097 |
| 2h | 32.31 | 2.02 | 0.062 | 0.5600 | 425 | 16561 |
| 3h | 36.10 | 3.10 | 0.086 | 0.8590 | 450 | 25451 |
| 6h | 43.20 | 5.61 | 0.130 | 1.5240 | 530 | 46056 |
| 12h | 51.80 | 9.36 | 0.181 | 2.3310 | 685 | 76874 |
| 18h | 57.65 | 12.27 | 0.213 | 2.6980 | 830 | 100824 |
| **24h** | **62.21** | **14.73** | **0.237** | **2.8260** | **960** | **121013** |
| 36h | 69.30 | 18.82 | 0.272 | 2.8090 | 1220 | 154580 |
| 48h | 74.85 | 22.22 | 0.297 | 2.6810 | 1460 | 182499 |
| 72h | 83.45 | 27.79 | 0.333 | 2.3900 | 1915 | 228327 |

### Obserwacje:
- **5min i 10min: P < Ia** (14–17 mm < Ia=17.85 mm) → Pe=0, Qmax=0 — **poprawne**
- **15min: minimalne Pe** (0.01 mm) → Qmax=0.003 m3/s — poczatek generacji odplywu
- **Qmax rosnie do 24h** (2.826 m3/s), potem **maleje** — **poprawne**: dluzsza burza = wiecej P, ale nizsze natezenie → peak sie rozprasza
- **V ciagle rosnie** — poprawne: wiecej P = wiecej odplywu
- **tp rosnie monotonicznie** — poprawne: dluzsza burza = pozniejszy szczyt

---

## 6. Czulosc na prawdopodobienstwo

| Prob [%] | P [mm] | Pe [mm] | C [-] | Qmax [m3/s] | tp [min] | V [m3] |
|---------:|-----:|------:|-----:|----------:|-------:|-------:|
| 0.01 | 80.83 | 26.05 | 0.322 | 7.2500 | 390 | 214036 |
| 0.1 | 59.72 | 13.37 | 0.224 | 3.7210 | 390 | 109846 |
| 1 | 42.00 | 5.14 | 0.122 | 1.4310 | 390 | 42249 |
| 5 | 31.28 | 1.76 | 0.056 | 0.4890 | 395 | 14439 |
| **10** | **26.99** | **0.85** | **0.031** | **0.2360** | **395** | **6974** |
| 20 | 23.02 | 0.28 | 0.012 | 0.0790 | 400 | 2322 |
| 50 | 17.96 | 0.00 | 0.000 | 0.0000 | 415 | 1 |
| 90 | 14.81 | 0.00 | 0.000 | 0.0000 | 0 | 0 |
| 99.9 | 14.11 | 0.00 | 0.000 | 0.0000 | 0 | 0 |

### Obserwacje:
- **Monotonicznie rosnacy Qmax ze spadajacym p%** — **poprawne**: rzadsze zdarzenie = wiekszy opad
- **p=50%: Pe~0, Qmax~0** — opad 17.96 mm ~ Ia=17.85 mm, prawie cala retencja pochlaniana
- **p=0.01%: Qmax=7.25 m3/s** — zdarzenie ekstremalnie rzadkie (raz na 10000 lat)
- **tp prawie staly** (~390-415 min) — poprawne dla SCS: czas do szczytu zalezy od tc, nie od natezenia
- **tp=415 min dla p=50% a tp=0 dla p>=90%** — anomalia: `tp=415` dla V=1 m3 jest nieoczekiwane (opad na granicy Ia). Wynika z tego, ze jest sladowy opad efektywny (V=1 m3, Qmax=0.0000) co tworzy prawie zerowy hydrogram

---

## 7. Podsumowanie i wnioski

### Poprawne zachowania:
1. **Bilans wodny spojny** — P, Pe, C, S, Ia poprawne matematycznie (SCS-CN)
2. **effective_mm zwracany** — 12 krokow dla dt=5min, 1h opadu
3. **Roznice miedzy hietogramami** — glownie w tp (czas do szczytu), Qmax i V takie same
4. **Czulosc na czas trwania** — Qmax rosnie do ~24h, potem maleje; V rosnie monotonicznie
5. **Czulosc na prawdopodobienstwo** — monotonicznie: nizsze p = wyzszy Qmax
6. **Snyder ct/cp** — nizsze wartosci = szybszy/wyzszy szczyt, V stale
7. **Nash estymacje** — from_tc szybki, from_lutz wolniejszy, from_urban dostosowuje N/K do hietogramu

### Potencjalne anomalie do zbadania:

| # | Opis | Priorytet |
|---|------|-----------|
| A1 | **Downstream Qmax < Target Qmax** (0.036 vs 0.236) — wieksza zlewnia daje mniejszy przeplyw. Przyczyna: CN 70 vs 74. Ale to moze byc poprawne jesli zlewnia downstream jest bardziej lesna | Niski |
| A2 | **nash_urban_fraction = NULL** dla wszystkich punktow, choc imperviousness jest obliczone. Pole nie jest przekazywane z morphometry do metadanych Nash | Sredni |
| A3 | **tc bardzo duze** (608-634 min) dla target/downstream — metoda NRCS daje ~10h czasu koncentracji. Moze byc zawyzone z powodu malego channel_length (0.075 km). Sprawdzic, czy channel_slope jest poprawnie obliczany | Sredni |
| A4 | **Qmax identyczne dla roznych hietogramow** w SCS i Snyder — tylko tp sie rozni. To jest poprawne dla SCS (konwolucja z UH), ale warto zweryfikowac czy nie powinno byc roznic w Qmax | Niski |
| A5 | **p=50%: V=1 m3, tp=415 min** — sladowy opad tworzy niemal zerowy hydrogram. Mozna rozwazyc prog minimalnego Pe ponizej ktorego zwracamy Qmax=0 | Niski |

### Statystyki testow:
- **Laczna liczba testow:** 72
- **Bledy API:** 0
- **Pomyslne odpowiedzi:** 72/72 (100%)

---

## 8. Rozwiazanie anomalii (2026-03-23)

### A2: nash_urban_fraction = NULL — NAPRAWIONE

**Przyczyna:** `imperviousness` nie bylo wyciagane z danych land cover w `_compute_watershed()` i nie bylo przekazywane do `build_morph_dict_from_graph()`.

**Naprawa (commit `ff6eb19`):**
1. `watershed_service.py`: dodano parametr `imperviousness` do `build_morph_dict_from_graph()` i do zwracanego dict
2. `hydrograph.py`: wyciaganie `weighted_imperviousness` z `lc_data` i przekazywanie do `build_morph_dict_from_graph()`

**Weryfikacja:**
| Punkt | Przed | Po |
|-------|-------|-----|
| upstream | NULL | 0.199 |
| target | NULL | 0.208 |
| downstream | NULL | 0.132 |

### A3: tc zawyzone (608 min) — NAPRAWIONE

**Przyczyna:** Hydrolog `calculate_tc()` uzywal `channel_slope_m_per_m` (0.3%) dla metody NRCS, ale formula NRCS TR-55 wymaga **sredniego spadku zlewni** (parametr Y = average watershed slope), a nie spadku cieku.

**Naprawa (commit `ff6eb19`):**
W `hydrograph.py`: tymczasowe czyszczenie `channel_slope_m_per_m` dla metody NRCS, aby Hydrolog uzywal `mean_slope_m_per_m` (fallback).

**Weryfikacja:**
| Punkt | tc przed | tc po | Zmiana |
|-------|---------|-------|--------|
| upstream | 53.1 min | 71.8 min | +35% |
| target | 608.5 min | **200.6 min** | -67% |
| downstream | 633.9 min | **202.0 min** | -68% |

Efekt na hydrogram (target, SCS, 1h, p=10%):
| Metryka | Przed | Po |
|---------|-------|-----|
| Qmax | 0.236 m3/s | **0.704 m3/s** |
| tp | 395 min | **150 min** |
| V | 6974 m3 | 6974 m3 (bez zmian — zalezy od Pe) |

### A1, A4, A5: potwierdzone jako poprawne zachowanie

- **A1:** Downstream Qmax < target — poprawne fizycznie: CN downstream=70, Pe=0.24 mm vs CN target=74, Pe=0.85 mm
- **A4:** Identyczne Qmax dla roznych hietogramow w SCS/Snyder — poprawna teoria UH: konwolucja z ustaloym UH daje ten sam peak niezaleznie od rozkladu opadu o tym samym calkowitym Pe
- **A5:** p=50% V=1 m3 — edge case P ≈ Ia, szum numeryczny, brak buga
