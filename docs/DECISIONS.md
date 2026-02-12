# Rejestr decyzji — Hydrograf

Kazda decyzja architektoniczna lub projektowa jest udokumentowana ponizej.
Format: numer, data, kontekst (dlaczego temat powstal), rozwazone opcje, decyzja, konsekwencje.

---

## ADR-001: Graf w bazie zamiast rastrow runtime

**Data:** 2026-01-14
**Status:** Przyjeta

**Kontekst:** Operacje rastrowe sa zbyt wolne (> 30s) i wymagaja przesylania duzych plikow. Potrzebna byla architektura pozwalajaca na szybkie obliczenia runtime.

**Opcje:**
- A) Rastry w runtime — kazde zapytanie przetwarza NMT od nowa
- B) Preprocessing NMT raz → graf punktow w PostGIS, runtime: tylko SQL queries

**Decyzja:** Opcja B. Jednorazowy preprocessing NMT do grafu punktow w PostGIS. Runtime wykonuje tylko zapytania SQL.

**Konsekwencje:**
- Szybkie obliczenia (< 10s)
- Male przesyly sieciowe (GeoJSON ~ 100KB)
- Jednorazowy preprocessing (kilka godzin)
- Wymaga PostgreSQL z PostGIS

---

## ADR-002: Monolityczna aplikacja FastAPI

**Data:** 2026-01-14
**Status:** Przyjeta

**Kontekst:** MVP dla 10 uzytkownikow, deployment na pojedynczym serwerze. Trzeba bylo zdecydowac miedzy monolitem a microservices.

**Opcje:**
- A) Microservices — osobne serwisy dla watershed, hydrograph, preprocessing
- B) Jedna aplikacja FastAPI + jedna baza danych

**Decyzja:** Opcja B. Jedna aplikacja FastAPI z modulowa struktura wewnetrzna.

**Konsekwencje:** Prostsze deployment i debugging. Nizsza latencja (brak network calls). Trudniejsze skalowanie w przyszlosci (ale wystarczajace dla MVP).

---

## ADR-003: Leaflet.js zamiast Google Maps

**Data:** 2026-01-14
**Status:** Przyjeta

**Kontekst:** Potrzeba interaktywnej mapy z mozliwoscia wyboru punktu i wyswietlania granic zlewni.

**Opcje:**
- A) Google Maps API — potezne, ale platne i zamkniete
- B) Leaflet.js z podkladem OpenStreetMap — open-source, darmowy

**Decyzja:** Opcja B. Leaflet.js z OSM tiles.

**Konsekwencje:** Open-source, darmowy, lekki (40KB gzipped). Bogaty ekosystem pluginow. Wymaga samodzielnego hostingu tiles lub uzycie OSM.

---

## ADR-004: Hietogram Beta zamiast blokowego

**Data:** 2026-01-14
**Status:** Przyjeta

**Kontekst:** Hietogram blokowy jest zbyt uproszczony — zaklada rownomierne rozlozenie opadu w czasie, co daje nierealistyczne wyniki dla dlugich zdarzen.

**Opcje:**
- A) Hietogram blokowy — prosty, ale nierealistyczny
- B) Rozklad Beta (alpha=2, beta=5) — asymetryczny, realistyczny rozklad opadu

**Decyzja:** Opcja B. Rozklad Beta z parametrami (2, 5) dla realistycznego rozkladu opadu.

**Konsekwencje:** Bardziej realistyczny hydrogram. Sprawdzony w literaturze. Wymaga SciPy (dodatkowa zaleznosc).

---

## ADR-005: Docker Compose dla deployment

**Data:** 2026-01-14
**Status:** Przyjeta

**Kontekst:** Potrzeba powtarzalnego i izolowanego srodowiska (PostgreSQL + PostGIS + FastAPI + Nginx).

**Opcje:**
- A) Natywna instalacja — szybka, ale trudna do odtworzenia
- B) Docker Compose — konteneryzacja calego stacku

**Decyzja:** Opcja B. Konteneryzacja z Docker Compose (db + api + nginx).

**Konsekwencje:** Environment parity (dev = production). Latwe deployment na nowym serwerze. Izolacja zaleznosci. Wymaga Docker na serwerze.

---

## ADR-006: COPY zamiast INSERT dla importu DEM

**Data:** 2026-01-20
**Status:** Przyjeta

**Kontekst:** Import 5M rekordow NMT do flow_network trwal ~102 min (INSERT + UPDATE). Wazne gardlo calego preprocessingu.

**Opcje:**
- A) Individual INSERT — 2,644 rec/s
- B) executemany — 3,196 rec/s (1.2x)
- C) COPY FROM — 55,063 rec/s (21x)

**Decyzja:** Opcja C. PostgreSQL COPY FROM z plikiem CSV.

**Konsekwencje:** Import przyspieszony 27x (z ~102 min do ~3.8 min). Wymaga tymczasowego pliku CSV. Mniejsze zuzycie RAM niz executemany.

---

## ADR-007: Reverse trace zamiast iteracji po head cells

**Data:** 2026-01-20
**Status:** Przyjeta

**Kontekst:** Funkcja find_main_stream iterowala po wszystkich head cells (835k dla zlewni 2.24 km²) — trwalo ~246s.

**Opcje:**
- A) Iteracja po head cells — kompletna, ale O(n) po wszystkich headach
- B) Reverse trace — od ujscia podazaj za max flow_accumulation do zrodla

**Decyzja:** Opcja B. Reverse trace — od outlet podazaj w gore po max accumulation.

**Konsekwencje:** Przyspieszenie 330x (z ~246s do ~0.74s). Rezultat identyczny — glowny ciek ma zawsze max accumulation. Prostsza implementacja.

---

## ADR-008: Bezposrednia zaleznosc IMGWTools

**Data:** 2026-01-21
**Status:** Przyjeta

**Kontekst:** Poczatkowo dane opadowe IMGW byly pobierane reczne. IMGWTools v2.1.0 oferuje programowy dostep.

**Opcje:**
- A) Reczne pobieranie + import CSV — dziala, ale wymaga interwencji czlowieka
- B) Bezposrednia zaleznosc od IMGWTools — automatyczne pobieranie w pipeline

**Decyzja:** Opcja B. IMGWTools jako bezposrednia zaleznosc (GitHub, branch develop).

**Konsekwencje:** Automatyczny dostep do danych opadowych. Zaleznosc na branchu develop moze powodowac niestabilnosc — pin do tagu po stabilizacji.

---

## ADR-009: Migracja black+flake8 na Ruff

**Data:** 2026-02-07
**Status:** Przyjeta

**Kontekst:** Workspace ma zunifikowane standardy (`shared/standards/DEVELOPMENT_STANDARDS.md`) ktore wymagaja ruff. Hydrograf uzywal black (formatter) + flake8 (linter) — dwa osobne narzedzia.

**Opcje:**
- A) Zostawic black + flake8 — dziala, ale niezgodne ze standardem workspace
- B) Migrowac na ruff — jedno narzedzie (linter + formatter), konfiguracja w pyproject.toml

**Decyzja:** Opcja B. Migracja na ruff. Usunieto `[tool.black]` i `[tool.flake8]` z pyproject.toml. Dodano `[tool.ruff]` z regulami `E, F, I, UP, B, SIM`.

**Konsekwencje:** Jedno narzedzie zamiast dwoch. Konfiguracja w jednym pliku. Zgodnosc ze standardem workspace.

---

## ADR-010: Kondensacja PROGRESS.md z 975 do ~75 linii

**Data:** 2026-02-07
**Status:** Przyjeta

**Kontekst:** PROGRESS.md narastal kumulatywnie przez 17 sesji. Wiekszosc tresci byla nieaktualna. Plik nie pelnil roli "gdzie jestem teraz".

**Opcje:**
- A) Zostawic — pelna historia, ale trudna do nawigacji (975 linii)
- B) Skondensowac do 4 sekcji (status, checkpointy, ostatnia sesja, backlog)
- C) Jak B, ale historia sesji zachowana w git

**Decyzja:** Opcja C. PROGRESS.md = biezacy stan (~75 linii). Historia 17 sesji pozostaje w git history. CHANGELOG.md pokrywa zmiany per-release.

**Konsekwencje:** Agent AI czyta PROGRESS.md i od razu wie co robic. Szczegoly historyczne dostepne przez `git log` i `git show`.

---

## ADR-011: .venv jako podstawowe srodowisko deweloperskie

**Data:** 2026-02-07
**Status:** Przyjeta

**Kontekst:** Docker Compose prezentowany jako glowne srodowisko dev, ale w praktyce testy, linting i skrypty CLI juz dzialaly przez .venv. Jedyny potrzebny serwis Docker = PostGIS. Dodatkowo requirements.txt zawieralo przestarzale dev deps (black, flake8) mimo migracji na ruff (ADR-009).

**Opcje:**
- A) Zostawic Docker Compose jako primary — wymaga budowania obrazu po kazdej zmianie
- B) .venv + docker compose up -d db — szybki cykl dev, Docker dla pelnego stacku

**Decyzja:** Opcja B. .venv = development, Docker = testowanie pelnego stacku i produkcja. Dev deps przeniesione do pyproject.toml [project.optional-dependencies]. requirements.txt zawiera tylko runtime deps (Dockerfile instaluje lekki obraz).

**Konsekwencje:** Szybszy cykl dev (brak rebuild obrazu). Wymaga Python 3.12+ na hoscie. Zgodnosc z wzorcem Kartograf. Czysty podzial runtime/dev dependencies.

---

## ADR-012: Migracja z pysheds na pyflwdir (Deltares)

**Data:** 2026-02-07
**Status:** Przyjeta

**Kontekst:** pysheds zwraca nieudokumentowane wartosci fdir (-1, -2) dla pitow i nierozwiazanych platow, co powoduje broken stream chains w flow_network (233 przy E2E). Fix wymaga dodatkowych krokow (fill_internal_sinks). Ponadto pysheds ma 10 zaleznosci i wymaga tymczasowego pliku GeoTIFF na dysku.

**Opcje:**
- A) Zostawic pysheds z fix_internal_sinks — dziala, ale 233 broken streams i duzo workaroundow
- B) pyflwdir (Deltares, MIT) — 3 zaleznosci (numpy, numba, scipy — juz w projekcie), praca na numpy arrays, Wang & Liu 2006

**Decyzja:** Opcja B. Nowa funkcja `process_hydrology_pyflwdir()` zastepuje `process_hydrology_pysheds()`. Jedno wywolanie `fill_depressions()` zastepuje 5 krokow pysheds. `fix_internal_sinks()` zachowane jako safety net.

**Konsekwencje:**
- Broken streams: 233 → 1 (jedyny to efekt brzegowy)
- Max accumulation: 1,067,456 → 1,823,073 (+71% — lepsza ciaglosc sieci)
- Pipeline 17% szybciej (173s vs 208s)
- Brak temp file (pysheds wymaga GeoTIFF na dysku)
- Mniej zaleznosci (3 vs 10)

---

## ADR-013: Wypalanie ciekow w DEM (stream burning)

**Data:** 2026-02-07
**Status:** Przyjeta

**Kontekst:** Cieki wyznaczone wylacznie z akumulacji przeplywu (threshold na flow accumulation) moga odchodzic od rzeczywistych w obszarach plaskich lub z niskiej jakosci NMT. Dostepna jest warstwa BDOT10k z rzeczywista siecia rzeczna.

**Opcje:**
- A) Tylko DEM-derived — cieki wyznaczane wylacznie z akumulacji, brak korekty
- B) Stream burning AGREE — zaawansowany algorytm (Hellweger 1997), wymaga bufora i wygładzania
- C) Stream burning proste — obnizenie DEM o stala wartosc wzdluz znanych ciekow

**Decyzja:** Opcja C. Proste obnizenie DEM o stala wartosc (domyslnie 5m) wzdluz ciekow z GeoPackage. Rasteryzacja ciekow na siatke DEM za pomoca `rasterio.features.rasterize(all_touched=True)`, nastepnie `dem[stream_mask] -= burn_depth`.

**Konsekwencje:**
- Lepsza zgodnosc wyznaczonych ciekow z BDOT10k w obszarach plaskich
- Narzut obliczeniowy ~2-3s (rasteryzacja + odejmowanie)
- Opcjonalne — aktywowane flaga `--burn-streams <path.gpkg>`
- Domyslna glebokosc 5m (konfigurowalna `--burn-depth`)
- Wypalanie przed depression filling (pyflwdir) — depresje po wypalaniu sa wypelniane normalnie
- Usuniecie warstwy `02b_inflated` (zbedna po migracji na pyflwdir)

---

## ADR-014: Rozszerzenie parametrow morfometrycznych i analiz rastrowych

**Data:** 2026-02-07
**Status:** Przyjeta

**Kontekst:** Hydrograf (v0.3.0) obliczal podstawowe parametry morfometryczne (area, perimeter, length, elevation, slope, CN). Brakowalo wskaznikow ksztaltu zlewni (Kc, Rc, Re, Ff), wskaznikow rzezbowych (Rh, HI, krzywa hipsometryczna), wskaznikow sieci rzecznej (Dd, Fs, Rn, max Strahler) oraz dodatkowych warstw rastrowych (aspect, TWI, Strahler stream order). Brak wektoryzacji ciekow jako LineString w bazie.

**Opcje:**
- A) Minimalna rozbudowa — tylko wskazniki ksztaltu (obliczane z istniejacych danych)
- B) Pelna rozbudowa — nowe rastery (aspect, TWI, Strahler), wektoryzacja ciekow, 15 nowych parametrow morfometrycznych, krzywa hipsometryczna
- C) Rozbudowa z zewnetrzna biblioteka (SAGA GIS / WhiteboxTools) — wiecej wskaznikow, ale nowa zaleznosc

**Decyzja:** Opcja B. Pelna rozbudowa z wykorzystaniem istniejacych narzedzi (pyflwdir, scipy, numpy). Implementacja w 4 etapach: (1) nowe rastery, (2) wektoryzacja ciekow, (3) parametry morfometryczne, (4) rozszerzenie API.

**Konsekwencje:**
- 3 nowe warstwy rastrowe: `07_stream_order.tif` (Strahler), `08_twi.tif` (TWI), `09_aspect.tif`
- Wektoryzacja ciekow z DEM jako LineString w `stream_network` (source='DEM_DERIVED')
- Kolumna `strahler_order` w `flow_network` (migracja 003)
- 11 nowych pol Optional w `MorphometricParameters` (backward compatible)
- Krzywa hipsometryczna dostepna opcjonalnie (`include_hypsometric_curve=true`)
- Nowe wskazniki obliczane z istniejacych danych — brak dodatkowych zaleznosci
- Wskazniki sieci (Dd, Fs, Rn) wymagaja wektoryzacji ciekow w bazie

---

## ADR-015: Ochrona przed resource exhaustion (OOM)

**Data:** 2026-02-09
**Status:** Przyjeta

**Kontekst:** Podczas E2E testu (2026-02-08) `traverse_upstream()` zostal wywolany na ujaciu z `flow_accumulation=1,760,000`. Brak jakichkolwiek limitow spowodowal OOM crash (~800-1000 MB peak), co zabilo sesje. Python `.fetchall()` ladowal 1.76M wierszy bez limitu, PostgreSQL mial `statement_timeout=0` (nieograniczony), brak LIMIT w CTE, brak limitow zasobow Docker. Kontener PostGIS nie byl problemem (172 MB, 1.08% RAM) — winny byl proces Python.

**Opcje:**
- A) Tylko LIMIT w CTE — chroni przed duzymi wynikami, ale nie zapobiega dlugim zapytaniom
- B) Wielowarstwowa ochrona: pre-flight check + CTE LIMIT + statement_timeout + Docker limits
- C) Jak B, ale z przetwarzaniem strumieniowym (server-side cursor) — bardziej skomplikowane

**Decyzja:** Opcja B. Cztery warstwy ochrony:
1. Pre-flight check (`check_watershed_size()`) — sprawdzenie `flow_accumulation` ujscia przed CTE (<1ms, PK lookup)
2. LIMIT w rekurencyjnym CTE — ograniczenie wynikow SQL
3. `statement_timeout=30s` w polaczeniu z baza — timeout na poziomie sesji PostgreSQL
4. Docker resource limits — `memory: 2G` (db), `memory: 1G` (api), PostgreSQL tuning

**Konsekwencje:**
- Zlewnie >2M komorek odrzucane natychmiast z czytelnym komunikatem
- Dlugie zapytania przerywane po 30s (API) lub 600s (skrypty CLI)
- Kontenery Docker nie moga wyczerpac calego RAM hosta
- PostgreSQL optymalnie skonfigurowany dla 2 GB kontenera (shared_buffers=512MB, work_mem=16MB)

---

## ADR-016: Przepisanie delineate_subcatchments na pyflwdir.basins()

**Data:** 2026-02-12
**Status:** Przyjeta

**Kontekst:** Pipeline `process_dem.py --thresholds "100,1000,10000,100000"` zostal zabity po ~20 minutach pracy (exit code 144, sygnal 16) podczas delimitacji zlewni czastkowych dla progu 100 m² (najgestszego, 76 596 segmentow).

Przyczyna: funkcja `delineate_subcatchments()` (linie 1687-1770) uzywala podwojnej petli w czystym Pythonie (`for i in range(nrows): for j in range(ncols)`) iterujacej po ~4.9M aktywnych komorkach rastra 20.6M (4737×4358). Dla kazdej nielabelowanej komorki wykonywala sledzenie w dol (trace downstream) tworzac dynamiczna liste `path`. Szacowany czas: 30-60+ minut na jeden prog FA.

Dowody awarii:
- Exit code 144 (128+16) — sygnal od srodowiska hostingowego
- Brak OOM killera w `dmesg` — limit na poziomie sesji, nie kernela
- 1.5 GB swap zajete po awarii — system pod presja pamieciowa
- Transkrypt sesji konczy sie bez odpowiedzi po otrzymaniu bledu — cala sesja przerwana
- Stan bazy: `flow_network` 4.9M rekordow (OK), `stream_network` 397 seg. (tylko prog 100), `stream_catchments` 0, `depressions` 0

**Opcje:**
- A) `scipy.ndimage.watershed_ift` — rozlewanie etykiet strumieniowych po rasterze
- B) `pyflwdir.FlwdirRaster.basins()` — juz zaimportowany w skrypcie, dedykowany do D8
- C) Numba `@njit` — kompilacja istniejacego algorytmu do C

**Decyzja:** Opcja B. `pyflwdir.FlwdirRaster.basins(idxs=stream_idxs, ids=segment_ids)` — propagacja etykiet upstream po grafie D8 w C/Numba (O(n), jedno przejscie). Obiekt `FlwdirRaster` tworzony raz w `process_dem()` i reuzywany. Identyczny algorytm co petla Pythonowa, ale skompilowany.

**Konsekwencje:**
- Pipeline z 4 progami FA ukonczy sie w minutach zamiast godzin
- Brak nowych zaleznosci (pyflwdir juz w requirements.txt)
- Etykiety zgodne z `vectorize_streams()` label raster (ten sam 1-based segment_id)
- `FlwdirRaster` tworzony raz w `process_dem()` (~0.5s) zamiast wielokrotnie w funkcjach

---

## ADR-017: Podzial process_dem.py na moduly core/ i optymalizacja pipeline

**Data:** 2026-02-12
**Status:** Przyjeta

**Kontekst:** Skrypt `process_dem.py` (2843 linii) realizowal caly pipeline przetwarzania DEM jako monolith. Glowne problemy: (1) trudnosc utrzymania i testowania, (2) dwa bottlenecki wydajnosciowe — `vectorize_streams()` ~300s (czyste petle Python po 20M komorkach) i `create_flow_network_records()` ~120s (budowanie 20M dictow, ~490MB RAM), (3) zduplikowane obliczenia gradientow Sobel (slope i aspect niezaleznie). Calkowity czas pipeline: ~22 min.

**Opcje:**
- A) Refaktoryzacja in-place — optymalizacja bez zmiany struktury pliku
- B) Podzial na moduly `core/` + optymalizacja (Numba, NumPy) — lepsze SoC, testowalnosc
- C) Przepisanie na Cython/Rust — maksymalna wydajnosc, ale duzy naklad pracy

**Decyzja:** Opcja B. Podzial `process_dem.py` na 6 modulow w `core/`: `raster_io`, `hydrology`, `morphometry_raster`, `stream_extraction`, `db_bulk`, `zonal_stats`. Orchestrator z re-eksportami dla backward compat. Optymalizacje: (1) wspolne gradienty Sobel, (2) Numba `@njit` dla upstream counting i headwater detection, (3) NumPy wektoryzacja `create_flow_network_tsv()` z bezposrednim TSV do COPY.

**Konsekwencje:**
- `process_dem.py` z 2843 do ~700 linii (orchestrator + re-eksporty)
- 6 nowych modulow `core/` z 85 nowymi testami jednostkowymi
- Numba 0.63.1 — transitive dep od pyflwdir, bez nowej zaleznosci
- Szacowane przyspieszenie: ~22 min → ~6-8 min (vectorize_streams 300s→10s, flow_network 120s→5s)
- Backward compat: re-eksporty w `scripts/process_dem.py`, stare `create_flow_network_records()` zachowane

---

## ADR-018: Optymalizacja PostGIS w workflow — in-memory flow graph + pre-gen tiles

**Data:** 2026-02-12
**Status:** Przyjeta

**Kontekst:** Analiza roli PostGIS w workflow Hydrograf wykazala, ze preprocessing juz pracuje w natywnych formatach rastrowych (numpy/pyflwdir), a DB jest tylko magazynem wynikow. W runtime kluczowe operacje to: (1) `traverse_upstream()` — recursive CTE na 19.7M wierszach (2-5s), (2) MVT tile serving — `ST_AsMVT` per-request (50-200ms), (3) martwy kod DEM tiles (`dem_raster`). PostGIS nie ma kluczowych algorytmow hydrologicznych (fill, fdir, acc, strahler), wiec przeniesienie calego pipeline do PostGIS jest niewykonalne.

**Opcje:**
- A) DB na sam koniec — juz zaimplementowane (preprocessing jest 100% numpy)
- B) Wszystko w PostGIS — niewykonalne (brak 4/5 kluczowych algorytmow)
- C) Optymalizacje hybrydowe:
  - C1: Pre-generacja kafelkow MVT (tippecanoe) — tile serving z ~50-200ms → ~1ms
  - C2: Graf przeplywow in-memory (scipy.sparse) — traverse_upstream z 2-5s → 50-200ms
  - C3: Usunac martwy kod dem_raster — klarownosc kodu
  - C4: Partial index na stream_network dla DEM_DERIVED

**Decyzja:** Opcja C. Cztery optymalizacje hybrydowe:
1. **In-memory flow graph** (`core/flow_graph.py`): ladowanie 19.7M komorek do numpy arrays + scipy sparse CSR matrix przy starcie API. BFS traversal via `scipy.sparse.csgraph.breadth_first_order` (~50-200ms). SQL fallback gdy graf nie zaladowany. API memory limit: 1G → 3G.
2. **Pre-generacja MVT tiles** (`scripts/generate_tiles.py`): eksport GeoJSON + tippecanoe → .mbtiles → .pmtiles. Frontend: auto-detekcja statycznych tiles z fallback na API.
3. **Usuniety martwy kod**: DEM tile endpoint (lines 1-238 z tiles.py), `import_dem_raster.py`, colormap/elevation helpers.
4. **Migracja 009**: partial GIST index na `stream_network WHERE source = 'DEM_DERIVED'`.

**Konsekwencje:**
- `traverse_upstream`: 2-5s → 50-200ms (10-100x przyspieszenie)
- Tile serving: 50-200ms → ~1ms (z pre-gen tiles, wymaga tippecanoe)
- API memory: 1G → 3G (numpy arrays + sparse matrix ~1 GB)
- tiles.py: z 427 do ~200 linii (usuniety DEM raster endpoint)
- Fallback: SQL CTE dziala nadal gdy graf nie zaladowany

---

<!-- Szablon nowej decyzji:

## ADR-XXX: Tytul

**Data:** YYYY-MM-DD
**Status:** Przyjeta | Odrzucona | Zastapiona przez ADR-YYY

**Kontekst:** Dlaczego temat powstal.

**Opcje:**
- A) ...
- B) ...

**Decyzja:** Ktora opcja i dlaczego.

**Konsekwencje:** Co z tego wynika.

-->
