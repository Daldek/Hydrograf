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
