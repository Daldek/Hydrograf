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

## ADR-019: Naprawa deduplikacji ciekow multi-threshold

**Data:** 2026-02-12
**Status:** Przyjeta

**Kontekst:** Siec ciekow (`stream_network`) byla pofragmentowana przy wyzszych progach akumulacji (FA). Analiza wykazala, ze `idx_stream_unique` (migracja 002) nie zawieral `threshold_m2` — wszystkie cieki DEM-derived maja `name=NULL` (COALESCE=''), wiec cieki z roznych progow w tym samym miejscu (ten sam geohash) byly traktowane jako duplikaty. `ON CONFLICT DO NOTHING` w `insert_stream_segments()` cicho pomijal "duplikaty". Utrata: 2257 segmentow (26-42% przy wyzszych progach).

**Opcje:**
- A) Dodac `threshold_m2` do unique index — najprostsza zmiana, cieki z roznych progow nie koliduja
- B) Usunac unique index calkowicie — ryzyko prawdziwych duplikatow przy reimporcie
- C) Zmieniac INSERT na upsert — komplikuje logike, nie rozwiazuje problemu indexu

**Decyzja:** Opcja A. Migracja 010: DROP + CREATE idx_stream_unique z `threshold_m2`. Dodano diagnostyke (warning w `insert_stream_segments()` gdy segmenty pominiete) i walidacje (stream vs catchment count per threshold w `process_dem.py`).

**Konsekwencje:**
- Po re-runie pipeline: 82624 → 84872 ciekow (z 84881 catchments)
- Progi 1000/10000/100000 m²: stream == catchment count (idealnie sparowane)
- Prog 100 m²: 9 segmentow odrzuconych przez geohash collision (0.012%) — rozne segmenty o identycznym 12-znakowym geohash (precyzja ~3.7cm przy 1m DEM)
- Przyszle cieki MPHP (z name != NULL) nadal deduplikowane poprawnie
- Zrealizowano 2026-02-12: `alembic upgrade head` (migracje 008-010) + pipeline re-run z `--clear-existing` (17.5 min)

---

## ADR-020: Punkty drenazu w zbiornikach bezodplywowych (BDOT10k)

**Data:** 2026-02-12
**Status:** Przyjeta

**Kontekst:** `pyflwdir_fill_depressions(outlets="edge", max_depth=-1.0)` wypelnia WSZYSTKIE zaglebienia i kieruje wode do krawedzi DEM. Dla jezior bezodplywowych (endorheic) jest to niepoprawne — woda wplywaja do zbiornika, ale nie wyplywa. Zbiornik powinien byc sinkiem w grafie przeplywu.

**Opcje:**
- A) Ignorowac — akceptacja bledu routingu (woda z jeziora plynie do krawedzi rastra)
- B) Post-processing fdir — reczna korekta flow direction po pyflwdir (skomplikowane, podatne na bledy)
- C) Pre-processing DEM — wstrzykniecie NoData w punkcie drenazu przed pyflwdir, aby pyflwdir traktowal go jako lokalny outlet

**Decyzja:** Opcja C. Dwuetapowy algorytm:
1. **Klasyfikacja** (`classify_endorheic_lakes()`): analiza topologii ciekow BDOT10k (OT_PTWP_A + OT_SWRS_L/SWKN_L/SWRM_L) + porownanie elewacji DEM (far_end vs near_end). Brak ciekow lub tylko doplywy → bezodplywowy. Przynajmniej 1 odplyw → przeplywowy.
2. **Wstrzykniecie NoData** po `fill_internal_nodata_holes()`, przed `pyflwdir_fill_depressions()` — pyflwdir traktuje NoData jako outlet, routuje wode do drain point.

**Konsekwencje:**
- Zbiorniki bezodplywowe staja sie poprawnymi sinkami w grafie przeplywu
- Wymaga BDOT10k GPKG z warstwami OT_PTWP_A + OT_SWRS_L/SWKN_L/SWRM_L (pobierane przez Kartograf)
- Opcjonalne — aktywowane automatycznie gdy `--burn-streams` wskazuje na GPKG z warstwami wodnymi
- Drain points wstrzykiwane PO fill_holes (inaczej zostana wypelnione) i PRZED pyflwdir
- Komórki wskazujace na drain point dostaja `downstream_id = NULL` w flow_network (sink)
- Diagnostyka w logach: `endorheic: N, exorheic: M, drain_points: N`

---

## ADR-021: Graf zlewni czastkowych zamiast rastrowych operacji runtime

**Data:** 2026-02-13
**Status:** Przyjeta

**Kontekst:** Endpoint `select-stream` dzialal na poziomie rastra (19.7M komorek): BFS po `flow_network` → budowanie granicy z pikseli → szukanie zlewni czastkowych wewnatrz granicy → obliczanie statystyk z komorek. Zlewnie czastkowe (~87k) juz istnialy jako gotowe poligony — operacje rastrowe w runtime byly niepotrzebne.

**Opcje:**
- A) Zostawic raster-based flow — dziala, ale wolne (200ms-5s) i zlozne architektonicznie
- B) Graf zlewni czastkowych in-memory (~87k wezlow) z pre-computed stats — zero operacji rastrowych w runtime

**Decyzja:** Opcja B. Nowy modul `core/catchment_graph.py` — in-memory graf (~8 MB) zaladowany przy starcie API. Flow: klik → `ST_Contains` na `stream_catchments` → BFS po grafie → agregacja pre-computed stats z numpy arrays → `ST_Union` poligonow dla granicy.

Nowe kolumny w `stream_catchments` (migracja 012): `downstream_segment_idx`, `elevation_min_m`, `elevation_max_m`, `perimeter_km`, `stream_length_km`, `elev_histogram` (JSONB — histogram wysokosci ze stalym interwalem 1m, mergowalny).

Pipeline: `compute_downstream_links()` wyznacza graf connectivity (follow fdir 1 komorke z outlet kazdego segmentu), `zonal_min`/`zonal_max`/`zonal_elevation_histogram` obliczaja pre-computed stats.

**Konsekwencje:**
- `select-stream`: ~200ms-5s → ~5-50ms (10-100x przyspieszenie)
- API memory: +8 MB (vs 1 GB flow graph — marginalny narzut)
- Krzywa hipsometryczna z mergowania histogramow (O(k) per catchment, k≈20 bins)
- Wymaga re-runu pipeline (nowe kolumny w `stream_catchments`)
- Endpoint `select-stream` calkowicie przepisany — brak zaleznosci od flow graph i operacji rastrowych
- 19 nowych testow jednostkowych (`test_catchment_graph.py`), 8 testow integracyjnych zaktualizowanych

---

## ADR-022: Eliminacja FlowGraph z runtime API

**Data:** 2026-02-14
**Status:** Przyjeta

**Kontekst:** API ladowalo FlowGraph (~19.7M komorek, ~1 GB RAM, ~90s startup) do pamieci przy starcie serwera, mimo ze CatchmentGraph (~87k wezlow, ~8 MB, ~3s) juz dostarczal te same dane w formie zagregowanej (ADR-021). FlowGraph byl redundantny — endpointy `delineate-watershed`, `generate-hydrograph` i `select-stream` wszystkie mogly korzystac z CatchmentGraph. Dodatkowo `find_main_stream()` w sciezce FlowGraph zwracal `channel_length=0` (bug — downstream_id=None w pamieci). Endpoint `terrain-profile` wykonywal LATERAL JOIN na 19.67M wierszach `flow_network` — jedyne pozostale runtime-query do tej tabeli.

**Opcje:**
- A) Zostawic FlowGraph obok CatchmentGraph — 1.1 GB RAM, redundantne dane, wolny startup
- B) Usunac FlowGraph z runtime, zastapic CatchmentGraph + rasterio DEM sampling — 40 MB RAM, 3s startup

**Decyzja:** Opcja B. Nowy modul `core/watershed_service.py` z reuzywalnymi funkcjami (wzorzec z `select_stream.py`). Endpointy `watershed.py` i `hydrograph.py` przepisane na CatchmentGraph. Endpoint `profile.py` zmieniony z SQL LATERAL JOIN na bezposredni odczyt z pliku DEM przez rasterio. FlowGraph usuniety z `api/main.py` lifespan — zachowany w `core/flow_graph.py` dla skryptow CLI.

**Konsekwencje:**
- RAM API: ~1.1 GB → ~40 MB (-96%)
- Startup: ~93s → ~3s (-97%)
- Docker memory limit: 3 GB → 512 MB (-83%)
- flow_network runtime queries: 3 endpointy → 0 (-100%)
- Boundary quality: raster polygonize / convex hull → ST_Union pre-computed (lepsza)
- main_stream_geojson: broken (None) → z stream_network (naprawione)
- Profile endpoint: LATERAL JOIN 19.7M → rasterio plik DEM (szybsze, dokladniejsze)
- Legacy functions (find_nearest_stream, traverse_upstream) zachowane w `core/watershed.py` dla skryptow CLI
- Nowy modul `core/watershed_service.py` (~400 linii) — wspolna logika dla 3 endpointow
- 29 nowych testow (25 unit + 4 integracyjne), 548 testow lacznie

---

## ADR-024: Precyzyjna selekcja cieku — segmentacja konfluencyjna + fine-threshold BFS

**Data:** 2026-02-15
**Status:** Superseded (przez ADR-026)

**Kontekst:** Klikniecie na ciek zaznaczalo cala zlewnię tego cieku, niezaleznie od miejsca klikniecia. Dwa powody: (1) grube progi (100000 m²) — caly ciek to 1 segment, (2) segmentacja Strahlerem — segmenty lamia sie TYLKO przy zmianie rzedu, wiec ciek rzedu 2 z 5 doplywami rzedu 1 to wciaz 1 segment. Poprzednia proba (branch `feature/f1-fix-hierarchical`) — hierarchiczne scalanie z catchment_merge.py — niepowodzenie z powodu ryzyk kaskadowych bledow danych i kruchej topologii.

**Opcje:**
- A) Hierarchiczne scalanie (catchment_merge.py, migracja 015) — kaskadowe ryzyko, artefakty geometrii
- B) Segmentacja konfluencyjna (preprocessing) + fine-threshold BFS (query) — proste, lokalne zmiany

**Decyzja:** Opcja B. Dwa niezalezne kroki:

1. **Preprocessing — segmentacja konfluencyjna:** Dodanie warunku `upstream_count[nr, nc] > 1` w `vectorize_streams()` obok istniejacego warunku Strahlera. Segmenty lamia sie przy KAZDEJ konfluencji (dwoch lub wiecej doplywow), nie tylko przy zmianie rzedu. Istniejacy mechanizm (junction point, label raster, downstream links) obsluguje to bez zmian.

2. **Query — fine-threshold BFS:** Nowa funkcja `find_stream_catchment_at_point()` snap-to-stream na progu 100 m² (najdrobniejszym). BFS po CatchmentGraph na progu 100 m². Granica z `ST_UnaryUnion(ST_Collect(ST_SnapToGrid(geom, 0.01)))`. Mapowanie na display threshold dla MVT via `map_boundary_to_display_segments()`. Fallback do display threshold gdy brak danych na progu 100.

**Konsekwencje:**
- Segmenty: ~78k → ~120-160k na progu 100 m² (po re-run pipeline)
- CatchmentGraph: ~8 MB → ~16 MB RAM (miesci sie w limicie 512 MB)
- Czas odpowiedzi: ~200-600ms → ~600ms-3s (wiecej segmentow do ST_Union)
- Pipeline runtime: ~15-20 min (bez zmian)
- Schemat DB: bez zmian (zero migracji)
- Wymaga re-run pipeline po zmianach preprocessing
- Backward compatible: fallback do display threshold gdy brak fine danych

---

## ADR-025: Warunkowy próg selekcji cieku — fine BFS tylko dla display_threshold==100

**Data:** 2026-02-16
**Status:** Superseded (przez ADR-026)

**Kontekst:** Po ADR-024 endpoint `select_stream` zawsze wykonywal snap-to-stream i BFS na progu 100 m² (najdrobniejszym), niezaleznie od progu wyswietlanego na mapie. Powodowalo to snap do drobnych doplywow niewidocznych przy grubszych progach (1000, 10000, 100000), koniecznosc ekstremalnego przyblizenia do cieku oraz zwracanie zlewni niezgodnej z widokiem uzytkownika.

**Opcje:**
- A) Zawsze fine BFS (100) — precyzyjne, ale niespojne z widokiem mapy przy grubszych progach
- B) Warunkowe rozgalezienie: fine BFS dla display_threshold==100, snap+BFS na progu wyswietlanym dla pozostalych

**Decyzja:** Opcja B. Warunkowe rozgalezienie w `select_stream.py`:
- `display_threshold == 100`: obecna logika ADR-024 (fine BFS, precyzyjna selekcja miedzykonfluencyjna) bez zmian
- `display_threshold != 100` (1000, 10000, 100000): snap-to-stream i BFS na progu wyswietlanym — spojne z widokiem mapy

**Konsekwencje:**
- Klikniecie na ciek przy progu 10000 snap-uje do cieku widocznego na mapie (nie do drobnego doplywu)
- Brak potrzeby ekstremalnego przyblizenia przy grubszych progach
- Logika cascade merge dziala poprawnie niezaleznie od progu startowego
- Display mapping (`map_boundary_to_display_segments`) dalej aktywne gdy merge_threshold != display_threshold
- Zero zmian w `watershed_service.py`, `catchment_graph.py`, schemacie DB i frontendzie

---

### ADR-026: Selekcja oparta o poligon zlewni (2026-02-16)

**Status:** Zatwierdzony

**Kontekst:** Snap-to-stream (`ST_ClosestPoint`) powodował błędne przypisanie kliknięcia do sąsiedniej zlewni, gdy jej ciek płynął blisko granicy. Próg 100 m² generował 105k zlewni cząstkowych bez praktycznego zastosowania. Geometria poligonów była pikselowa (schodkowe krawędzie z rastra).

**Decyzja:**
1. Selekcja oparta o poligon (`ST_Contains` na `stream_catchments`) zamiast snap-to-stream
2. Usunięcie progu 100 m² ze zlewni cząstkowych (cieki w `stream_network` zostają)
3. Zwiększenie tolerancji simplify geometrii z `cellsize/2` do `cellsize` (1m)
4. Dodanie kolumny `segment_idx` do `stream_network` (migracja 014)
5. `DEFAULT_THRESHOLD_M2 = 1000` (było 100)

**Konsekwencje:**
- ADR-024 (fine-threshold BFS) i ADR-025 (warunkowy próg) stają się nieaktualne
- `stream_catchments`: 117k → ~12k rekordów (po re-run pipeline)
- CatchmentGraph: ~5 MB → <1 MB RAM
- Eliminacja `find_nearest_stream_segment()` i `find_stream_catchment_at_point()` z flow selekcji
- `map_boundary_to_display_segments()` nie jest potrzebna (ten sam próg dla BFS i display)
- Wymaga re-run pipeline

---

## ADR-027: Snap-to-stream zamiast ST_Contains w selekcji cieku (2026-02-17)

**Status:** Zatwierdzony (zastepuje mechanizm z ADR-026)

**Kontekst:** ADR-026 wprowadzil selekcje oparta wylacznie o `ST_Contains(geom, ST_Point(click))` na tabeli `stream_catchments`. Trzy problemy:

1. **Bledna selekcja przy konfluencjach:** Klikniecie blisko granicy zlewni czastkowej moglo trafic w SASIEDNIA zlewnie zamiast tej zawierajacej widoczny ciek. BFS od zlego startu → calkowicie zly wynik.
2. **Bug `id` vs `segment_idx`:** Funkcja `find_nearest_stream_segment()` uzywala kolumny `id` (auto-increment PK) zamiast `segment_idx` (1-based per threshold, migracja 014). Wartosci `id` i `segment_idx` sa ROZNE — lookup w grafie po blednym indeksie zawisze zwracal None.
3. **Martwy kod:** `find_stream_catchment_at_point()` w `watershed_service.py` nigdzie nie uzywany (przywleczony z ADR-024/025).

**Przyczyna glowna problemu #2:** Migracja 014 dodala kolumne `segment_idx` do `stream_network`, ale nie zaktualizowano wszystkich zapytan SQL odwolujacych sie do tej tabeli. Funkcja `find_nearest_stream_segment()` nadal pobierala `id` i zwracala go jako `segment_idx`.

**Opcje:**
- A) Naprawa ST_Contains — uzycie centroidu cieku zamiast punktu klikniecia → nie rozwiazuje problemu bliskosci granicy
- B) Snap-to-stream + graph lookup — ST_Distance na stream_network → segment_idx → O(1) lookup w grafie → BFS. ST_Contains jako fallback

**Decyzja:** Opcja B. Nowy flow selekcji:
1. `find_nearest_stream_segment()` → `ST_DWithin(1000m)` + `ORDER BY ST_Distance` na `stream_network` → zwraca `segment_idx`
2. `cg.lookup_by_segment_idx(threshold, segment_idx)` → O(1) dict lookup → internal graph index
3. Jesli lookup fail → fallback: `cg.find_catchment_at_point()` (ST_Contains)
4. BFS upstream + agregacja stats — bez zmian

Dodatkowo: `verify_graph()` w `CatchmentGraph` — diagnostyka spojnosci grafu przy starcie (per-threshold: nodes, outlets, unique segment_idx).

**Konsekwencje:**
- Eliminacja blednej selekcji przy konfluencjach — uzytkownik klika na WIDOCZNY ciek, system identyfikuje TEN ciek
- Fix bugu `id` vs `segment_idx` — poprawny lookup w grafie
- `verify_graph()` raportuje niespojnosci przy starcie API — wczesne wykrywanie problemow danych
- Usuniety martwy kod `find_stream_catchment_at_point()`
- ST_Contains zachowany jako fallback (klikniecia z dala od ciekow)
- `watershed.py` (delineate) i `hydrograph.py` — BEZ ZMIAN (uzyja ST_Contains poprawnie — uzytkownik klika dowolnie na mape)

**Lekcje na przyszlosc (zapobieganie):**
1. Po kazdej migracji DB (nowa kolumna) — audyt WSZYSTKICH zapytan SQL do tej tabeli
2. Nigdy nie aliasowac nazw kolumn w dict-ach — uzywac nazwy z bazy (`result.segment_idx`, nie `result.id` jako `"segment_idx"`)
3. Testy integracyjne selekcji musza testowac edge cases: klikniecia blisko konfluencji, blisko granicy zlewni
4. Weryfikacja spojnosci danych miedzy tabelami (`stream_network ↔ stream_catchments`) przy starcie
5. Regularne czyszczenie martwego kodu — nieuzywane funkcje maskuja problemy

---

### ADR-028: Eliminacja tabeli flow_network (2026-02-17)

**Status:** Zatwierdzony
**Kontekst:** Tabela `flow_network` przechowywala dane kazdego piksela DEM (~39.4M wierszy dla 8 arkuszy). Ladowanie trwalo ~17 min (58% pipeline). Zadne API endpoint nie czyta z niej w runtime — wszystkie endpointy korzystaja z `stream_network`, `stream_catchments` i CatchmentGraph.
**Decyzja:** Eliminacja tabeli flow_network z pipeline i bazy. Migracja 015 (DROP TABLE). Usuniecie ~1000 linii martwego kodu (db_bulk flow_network functions, flow_graph.py, watershed.py legacy CLI).
**Konsekwencje:**
- Pipeline 8 arkuszy: ~29 min → ~12 min (-58%)
- Pipeline 25 arkuszy (powiat): ~3h → ~50 min (-60%)
- Rozmiar DB: -2 GB (-80%)
- Legacy CLI (watershed.py traverse_upstream_sql) usuniete
- Nadpisa: ADR-006 (COPY vs INSERT) — COPY nie jest juz potrzebne dla flow_network

**Implementacja:** migracja Alembic 015 (DROP TABLE flow_network), process_dem.py bez INSERT flow_network

---

## ADR-029: Wyznaczanie glownego cieku w CatchmentGraph (trace_main_channel)

**Data:** 2026-02-22
**Status:** Przyjeta

**Kontekst:** `channel_slope_m_per_m` byl obliczany z calkowitej dlugosci sieci rzecznej (suma WSZYSTKICH segmentow upstream) zamiast z dlugosci glownego cieku. Dla rozgalezionej zlewni calkowita siec jest 2-10x dluzsza od glownego cieku, co powodowalo zanizenie spadku i zawyZenie czasu koncentracji (Kirpich: `tc ~ S^(-0.385)`). Skutek: szczyt wezbrania zanizony → ocena zagrozenia powodziowego niebezpiecznie optymistyczna.

**Opcje:**
- A) Zapytanie SQL do `stream_network` (wyszukiwanie najdluzszej sciezki w DB)
- B) In-memory trace po `_upstream_adj` wg rzedu Strahlera (nowa metoda CatchmentGraph)
- C) Pre-compute glownego cieku w pipeline (dodatkowa kolumna DB)

**Decyzja:** Opcja B — `CatchmentGraph.trace_main_channel()`. Traweruje upstream od outletu, na kazdej konfluencji wybiera galaz o najwyzszym rzedzie Strahlera (tie-break: max stream_length, max area). Zwraca dlugosc i spadek glownego cieku. O(path_length), typowo 10-50 wezlow, <1ms.

**Konsekwencje:**
- Poprawny `channel_slope_m_per_m` → poprawny czas koncentracji → poprawny szczyt wezbrania
- `aggregate_stats()["stream_length_km"]` nadal zwraca sume calej sieci (uzywane do drainage density)
- Brak zmian w DB/migracjach — logika w 100% in-memory
- Naprawione 3 miejsca: `catchment_graph.py`, `watershed_service.py`, `select_stream.py`

---

## ADR-030: Usuniecie progu FA 100 m² z systemu

**Data:** 2026-02-24
**Status:** Przyjeta

**Kontekst:** Prog 100 m² generowal ~2.5M segmentow ciekow (90% tabeli stream_network), nie maja odpowiednich zlewni czastkowych (usuniete w ADR-026), wydluzaja pipeline o ~50%, zajmuja ~2 GB przestrzeni. Nie sa uzywane w API ani frontendzie.

**Opcje:**
- A) Zostawic prog 100 m² — dane istnieja, ale sa nieuzywane i kosztowne
- B) Usunac prog 100 m² z DEFAULT_THRESHOLDS_M2 i bazy danych

**Decyzja:** Opcja B. Usuniecie progu 100 z DEFAULT_THRESHOLDS_M2 → [1000, 10000, 100000]. Migracja 017 usuwa dane z bazy. Domyslny stream_threshold zmieniony na 1000.

**Konsekwencje:**
- Pipeline szybszy (~50% krocej)
- Baza lzejsza (~2 GB mniej)
- 3 progi zamiast 4
- Brak mozliwosci rollbacku danych (wymaga ponownego uruchomienia pipeline)

---

## ADR-031: Flaga --waterbody-mode do sterowania obsługa zbiornikow wodnych

**Data:** 2026-02-24
**Status:** Przyjeta

**Kontekst:** Funkcja `classify_endorheic_lakes()` zawsze klasyfikuje zbiorniki z BDOT10k gdy dostepny jest plik hydro. Potrzebna elastyczna kontrola: wylaczenie klasyfikacji, filtrowanie malych zbiornikow, uzywanie wlasnej warstwy.

**Opcje:**
- A) Jedna flaga `--waterbody-mode` z wartosciami enum (auto/none/custom) + osobna flaga sciezki
- B) Dwie flagi: `--waterbody-mode` (auto/none lub sciezka) + `--waterbody-min-area` (float)
- C) Trzy osobne flagi (--no-waterbodies, --waterbody-path, --waterbody-min-area)

**Decyzja:** Opcja B. `--waterbody-mode` przyjmuje "auto", "none" lub sciezke do pliku. `--waterbody-min-area` filtruje zbiorniki po powierzchni. Custom waterbody file → wszystkie traktowane jako endoreiczne (bez klasyfikacji ciekow).

**Konsekwencje:**
- Pelna kontrola bez zmian w istniejacym pipeline (domyslne "auto" = identyczne zachowanie)
- Custom layer nie wymaga ciekow z BDOT10k — uproszczona sciezka dla uzytkownikow z wlasna warstwa
- `min_area` dziala zarowno z auto jak i custom path
- Parametry propagowane przez bootstrap.py, prepare_area.py, process_dem.py do core/hydrology.py

---

### ADR-032: Wygładzanie granic zlewni (Chaikin smoothing)

**Data:** 2026-03-01
**Status:** Przyjęta

**Kontekst:** Granice zlewni generowane z rastra (rasterio.features.shapes) mają kształt schodkowy (pixel staircase). Douglas-Peucker z tolerancją 5m redukuje wierzchołki, ale nie wygładza narożników. Schodkowe granice zawyżają obwód, wpływając na wskaźniki morfometryczne (Kc, Rc, Re).

**Decyzja:**
1. `ST_SimplifyPreserveTopology(geom, 5.0)` przed wygładzaniem
2. `ST_ChaikinSmoothing(geom, 3)` — 3 iteracje corner-cutting
3. Tolerancja simplify w preprocessingu: `cellsize` → `2*cellsize`

**Konsekwencje:**
- Gładkie granice zlewni bez schodków
- Dokładniejsze wskaźniki morfometryczne
- Minimalny narzut wydajnościowy (~10-20ms per merge)
- Geometria w DB bez zmian (wygładzanie tylko runtime)

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
