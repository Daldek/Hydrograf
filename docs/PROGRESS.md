# PROGRESS — Hydrograf

## Stan bieżący (2026-11-05)

- **Gałąź `fix/remove-nash-from-tc` (2026-11-05, do kandydata v0.5.0; decyzja autora):** usunięta estymacja Nasha z czasu koncentracji (`nash_estimation: "from_tc"`, `NashIUH.from_tc`, przestarzała w Hydrologu od 0.6.2) i pole żądania `nash_n`; żądanie z `from_tc` dostaje 400 `validation_error` przy `/body/nash_estimation` z dozwolonymi wartościami, `GET /api/scenarios` bez `from_tc` i `nash_defaults`, żadna estymacja Nasha nie liczy Tc. GUI: bez opcji „z Tc (deprecated)” i pola „N (zbiorniki)”; objaśnienia (i), instrukcja, prezentacja HTML i PDF (przedrukowany, 31 slajdów) bez wzmianek. Zamyka Open questions 5.
- **Gałąź `feature/handoff-to-hydrolog` (2026-11-04, nie scalona; scalenie po v0.5.0, decyzja autora):** przekazanie zlewni do GUI Hydrologa jako `nogat-handoff/1` z `hydrolog-network/1` (ADR-068, plan `docs/plans/2026-11-04-handoff-to-hydrolog.md`). API: `handoff` w odpowiedziach delineacji (sama zlewnia) i hydrogramu (zlewnia, opad, odpływ, wynik bez zaokrągleń), pole żądania `morphometry_origin`; GUI: „Kopiuj do Hydrologa” i „Plik przekazania” pod sekcjami panelu „Zlewnia”; przewodnik slajd 26 (31 slajdów; PDF prezentacji odświeżony 2026-11-05 na gałęzi `fix/remove-nash-from-tc`). Próba w obie strony z Kamiennikiem (51,01544; 15,88984) przez produkcyjne API tylko do odczytu: Hydrolog otwiera przekazanie w „Hydrogramie zlewni”, porównanie „zgodny” (SCS, Nash, Snyder, własna seria, tryb zaawansowany). Do zmiany po stronie Hydrologa: przekazanie bez opadu jest odrzucane, teksty „Do schowka” i „w przygotowaniu”.

- **Produkcja = `develop` (0.5.0.dev0; 2026-11-02 `a247bf3`, wtedy błędnie v0.8.0.dev0)** na `127.0.0.1:8080`, z zewnątrz przez tunel Cloudflare `hydrograf-test.debever.pl`. Zaktualizowana **w miejscu** 2026-11-02 ok. 22:15–22:20: checkout `~/workspace/Hydrograf` z `08d8190` (`feature/visual-identity`) na `develop`, obraz `hydrograf-api:latest` przebudowany (piny Kartograf `eab8612`, Hydrolog `1708a09`, IMGWTools `71bae77`), `hydro_api` odtworzony; przerwa ok. 21 s. Bez migracji bazy (alembic `003` = head). `.env`: `HYDROGRAF_PUBLIC_HOST=hydrograf-test.debever.pl`, magazyn Kartografa prywatny (`cache/kartograf`, bez `HYDROGRAF_KARTOGRAF_ROOT`). Wynik SFINCS `sfincs-kamiennik-24h-p1` (24 h, p = 1%, zwierciadło do 281,43 m n.p.m.) zastąpił wynik 12 h.
- **Przebudowa 2026-11-03, 08:39–08:41:** obraz `hydrograf-api:latest` z `develop` `aafeb5a` (`6afc6f68a760`; wersja 0.5.0.dev0, `/health` i panel admina podają ją z `core/version.py` zamiast stałej `1.0.0`), `hydro_api` odtworzony (`--no-deps --force-recreate`), `docker builder prune -f` przed budową. Przerwa ok. 9 s (502 od 08:40:57 do 08:41:05, `health-loop-2026-11-03.log` w katalogu kopii). Po: `/health` 200 z `"version": "0.5.0.dev0"` (8080 i host publiczny), OpenAPI `info.version` 0.5.0.dev0, delineacja 15,15 km² i 37,22 km², admin bez klucza 401. Tag rollbacku przemianowany: `hydrograf-api:pre-0.5.0` (było `vi-0.7.0`).
- **Przebudowa 2026-11-04, ok. 11:00 (piny zestawu Nogata):** checkout produkcji przesunięty `--ff-only` z `f3404cd` na `develop` `d901268`; obraz `hydrograf-api:latest` przebudowany z pinami `candidate-1` (Kartograf `9deaa31`, Obserwator `ea158dc` — dawniej IMGWTools, import `obserwator` — Hydrolog `2eb8bd0`; w obrazie obserwator 3.0.0, kartograf 0.8.0.dev0, hydrolog 1.0.0.dev0), `hydro_api` odtworzony (`--no-deps --force-recreate`). Bez migracji bazy. Po: `/health` 200 (8080 i host publiczny), hydrogram projektowy z PMAXTP 200 (1,67 km², 48,83 mm/1 h, p = 1%, Qmax 1,067 m³/s, także przez host publiczny), delineacja 200, punkt poza granicą 404 `application/problem+json`, admin bez klucza 401, brak błędów w logu. Kopia i rollback: `/data/nmt/hydrograf-backup-2026-11-04-pinset/` (`ROLLBACK.txt`, `hydro_db.dump` z SHA-256, `env`, `git-head.txt`), obraz `hydrograf-api:pre-pinset-2026-11-04`.
- **Przebudowa 2026-11-04, ok. 11:55 (Obserwator `1ee5457`):** checkout produkcji przesunięty `--ff-only` z `d2f727f` na `develop` `9e50785`; obraz przebudowany z Obserwatorem `1ee5457` zestawu `candidate-1` (w obrazie obserwator 3.0.0.dev0, kartograf 0.8.0.dev0, hydrolog 1.0.0.dev0), `hydro_api` odtworzony (`--no-deps --force-recreate`). Bez migracji bazy. Po: `/health` 200, hydrogram projektowy 200 (punkt 50,861 N 16,144 E, 1 h, p = 10%, Qmax 0,028 m³/s), `fetch_pmaxtp` w kontenerze odpowiada (POT), nieznana trasa 404 `application/problem+json`, admin bez klucza 401. Kopia i rollback: `/data/nmt/hydrograf-backup-2026-11-04-std10/` (`ROLLBACK.txt`, `hydro_db.dump` z SHA-256, `env`, `git-head.txt`), obraz `hydrograf-api:pre-std10-2026-11-04`.
- **Kopia i rollback:** `/data/nmt/hydrograf-backup-2026-11-02/`: `ROLLBACK.txt` (procedura), `hydro_db.dump` z sumą SHA-256, `env`, `frontend-data-results` (wynik 12 h), `git-head.txt` (`08d8190`), K0 przed i po (`prod-baseline.txt`, `prod-baseline-080.txt`), `health-loop.log`, smoke. Rollback: `git checkout --detach 08d8190`, `docker tag hydrograf-api:pre-0.5.0 hydrograf-api:latest` (obraz z 2026-10-18; do 2026-11-03 tag `vi-0.7.0`), `.env` i `frontend/data/results` z kopii, `docker compose up -d --no-build --force-recreate api`; baza bez zmian schematu, jej odtworzenie tylko w razie potrzeby.
- **Sprawdzenie:** smoke po przełączeniu na 8080 i przez host publiczny z tymi samymi wynikami (`/health` 200, delineacja 15,15 km² i 37,22 km² przy przekroju Kamiennika, punkt poza granicą 404 `application/problem+json`, „Identyfikuj” w czaszy 281,43 m / 16,28 m wody, `water_levels` profilu z wynikiem 24 h, admin bez klucza 401, zasoby z `?v=`). Testy przeglądarkowe GPT: staging 7/8, produkcja 8/8 PASS.
- **Staging zakończony:** stos `hydrograf-staging` (port 8081) usunięty; narzędzia `docker-compose.staging.yml` i `scripts/staging-compose.sh` zostają w repo na kolejne wydania.
- **Git:** gałęzie scalone do `develop` i usunięte; lokalnie tylko `develop` i `main`, jeden worktree (produkcja).
- **Bootstrap:** test Kamiennika z pustego magazynu prywatnego zaliczony (331 s). Pełny bootstrap obszaru z zestawu Archiwisty (S5 planu migracji) odłożony na po v0.5.0.
- **Otwarte w produkcji:** baza produkcji ma nadal 3436 z 3812 wierszy `bdot_streams` z nazwą `'nan'` (`SELECT`, 2026-11-02 ok. 22:40), więc karta „Identyfikuj” pokazuje przy ciekach bez nazwy „nan (…)” zamiast „bez nazwy (…)” (jak na stagingu w S2). Poprawka loadera (`2da5b2a`) działa tylko przy nowym imporcie; dla tej bazy CHANGELOG podaje `UPDATE bdot_streams SET name = NULL WHERE btrim(name) IN ('', 'nan');` — zapis do produkcji na decyzję autora.

### Decyzje
- **ZAMROŻENIE (autor, 2026-11-02):** od teraz do scalenia `develop` → `main` i tagu `v0.5.0` (stawia autor) praca nad Hydrografem jest zamrożona: wyłącznie krytyczne poprawki łamiące API albo rażące błędy. Decyzją autora z 2026-11-03 zamrożenie dopuszcza też zmianę samej dokumentacji: IMGWTools nazywa się Obserwator (od swojej v3.0.0; plan Nogata `docs/plans/2026-11-03-imgwtools-to-obserwator.md`, krok 4). Kod, konfiguracja, `pyproject.toml`, `uv.lock`, Docker i pliki env bez zmian.
- **Numer wydania (autor, 2026-11-03):** następne wydanie Hydrografa to **v0.5.0** (ostatnie: v0.4.0 na `main`; `develop` ma `0.5.0.dev0` od `a115135`). Commity z 2026-11-02 (`7109d36`, `8f3216e`) błędnie podały 0.8.0 / 0.8.0.dev0 (to wersja Kartografa); poprawione 2026-11-03.
- Produkcja przełączona w miejscu na `develop` zamiast przełączenia nginx blue/green (S7 planu `docs/plans/2026-11-02-store-migration.md`); S5 po v0.5.0.
- **Wyjątek od zamrożenia (2026-11-03):** CI na GitHubie (`pip-audit`) zgłosiło PYSEC-2026-4320 w `certifi` 2026.7.22; `backend/uv.lock` podniesiony do 2026.10.23 (`a6fe779`), bramka i `pip-audit` zielone, obraz produkcji przebudowany (`/health` 200, `certifi` 2026.10.23 w kontenerze, przerwa ok. 10 s). Archiwista miał tę samą wersję: `34e83f4`, instancja :8090 zaktualizowana.

### Następne kroki (wydanie v0.5.0)
1. Kolejna runda testów i code review.
2. Commit wydania: wersja 0.5.0, sekcja `[0.5.0]` w CHANGELOG (z `[Unreleased]`).
3. Piny producentów po tagach: Kartograf, Obserwator, Hydrolog (REL-5.3, ADR-060, ADR-061); do tagów piny idą za zestawem wydania Nogata (krok 6).
4. Merge `develop` → `main`; tag `v0.5.0` stawia autor.
5. Po wydaniu: S5 (bootstrap z zestawu Archiwisty), dane Dockera z `/` na `/data` ([BACKLOG.md](BACKLOG.md)).
6. ✅ (2026-11-03, `feature/pin-set`) Piny za zestawem wydania Nogata (candidate-1, plan Nogata `docs/plans/2026-11-03-one-pin-set.md`, D5 dopuszcza to w zamrożeniu jako zmianę API producenta): Kartograf `9deaa31`, Obserwator `ea158dc` (dystrybucja `obserwator` zamiast IMGWTools `71bae77`), Hydrolog `2eb8bd0`; importy `obserwator.fetch_pmaxtp` i `ObserwatorConnectionError`, `ObserwatorDataError`, `ObserwatorValidationError` zamiast `IMGW*Error`. Własne ustawienia `IMGW_GRID_SPACING_KM` i `IMGW_RATE_LIMIT_DELAY_S` nazywają dostawcę i zostają. Produkcja ma obraz ze starymi pinami do przebudowy przez autora.

## Status projektu

| Element | Status | Uwagi |
|---------|--------|-------|
| API (FastAPI + PostGIS) | ✅ Gotowy | 24 endpointy (11 core + 13 admin). Unified delineate-watershed (ADR-050). Sewer admin API (ADR-051). Od scalenia `feature/producer-heads` (2026-11-02) błędy jako `application/problem+json` z kodami wspólnego rejestru Nogata i tekstami wg `Accept-Language` (ADR-059). |
| Wyznaczanie zlewni | ✅ Gotowy | traverse_upstream, concave hull, tryb precomputed + precise (ADR-050) |
| Parametry morfometryczne | ✅ Gotowy | area, slope, length, CN + 11 nowych wskaznikow |
| Generowanie hydrogramu | ✅ Gotowy | SCS-CN + Nash (3 estymacje), 432 scenariusze |
| Preprocessing NMT | ✅ Gotowy | pyflwdir (~12 min/8 arkuszy po eliminacji flow_network), stream burning BDOT10k. Limit pamięci: szczyt ~103 B/komórkę rastra, czyli ~160M komórek przy 8G + 8G swap (~80M bez swapu); plan F1–F7 w `docs/TECHNICAL_DEBT.md` |
| Integracja Hydrolog | ✅ Gotowy | Pin zestawu Nogata `2eb8bd0` (1.0.0.dev0, `develop` Hydrologa; 2026-11-03, `feature/pin-set`; wywoływane API bez zmian, `OutsideTypicalRange` to podklasa `UserWarning`). Na produkcji od 2026-11-02 (`develop` `a247bf3`; wcześniej v0.6.3): pin `1708a09` (1.0.0.dev0, `fix/snyder-recession`, ADR-060; było `2a5ba1a`; od 2026-11-02 hydrogram jednostkowy Snydera biegnie do końca recesji, szczyt = qpR, B3); Snyder daje inny hydrogram (korekta czasu trwania, ta sama objętość): przy opadzie 1 h szczyt +11–12% i 25–70 min wcześniej, przy 12–24 h +3,5…+9,6% i 15–65 min wcześniej (pomiary S2/S3 planu migracji magazynu) |
| Integracja Kartograf | ✅ Gotowy | Pin zestawu Nogata `9deaa31` (0.8.0.dev0, `develop` Kartografa; 2026-11-03, `feature/pin-set`; sygnatury wywoływanych funkcji bez zmian). Na produkcji od 2026-11-02 (`develop` `a247bf3`; wcześniej v0.7.0): pin `eab8612` (0.8.0.dev0, gałąź Kartografa `feature/archiwista-projects`, 2026-10-31; ten sam co Archiwista; wybór arkuszy po obiektach `--geometry`); cache surowych pobrań to magazyn Kartografa `cache/kartograf/` (ADR-061), raster HSG jednej analizy to zwykły plik tymczasowy; katalogi układu 0.7.0 nie są czytane. Od S4 planu migracji (2026-11-02) magazyn może być wspólny z Archiwistą: `HYDROGRAF_KARTOGRAF_ROOT` (ADR-066); od H1 (ADR-067) magazyn wspólny jest dla Hydrografa tylko do odczytu, a wejście Kartografa bootstrapu pochodzi z zamkniętego zestawu projektu Archiwisty (`--project`, `--set`). Produkcja ma magazyn prywatny; bootstrap Kamiennika z pustego magazynu prywatnego zaliczony (331 s) |
| Integracja Obserwatora | ✅ Gotowy | Pin zestawu Nogata `ea158dc` (Obserwator 3.0.0, pakiet `obserwator`; 2026-11-03, `feature/pin-set`). Na produkcji od 2026-11-02 (`develop` `a247bf3`; wcześniej IMGWTools v2.1.0): pin `71bae77` (IMGWTools 3.0.0 sprzed zmiany nazwy, pakiet `imgwtools`, ADR-060) do przebudowy obrazu |
| Środowisko i jakość kodu | ✅ Gotowy | Od scalenia `feature/producer-heads` (standard Nogata 2.1, ADR-058): uv i `backend/uv.lock` zamiast `requirements.txt`, ruff (DEV-7.2), mypy `strict` (DEV-7.3), `affine>=2.4,<3` (ADR-062) |
| CN calculation | ✅ Gotowy | cn_tables + cn_calculator + determine_cn() |
| Kanalizacja deszczowa | ✅ Gotowy | SewerGraph, inlet burning, FA routing (ADR-051). Jawna topologia (ADR-052), walidacja strict, 2-fazowy pipeline. MVT tiles, overlay frontend, admin panel sewer. |
| Frontend | 🔶 Faza 4+ gotowa | 25 modułów JS na `window.Hydrograf` (19 core + 6 admin) + `theme-init.js`/`theme-switch.js`. Sewer overlay + admin-sewer. GUI w identyfikacji Nogata (ADR-065) na produkcji od 2026-11-01, od 2026-11-02 z `develop` (`a247bf3`); 2026-11-01/02 doszły wyniki analiz zewnętrznych (SFINCS, obecnie wynik 24 h), nakładka MZP ISOK, ekran powitalny, instrukcja 30 slajdów, zwierciadło wody na profilu terenu, wersjonowanie zasobów `?v=`, tryb „Identyfikuj”. Od scalenia `feature/producer-heads` błędy API pokazywane z `detail` problem+json. |
| Panel administracyjny | ✅ Gotowy | /admin: Dashboard, Bootstrap, Zasoby, Czyszczenie, Kanalizacja (ADR-034, ADR-051) |
| Testy | ✅ Gotowy | 1165 passed (sesja 88) + znany fail środowiskowy (test_select_stream, brak DB na localhost). Od scalenia `feature/producer-heads`: bramka `scripts/gate.sh` (ruff format, ruff check, mypy, pytest offline z pokryciem ≥ 80%, wersje zasobów `?v=`, commity) i CI `.github/workflows/ci.yml` |
| Dokumentacja | ✅ Gotowy | Audyt 16 plikow (2026-02-22), standaryzacja wg shared/standards (2026-02-07). Od scalenia `feature/producer-heads`: dokumenty wg standardu Nogata 2.1 po angielsku (część jeszcze po polsku), `docs/DEVELOPMENT_STANDARDS.md` usunięty (reguły w `CLAUDE.md`), backlog w `docs/BACKLOG.md`, ADR-058 i dalsze w `docs/decisions/` |

## Checkpointy

### CP1 — Health endpoint ✅
- **Data:** 2026-01-15
- **Wersja:** v0.1.0
- **Zakres:** Setup, Docker Compose, GET /health, migracje Alembic

### CP2 — Wyznaczanie zlewni ✅
- **Data:** 2026-01-18
- **Wersja:** v0.2.0
- **Zakres:** POST /delineate-watershed, traverse_upstream, build_boundary, integracja Hydrolog

### CP3 — Generowanie hydrogramu ✅
- **Data:** 2026-01-21
- **Wersja:** v0.3.0
- **Zakres:** POST /generate-hydrograph, SCS-CN, 432 scenariusze, COPY 27x, reverse trace 330x, Land Cover, IMGWTools

### CP4 — Frontend z mapa ✅
- **Data:** 2026-03-03
- **Wersja:** v0.4.0
- **Zakres:** Leaflet.js, Chart.js, interaktywna mapa, panel parametrow, glassmorphism, MVT tiles (streams/catchments/landcover), DEM tiles (piramida XYZ z hillshade), select-stream, GUGiK WMTS, wygladzanie granic zlewni (ADR-032), podniesienie budynkow w NMT (ADR-033), panel administracyjny (ADR-034), konfiguracja YAML pipeline, Docker hardening (ADR-036), cache/data separacja (ADR-037), HSG Poland-wide cache (ADR-038)

### CP5 — MVP ⏳
- **Wersja:** v1.0.0 (planowana)
- **Zakres:** Pelna integracja frontend+backend, deploy produkcyjny

## Gałąź `feature/producer-heads` (scalona 2026-11-02)

Gałąź `feature/producer-heads` (od `chore/nogat-2.1`, prace do 2026-10-25) scalono 2026-11-02 do `feature/store-migration` razem z `feature/visual-identity` (krok S1 planu `docs/plans/2026-11-02-store-migration.md`). Jej stan w skrócie:
- **Standard Nogata 2.1 (ADR-058):** uv i `backend/uv.lock` zamiast `requirements.txt` (wersje z obrazu z 2026-10-18, ograniczenia `sqlalchemy<2.1` i `affine<3`), ruff (DEV-7.2), mypy `strict` nad `api core models scripts utils tests`, ustawienia pytest (markery `live`, `db`, `slow`, `benchmark`, `tests/contract`, próg pokrycia 80), bramka `scripts/gate.sh` i `scripts/check-commits.sh` (bez zmian z Nogata), CI i Dependabot, pliki kontrybucji (`SECURITY.md`, `CONTRIBUTING.md`, `CONTRIBUTORS.md`, szablon PR z polem CLA; `docs/CLA.md` jeszcze nie istnieje), `CLAUDE.md` po angielsku z sekcją Deviations, README wg DOC-2.1, indeks ADR. `docs/DEVELOPMENT_STANDARDS.md` i `.pre-commit-config.yaml` usunięte; wersje zasobów `?v=` po scaleniu sprawdzają bramka i zadanie CI `frontend-assets` (`python3 scripts/bump_asset_versions.py --check`).
- **Błędy REST jako problem+json (ADR-059):** `HydrografError` z komunikatami z `core/messages.py`, kody wspólnego rejestru (`schemas/nogat/`, generowany `core/_errors.py`), `Accept-Language` (interfejs wysyła `pl`), statusy wg rejestru (m.in. błędne wartości 422 → 400, zły klucz admina 403 → 401, zlewnia > 250 km² 400 → 422, brak opadu 400 → 404).
- **Piny producentów po commicie (ADR-060, ADR-061):** po scaleniu Kartograf `eab8612d5666cafa43d1e2c4f0a034583310b66e` (0.8.0.dev0, gałąź `feature/archiwista-projects`, 2026-10-31; ten sam co Archiwista, wybiera arkusze po obiektach `--geometry`; gałąź PH miała `d11f621` z `feature/data-output`), IMGWTools `71bae77` (3.0.0) i Hydrolog `2a5ba1a` (1.0.0.dev0) bez zmian; `affine>=2.4,<3` zostaje (ADR-062: pyflwdir 0.5.12 nie działa z affine 3, poprawka czeka na 0.5.13).
- **Magazyn Kartografa (ADR-061):** cache surowych pobrań (NMT, BDOT10k, raster HSG Polski) to `cache/kartograf/`, cache metadanych `cache/kartograf_meta.db`, raster HSG jednej analizy CN to zwykły plik tymczasowy (`calculate_hsg`); katalogi `cache/nmt/`, `cache/bdot10k/`, `cache/soil_hsg/` układu 0.7.0 nie są czytane, czyszczenie cache je usuwa; `download_dem` i `download_landcover` biorą `--root` i `--metadata-cache`.
- **Hydrolog 1.0 API:** Snyder liczy hydrogram jednostkowy dla czasu trwania równego krokowi (korekta czasu trwania) — przy kroku 5 min szczyt wyższy o 11–12% i wcześniejszy o 25–70 min, objętość ta sama (zmiana łamiąca dla klientów API); SCS, Nash, wszystkie metody tc i hietogramy bez zmian.
- **Usunięty martwy kod:** `core/watershed.py` i funkcje komórkowe `core/morphometry.py` (zostaje `calculate_shape_indices`) z testami; naprawione kroki 3, 4 i 6 `scripts/analyze_watershed.py` oraz wywołania `process_dem` w `prepare_area.py` i `analyze_watershed.py`.

Czego gałąź PH nie uruchomiła: testów `db` (brak bazy), CI (żadne zadanie nie ruszyło, gałęzie bez pull requestu), prawdziwego pobrania NMT, BDOT10k i SoilGrids, `bootstrap` od początku do końca ani obrazu Docker (działający stos ma obraz zbudowany na starych pinach). Pominięte pozycje adopcji należą do autora: przepisanie historii, rulesety GitHub, `docs/CLA.md`, linie `Approved:` planów, wpis w rejestrze Nogata, tagi i wydania, push i merge `chore/nogat-2.1`. Poniżej listy Next i Open questions z PROGRESS gałęzi PH (`git show feature/producer-heads:docs/PROGRESS.md`) bez zmian, po angielsku; jedyna zmiana to pin Kartografa po scaleniu (`eab8612` zamiast `d11f621`). Otwarte pozycje backlogu obu gałęzi są w [BACKLOG.md](BACKLOG.md).

### Next (z gałęzi PH)

1. **Finish the standard 2.1 adoption on `chore/nogat-2.1`** (one commit per step, gate
   green before each; rules: `git -C ~/workspace/Nogat show feature/data-output:standards/<file>`;
   Archiwista's branch `chore/nogat-2.1` is the worked example of an `app`). Remaining
   gaps of the inventory of 2026-10-25, in this order:
   - **mypy is done**; its deviations go to the Deviations section of CLAUDE.md (DEV-7.3):
     `migrations/` is excluded; the packages without types (`affine`, `fiona`, `geopandas`,
     `pandas`, `psutil`, `pyflwdir`, `rasterio`, `scipy`, `shapely`, `yaml`) are per-module
     `ignore_missing_imports` overrides, not a global switch; Hydrolog, Kartograf and IMGWTools
     ship `py.typed` at the pinned heads (DEV-7.4), so their calls are checked;
     `tests.*` allows untyped definitions and calls and does not check the bodies of
     untyped functions (`check_untyped_defs = false`, about 1,260 unannotated tests);
     `scripts.*` allows untyped definitions and calls (46 findings) and its annotated code is
     checked. To lift an override, annotate the module and delete its line in `pyproject.toml`.
   - **Coverage** (DEV-7.5) is done: `fail_under` is 80 and the offline suite covers 85% of
     `api`, `core`, `models` and `utils` (`scripts/`, `migrations/` and `tests/` are omitted
     from the measure). Modules still below 75%: `core/watershed_service.py` 53%,
     `core/catchment_graph.py` 60%, `core/raster_io.py` 67%, `api/endpoints/hydrograph.py`
     and `watershed.py` 70%; most of what is missing is PostGIS SQL that only the `db` job
     runs.
   - **Translations** to English (DEV-2.1, ECO-005). Done: ARCHITECTURE, PRD, SCOPE,
     BACKLOG, TECHNICAL_DEBT, CROSS_PROJECT_ANALYSIS, `docs/integrations/KARTOGRAF.md`,
     `backend/scripts/README.md` and the [Unreleased] section of the CHANGELOG (sections as
     DOC-7.1). Still Polish, most useful first: DECISIONS (the bodies of ADR-001 to ADR-057,
     kept as records; the index and ADR-058 on are English), DATA_MODEL (nothing in it
     describes the Kartograf layout: a translation only), COMPUTATION_PIPELINE (its sections
     5.1 and 5.3 are English), `docs/integrations/HYDROLOG.md` and `IMGWTOOLS.md` (now `OBSERWATOR.md`; their pins
     are English), BENCHMARK_QUERIES, the released versions of the CHANGELOG (0.4.0 and
     older, records); QA_REPORT is English.
     After the documents: docstrings, comments and log messages of the 23,700 lines of
     Python, and user-facing texts into translation resources (DEV-2.3, DEV-15.2). The 40
     plans of the ignored `notes/superpowers/plans/` move to `docs/plans/` after
     translation, without `Approved:` lines (the author approves). The links of the ADR
     index in `docs/DECISIONS.md` follow the headings of ADR-001 to ADR-057; translating a
     heading means regenerating its link.
   - **Error registry and REST: loose ends.** Done: registry, `HydrografError`, the catalogue
     of 45 messages, problem documents, `Accept-Language`, OpenAPI ids, contract tests.
     Left: `frontend/js/admin/admin-sewer.js` (5 `fetch` calls) does not send
     `Accept-Language` yet; the admin operations document `401` only, so `404` and `409` of
     `bootstrap/start`, `bootstrap/cancel` and the feedback routes are undocumented; the 429
     of nginx (`limit_req`) and its gateway errors are plain responses, and an `error_page`
     that returns a problem document would close AGI-6.3; the validation texts in `errors[]`
     are pydantic's English; the texts of core exceptions that reach `details.cause`
     (`invalid_parameters`, `invalid_bbox`, `invalid_boundary_file`) are whatever the
     library said.
   - **Other gaps found**, not in scope of a step: logs use f-strings (DEV-12.3), 60 lines of
     JavaScript are longer than 100 columns and the modules are IIFEs, not ES modules
     (DEV-15.1), the front end has Polish text inline (DEV-15.2), `tests/performance` stands
     beside the standard tree (DEV-5.2). Deviations are recorded in CLAUDE.md. Found by mypy:
     `scripts/analyze_watershed.py` imported `find_nearest_stream` and `traverse_upstream` from
     `core.watershed`, which has neither, so its delineation (step 3) failed at run time; fixed:
     step 3 calls the route function of `POST /api/delineate-watershed` (precomputed mode), step 4
     takes the morphometry from it, and `tests/unit/test_analyze_watershed_delineate.py` runs the
     steps on a synthetic graph offline. `FlowCell`, `build_boundary`,
     `build_boundary_polygonize`, `calculate_watershed_area_km2` (all of `core/watershed.py`,
     deleted with the module) and the cell functions of `core/morphometry.py`
     (`build_morphometric_params`, `find_main_stream` and the like) had no caller outside
     their tests and are deleted with those tests, together with the constants
     `MAX_WATERSHED_CELLS` and `MAX_STREAM_DISTANCE_M`; `core/morphometry.py` keeps
     `calculate_shape_indices`. The main stream of the API path (the catchment-graph route) is
     determined by `CatchmentGraph.trace_main_channel()` in `core/catchment_graph.py`, called from
     `build_morph_dict_from_graph()` in `core/watershed_service.py` (the route
     `POST /api/delineate-watershed` and `scripts/analyze_watershed.py` step 3 both use it). The
     calls of `process_dem` in `prepare_area.py` and `analyze_watershed.py` that passed parameters
     it had lost (`batch_size`, `stream_threshold`) are fixed and tested
     (`tests/unit/test_process_dem_callers.py`).
     Found by the tests of `load_bdot_streams_from_gpkg` (`core/db_bulk.py`), not fixed: a
     feature with an empty name column gets the name `'nan'` (a pandas NaN is truthy), and a
     feature without geometry stops the load (`row.geometry` is NaN, so `.is_empty` fails).
2. **Migrate to the producers' heads** (Nogat plans `2026-10-24-data-output.md` step 8 and
   `2026-10-20-first-release-set.md` step 8; ADOPTION_PLAN 5.1). Done on `feature/producer-heads`
   (ADR-060, ADR-061): Hydrolog, IMGWTools and Kartograf, below. The method: pin the producer's
   commit while its tag is missing (REL-5.3), migrate, run the suite, then pin the tags: when a
   tag exists replace the `rev` in `[tool.uv.sources]` by it, narrow the range of `dependencies`
   (REL-5.6), run `uv lock` and the gate, and repeat the comparisons described below.
   - **IMGWTools: done on `feature/producer-heads`** (ADR-060, pinned `71bae77`, 3.0.0).
     `fetch_pmaxtp(latitude, longitude, *, method='POT', timeout=30.0, validate_coords=True)` keeps
     its model (`result.data.get_precipitation(...)`, `ks`, `sg`, `rb`); `method` became
     keyword-only, and Hydrograf passes only `latitude=` and `longitude=`. Both call sites
     (`scripts/preprocess_precipitation.py::fetch_pmaxtp_for_point` and
     `scripts/analyze_watershed.py::fetch_precipitation_imgw`) ran offline against the real
     parsing, with a canned PMAXTP answer in place of the HTTP call: 432 scenarios without a gap,
     the nearest duration and a fractional probability. They catch only `IMGWConnectionError`,
     `IMGWDataError` and `IMGWValidationError`, and `tests/unit/test_imgw_call_sites.py` runs both
     through the real library with an `httpx.MockTransport` answer (`serve_imgw` in
     `tests/conftest.py`), also for the errors that must surface. Renames in IMGWTools that
     Hydrograf does not use: `IMGW_STORE_ROOT` is `IMGW_ROOT`, `IMGW_DATA_DIR` is
     `IMGW_REFERENCE_DIR`, store and export options are `root`, `output_dir`, `output`.
     Hydrograf's own settings `IMGW_GRID_SPACING_KM` and `IMGW_RATE_LIMIT_DELAY_S`
     (`core/config.py`, `.env.example`) share the `IMGW_` prefix of IMGWTools, which ignores the
     names it does not know. IMGWTools ships `py.typed`, so mypy checks the call. Its probability
     parameter was annotated `int` while the keys are `str(percent)` and Hydrograf asks for 0.01 to
     98.5 (a `type: ignore` in `scripts/preprocess_precipitation.py`): IMGWTools took the request
     (`277f68d`: a `float`, one of the 27 published percentages, else `IMGWValidationError` with
     the allowed list) and the pin moved to its head, so the `type: ignore` is gone.
   - **Hydrolog: done on `feature/producer-heads`** (ADR-060, pinned `2a5ba1a`, 1.0.0.dev0, the
     head of `feature/routing-schematic`, which stacks `chore/nogat-2.1` and `feature/routing-*`).
     The imports resolve and the offline suite passed unchanged at the first pin `28be47d` (1,362
     tests): no test pinned a number that changed. The commits after it add the network objects
     (ADR-0012, `5ae6d49`) and the network schematic (ADR-0013, `2a5ba1a`), which nothing in
     Hydrograf calls; the gate is green at `2a5ba1a` too. mypy
     checks the calls now (Hydrolog ships `py.typed`): three errors in
     `api/endpoints/hydrograph.py` and two in `scripts/analyze_watershed.py`, fixed. The real
     endpoint (`generate_hydrograph` on the fast path with `morphometry`, only the precipitation
     lookup replaced) ran on 0.6.3 and on `28be47d` over 138 combinations (three catchments, six
     concentration-time methods, three hyetograph types, the SCS and Snyder models and the three
     Nash estimations): every `tc_min` is the same (`_calculate_tc` forces the mean slope for NRCS
     and calls `ConcentrationTime.faa|kerby|kerby_kirpich` itself, so the changes of
     `calculate_tc` do not reach the API), the SCS and Nash hydrographs are the same, and the
     Snyder hydrograph differs: the peak is 11 to 12% higher and comes 25 to 70 minutes earlier at
     a time step of 5 minutes, the volume is the same (the duration correction of Snyder;
     CHANGELOG, breaking for API clients). `scripts/analyze_watershed.py` offers `nrcs` instead of
     `scs`, which Hydrolog never accepted. The CLI of Hydrolog changed (catalog,
     `hydrolog-result/1`, exit codes 13 for `calculation_error` and 12 for `forbidden`); Hydrograf
     uses the library only. Routing (`route lag|cascade|level-pool|muskingum|muskingum-cunge|
     network`, ADR-0007 to ADR-0010) is in the pinned head; nothing calls it, an option for the
     sewer and Hydraulik work. Closed 2026-11-05: the REST option `nash_estimation: "from_tc"`
     (it called `NashIUH.from_tc`, which the changelog of Hydrolog announces for removal in
     1.0.0) is removed: Open questions 5.
   - **Kartograf: done on `feature/producer-heads`** (ADR-061, pinned `eab8612` since the merge of
     2026-11-02, 0.8.0.dev0, Kartograf branch `feature/archiwista-projects`; the branch had `d11f621`).
     Every call is migrated and every migrated call runs against the real Kartograf in the tests
     (`tests/kartograf_offline.py` stubs only the provider classes: the GUGiK sheet index, BDOT10k
     and SoilGrids; `kartograf.testing` builds the stores the tests read). The cache of raw downloads
     is the store `cache/kartograf/` (NMT, BDOT10k, the HSG raster of Poland), the metadata cache is
     `cache/kartograf_meta.db`, the HSG raster of one CN calculation is a plain temporary file.
     Measured on the real library with a stubbed index: a plain directory drops a sheet that has only
     a partial flight, takes an older full flight for a sheet whose newest flight is partial, and
     refuses a second run (`conflict`, `output_exists`); the store keeps both and answers `local`.
     The documents that describe the layout and the API are rewritten in English (Status, Data
     output). Not run: a real download of the NMT, BDOT10k and SoilGrids (no network test in the
     offline suite), `bootstrap` end to end, the Docker image. Known defect that the documents
     state: no script passes `building_gpkg`, so building raising (ADR-033) does not run in the
     pipeline; ADR-033 makes the parameter optional, so it is a backlog item for the author
     ([BACKLOG.md](BACKLOG.md), Bugs and diagnoses).
   - **Hydraulik** (`depends_on`, planned): integration halted by the author (session 99);
     nothing to migrate.
3. **Engineering items with the highest priority** from the former backlog (all of it:
   [BACKLOG.md](BACKLOG.md)): the hardening of the public attack surface, starting with three
   unauthenticated denial-of-service paths (precise delineation without an area limit, XYZ
   tiles without zoom validation, tile routes without a zoom floor and `statement_timeout`;
   spec `notes/superpowers/specs/2026-08-08-public-security-hardening-spec.md`, outside the
   repository); the hyetograph and hydrograph "no data" bug from the tester's feedback; the
   hardcoded accumulation thresholds in `scripts/bootstrap.py` (`--thresholds`); the
   decision on the NMT versioning ADR (superseded in part by Kartograf's store); hardcoded
   secrets in `core/config.py` and `migrations/env.py`.

### Open questions (z gałęzi PH)

1. D5 and D6 of session 97: the HSG fallback "B" and step 5 as non-critical (a failed step 5
   still ends bootstrap with exit 0); data of the 0.6.1 layout are not reused.
2. GDAL's Python binding stays outside `uv.lock` because it must equal the system library of
   the image: accept as a deviation of DEV-6.3, or install `gdal-bin` and drop the pip build
   (`generate_dem_tiles.py` runs `gdal2tiles.py`).
3. Merge of `feature/kartograf-wykorzystanie` and `chore/nogat-2.1` into `develop`: order and
   who resolves PROGRESS, CHANGELOG and `requirements.txt`.
4. Text of `docs/CLA.md` and how the CLA is signed. `CONTRIBUTING.md` describes signing by a
   comment on the pull request, as in Retman and Archiwista, and the template has the
   checkbox; both name `docs/CLA.md`, which does not exist yet.
5. ✅ (2026-11-05, `fix/remove-nash-from-tc`, author's decision) `nash_estimation: "from_tc"` of
   `POST /api/generate-hydrograph` (it called `NashIUH.from_tc`, deprecated since Hydrolog 0.6.2
   and announced for removal in 1.0.0), the request field `nash_n` and the front-end choice are
   removed; a request with `from_tc` gets 400 `validation_error`.

## Ostatnia sesja

**Data:** 2026-11-02 (krok S1 planu `docs/plans/2026-11-02-store-migration.md`: scalenie `feature/producer-heads` do `feature/store-migration`, konflikty, piny, bramka offline)

### Co zrobiono
- **Scalenie** w worktree `~/workspace/Hydrograf-store` (gałąź `feature/store-migration` = `feature/visual-identity` `08d8190` + plan `1085641`): `git merge --no-ff feature/producer-heads` (`f9d2118`) → `dcae5be`. 18 konfliktów rozstrzygniętych wg tabeli planu (szczegóły w komunikacie commita): `watershed.py` szkielet PH + podgląd zlewni VI (błędy z rejestru, nowy komunikat `delineation_preview_failed`); `hydrograph.py` typy i błędy Hydrologa 1.0 + AMC i własna seria opadu (hietogram PMAXTP rzuca `InvalidRequestError`, `_design_storm` zawęża typy dla mypy); `profile.py` `ProfileWaterLevel` + `NoDataError`; `main.py` typowany middleware PH z request-id i logowaniem żądań VI; `morphometry.py` wersja PH; `test_profile.py` testy poziomów wody VI z testem 422 przepisanym na 400 problem+json; `.env.example` PH + `FRONTEND_DATA_DIR`; `ci.yml` CI Nogata + zadanie `frontend-assets` (akcje po SHA); `.pre-commit-config.yaml` usunięty (sprawdzenie `?v=` jest krokiem `scripts/gate.sh` i zadaniem CI); `api.js` `apiFetch` + `result_ids` + komunikaty z problem+json; dokumenty jak w sekcji gałęzi PH wyżej.
- **Kod VI pod bramkę PH:** `/api/layers` i `get_catchment_levels_feature_collection` z typami, docstringi walidatorów (D102), `ruff format` 5 plików; testy VI dostosowane, nie kasowane (`test_missing_threshold_returns_422`, `test_invalid_series_returns_422`, `test_too_many_result_ids_returns_422` → warianty `_400` z asercjami problem+json). Jedyny usunięty test to `test_nodata_uses_approximate_comparison` (sprawdzał tekst źródła; usunięty już na VI).
- **Frontend:** `js/api.js` bierze komunikat z problem+json: przy błędzie walidacji polski tekst walidatora z `errors[]` (bez „Value error, ”), inaczej `detail`, przy błędzie klienta z `hint`; strona błędu nginx → stałe teksty; `GET /api/layers` i podgląd zlewni też wysyłają `Accept-Language: pl`. Sprawdzone skryptem Bun z atrapą `fetch` (404 z podpowiedzią, 400 walidatora i wbudowany, 500, 502 HTML). `js/admin/admin-sewer.js` wysyła `Accept-Language: pl` (`ceed7ef`). Wersje `?v=` przeliczone.
- **Piny:** Kartograf `eab8612` (jak Archiwista), `uv lock` zmienił tylko kartograf; w `uv.lock` affine 2.4.0 i pyflwdir 0.5.12; Hydrolog `2a5ba1a` i IMGWTools `71bae77` bez zmian. Erraty ADR-060/061, `integrations/KARTOGRAF.md`, `CROSS_PROJECT_ANALYSIS.md` (`9389ede`).
- **Bramka offline zielona** (`bash scripts/gate.sh`, `uv sync --locked --all-extras` w `backend/.venv` worktree): ruff format i ruff check czyste, mypy strict czysty (167 plików), pytest 1351 passed, 19 deselected (`db` i `benchmark`), pokrycie 86,52% (próg 80), wersje zasobów aktualne, krok commitów zielony. `python3 scripts/bump_asset_versions.py --check` zielony. Liczba testów: PH ma 1302 testy offline (1360 w PROGRESS PH to stan sprzed `bde9bc2`, który usunął testy martwego kodu); po scaleniu 1351 = 1302 − 1 (test tekstu źródła) + 45 testów VI + 3 przepisane testy VI + 2 przypadki kontraktu OpenAPI dla nowych tras VI.
- Produkcja nietknięta: checkout `~/workspace/Hydrograf` na `08d8190`, `git status --short` jak przed sesją (`?? .claude/`); bez Dockera.

### W trakcie
- Nic. Nieuruchomione w S1 (z założenia, krok S2): 19 testów z PostGIS (11 `db`, 8 `benchmark`), obraz Dockera, smoke API i frontendu w przeglądarce, prawdziwe pobieranie Kartografa.

### Następne kroki
- S2 planu: pliki stagingu (`docker-compose.staging.yml`, `scripts/staging-compose.sh`, `.env.staging` w `.gitignore`), K0, obraz `hydrograf-api:store-staging` po K1, testy `db` na jednorazowej bazie, smoke API (Snyder, problem+json, `water_levels`) i frontendu na 8081.
- Push i kolejność scaleń tylko za zgodą autora.

### Poprawki interfejsu z uwag testerów, przed S3 (gałąź `feature/store-ui`, worktree `~/workspace/Hydrograf-store-ui`, 2026-11-02)
- **Zoom kółkiem nie zatrzymywał się po przestaniu kręcenia** (`js/map.js`). Odtworzone w Chromium (atrapa serwera statycznego worktree, zdarzenia `wheel` syntetyczne i przez CDP): (1) Leaflet zamienia każdą 40-ms paczkę zdarzeń na co najmniej cały poziom (`zoomSnap` 1, sigmoida zaokrąglana w górę), a touchpad, Magic Mouse i sterowniki płynnego przewijania wysyłają po zatrzymaniu wygasający ogon małych zdarzeń: muśnięcie na 1 poziom dawało 4–7 poziomów w 1–2 s; (2) po każdym kroku MapLibre przerysowuje podkład wektorowy, strona jest zajęta, kolejka zdarzeń i timer zoomu czekają i przybliżają (często o kilka poziomów naraz) już po zatrzymaniu kółka (programowy WebGL: 8 ząbków → zoom jeszcze 1,1 s, muśnięcie → 3,4 s). Poprawka: `wheelZoomHandler` = `ScrollWheelZoom` Leafletu z dwoma strażnikami (ogon gestu < 0,5 najsilniejszego zdarzenia ignorowany, przerwa 80 ms lub zmiana kierunku = nowy gest; wejście starsze niż 150 ms nie zaczyna kroku). Kółko z ząbkami bez zmian. Dowody: `~/scratch/store-ui/ui/wheel-evidence.txt`, `wheel-before.json`, `wheel-after.json`, skrypt `wheel-lab.js`.
- **Objaśnienia (i) tylko po kliknięciu/dotknięciu** (`js/info.js`, `css/app.css`): Enter/spacja na przycisku, zamykanie tym samym (i), Esc, kliknięciem obok i przejściem fokusu do innego pola; bez otwierania po najechaniu i fokusie; `aria-expanded`/`aria-controls`.
- **„Próg akumulacji spływu”** zamiast „Próg FA” (`js/layers.js`): ha poniżej 1 km², km² od 1 km² (`Hydrograf.layers.formatThreshold`), także w komunikacie o zmianie progu przy wyznaczaniu (`js/app.js`); API bez zmian (m²).
- **Szyna Mapa · Instrukcja · Logowanie na każdej stronie** (`index.html`, `admin.html`, `instrukcja/index.html`, `css/chrome.css`, `js/welcome.js`): „Instrukcja” przeniesiona z górnego paska (na stronie mapy nadal otwiera okno powitalne), „Administracja” → „Logowanie”.
- **„Usługi działają” tylko w `/admin`** (`js/admin/admin-app.js`, `js/admin/admin-api.js`): z `GET /health` od otwarcia strony, potem z dashboardu; teksty po polsku zamiast „Healthy/Unhealthy”. Ze strony mapy usunięte: plakietka, „Ponów”, `checkHealth`.
- Instrukcja i prezentacja HTML: slajdy 8, 12, 19, 26 i 29; zrzut telefonu (slajd 29) z nowym górnym i dolnym paskiem wklejonym z bieżącego interfejsu. `docs/ARCHITECTURE.md` 2.8, `docs/CHANGELOG.md`.
- Produkcja nietknięta (bez Dockera; serwery deweloperskie na portach 18765/18766 z atrapami API).
- Następne: PDF prezentacji nieprzegenerowany (po scaleniu z `feature/store-identify`, która też zmienia prezentację); zrzuty slajdów 10 i 13 mają na krawędzi ścinki starej szyny i górnego paska (do podmiany przy nowych zrzutach po S3); mapa wyboru bbox w `/admin` ma domyślne kółko Leafleta (`docs/BACKLOG.md`).

### Tryb „Identyfikuj” (2026-11-02, gałąź `feature/store-identify`, pozycja 6 uwag testerów przed S3)
- [x] **Tryb identyfikacji punktu:** `GET /api/identify-point` (parametry zapytania `latitude`, `longitude`, `threshold_m2`, powtarzane `result_ids`; do 2026-11-02 przed wydaniem `POST` z ciałem JSON) (`api/endpoints/identify.py`, `core/point_info.py`, modele w `models/schemas.py`, komunikaty `no_data_at_point`, `identify_failed`) i czwarty przycisk „Identyfikuj” z kartą „Informacje o punkcie” (`js/identify.js`); współrzędne WGS84/PL-1992 z kopiowaniem, rzędna i spadek z NMT, głębokość i zwierciadło wody włączonych wyników, ciek BDOT10k do 25 m, wody powierzchniowe z `bdot_lakes.geojson` (nie ma ich w bazie), pokrycie terenu z CN, HSG, zagłębienie, zlewnia cząstkowa. Poza NMT 404 `no_data`. Instrukcja i prezentacja: slajd 9 „Cztery tryby pracy”, nowy `Hydrograf-tryby.png`; PDF prezentacji nie regenerowany.
- Testy: 14 jednostkowych (`test_point_info.py`), 20 integracyjnych endpointu offline (`test_identify_point.py`, w tym walidacja parametrów zapytania i 405 dla `POST`), 5 testów SQL z markerem `db` (`test_identify_point_db.py`) do uruchomienia w S2 na PostGIS. Smoke: API i przeglądarka na kopii danych (NMT, SFINCS, BDOT10k), baza zastąpiona atrapą; zrzuty w `~/scratch/store-ui/identify/`.

### Scalenie uwag testerów 1–6 do `feature/store-migration` (2026-11-02, przed S3)
- `4f4163b` scalenie `feature/store-ui` (bez konfliktów), `db71226` scalenie `feature/store-identify` (konflikt tylko w hashach `?v=` w `frontend/index.html`; `scripts/bump_asset_versions.py`). PDF prezentacji wydrukowany raz po scaleniu (30 slajdów 16:9). Bramka offline zielona (1381 testów, pokrycie 86,64%), smoke w Chromium na serwerze statycznym z atrapami API; szczegóły w „Wynikach” planu `docs/plans/2026-11-02-store-migration.md`, zrzuty w `~/scratch/store-ui/landing/`.
- Następne: zrzuty slajdów 8 i 29 (pasek z trzema trybami) oraz 10 i 13 do podmiany po S3; S2 planu.

### Krok S2 planu: zielony stos na kopii produkcji (2026-11-02)
- **Stos `hydrograf-staging` na 127.0.0.1:8081** z `scripts/staging-compose.sh` (`491daec`): obraz `hydrograf-api:store-staging` (`sha256:ce03f2f4f201…`, 1,94 GB; kartograf 0.8.0.dev0 `eab8612`, hydrolog 1.0.0.dev0 `2a5ba1a`, imgwtools 3.0.0 `71bae77`, affine 2.4.0, pyflwdir 0.5.12), baza `hydro_staging_db` z świeżego `pg_dump` produkcji (12 tabel z równymi liczbami wierszy, `alembic current` = `003`), dane zestawu `copy` skopiowane `cp -a` do `/data/nmt/hydrograf-staging/copy/` (liczby plików i rozmiary równe źródłu). Limity: db 1,5 GB/1 CPU, api 3 GB/2 CPU.
- **Testy `db`** na jednorazowej `hydro_staging_testdb`: 15 zaliczonych, 1 pominięty (`test_st_contains_vs_production_data` potrzebuje zlewni progu 1000, których produkcja nie ma), w tym 5 testów SQL trybu „Identyfikuj”.
- **Smoke: te same żądania do produkcji (8080) i stagingu (8081)** — do produkcji tylko GET i obliczeniowe POST; zgłoszenie (`[staging-smoke]`, usunięte) i admin z kluczem tylko w stagingu. Hydrogramy: p = 1%, Beta 2/5, AMC II, morfometria z delineacji tego samego serwera (jak w interfejsie); zlewnie 15,16 km² (51,0376/16,1723), 37,23 km² (przekrój Kamiennika, 51,01538/15,890496) i 134,97 km² (punkt 51,01544/15,88984 trafia w zlewnię Kaczawy).

| Obszar | Produkcja 8080 | Staging 8081 | Ocena |
|---|---|---|---|
| `/health`, `/api/scenarios`, `/api/tiles/thresholds`, `/api/layers` | 200 | 200, ten sam JSON | równe |
| 21 plików statycznych: `results/index.json`, `wse_max.tif`, `max_depth.tif`, kafle wyniku, `.pbf`, `dem_tiles`, `bdot_*.geojson`, `soil_hsg.geojson`, PNG nakładek | 200 | 200, te same SHA-256 | równe |
| Kafle MVT `streams`, `catchments` (progi 10000 i 100000), `landcover`; z12 i z14 | 200 | 200, te same obiekty; rozmiar −472…+18 B | równe (kolejność obiektów w kafelku; rozmiar produkcji też się zmienia między wywołaniami) |
| `/api/depressions` (dwa filtry) | 500 i 115 obiektów | to samo | równe |
| Delineacja 51,0376/16,1723, progi 100000 i 10000 | 15,16 km², CN 70,5 | ta sama odpowiedź | równe |
| Przekrój Kamiennika, progi 100000 i 10000 | 37,23 km², CN 67,9, ujście 51,01544/15,88984 | ta sama odpowiedź | równe |
| Podgląd zlewni (69, 718, 209 odcinków) | 200 | te same wielokąty; przy 209 inna kolejność w MultiPolygon | równe |
| Hydrogram SCS-CN i Nash, 3 zlewnie × 1 h i 24 h | — | Q, tp i V identyczne (12 przypadków) | równe |
| Snyder, 1 h | Q 1,898 / 3,599 / 11,755 m³/s; tp 385 / 420 / 565 min | 2,123 / 4,028 / 13,194 m³/s; 345 / 375 / 500 min | oczekiwane (ADR-060): +11,9–12,2%, 40–65 min wcześniej, V równe |
| Snyder, 24 h | Q 14,517 / 38,825 / 122,551 m³/s; tp 940 / 975 / 1125 min | 15,309 / 41,150 / 132,126 m³/s; 895 / 925 / 1060 min | oczekiwane co do kierunku: +5,5–7,8% (ADR-060 podaje 11–12% dla krótszych opadów), 45–65 min wcześniej, V równe |
| Profil przez czaszę zbiornika z `result_ids` | zwierciadło 277,48 m n.p.m., 323 próbki mokre, gł. maks. 12,6 m | ta sama odpowiedź | równe (wynik 12 h `sfincs-kamiennik-12h-p1`; obecny wynik 24 h `sfincs-kamiennik-24h-p1`: zwierciadło 281,43 m) |
| Błędy: punkt poza granicą (delineacja, hydrogram), profil poza NMT | 404 `application/json`, `{"detail": …}` | 404 `application/problem+json` (`type`, `title`, `status`, `detail`, `code`, `hint`) | oczekiwane (ADR-059) |
| Walidacja (szerokość 200, hydrogram bez `duration`) | 422, lista błędów pydantic | 400 problem+json z `errors[]` | oczekiwane |
| Admin bez klucza | 401 `application/json` | 401 problem+json | oczekiwane |
| `POST /api/identify-point` | 404 (brak trasy) | 200: czasza 4,04 m i 12,6 m wody, zwierciadło 277,48 m (wynik 12 h; z wynikiem 24 h: 16,55 m wody, 281,43 m); poza danymi 404 problem+json po polsku | nowa funkcja (uwaga 6) |
| Admin z kluczem stagingu: 6 GET, zgłoszenie `[staging-smoke]` | — | 200; wiersz id 14 dodany, widoczny i usunięty | OK |
| Komunikat w panelu po kliknięciu poza granicą | „… w tym punkcie. Kliknij w obszarze pokrytym liniami spływu.” | „… w tym miejscu. Kliknij w obszarze zlewni.” (`detail` + `hint`) | oczekiwane |
| Kółko: zdarzenia syntetyczne od poziomu 10, bez podkładu, 3 powtórzenia | muśnięcia z ogonem → 14 / 15 / 17, przeciągnięcie 1 s → 16–17, ząbki 5 × 120 ms → 12 | → 11 / 11 / 11 (koniec po ok. 0,3 s), → 12, → 12 | oczekiwane (uwaga 1) |
| Objaśnienie (i) | otwiera się po najechaniu | tylko po kliknięciu, Esc zamyka | oczekiwane (uwaga 2) |
| Próg linii spływu | „Próg FA” 10 000 / 100 000 m² | „Próg akumulacji spływu” 1 ha / 10 ha | oczekiwane (uwaga 3) |
| Szyna | Mapa · Administracja, „Instrukcja” w górnym pasku | Mapa · Instrukcja · Logowanie na mapie, w `/instrukcja/` i `/admin`; telefon: dolny pasek | oczekiwane (uwaga 4) |
| Status usług | plakietka „Usługi działają” na mapie | tylko w `/admin` (ekran logowania i panel) | oczekiwane (uwaga 5) |
| Warstwy, SFINCS z legendą i kryciem, MZP (`wody.isok.gov.pl` 200), profil z wodą, ekran powitalny, instrukcja, `?v=`, błędy JS | działa, 0 błędów | działa, 0 błędów; te same 404 kafli poza zasięgiem danych | równe |
| Nazwa cieku w karcie punktu | — | „nan (rów)” zamiast „bez nazwy (rów)” | **nieoczekiwane**, niżej |

- **Otwarte:**
  - „nan” w karcie punktu: 3436 z 3812 wierszy `bdot_streams` ma `name = 'nan'` (w produkcji też, ale tam nazwy nic nie pokazuje). Przyczyna: `core/db_bulk.py` `load_bdot_streams_from_gpkg` sprawdza `if row[col]`, a NaN to prawda, więc zapisuje `str(NaN)`. Poprawka do decyzji przed S3/S5: loader z `pd.notna` plus dane (`NULLIF(name, 'nan')` albo ponowny import); można też dodać osłonę w `core/point_info.py`;
  - Snyder przy opadzie 24 h odbiega od zakresu z ADR-060 (+5,5–7,8% zamiast 11–12%); kierunek i przesunięcie się zgadzają;
  - „Głębokość przy zaporze 12,33 m” z 2026-11-01 to odczyt kursora na innej linii; linia przez najgłębszą komórkę NMT (264,88 m n.p.m.) daje 12,6 m, w produkcji tak samo.
- **Następne kroki:** S3 planu (K1 spełnione; nie rozpoczęte), potem punkt kontrolny autora S4. Szczegóły i K0 są w „Wynikach” planu.

### Krok S3 planu: bootstrap Kamiennika do magazynu Kartografa i porównanie (2026-11-02)
- **Zestaw `s3`:** baza `hydro_s3` (PostGIS, migracje 001 → 003 z entrypointu), katalogi `/data/nmt/hydrograf-staging/s3/`, granica `kamiennik_37km2_sfincs.gpkg` skopiowana z produkcji (37,2234 km²).
- **Bootstrap** `run --rm --no-deps --name hydro_staging_bootstrap_s3 api python -m scripts.bootstrap --boundary-file /data/boundary/kamiennik_37km2_sfincs.gpkg --cache-dir /cache --skip-infra --skip-serve` (z `HYDROGRAF_STAGING_SET=s3 HYDROGRAF_STAGING_DB=hydro_s3`; dodane tylko `-T` i `PYTHONUNBUFFERED=1` dla kolejności logu): kod 0, 372,4 s, szczyt pamięci 2,09 GiB przy limicie 3 GiB (krok 5, HSG z rastra Polski: 1,45 GiB pamięci anonimowej), swap 0. Kroki: NMT 15/15 arkuszy 27,4 s; przetwarzanie NMT 210,6 s (3 048 412 komórek, 4437 odcinków); pokrycie terenu 4,8 s (18 305 obiektów, powiaty 0205 i 0226); HSG 41,0 s; opady 31,7 s (24 punkty); depresje 2,3 s (13 173); kafle MVT 36,4 s; nakładki 18,1 s. Logi i próbki cgroup: `/data/nmt/hydrograf-staging/bootstrap-s3-20261102*`.
- **Magazyn** `/data/nmt/hydrograf-staging/cache/kartograf` (256 MB): znacznik `kartograf-store/1`; segmenty NMT 5 m (15 arkuszy = lista z logu kroku 2), BDOT10k 0205 i 0226, HSG `0-5cm` i trzy warstwy SoilGrids; 57 sidecarów `kartograf-meta/1` z SHA-256 zgodnym z plikami; `kartograf_meta.db` obok magazynu; brak starego układu `cache/nmt|bdot10k|soil_hsg`. **Niezgodność:** 15 plików `<arkusz>.prj` obok arkuszy NMT (`missing_sidecar` w `iter_store`) zapisuje Hydrograf (`utils/raster_utils.py`, `_ensure_prj_sidecar`) — obcy plik w magazynie (ADR-061), do decyzji przed S5.
- **Wyjścia:** wszystkie tabele niepuste (`stream_network` 4421, `stream_catchments` 4437, `land_cover` 18 305, `soil_hsg` 1, `precipitation_data` 10 368, `depressions` 13 173); NMT, `land_cover` i `soil_hsg` pokrywają granicę w 100%; kafle MVT, `dem_tiles`, nakładki PNG i GeoJSON wygenerowane.
- **Porównanie:** produkcja 8080 (stary kod, stare dane), `copy` 8081 (nowy kod, stare dane) i `s3` (nowy kod, dane z magazynu; API w `hydro_staging_api_s3` bez portu, przez `docker exec`, po porównaniu usunięty). Punkty: wyświetlane ujście Kamiennika, punkt na odcinku 21911/2477 i punkty delineacji przekrojów K1–T3 z `cross_sections.gpkg`. Hydrogramy: 12 h, p = 1%, AMC II, Beta 2/5, tc NRCS, Nash `from_lutz`, Snyder Ct 1,5 / Cp 0,6, morfometria z delineacji tego samego serwera.

| Punkt (próg) | Pow. prod / copy / s3 [km²] | Δ s3–prod | CN prod / copy / s3 | IoU prod–copy / prod–s3 | Ocena |
|---|---|---|---|---|---|
| Ujście wyświetlane 51,015442/15,889836 (10 ha i 1 ha) | 134,97 / 134,97 / 40,22 | −70,2% | 69,6 / 69,6 / 68,6 | 1,000 / 0,298 | efekt krawędzi obszaru `s3` (Kaczawa ucięta na arkuszach Kamiennika) |
| Ujście, odcinek 21911/2477 (10 ha i 1 ha) | 37,23 / 37,23 / 37,23 | 0,0% | 67,9 / 67,9 / 67,9 | 1,000 / 1,000 | OK |
| K1 | 29,35 / 29,35 / 29,35 | 0,0% | 67,3 / 67,3 / 67,3 | 1,000 / 1,000 | OK |
| K2 | 18,71 / 18,71 / 18,71 | 0,0% | 65,4 / 65,4 / 65,4 | 1,000 / 1,000 | OK |
| K3 | 15,53 / 15,53 / 15,53 | 0,0% | 64,7 / 64,7 / 64,7 | 1,000 / 1,000 | OK |
| K4 | 10,06 / 10,06 / 10,06 | 0,0% | 66,4 / 66,4 / 66,4 | 1,000 / 1,000 | OK |
| C1 | 8,67 / 8,67 / 8,67 | 0,0% | 69,3 / 69,3 / 69,3 | 1,000 / 1,000 | OK |
| T2 | 3,96 / 3,96 / 3,96 | 0,0% | 68,2 / 68,2 / 68,2 | 1,000 / 1,000 | OK |
| T3 | 2,43 / 2,43 / 2,43 | 0,0% | 65,0 / 65,0 / 65,0 | 1,000 / 1,000 | OK |

| Punkt | P prod / s3 [mm] | SCS Q prod = copy → s3 [m³/s] | Nash Q prod = copy → s3 [m³/s] | Snyder prod → copy (efekt kodu) | Snyder s3 względem copy | Ocena |
|---|---|---|---|---|---|---|
| Ujście, odcinek 21911/2477 | 103,07 / 103,19 | 48,32 → 48,44 (+0,3%) | 50,87 → 51,00 (+0,2%) | 29,73 → 32,57 (+9,6%, tp −45 min) | +0,2%, tp 0 | OK |
| K1 | 102,72 / 103,13 | 40,27 → 40,61 (+0,8%) | 44,03 → 44,40 (+0,8%) | 26,68 → 28,95 (+8,5%, −35 min) | +0,8% | OK |
| K2 | 103,06 / 103,08 | 23,61 → 23,62 (+0,1%) | 26,32 → 26,33 (0,0%) | 16,06 → 17,40 (+8,3%, −30 min) | 0,0% | OK |
| K3 | 103,79 / 104,23 | 20,75 → 20,94 (+0,9%) | 23,29 → 23,50 (+0,9%) | 14,82 → 15,90 (+7,3%, −30 min) | +0,9% | OK |
| K4 | 104,21 / 103,36 | 16,21 → 15,94 (−1,7%) | 18,28 → 17,97 (−1,7%) | 12,62 → 13,34 (+5,7%, −20 min) | −1,7% | OK |
| C1 | 102,41 / 103,26 | 13,74 → 13,96 (+1,6%) | 14,53 → 14,77 (+1,6%) | 8,96 → 9,70 (+8,2%, −30 min) | +1,7% | OK |
| T2 | 103,90 / 103,12 | 7,73 → 7,61 (−1,5%) | 8,35 → 8,22 (−1,5%) | 6,44 → 6,67 (+3,6%, −15 min) | −1,5% | OK |
| T3 | 104,10 / 103,31 | 4,34 → 4,27 (−1,6%) | 4,50 → 4,43 (−1,6%) | 3,45 → 3,57 (+3,5%, −15 min) | −1,6% | OK |
| Ujście wyświetlane (inne zlewnie) | 103,04 / 103,19 | 193,18 → 54,73 | 175,92 → 56,74 | 88,66 → 98,27 (+10,8%, −60 min) | — | nie porównywać (134,97 vs 40,22 km²) |

- **Wnioski:** granice, powierzchnie i CN zlewni Kamiennika z magazynu są identyczne z produkcją (te same arkusze i kampanie GUGiK, ten sam BDOT10k do wypalania). Różnice hydrogramów `s3`–`copy` (±1,7%) biorą się wyłącznie z opadu: siatka PMAXTP 2 km w `s3` jest przesunięta o 815 m (jej początek to narożnik bbox obszaru), więc IDW w centroidzie daje ±0,8%. Snyder Hydrologa 1.0 (ADR-060) przy 12 h: +3,5…+9,6% szczytu i 15–45 min wcześniej, objętość równa; zakres 11–12% z planu dotyczy krótkich opadów. Drobna różnica morfometrii: `divide_flow_path_km` przy ujściu 17,59 → 16,04 (w `s3` równa najdłuższej drodze spływu).
- **Smoke w przeglądarce, 8081 z danymi `s3`** (12:54:31–12:57:55, potem powrót na `copy`): warstwy (NMT, BDOT10k, HSG, pokrycie, zagłębienia, linie spływu 1 i 10 ha, SFINCS 24 h, MZP z `wody.isok.gov.pl` 200), (i) tylko kliknięciem, „Próg akumulacji spływu” 1 ha / 10 ha, szyna Mapa · Instrukcja · Logowanie, Identyfikuj w czaszy (264,88 m n.p.m., woda 16,55 m, Kamiennik, HSG B, odcinek 37,11 km²) i na Kamienniku przy K3 (15,53 km²), profil przez czaszę z linią wody, zlewnia w ujściu 37,23 km²; 0 błędów JS. Zrzuty w `~/scratch/store-s3/`.
- **Staging w sieci domowej** (polecenie autora, `aa6758f`): nginx stagingu także na `192.168.88.9:8081`; odtworzony tylko `hydro_staging_nginx`; przez adres LAN 200 z CSP, zasoby, API i kafle działają, 0 błędów JS. Produkcja nadal tylko na 127.0.0.1:8080.
- **Otwarte (do S4):** `.prj` w magazynie; „nan” w karcie punktu odtwarza się na danych z bootstrapu (T2 „nan (rzeka)”, 4410 z 4915 wierszy `bdot_streams` w `hydro_s3`), więc bez poprawki loadera S5 zapisze to samo; wynik SFINCS 12 h zastąpiony na stagingu (`copy` i `s3`) wynikiem 24 h z równoległej sesji.
- K0: pusty diff i `/health` 200 przed każdą czynnością i po niej. Staging po kroku: zestaw `copy` (baza `hydro_db`) na 127.0.0.1:8081 i 192.168.88.9:8081. **Następne kroki:** S4, punkt kontrolny autora.

### Krok S4 planu i przygotowanie S5: dwie poprawki, magazyn wspólny z Archiwistą (2026-11-02)
- **Decyzje autora w S4:** dwie wady z S2/S3 naprawić przed S5; magazyn Kartografa wspólny z publiczną Archiwistą (`~/data/archiwista-public/store`); wiązanie LAN stagingu usunąć po S7 (w planie: krok 2 przełączenia w S7).
- **Pliki `.prj` w magazynie** (`ecc0aae`): `normalize_crs(files, output_dir)` nic nie zapisuje obok arkuszy (`output_dir` wymagany; `_ensure_prj_sidecar` i `_get_epsg2180_wkt` usunięte), CRS mozaiki nadaje `create_vrt_mosaic(target_crs=)`: `gdalbuildvrt -a_srs -allow_projection_difference` (bez flagi GDAL 3.10.3 pomija arkusz o innym lub brakującym CRS) i GeoTIFF zapasowego `rasterio.merge` (kontener nie ma narzędzi GDAL). Z magazynu stagingu usunięte 15 plików `.prj` (`run --rm` jako UID 999): `iter_store` przed 15 × `missing_sidecar`, po 0 problemów.
- **„nan” zamiast braku nazwy** (`2da5b2a`): przy pandas 3 brak `NAZWA` to NaN, a `str(NaN)` dawało `'nan'`; teraz brak i pusta nazwa to `NULL`, nazwy przycięte. GeoJSON-y BDOT10k miały już `null` (nowy test), `land_cover` nie bierze tekstu z GeoPackage. Dla baz sprzed poprawki: `UPDATE bdot_streams SET name = NULL WHERE btrim(name) IN ('', 'nan');` — wykonane w stagingu (`hydro_s3`: 4410 wierszy, `hydro_db` zestawu `copy`: 3436); produkcja nietknięta, S5 zbuduje bazę poprawionym loaderem. Karta punktu na 8081: „Ciek: bez nazwy (rzeka)”, 0 błędów JS.
- **Magazyn wspólny** (`a39e69d`, ADR-066 jako aneks do ADR-061): `HYDROGRAF_KARTOGRAF_ROOT` w `store_dir()` (pusta: prywatny `<cache_dir>/kartograf`; `kartograf_meta.db` zawsze w `<cache_dir>`), czyszczenie cache nie rusza magazynu wspólnego, krok 2 bootstrapu staje przed pierwszym zapisem, gdy w `versions/.incoming` jest wpis zmieniony w ostatnich 10 min (`writes_in_progress`). Kartograf `eab8612` nie ma blokad (wyłączne `os.link`, `os.replace`); reguła: bootstrap tylko wtedy, gdy nie pobiera Archiwista. Testy czyszczą zmienną (`tests/conftest.py`).
- **ACL** (jako właściciel; `setfacl` 2.3.2 z paczki Debiana rozpakowanej bez roota, bo na hoście nie ma `acl` ani sudo): `setfacl -R -m u:999:rwX` i `setfacl -R -d -m u:999:rwX,u:claude-agent:rwX` na `~/data/archiwista-public/store`; 7868 obiektów z `user:999`, domyślne wpisy na 3827 katalogach; rodzice bez zmian (bind mount ich nie przechodzi, sprawdzone jako UID 999). Ograniczenie: paczki BDOT10k Kartograf przenosi z `/tmp` z trybem pliku tymczasowego (maska `---` u Archiwisty, `r--` u Hydrografa); naprawa to ponowne pierwsze `setfacl`.
- **Archiwista:** bez restartu i bez sesji; `GET /` i `/api/v1/session/methods` 200, w `index.sqlite` (tylko odczyt) pierwszy skan po ACL `succeeded`, magazyn `zespol` `available`, 735 wersji, 4 segmenty, te same 2 `stale_incoming`.
- **Staging** (`360e789`): magazyn pod `/kartograf` (`:ro`, `HYDROGRAF_KARTOGRAF_STORE_MODE=rw` tylko dla bootstrapu S5), `HYDROGRAF_KARTOGRAF_ROOT=/kartograf`, `HYDROGRAF_KARTOGRAF_STORE` w `.env.staging`; obraz `hydrograf-api:store-staging` przebudowany (`sha256:2a8b1eb4fc68…`); działający `hydro_staging_api` nieodtworzony. Smoke `run --rm` jako UID 999: `list_segments` = 4 segmenty NMT Archiwisty, `iter_store` 642 `link` / 642 `full_sheet` / 735 `version` / 2 `stale_incoming`, `writes_in_progress` = [], mozaika 2 arkuszy bez `.prj` w EPSG:2180, katalogi arkuszy bez zmian.
- **Bramka:** 1389 testów offline, pokrycie 86,64%; testy `db` na jednorazowej bazie: 15 zaliczonych, 1 pominięty. K0 pusty przed i po każdej czynności.
- **Następne kroki:** S5 (warunki w planie, m.in. brak pobierań w Archiwiście i ≥ 5 GB wolnego na `/`). Szczegóły w „Wynikach” planu.

### Krok H1 planu Nogata: zestaw Archiwisty jako jedyne wejście Kartografa (2026-11-02)
- **Decyzja autora (wariant B, plan Nogata `docs/plans/2026-11-02-archiwista-sets-for-hydrograf.md`, gałąź `plan/archiwista-sets-hydrograf`):** do magazynu wspólnego pisze wyłącznie Archiwista; Hydrograf czyta go tylko przez zamknięty zestaw projektu Archiwisty, ściśle (każde wejście Kartografa to pin sprawdzony SHA-256). ADR-067 zastępuje w części ADR-066 (decyzje 2 i 4) i poprawia jego fakt 4: wada trybu pliku jest w RCN `_unpack_checked_layers` i WFS `_fetch_features` Kartografa, nie w BDOT10k (paczki BDOT10k są czytelne dla UID 999; naprawa w Kartografie później, D10).
- **Bootstrap z zestawu:** `python -m scripts.bootstrap --project PATH --set NAZWA [--dry-run]` (wyklucza się z `--bbox`, `--sheets`, `--boundary-file`). Przed krokiem 1 sprawdza plik projektu, plik obszaru i jego SHA-256, zamknięcie zestawu (`state` brak albo `closed`), zapisany `pins_sha256`, magazyn projektu (oznaczony; przy ustawionym `HYDROGRAF_KARTOGRAF_ROOT` ten sam katalog) i każdy pin Kartografa (rozmiar i SHA-256), potem wymagania: arkusze obszaru projektu wśród pinów NMT (D3), powiaty PRG dla ramek przypiętych arkuszy wśród pinów BDOT10k (bez `--skip-landcover`), dokładnie jeden raster HSG pokrywający mozaikę wg prostokąta z sidecara (D4; bez `--skip-hsg`), jedna wersja na jednostkę. Kroki 2–5 biorą przypięte pliki (krok 2: `N/N arkuszy z zestawu`, nic nie pobiera); kroki 6–10 bez zmian.
- **Odmowy:** polskie `BŁĄD:` i `Wskazówka:`, w ostatnim wierszu stderr dokument `hydrograf-error/1`, kod wyjścia z rejestru (tabela w ADR-067; nowych kodów brak). Nowe klasy `InvalidDataError` i `SourceUnavailableError`, teksty EN i PL w `core/messages.py`.
- **Tożsamość zestawu:** wiersz `Bootstrap from a set: {json}` w logu i `<output>/bootstrap_set.json` (`hydrograf-bootstrap-set/1`, status running → ok albo failed); przebieg bez zestawu usuwa plik.
- **Tylko odczyt:** `refuse_shared_store()` i `private_store_dir()` (`utils/kartograf_store.py`): przy ustawionym `HYDROGRAF_KARTOGRAF_ROOT` odmawiają `download_bdot10k`, `download_sheets`, `fetch_landcover`, kroki 2 i 5 ścieżki prywatnej, a przez nie `download_dem`, `download_landcover`, `prepare_area`, `analyze_watershed --download` i zapasowe CN; `POST /api/admin/bootstrap/start` → `403` problem+json (D8). Usunięte: `writes_in_progress`, `ACTIVE_WRITE_WINDOW_S`, `STAGING_GLOB`, strażnik kroku 2, `HYDROGRAF_KARTOGRAF_STORE_MODE` (staging montuje magazyn zawsze `:ro`).
- **Moduły i testy:** `utils/archiwista_project.py`, `utils/kartograf_set.py`; `tests/unit/test_bootstrap_set.py` (prawdziwy Kartograf, magazyn offline: każda odmowa z tabeli, wymagania, wektor testowy `pins_sha256`), `test_kartograf_store.py`, `test_admin_bootstrap.py`; `test_messages.py` przegląda też `utils` i `scripts`.
- **Dokumentacja:** ADR-067, erraty ADR-066, `docs/DECISIONS.md`, `integrations/KARTOGRAF.md` 7.3, `backend/scripts/README.md`, `.env.example`, `docker-compose.staging.yml`, CHANGELOG, plan migracji (S5 przepisany jako „bootstrap z zestawu”, wyniki H1).
- **Smoke `--dry-run`:** na jednorazowej kopii magazynu S3 (`/home/claude-agent/data/tmp/h1-smoke/`, 21 wersji, projekt z czterema zestawami) zamknięty zestaw kod 0 (15/15 arkuszy, PRG 0205 i 0226, raster HSG, skrót z pliku), otwarty 4 `set_open`, brak pinu 3, bez BDOT10k 14 `set_counties_missing`, zmieniony SHA-256 7 `pin_changed` i 7 `set_digest_mismatch`, nieznany zestaw 3, `--bbox` przy magazynie wspólnym 12 `forbidden`, `--project` bez `--set` 2, inny `HYDROGRAF_KARTOGRAF_ROOT` 2 `store_mismatch`; magazyn bez zmian (272 wpisy). Na prawdziwym magazynie wspólnym (tylko odczyt) z kopią pliku projektu Kaczawy (zestaw „2020”, 205 pinów, bez `state`): `--skip-landcover --skip-hsg --dry-run` kod 0, 205/205 pinów, 205 arkuszy obszaru (około 3 s); bez pominięć kod 14 `set_counties_missing` z dziesięcioma powiatami (0205, 0206, 0207, 0209, 0218, 0219, 0221, 0226, 0261, 0262); magazyn bez zmian (7868 wpisów). Testy `db` na jednorazowej `hydro_h1_testdb` (migracje 001 → 003): 15 zaliczonych, 1 pominięty.
- **Pełny przebieg kroków 2–5 z zestawu** (bez `--dry-run`, jednorazowa baza PostGIS `hydro_h1_testdb`, kopia kodu poza worktree): kod 0 w 110 s, `15/15 arkuszy z zestawu`, 3 048 412 komórek, 4437 odcinków z wypalaniem przypiętego BDOT10k, 18 305 obiektów pokrycia z 2 powiatów, HSG z rastra zestawu — liczby jak w bootstrapie S3; `bootstrap_set.json` ze statusem `ok`; magazyn bez zmian. Testy `db` na tej bazie: 15 zaliczonych, 1 pominięty; kontener zatrzymany.
- **Bramka:** `GATE_COMMIT_RANGE=babe8ff..HEAD bash scripts/gate.sh` zielona: 1416 testów offline, pokrycie 86,84%.
- **Pytania do autora:**
  1. D12 planu Nogata (jeden producent na zestaw w budowie; producent w każdym wywołaniu wymagałby `archiwista-project/2`): Hydrograf czyta tylko piny `kartograf`, piny innych producentów pomija. Czy tak ma zostać, gdy dojdą zestawy kilku producentów (IMGWTools)?
  2. H2 czeka na wdrożenie Archiwisty (A3) i przeniesienie Kaczawy do `projects/kaczawa` (A4): montowanie dzisiejszego katalogu `projects` odsłoniłoby kontenerowi wszystkie projekty.
  3. Czy zapis zestawu (`bootstrap_set.json`) pokazywać w panelu admina? Nie zrobione (poza zakresem H1).
- **Następne kroki:** H2 (montowania pod ścieżkami hosta, katalog projektu, ACL `rX`) po A3 i A4, potem S5 z zestawu zamkniętego przez autora (A5). Szczegóły w „Wynikach” planu.

### Drobne poprawki przed S5 (2026-11-02, decyzje autora)
- **MZP nad NMT** (`231dcf7`): `hazardPane` z-index 240 → 255, między `demPane` (250) a `landcoverPane` (260); wyniki analiz (300) i linie spływu (350) dalej nad MZP. Slajd 14 instrukcji i prezentacji („nad podkładem i NMT, ale pod wynikiem SFINCS”), PDF prezentacji wydrukowany ponownie (30 slajdów, zmienione tylko to zdanie), `?v=` przeliczone, ARCHITECTURE, CHANGELOG, pozycja backlogu zamknięta. Sprawdzone na stagingu 8081 (`frontend/` montowany z worktree, bez restartu): NMT i MZP 1 % włączone, Legnica, zoom 14 — głębokości MZP widoczne nad NMT, 0 błędów JS (zrzut `/home/claude-agent/data/tmp/mzp-over-nmt.png`).
- **`HYDROGRAF_PUBLIC_HOST`** (`0f672e4`): `hydrograf-test.debever.pl` w `.env.staging` (tryb 600) i jako zakomentowany wpis `.env.example`; żaden kod zmiennej nie czyta; `.env` zamrożonej produkcji bez zmian. Pozycja backlogu zamknięta.
- **Nota ADR-061** (`0f672e4`): wskazuje ADR-066 i ADR-067 — magazyn wspólny tylko do odczytu, czytany wyłącznie przez `bootstrap --project --set`, pobierania odrzucane; indeks ADR „amended by ADR-066 and ADR-067”.
- **Instrukcja: karta potwierdzona przez autora, kod bez zmian:** „Otwórz instrukcję” w oknie powitalnym otwiera przewodnik w nowej karcie (`target="_blank"`); „Instrukcja” na szynie to zwykły odnośnik `/instrukcja/` w tej samej karcie (na `/admin` i `/instrukcja`); na stronie mapy zwykłe kliknięcie otwiera najpierw okno powitalne (Ctrl/Shift/środkowy przycisk — odnośnik), jak dotąd.
- **Snyder:** testerzy nie dostają osobnej informacji (decyzja autora); zmiana opisana tylko w CHANGELOG. Pozycja 2 „Otwartych decyzji” planu migracji rozstrzygnięta.
- K0 pusty diff i `/health` 200 przed i po sprawdzeniu w przeglądarce.

### Błędy B1, B2, B4, B5 z raportu GPT przed v0.5.0 (2026-11-02 wieczór; wcześniej błędnie v0.8.0)
- **Decyzja autora:** pełny S5 (bootstrap z zestawu dla całej Kaczawy) odłożony na po v0.5.0; v0.5.0 przełącza produkcję w miejscu (zapis w planie migracji, przy S5). Kod `--project/--set` zostaje.
- **API** (`0c9c154`): `errors[].message` po polsku dla `Accept-Language: pl` (tekst typu błędu pydantic z granicami, np. „Wartość nie może być większa niż 0,8.”; angielski bez zmian); `morphometry.area_km2` powyżej `area_limit_km2` (250) daje 422 `catchment_too_large` jak zlewnia wyznaczona; `POST /api/terrain-profile` zwraca `dem_gaps` (addytywnie, `elevations_m` dalej 0,0 w luce). Testy: kontrakt komunikatów, limit powierzchni (250,01 → 422, 250 → 200), luka NMT vs 0 m n.p.m.
- **Frontend** (`46f2162`): B1 walidacja pól liczbowych przed żądaniem z komunikatem pod polem (też `errors[]` serwera), stary wynik ukryty, bez cichych wartości domyślnych; B2 limit powierzchni w trybie zaawansowanym; B4 pasek trybów w dwóch rzędach na telefonie (375 px: scrollWidth 375), × chowa panel „Zlewnia” bez kasowania, przycisk „Wyczyść wynik”; B5 luka na wykresie profilu, notka z udziałem luki, komunikat dla linii poza NMT.
- Staging: obraz `hydrograf-api:store-staging` przebudowany z worktree, `hydro_staging_api` odtworzony (teraz z montowaniem `/kartograf:ro`); sprawdzone w Chromium na 8081 (1440 × 900 i 375 × 812), 0 błędów JS, zrzuty `/home/claude-agent/data/tmp/r1-*.png`. K0 pusty diff i `/health` 200 przed i po.
- Otwarte dla autora: `null` zamiast 0,0 w `elevations_m` (zmiana schematu odpowiedzi, łamiąca); B3 (Snyder) diagnozowany osobno.

### Trasy admina jako zasoby, przed v0.5.0 (2026-11-02; wcześniej błędnie v0.8.0)
- **API (łamiące, w miejscu, bez starych tras):** `DELETE /api/admin/sewer/delete` → `DELETE /api/admin/sewer`; `POST /api/admin/sewer/config` → `PUT /api/admin/sewer/config` (to samo ciało); `POST /api/admin/feedback/{id}/read` → `PATCH /api/admin/feedback/{id}` z `{"is_read": true|false}` (`FeedbackUpdate`, ścisły `bool`; brak lub inny typ → 400 `validation_error`). CORS dopuszcza `PUT` i `PATCH`. Stare trasy: 404 (`/sewer/delete`, `/feedback/{id}/read`) i 405 (`POST /sewer/config`).
- **Panel `/admin`:** `admin-api.js` `setFeedbackRead(id, isRead)` zamiast `markFeedbackRead`; w każdym wierszu zgłoszenia przycisk „Oznacz przeczytane” / „Oznacz nieprzeczytane” (zmiana od razu, licznik nieprzeczytanych za nią, cofnięcie przy błędzie); rozwinięcie wiersza nadal oznacza przeczytane; `admin-sewer.js` z `PUT` i `DELETE /api/admin/sewer`. `?v=` przeliczone.
- Testy: `test_admin_feedback.py` (PATCH na `true` i `false`, 404, trzy błędne ciała, brak starej trasy), `test_admin_uploads.py` na nowych trasach. ARCHITECTURE 2.9 (§2.2.8 z endpointami zgłoszeń), CHANGELOG (jeden wpis łamiący), BACKLOG: pozycja v0.5.x `GET /api/streams`, `/api/catchments`, `/api/catchments/{id}`.
- Staging: obraz `hydrograf-api:store-staging` przebudowany, `hydro_staging_api` odtworzony; na 8081 w Chromium (1440 × 900): zgłoszenia 13 i 12 przełączone na przeczytane i z powrotem (6 × `PATCH` 200, stan w bazie zgodny z widokiem, na końcu przywrócony: 13 nieprzeczytane, 12 i 11 przeczytane), status kanalizacji „Brak danych”, 0 błędów JS. Stare trasy przez `curl`: 404/405. K0 pusty diff i `/health` 200 przed i po.

### Poprzednia sesja (2026-11-01/02 — kopia produkcji, przycięcie danych do zlewni Kaczawy, wyniki SFINCS w „Wynikach analiz”, instrukcja i ekran powitalny, nakładka MZP ISOK, cache zasobów za Cloudflare, zwierciadło wody na profilu terenu)

### Co zrobiono
- **Kopia zapasowa produkcji przed zmianami:** `/data/nmt/hydrograf-backup-2026-11-01/` (inny dysk niż produkcja; jedyny zapisywalny katalog na `/data`): `hydro_db.dump` (`pg_dump -Fc`, 12 tabel), `globals.sql`, `data.tar.zst`, `frontend_data.tar.zst`, `frontend_tiles.tar.zst`, `cache.tar.zst`, `config.tar.zst` (z `.env` i `admin.key`, tryb 640), `git_head.txt`, `SHA256SUMS`. Sprawdzone `zstd -t`, liczbą plików archiwów względem źródła i `pg_restore -l`. Przywrócenie: `pg_restore -c -d hydro_db` + rozpakowanie archiwów do katalogu repo.
- **Przycięcie danych do zlewni Kaczawy powyżej węzła 51,222825 N; 16,179380 E (790,57 km²; segment 159 przy progu 100000, 870 przy 10000).** Pierwszy przebieg tego dnia szedł do węzła 51,229046; 16,198853 (813,17 km², segment 23/93) i obejmował część zlewni Czarnej Wody — korekta autora, przycięte ponownie. Granica = pierścień zewnętrzny sumy zlewni cząstkowych (suma ma luki poligonizacji), MultiPolygon 2 części (7 komórek łączy się narożnikiem), `data/boundary/zlewnia_kaczawy_790km2_przyciecie.gpkg`. Skrypt operacyjny poza repo (`~/scratch/hydrograf-clip/clip_hydrograf.py`), fazy w `docker compose run --rm --no-deps api`, wyniki do katalogu staging i podmiana `rename` wpis po wpisie (katalogi `frontend/data` i `frontend/tiles` są bind-mountami `hydro_api`, więc nie podmieniano samych katalogów).
  - Baza: `stream_catchments`/`stream_network` — tylko domknięcie w górę od ujścia (41 277 / 4 492 zlewni, po 790,566 km²); `downstream_segment_idx` ujścia ustawione na NULL jak przy innych ujściach brzegowych. `land_cover`, `soil_hsg`, `bdot_streams` przycięte geometrycznie (`soil_hsg.area_m2` i `bdot_streams.length_m` przeliczone); `land_cover` i `soil_hsg` pokrywają granicę w 100% (790,564 km²). `precipitation_data`: punkty w buforze 3,5 km (maks. odległość do 4. sąsiada IDW w granicy 2,93 km, więc opad w każdym punkcie zlewni bez zmian; 314 → mniej punktów). `depressions` przeliczone z przyciętych rastrów (214 907; zagłębienia przecięte granicą mają poprawną objętość).
  - Rastry `data/nmt/*.tif` (16): przycięte do okna granicy, nodata poza nią (31 622 576 komórek = 790,564 km²). `data/hydro/hydro_merged.gpkg` i `data/sewer_network.gpkg` przycięte. `cache/` bez zmian (surowe arkusze i powiaty).
  - Frontend: kafle MVT, `dem.png`, `dem_tiles/` (okno barw p5–p95 policzone na nowo z przyciętego NMT), `streams.png`, `depressions.png`, `soil_hsg.geojson`, `bdot_*.geojson` wygenerowane od nowa. Restart `hydro_api`: graf 45 769 węzłów, 45 767 krawędzi.
  - Smoke: delineacja 51,0376/16,1723 → 15,16 km² (jak przed przycięciem), przekrój Kamiennika → 37,23 km², punkt poza granicą → 404 z komunikatem; warstwy w przeglądarce kończą się na granicy, bez błędów JS. Profil terenu poza granicą zwraca 0,0 m (dotychczasowe zachowanie poza mozaiką; komunikat to część pozycji backlogu o przycinaniu, `docs/BACKLOG.md`).
- **Wyniki analiz zewnętrznych w panelu „Warstwy”** (gałąź `feature/analysis-results`, commity `8377c23`, `5449d70`, fast-forward do `feature/visual-identity` w checkoucie produkcyjnym): manifest `frontend/data/results/index.json` (`hydrograf-results/1`, `kind: raster_tiles`), wiersze w istniejącej grupie „Wyniki analiz” pod „Liniami spływu”, legenda, krycie, (i), przybliżenie do zasięgu; bez manifestu interfejs bez zmian.
- **Model SFINCS zlewni Kamiennika** (Hydraulik `Hydraulik-sfincs`, `feature/sfincs-swmm`, SFINCS v2.4.1 w Dockerze; katalog `~/hydraulik-work/kamiennik-12h-p1/`): domena = zlewnie cząstkowe w górę od segmentu 21911 (37,22 km², `data/boundary/kamiennik_37km2_sfincs.gpkg`), NMT 5 m z Hydrografa bez zmian (decyzja autora: zapora zbiornika Świerzawa bez upustu, niecka ~1,12 mln m³ do przelewu 279,63 m n.p.m.), BDOT10k 0205+0226 i HSG z `cache/`, opad 12 h p = 1% 105,0 mm (PMAXTP z `precipitation_data`, IDW w centroidzie; Hydraulik pobiera PMAXTP tylko do 180 min), Beta α = 2 β = 5, recesja 6 h, siatka 5 m (1 491 703 komórki; Hydraulik wyrównuje siatkę do wielokrotności 5 m, a NMT GUGiK ma narożniki na x,5 — teren jest interpolowany o pół komórki). Przebieg 1 (50 min): bilans 0,04%, ale `huthresh` = 0,05 m Hydraulika zatrzymał wodę na zboczach — przez przekrój wypłynęło ~1,7 tys. z 1,14 mln m³.
  - **Przebieg 2 (`huthresh` = 0,001 m, 4 h 50 min, `exit=0` 2026-11-02 00:04) opublikowany zamiast wstępnego** (ten sam `id` `sfincs-kamiennik-12h-p1`; `results/max_depth_huthresh0001.tif`, `results/summary_huthresh0001.json`, szeregi stacji `stacje_run2.csv` z `results export --variable stations` w katalogu wyniku; `stacje_run2_czesciowe.csv` usunięty). Bilans: opad 3,916 mln m³, infiltracja 2,774 mln m³, spływ 1,141 mln m³; przez przekrój wypłynęło 11,6 tys. m³ (1% spływu, przebieg 1: 1,7 tys.), w zlewni zostało 1,130 mln m³, z tego ~0,67 mln m³ w czaszy (0,155 km²). Zbiornik: maks. głębokość 12,3 m przy zaporze, poziom 277,48 m n.p.m. na koniec (18 h), wciąż rośnie ~0,19 m/h, 2,15 m poniżej przelewu — bez przelania; w siatce modelu (teren interpolowany) przelew wychodzi wyżej, ~281,2 m. Poniżej zapory ≤ 5 mm. Przekrój: maks. 0,76 m po 4 h 28 min (komórka w lokalnym obniżeniu, w przebiegu 1 0,67 m). Powierzchnia ≥ 0,1 m: 1,92 km² (przebieg 1: 0,57), ≥ 0,3 m: 1,16 km² (0,11). Weryfikacja: manifest przez :8080, kafle 200, warstwa i (i) w przeglądarce bez błędów konsoli. Mały odpływ wynika z zapory bez upustu (prawie cała zlewnia jest powyżej zapory), nie z modelu.
  - **Przebieg 3 przygotowany i uruchomiony** (`model_24h/`, `run_24h/`): opad 24 h p = 1% 134,5 mm (IDW potęga 2, 4 najbliższe punkty PMAXTP; kontrola tą samą metodą dla 12 h daje 105,0 mm jak w przebiegach 1–2), Beta 2/5, krok 5 min, recesja 12 h (`tstop` 36 h). W `sfincs.inp` ręcznie: `huthresh = 0.001`, `dtout = 3600` (mapy godzinowe), `dtmaxout = 129600` (SFINCS 2.4.1 zeruje `zsmax`/`vmax` po każdym zapisie maksimów, a Hydraulik bierze ostatnią ramkę — przy `dtmaxout` < `tstop` podsumowanie byłoby błędne) i `crsfile = sfincs.crs` z 7 przekrojami (`inputs/cross_sections.gpkg`): K1–K4 na Kamienniku (29,35 / 18,71 / 15,53 / 10,06 km²), C1 Czerwieniec (8,67 km²), T2 i T3 na dopływach (3,96 / 2,43 km²); format `crs` sprawdzony w źródle SFINCS v2.4.1 i krótkim teście, przepływ z nurtem dodatni. Pierwszy start 00:04 zatrzymany po 7,6 h symulacji i ponowiony z przekrojami 2026-11-02 01:03. Hydrologia dla przekrojów (Hydrolog, SCS + Kirpich, CN z rastra modelu): `results/hydrology_sections_24h.csv` i `_summary.json` (np. K1: Qmax 43,7 m³/s po 570 min; wariant z CN Hydrografa daje +13–17% objętości); porównanie SFINCS–Hydrolog skryptem `compare_sections.py` po zakończeniu.
- **Wynik SFINCS z poziomem wody:** w katalogu wyniku `wse_max.tif` (`zsmax` przebiegu 2, EPSG:2180, siatka jak `max_depth.tif`, nodata przy głębokości < 0,05 m; 103 667 mokrych komórek, 260,16–471,76 m n.p.m.), w manifeście pole `water_level`.
- **Profil terenu na telefonie** (`08df412`): linii nie dało się zakończyć (koniec tylko na `dblclick`, dotyk dodawał dwa punkty). Teraz stuknięcie do 20 px od ostatniego punktu kończy linię, a pasek nad mapą (licznik punktów, Cofnij, Zakończ, Anuluj) zastępuje Esc i Backspace.
- **Instrukcja i ekran powitalny** (gałąź `docs/instrukcja-v2`, worktree `Hydrograf-guide`): przewodnik rozbudowany z 10 do 25 slajdów przez GPT-6-Sol (przerwał na limicie ChatGPT przed commitem; pracę przejrzał i poprawił Opus: opis nowego paska profilu, nowy zrzut profilu, Snyder bez wpływu Tc, ekran powitalny w opisie przycisku) — `2ba7cc9`; rozdział „Na start” prostym językiem (slajdy 3–6: czym jest Hydrograf ze słowniczkiem, czego się spodziewać, kto i po co, start w 3 krokach, obszar danych) — `30a4164`; ekran powitalny `js/welcome.js` (natywny `<dialog>`, „Otwórz instrukcję” w nowej karcie, „Przejdź do mapy”, „Nie pokazuj ponownie” w `localStorage` `hydrograf-welcome-hidden`, ponowne otwarcie przyciskiem „Instrukcja”) — `8847fdf`. Prezentacja HTML/PDF zgodna z przewodnikiem.
- **Raport testów frontendu (GPT, 2026-11-01, wersja `5449d70`):** `~/scratch/gpt-guides/hydrograf-test-report.md` — 0 krytycznych, 0 wysokich, 5 średnich (B1–B5, w `docs/BACKLOG.md`, Bugs and diagnoses), 10 niskich (B6–B15; B14 rozwiązane przez `08df412`), 3 informacyjne; zero błędów JS. Wyznaczanie zlewni 37 km² trwa 4–5 s.
- **Nakładka „Mapa zagrożenia powodziowego” (MZP ISOK)** (gałąź `feature/isok-mzp`, worktree `Hydrograf-isok`; `0e12eca`, slajd 14 przewodnika `6aea0d4`): WMS 1.3.0 Wód Polskich/KZGW (`wody.isok.gov.pl`, usługi `MZP20_Glebokosc_{Niskie,Srednie,Wysokie}PrawdopodPowodzi`, warstwy `16`/`16`/`1`; REST i WMTS dają 401), głębokości dla p = 0,2 / 1 / 10 %, legenda w HTML (4 klasy), CC BY 4.0. Głębokości rysowane od przybliżenia 14 (poniżej podpowiedź, bez zapytań); obrazy 512 px, odpowiedzi 0,4–2 s, pojedyncze 10–30 s. Panel `hazardPane` z-index 240: nad podkładami, pod NMT (250) i wynikami analiz (300) — przy NMT na kryciu 70% MZP jest przygaszona (kolejność do decyzji, `docs/BACKLOG.md`). CSP `img-src` + `https://wody.isok.gov.pl`. Wdrożenie wymagało restartu `hydro_nginx`, nie reloadu: `nginx.conf` jest montowany jako pojedynczy plik, a merge zapisał go pod nowym i-węzłem, więc kontener widział starą wersję.
- **Cache zasobów za Cloudflare** (`357b997`): po wdrożeniu MZP Cloudflare serwował stary `js/layers.js` (`HIT`, przeglądarkom `max-age` 4 h). `scripts/bump_asset_versions.py` dopisuje `?v=<10 znaków SHA-256>` do własnych JS/CSS w `index.html`, `admin.html`, `instrukcja/index.html` (`--check` w nowym zadaniu CI `frontend-assets`, hook `pre-commit` przy zmianach w `frontend/` — w tym checkoucie `pre-commit install` nie jest wykonane, więc skrypt trzeba uruchamiać ręcznie); HTML i `/admin` z `Cache-Control: no-cache` + ETag (`expires -1`, nagłówki bezpieczeństwa dziedziczone). Przy okazji: `HYDROGRAF_PUBLIC_HOST` w `.env` wskazuje host, którego nie ma w DNS (`docs/BACKLOG.md`). Od scalenia z `feature/producer-heads` (2026-11-02) hooka `pre-commit` nie ma (`.pre-commit-config.yaml` usunięty): po zmianie pliku JS/CSS uruchomić `python3 scripts/bump_asset_versions.py`, a `--check` wykonują bramka `scripts/gate.sh` i zadanie CI `frontend-assets`.
- **Zwierciadło wody na profilu terenu** (gałąź `feature/profile-water-level`, worktree `Hydrograf-wse`; `9d281b8` API, `2c4aff7` frontend, `70beff6` dokumentacja): `POST /api/terrain-profile` przyjmuje `result_ids` (≤ 20) i zwraca `water_levels` z rastrów `water_level` manifestu (`core/analysis_results.py`, ustawienie `FRONTEND_DATA_DIR`, tylko pliki w `results/`; nieznane lub nieczytelne pomijane); wykres rysuje wodę (kolor `--info`) dla włączonych wyników, odczyt teren / zwierciadło / głębokość. Sprawdzenie: przekrój czaszy zbiornika 277,48 m n.p.m., głębokość przy zaporze 12,33 m (maks. modelu 12,31 m). Przerwa API ok. 2,5 min (2026-11-01 23:50–23:53 UTC): edycja `profile.py` przez pomyłkę w checkoucie produkcyjnym, cofnięta `git restore`, ale uvicorn `--reload` przeładował API dwa razy (graf zlewni 134 s).
- **Wdrożenia:** wszystkie gałęzie dnia (`feature/analysis-results`, `docs/instrukcja-v2`, `feature/isok-mzp`, `feature/profile-water-level`) scalone fast-forwardem do `feature/visual-identity` w checkoucie produkcyjnym (HEAD `70beff6`); podglądy na osobnych kontenerach usunięte, worktree zostawione. Pliki w trybie 644.

### W trakcie
- Przebieg 3 SFINCS (24 h p = 1% + 12 h, 7 przekrojów): liczy od 2026-11-02 01:03 (ok. 45% o 06:52, koniec ok. 13:00), koniec sygnalizuje `run_24h.exit` w `~/hydraulik-work/kamiennik-12h-p1/`. Nie dotykać kontenera ani katalogu roboczego w trakcie.
- `feature/visual-identity` (produkcja, HEAD `70beff6`) i scalone do niej gałęzie dnia niezmergowane do `develop`, niewypchnięte (zgoda autora); worktree `Hydrograf-guide`, `Hydrograf-isok`, `Hydrograf-results`, `Hydrograf-wse` do usunięcia po merge'u.

### Następne kroki
- Po przebiegu 3: `compare_sections.py` (SFINCS vs Hydrolog w 7 przekrojach), publikacja wyniku 24 h w manifeście (kafle, `max_depth.tif`, `wse_max.tif` jako `water_level`), porównanie z MZP 1%.
- Ustalenia dla Hydraulika (do jego dokumentacji): `huthresh` w `model build` (domyślne 0,05 m nie nadaje się do deszczu na siatce), brak `dtout`/`dtmaxout` i `crsfile` w `model build`, błędne podsumowanie przy `dtmaxout` < `tstop`, exit 9 przy `--output-dir` wewnątrz katalogu modelu, siatka wyrównana do wielokrotności `dx` (pół komórki przy NMT GUGiK), PMAXTP tylko 15–180 min, `results export` bez poziomu wody (`zsmax`).
- Decyzje autora (rozstrzygnięte 2026-11-02, „Drobne poprawki przed S5” wyżej): MZP nad NMT; ekran powitalny otwiera instrukcję w nowej karcie, a przycisk „Instrukcja” w tej samej — potwierdzone.
- Błędy B1–B5 z raportu testów GPT (`docs/BACKLOG.md`, Bugs and diagnoses); `HYDROGRAF_PUBLIC_HOST` poprawiony (wyżej).
- Przycinanie w pipeline (bootstrap zapisuje granicę, API odmawia poza nią) — pozycja backlogu (`docs/BACKLOG.md`, Features — other) nadal otwarta; tym razem przycięto jednorazowo skryptem.
- Merge `feature/visual-identity` do `develop` i push za zgodą autora.

### Poprzednia sesja (2026-11-01 — GUI w identyfikacji Nogata)

### Co zrobiono
- **Nowy interfejs w identyfikacji wizualnej Nogata** (standard DEV-15.3, decyzja ECO-055, wzorzec Nogat `design/`, makieta `design/mockups/hydrograf/`), ADR-065 (numer 065, bo 058–064 są zarezerwowane w specyfikacjach i planach Kartografa). Powłoka Archiwisty: górny pasek ze znakiem, przyciskami „Instrukcja” i „Zgłoś uwagę” oraz przełącznikiem motywu Auto/Jasny/Ciemny, szyna Mapa/Administracja, lewy panel „Warstwy” z jednym przyciskiem przybliżenia do zasięgu włączonych warstw, mapa z paskiem trybów Przeglądanie/Wybierz zlewnię/Profil terenu i dolną szufladą profilu, prawy panel „Zlewnia” z kluczowymi wartościami i sekcjami `<details>`. Panele z regulowaną szerokością 260–560 / 340–720 px, układ telefonu ≤ 860 px z dolnym paskiem i arkuszami od dołu; motyw jasny i ciemny.
- **Pliki:** `css/tokens.css` (kopia `design/tokens.css` Nogata z commita 29e7e1c, nagłówek go wskazuje; nie edytować, kopiować ponownie), `css/chrome.css` (powłoka wspólna dla strony głównej, `/admin`, `/instrukcja`), `css/app.css`, `css/admin.css`, `instrukcja/instrukcja.css`, `img/hydrograf.svg`, `js/shell.js`, `js/theme-init.js`, `js/theme-switch.js`. Usunięte: Bootstrap ze strony głównej (zostaje w `/admin` dla siatki i okien modalnych, przekolorowany tokenami), `css/glass.css`, `css/style.css`, `js/draggable.js`; formularz uwag to natywny `<dialog>`.
- **Podkłady:** OpenFreeMap szary (wektorowy; MapLibre GL 4.7.1 przez `@maplibre/maplibre-gl-leaflet` 0.0.22, styl positron), OSM GUGiK szary (tylko Polska), Ortofotomapa ESRI, bez podkładu. Usunięte: OSM kolorowy, GUGiK WMTS orto/topo, OpenTopoMap. CSP (`nginx.conf`, `nginx-ssl.conf.template`): `connect-src` + `https://tiles.openfreemap.org`, `img-src` + `blob:`, `worker-src`/`child-src blob:`, bez OpenTopoMap.
- **Wykresy** w kolorach tokenów, zgodne z motywem; hietogram liniowy jak hydrogram; pokrycie terenu i HSG jako poziome słupki skumulowane. Wiersze warstw pokazują krycie (dawniej przezroczystość).
- **Szyna** tylko Mapa i Administracja; profil terenu zostaje w trybach paska mapy, przewodnik to przycisk „Instrukcja” w górnym pasku każdej strony (główna, `/admin`, `/instrukcja`).
- **Objaśnienia (i)** (`js/info.js`, `js/info-texts.js`, teksty kluczowane polem API lub id kontrolki) w sekcjach Parametry podstawowe, Wskaźniki kształtu, Hietogram, Hydrogram; treści oparte na Hydrologu i backendzie (np. limit hydrogramu 250 km², `HYDROGRAPH_AREA_LIMIT_KM2`); uwagi o stosowalności pod Model UH, Metoda Tc, Estymacja Nash zależą od wyboru. Ostrzeżeń o stosowalności brak — API ich nie zwraca.
- **Tryb zaawansowany** (`js/advanced.js`): edycja morfometrii (powierzchnia, obwód, długość, wysokości, średni spadek, długość i spadek cieku, `length_to_centroid_km`, CN) wysyłanej do `POST /api/generate-hydrograph` bez zmian backendu; oznaczenie zmienionych pól, przywracanie pola i całości („Przywróć dane z Hydrografa”), walidacja blokuje zapytanie, komunikat „Obliczono na zmienionych danych wejściowych”; opad PMAXTP bez edycji. Luka danych: część zlewni ma `length_to_centroid_km = 0` — Snyder zawodzi do czasu wpisania Lc.
- **Przewodnik** w nowej wersji dla nowego GUI: zregenerowane `/instrukcja` i `docs/Hydrograf-prezentacja.html`/`.pdf`.
- **Runda 2 GUI (frontend + API, bez zmian schematu bazy):**
  - Objaśnienia (i) o stałej strukturze: opis, wzór w MathML, lista „gdzie:” ze zmiennymi i jednostkami, jednostka, osobny blok „Znaczenie dla analizy”, stosowalność i uwaga; teraz także w sekcjach Rzeźba terenu i Sieć rzeczna (76 wpisów w `js/info-texts.js`).
  - Hietogram: „Uwilgotnienie początkowe (AMC)” I/II/III (`amc`), bilans pokazuje CN użyty z jednym miejscem po przecinku i klasą AMC; „Źródło opadu” PMAXTP / Własna seria (`js/custom-rain.js`): czas trwania i krok tworzą tabelę, wklejanie z arkusza, import CSV 1 lub 2 kolumn, „Wczytaj z bieżącego hietogramu”.
  - Formularz hydrogramu w równej siatce: Model UH | Metoda Tc, dla Nasha Model UH | Estymacja Nash.
  - Tryb zaawansowany z dokładnością 0,01 km², 0,01 km, 0,1 m, 0,01 %, CN 0,1.
  - Warstwa „Kanalizacja deszczowa” tylko przy danych kanalizacji (`GET /api/layers` → `{"sewer": bool}`).
  - API: `POST /api/generate-hydrograph` przyjmuje `amc` i `custom_precipitation` (422 z polskim opisem przy błędach serii); `water_balance.cn_used` jako float, `precipitation.source`, `metadata.amc`; CN zlewni (`morphometry.cn`, `weighted_cn`) z dokładnością 0,1; `GET /api/scenarios` z `amc` i `custom_precipitation_max_steps`.
  - Dokumentacja: CHANGELOG, ARCHITECTURE (§2.2.3, §2.2.3a, §4.1, §4.2), COMPUTATION_PIPELINE (§5.2, §6.1, §6.4, §6.8), DATA_MODEL (§6.3, §6.4), DEVELOPMENT_STANDARDS, przewodnik (10 slajdów, zrzuty dodane `git add -f`, bo `.gitignore` ignoruje `*.png`).
- **Objaśnienia (i) zweryfikowane:** każde twierdzenie z `js/info-texts.js` sprawdzone w kodzie albo w literaturze; ewidencja `docs/INFO_TEXTS_SOURCES.md` (985 twierdzeń: 858 potwierdzonych, 113 poprawionych, 7 usuniętych, 7 nieweryfikowalnych). „Znaczenie dla analizy” rozdziela znaczenie hydrologiczne od użycia w Hydrografie (np. średnia szerokość i wskaźniki kształtu: wpływ na czas i kształt fali, w obliczeniach pośrednio przez L, L_g, L_c); 72 wpisy z linią „Źródła:”. Pozostałe do decyzji autora: nazwy „Wskaźnik rzeźby” (ΔH/√A to raczej spadek zlewni ψ / wskaźnik Meltona) i „Liczba chropowatości” (brak polskiego źródła nazwy).
- **Animacja wyznaczania zlewni:** `POST /api/delineate-watershed/preview` zwraca zlewnie cząstkowe, które scali właściwe wyznaczenie (wspólna funkcja `_select_precomputed`), pogrupowane wg głębokości w sieci, w ~25–35 ms (52–106 km²) i ~0,2 s (778 km²); mapa zapala je od ujścia w górę przez 0,5 s, pulsuje do nadejścia scalonej granicy (52 km²: ~4,7 s, 778 km²: ~88 s). Tryb precise bez podglądu.
- **Dokumentacja:** CHANGELOG, ARCHITECTURE (§4.1, §4.2, hosty CSP w §5.2), SCOPE, DEVELOPMENT_STANDARDS, README, ADR-065.
- **Wdrożenie na produkcję (port 8080, 2026-11-01):** checkout produkcyjny `Hydrograf/` przełączony na `feature/visual-identity` (`77c7f65`), restart `hydro_api` i `hydro_nginx` (nowy CSP). Instancja przeglądowa (`hydro_nginx_gui`, `hydro_api_gui`, sieć `hydrograf_gui`, worktree `Hydrograf-gui`) usunięta. Przerwa w działaniu ok. 3–4 min: pliki wypisane przez `git checkout` miały prawa 600 (powłoka miała `umask 077`), więc API (uid 999) nie mogło ich czytać; naprawione `chmod 644` na 75 plikach. Smoke: `/`, `/admin`, `/instrukcja/`, wyznaczenie zlewni, hydrogram, `GET /api/layers`, podgląd zlewni — bez błędów w konsoli.

### W trakcie
- Produkcja działa z gałęzi `feature/visual-identity`, której nie zmergowano do `develop` ani nie wypchnięto; `feature/logowanie-testow` zostaje w miejscu (`6f8b7f6`). Merge i push wymagają zgody autora.

### Następne kroki
- Przegląd GUI przez autora na produkcji (port 8080); merge `feature/visual-identity` i push za zgodą autora.
- Decyzja autora: nazwy wierszy „Wskaźnik rzeźby” i „Liczba chropowatości”.
- Zgłoszenie do Hydrologa: przeliczenie CN dla AMC I/III zaokrągla CN do liczby całkowitej.
- Backend: ujednolicić dokładność powierzchni między pełną ścieżką (2 miejsca) a szybką (4 miejsca); ostrzeżenia o stosowalności metod w API; `length_to_centroid_km = 0` w danych zlewni (Snyder); niespójne wskaźniki kształtu bardzo małych zlewni (wartości > 1 / < 1 wbrew definicji); `asymmetry_coefficient` nigdy nie jest liczony.

### Poprzednia sesja (2026-10-29/30 — bootstrap zlewni Kaczawy i mniejszego obszaru; pamięć przetwarzania NMT)

### Co zrobiono
- **Kod i zależności:** bootstrap szedł z kodu `feature/logowanie-testow` (`backend` podmontowany do kontenera); piny `requirements.txt` zgodne z obrazem: Kartograf 0.7.0, IMGWTools 2.1.0, Hydrolog 0.6.3. `feature/producer-heads` (Kartograf 0.8.0-dev) wymagałaby przebudowy obrazu i nowego układu danych — świadomie nieużyta.
- **Wybór arkuszy (Kaczawa, `obszar_analizy.gpkg`, 2255,8 km²):** bootstrap z `--boundary-file` dobrał 928 arkuszy, bo `kartograf.find_sheets_for_geometry` szuka arkuszy w obwiedni każdego obiektu, nie w wielokącie (plik ma jeden obiekt). Przebieg przerwano po 183 arkuszach i uruchomiono z `--sheets` dla 513 arkuszy przecinających wielokąt (`data/boundary/kaczawa_sheets.txt`). Skala: Kartograf nazywa siedmioczłonowe godło (np. `M-33-20-C-a-2-1`) „1:10000”, GUGiK — modułem 1:5000; NMT 5 m jest publikowany w tym podziale, więc grubsza `--scale` daje te same pliki.
- **Dwa OOM Kaczawy (raster 183 332 457 komórek):** przebieg 1 (limit 8G + 8G swap) przeszedł TWI i padł przy statystykach podzlewni progu 10000 (140 183 etykiety). Przebieg 2 po `docker update --memory 12g --memory-swap 16g` padł wcześniej, przy TWI: `--memory-swap` to sufit RAM + swap, więc łączny limit został 17,18 GB, a swap spadł do 4G. Szczyt obecnego kodu przy tym rastrze ≈ 19 GB.
- **Przerwa API testowego:** bootstrap Kaczawy szedł przez `docker compose exec` w `hydro_api`; OOM przebiegu 2 zabił też proces roboczy uvicorn (został sam proces `--reload`). `hydrograf-test.debever.pl` nie odpowiadał 2026-10-30 ok. 03:55–07:30 czasu lokalnego; przywrócono `docker compose restart api`.
- **Analiza pamięci `process_dem`:** pomiar na wycinku 16M komórek przeskalowany na 183M, prototyp poprawek F1–F7 (wyniki identyczne bit w bit) → szczyt ~9,1 GB. Zapisane jako niewdrożone (decyzja usera) w `docs/TECHNICAL_DEBT.md` i Backlogu (commit `93d9cd8`), razem z błędem par cykli w `fix_internal_sinks`.
- **Bootstrap mniejszego obszaru (`obszar_mniejszy.gpkg`, 827,7 km²):** 207 arkuszy przecinających wielokąt (342 w obwiedni; `data/boundary/mniejszy_sheets.txt`), wszystkie z cache. Uruchomiony w osobnym kontenerze `docker compose run --rm --no-deps` (limit 8G), więc OOM nie mógł zabić API. `EXIT 0` w 4478 s; szczyt pamięci ok. 7,0 GB. Kroki: NMT 42 058 347 ważnych komórek, 60 849 odcinków (2627 s); pokrycie terenu 95 804 obiekty z 10 powiatów; HSG 13 poligonów (B: 1, C: 12); opady 418/418 punktów, 180 576 rekordów (624 s); depresje 344 548; kafle MVT (875 s); overlay (283 s). W bazie: 54 901 cieków i 54 966 zlewni (10000 m²), 5879 cieków i 5883 zlewnie (100000 m²).
- **Weryfikacja przez publiczny adres:** `/api/tiles/thresholds` → `[10000, 100000]`; kafle statyczne cieków i zlewni oraz `/api/tiles/landcover` → 200; delineacja dla punktu na cieku 3. rzędu (51,0376 / 16,1723, próg 100000) → 200 w 4,6 s, 15,16 km²; hydrogram (1h, p = 1%) → 200 w 14,3 s, szczyt 4,3 m³/s po 195 min, 59 139 m³, opad 44,4 mm. Delineacja przy głównym cieku (51,2130 / 16,1734) przekroczyła 60 s po stronie klienta (`Large merge: 4492 segments`).
- **Drobne ustalenia środowiska:** oryginały obszarów mają tryb 640, a uid 999 kontenera ich nie czyta — kopie w `data/boundary/` z trybem 644; `data/logs` nie jest zapisywalny dla uid 999, więc logi przebiegów są w `data/` (`bootstrap-kaczawa-20261029.log`, `bootstrap-kaczawa-513-20261029.log`, `bootstrap-kaczawa-513-run2-20261030.log`, `bootstrap-mniejszy-20261030.log`). Krok 8 ostrzega o braku `ogr2ogr` i `pmtiles` w obrazie; kafle `.mbtiles` i katalogi `.pbf` powstają.

### W trakcie
- `hydro_api` ma limit 12g RAM / 16g z `docker update` (do odtworzenia kontenera, potem 8G z `docker-compose.yml`); przy bootstrapie w osobnym kontenerze nie jest potrzebny.
- Rastry pośrednie w `data/nmt/` to mniejszy obszar (Kaczawa nadpisana); arkusze NMT całej Kaczawy zostają w cache.
- Historia `feature/logowanie-testow` przepisana przed pierwszym pushem (2026-10-30, `git filter-branch` na zakresie `develop..`): ścieżka udziału i adres LAN hosta z dwóch commitów sesji prezentacji zastąpione placeholderami (`<STAGING_DIR>`, `<LAN_HOST_IP>`); drzewo końcowe bez zmian. Gałąź wypchnięta na origin.

### Następne kroki
- Bootstrap uruchamiać wyłącznie w osobnym kontenerze (`docker compose run --rm --no-deps api ...`), nigdy przez `exec` w `hydro_api`.
- Rastry powyżej ~160M komórek (np. cała Kaczawa, 183M) dopiero po wdrożeniu F1–F7 (`docs/TECHNICAL_DEBT.md`); wtedy ponowić Kaczawę.
- Pozostałe wnioski dopisane do Backlogu: dobór arkuszy po wielokącie, czas delineacji przy ujściu dużych cieków.
- Przycinanie prezentowanych danych do granicy zakresu analizy — priorytet wysoki (`docs/BACKLOG.md`, Features — other).

### Poprzednia sesja (2026-10-29 — prezentacja dla testerów)

### Co zrobiono
- Przygotowano siedmioslajdową prezentację `docs/Hydrograf-prezentacja.html` i PDF: wersja rozwojowa na pierwszym slajdzie, nawigacja, trzy tryby pracy, wyznaczanie zlewni, linie spływu, hietogram i hydrogram, NMT z profilem terenu oraz formularz „Zgłoś uwagę”. Kolorystyka: granat `#013e5c`, błękit `#0089b3`, zieleń `#84c340`, jasny błękit `#e4f0f5`; bez nazwy i logo strony referencyjnej.
- Otworzono działającą aplikację: zamiast wcześniejszej zlewni 1,73 km² wybrano zlewnię dopływu Kwisy przy Nawojowie Śląskim o dokładnej powierzchni 25,52 km² (punkt wyboru 51,160 / 15,321, ujście 51,160766 / 15,319717); włączono linie spływu i oba wykresy. Zrzut trzech trybów wykadrowano ponownie z fragmentem białego górnego paska, umieszczając tryby pośrodku. Profil NMT biegnie między punktami podanymi przez użytkownika: Wiatraczna 51,075441 / 15,466309 → Skalnik 51,038324 / 15,514557. Wysokości podane przez użytkownika to 437/485 m; raster w tych współrzędnych zwraca ok. 433/461 m. Zaktualizowane zrzuty: `docs/Hydrograf-tryby.png`, `docs/Hydrograf-zlewnia-wykresy.png`, `docs/Hydrograf-NMT-profil.png`; pozostają `docs/Hydrograf-mapa.png` i `docs/Hydrograf-feedback.png`.
- Sprawdzono w przeglądarce załadowanie pięciu obrazów i siedmiu slajdów; wyeksportowano PDF 16:9 ze zrzutami na stronach 2, 4, 5 i 7. Skopiowano HTML, PDF i pięć PNG do `<STAGING_DIR>`, potwierdzono zgodność SHA-256 kopii oraz załadowanie obrazów w HTML otwartym z katalogu docelowego.
- Uogólniono tekst slajdów wyników: tytuły „Wyznaczanie granicy zlewni oraz jej parametrów” i „Profil terenu”; usunięto podpisy oraz nazwy miejsc, wysokości i współrzędne z treści/tekstów alternatywnych prezentacji. Zrzuty danych pozostały bez zmian.
- Doprecyzowano slajd podstawowych funkcji dla osób bez doświadczenia GIS: krótkie objaśnienia zlewni, NMT, hietogramu i hydrogramu oraz rysowanie profilu przez dwa punkty i podwójne kliknięcie. Ponownie wygenerowano PDF i sprawdzono układ slajdu.
- Udostępniono przewodnik HTML z pięcioma obrazami pod `/instrukcja` i dodano przycisk „Instrukcja” do paska aplikacji. Potwierdzono w przeglądarce publiczny adres testowy, ładowanie wszystkich obrazów i przejście z aplikacji do przewodnika. Nginx przekierowuje ścieżkę katalogu `/instrukcja` na `/instrukcja/`.
- Naprawiono układ instrukcji na telefonach w `frontend/instrukcja/index.html` i `docs/Hydrograf-prezentacja.html`: automatyczna wysokość slajdów, jednokolumnowe sekcje i stopka pod treścią. Usunięto przycisk „Następny slajd” oraz nieużywany skrypt nawigacji w obu wersjach; kopię HTML w `<STAGING_DIR>` zsynchronizowano. Sprawdzono publiczną stronę przy 375 px (bez poziomego przewijania, siedem slajdów i pięć obrazów) i na desktopie.
- Sprawdzono najnowsze logi nginx, API i bazy: nowy wpis `GET /instrukcja/` ze statusem 200 i `request_id=c42356059819fe47fe5e9296aa8da49a` pojawił się bezpośrednio po żądaniu kontrolnym (11:02:16 UTC). API zapisywało żądania `/health` ze statusem 200, w sprawdzonym oknie baza nie emitowała wpisów. Nginx odnotował również 404 dla brakującego `/favicon.ico` (11:01:37 UTC); nie dotyczy działania instrukcji.
- Zwiększono retencję logów Docker `json-file` dla nginx, API i PostgreSQL z 5 do 50 plików po 10 MiB (maksymalnie 500 MiB na kontener). Odtworzono trzy usługi; `docker compose config`, aktywne opcje kontenerów i `GET /health` potwierdziły konfigurację oraz zdrową aplikację.
- Ograniczono publikację Nginx Hydrografa do `127.0.0.1:8080`: odtworzono kontener, potwierdzono `/health` 200 na loopbacku, brak połączenia przez adres LAN `<LAN_HOST_IP>:8080` oraz `/health` 200 przez publiczny Cloudflare Tunnel.

### W trakcie
- Brak otwartych prac przy instrukcji; jedyny zauważony błąd w sprawdzonym oknie logów to brak `/favicon.ico`.

### Następne kroki
- Udostępnić prezentację testerom i zbierać uwagi przez formularz w aplikacji. Opcjonalnie dodać favicon, by usunąć 404 z logu nginx.

### Poprzednia sesja (2026-10-29 — logowanie podczas testów)

### Co zrobiono
- Nginx miał zapełniony `tmpfs /var/log/nginx` (10 MiB), przez co nie zapisywał nowych żądań. Access/error skierowano na stdout/stderr, usunięto tmpfs logów, włączono rotację `json-file` 10 MiB × 5 plików dla nginx, API i DB. Odtworzono kontenery wymagające nowych opcji logowania, nginx przeładowano po zmianie formatu.
- Nginx zapisuje `request_id`, `request_time`, `upstream_time`, przekazuje ID do API na wszystkich trasach proxy. FastAPI zwraca `X-Request-ID` i loguje JSON ze statusem oraz `duration_ms`, również przy błędzie. Zaktualizowano konfigurację HTTP i nieaktywny szablon TLS.
- Weryfikacja: `nginx -t`, `docker compose config`, `ruff`, 7 testów API; `/health` i `/api/tiles/thresholds` 200, admin bez klucza 401, nieznana trasa 404. ID w nagłówku odpowiedzi zgadza się z logami nginx i API. API i DB zdrowe.
- Commit `8251ff8 fix(docker): rotate and correlate request logs` na osobnej gałęzi `feature/logowanie-testow` utworzonej od `develop` (bez commitów z `feature/kartograf-wykorzystanie` i bez pusha). Przegląd końcowy potwierdził wyniki testów oraz korelację ID dla odpowiedzi 200 i 404.
- Próbka logów z testów przez tunel: 2 delineacje i 17 hydrogramów zakończone 200, brak 5xx; 406 odpowiedzi 404 dla nieobecnych statycznych kafli `streams_100000` (powtarzające się współrzędne; sprawdzić pokrycie, jeśli tester zgłosi braki linii). Dla tunelu nginx widzi adres pośrednika, nie rzeczywiste IP testera. Cloudflare przekierowuje HTTP na HTTPS kodem 301 i zachowuje query; HTTPS `/` i `/health` odpowiadają 200. Do API i formularzy podawać bezpośrednio HTTPS (301 może zmienić POST na GET).

### W trakcie
- Brak otwartych zmian kodu w tej sesji; szablon nginx TLS jest zmieniony, ale pozostaje nieaktywny i bez testu z certyfikatami (TLS kończy Cloudflare).

### Następne kroki
- Zweryfikować, czy nieobecne kafle `streams_100000` wynikają z braku danych poza obszarem pokrycia, jeśli tester zobaczy brak linii w obrębie analizowanego terenu; nie ukrywać 404 bez diagnozy.
- Ustalić politykę prywatności/retencji logów i monitoring miejsca na dysku. Osobno zaplanować dashboard ruchu, jeśli potrzebne są statystyki; obecnie dostępny jest `docker compose logs`, bez realnego IP klientów tunelu.
- Zintegrować `feature/logowanie-testow` z `develop` po decyzji o merge'u. Osobna gałąź Kartografa i jej commity nie są częścią tego commita; unikać przypadkowego przebudowania obrazu z zależnościami różniącymi się między gałęziami.

### Poprzednia sesja (2026-10-08, sesja 97 — etap K: wdrożenie Kartografa v0.7.0; przepisanie historii git)

### Co zrobiono
- **Analiza Kartografa v0.7.0** (wydany 2026-10-08) i sondy empiryczne na kodzie Hydrografa: 7 testów padało (przeniesiony `providers.bdot10k`), `discover_asc_files` dublowało arkusze (hardlink + `kampanie/`), błędy pobierania NMT przechodziły po cichu, bootstrap kończył się kodem 0 przy całkowitej porażce pobrania NMT.
- **Etap K na gałęzi `feature/kartograf-0.7.0`** (plan w `notes/superpowers/plans/2026-10-08-kartograf-0.7.0-wdrozenie.md`, wykonany zespołem subagentów z recenzją per zadanie i końcową recenzją całej gałęzi): pin `@v0.7.0`; `download_sheets()` wsadowo z `MetadataCache` (`<cache_dir>/kartograf_meta.db`), `NmtDownloadReport`, jeden `NmtDownloadError` ze wszystkimi problemami naraz; bootstrap: `cache_dir` = korzeń danych Kartografa, mozaika wyłącznie z listy kroku 2, krok 2 `fail` → kod 1; walidacja `--bbox`/`--sheets` (kod 2); `hsg_poland.tif` bez zgodnego sidecara → `HsgCacheStaleError`; HSG z samych nodata nie daje „A”; `clean.py` czyści cache metadanych; KARTOGRAF.md v6.0, ADR-057 (aktualizacja), CHANGELOG.
- **Decyzje D1–D10 planu** (domyślne z planu, zatwierdzone przez kontynuację usera): D1 częściowy brak pokrycia = WARNING; D2 `unverified` = WARNING; D3 wyłączony cache = błąd; D4 stary HSG = błąd z instrukcją (równość wersji); D5 fallback HSG „B” bez zmian (do decyzji); D6 dane 0.6.1 nietknięte; D7 bootstrap z bazą — NIE wykonany; D8 `cache/soil_hsg/hsg_poland.tif` z 0.6.1 usunięty (zgoda usera); D9 `discover_asc_files` usunięte; D10 `--metadata-cache` wymagany, `--output ../cache/`.
- **Weryfikacja w kontenerze:** pobranie 2 arkuszy (układ ADR-026, kampanie, sidecar), drugi przebieg bez pobrań, brak pokrycia (całość → 1, część → 0 + WARNING), symulowana awaria sieci (pełna lista godeł), bootstrap: brak pokrycia → kod 1 przed bazą, zły bbox → 2. Obraz nie ma `gdalbuildvrt` — mozaika idzie fallbackiem `rasterio.merge`.
- **Awaria API po przebudowie obrazu:** niepinowane `sqlalchemy>=2.0.25` pobrało 2.1.4 (psycopg3 dla `postgresql://`) → crash-loop `alembic upgrade head`. Naprawa: `sqlalchemy>=2.0.25,<2.1`; API zdrowe. Backlog: migracja na 2.1 i plik constraints zależności.
- **Historia git przepisana** (`git filter-repo`, force push develop/main/tagi): usunięte szczegóły infrastruktury hosta; wszystkie hashe sprzed 2026-10-08 nieaktualne. Pozostałe ścieżki dysku danych hosta poprawione tylko w bieżących plikach (decyzja usera).
- Testy unit: 1045 passed (było 1021).

### Nastepne kroki
- Decyzja usera: merge `feature/kartograf-0.7.0` → `develop` (+ push).
- Decyzje otwarte z etapu K: D5 (fallback HSG „B” i krok 5 jako niekrytyczny), D6 (dane w układzie 0.6.1, ponowne pobranie Opolskiego w 0.7.0).
- Następny bootstrap pobierze HSG Polski od nowa (stary raster usunięty).
- Dalej: decyzje 1–16 z raportu rewizji specyfikacji (s96) → S1 → S2; S3 czeka na kolejne wydanie Kartografa (Archive, kafle SoilGrids, surowy ZIP BDOT, wersja BDOT w sidecarze, publiczne odkrywanie TERYT).

### Poprzednia sesja (2026-10-06/08, sesja 96 — przygotowanie do wdrożenia programu „jedno źródło prawdy” config/ścieżki/dane; magazyn danych)

### Co zrobiono
- **Sesje 94–95 (2026-09-28/29, bez zmian w repo):** trzy specyfikacje w `notes/superpowers/specs/`: cz. 1 konfiguracja i ścieżki (zaakceptowana, ADR-059), cz. 2 manifest przebiegów w DB (zaakceptowana, ADR-060), cz. 3 archiwum surowych danych + PMAXTP na natywnej siatce (rew. 2, niezaakceptowana, ADR-061, zamyka ADR-058).
- **Zewnętrzny magazyn danych (decyzja usera):** `<STAGING_DIR>` (zapis) = staging na wszystkie dane nieserwowane bezpośrednio przez Hydrografa (pobrania Kartografa itd.); `<ARCHIVE_DIR>` = docelowe archiwum, dane trafiają tam po ręcznej weryfikacji usera, dla agenta/aplikacji tylko odczyt. Zmienia założenie cz. 3 (archiwum zapisywane przez bootstrap).
- **Commity (bez pusha):** `118c9b1` reorganizacja docs → `docs/integrations/` + audyt KARTOGRAF v5.2 (z poprawionymi linkami `*_INTEGRATION.md`), `a029e28` usunięcie progu 1000 m² z domyślnych progów, `a0aa34e` PROGRESS s91–93.
- **Rewizja spójności 3 speców:** raport `notes/superpowers/reports/2026-10-06-rewizja-spojnosci-specow.md` — 22 rozbieżności (m.in. numeracja migracji 004 indeksy / 005 manifest / 006 archiwum, `hydrography.json` vs `/api/dataset`, semantyka `run_source_units`, wersja NMT `<rok>.<n>` vs s93), wpływ stagingu (100 GB < NMT Polski ~118 GB, uid 999 kontenera bez dostępu do udziałów, ryzyko automount), stan Kartografa 0.7.0-dev i IMGWTools względem wymagań cz. 3, szkic dokumentu nadrzędnego, 16 decyzji usera (§6).

### Nastepne kroki
- Przejść z userem 16 decyzji z §6 raportu, nanieść na specy (cz. 3 → rew. 3 z modelem staging/archiwum), napisać dokument nadrzędny.
- Implementacja cz. 1 → cz. 2 → cz. 3 na nowej gałęzi — dopiero po zakończeniu zmian usera w Kartografie.
- Montowanie udziałów pod kontener (grupa, opcje, znaczniki) — user z sudo, wg decyzji.
- Progi nadal niespójne: `bootstrap.py` `[10000, 100000]` vs `config.py`/`process_dem.py` `[10000, 100000, 1000000]`; 1000 zostało w `config.yaml.example`, `layers.js` (FALLBACK), `watershed_service.py` (eskalacja) — porządkuje cz. 1.

### Poprzednia sesja (2026-09-28, sesja 93 — pobranie NMT 5m dla województwa opolskiego z reużyciem pilotażu; wersjonowanie NMT)

### Co zrobiono
- **Reużycie pilotażu z s91:** wszystkie 964 pliki `<HOST_DATA_DIR>/nmt/pilot_opolskie/` mają nagłówek ASC zgodny z bboxem swojego godła — stary `sheet_finder` zawinił tylko doborem obszaru, nie treścią (korekta wniosku z s92). 932 z nich należą do Opolskiego (target: 3720 arkuszy z `<HOST_DATA_DIR>/nmt/boundaries/wojewodztwa/opolskie.gpkg`).
- Pułapka: pilotaż ma godła z zerami (`M-33-036-…`), Kartograf zwraca bez zer (`M-33-36-…`); `SheetParser` nie normalizuje paddingu, a `FileStorage.get_path()` buduje ścieżkę ze stringu → `skip_existing` nie widziałby plików. Pliki przeniesione (hardlink + usunięcie starej nazwy) pod ścieżki bez zer. W `pilot_opolskie/` zostało 32 pliki spoza Opolskiego (45 MB). Decyzja: zostajemy przy formie bez zer (kanoniczna w Kartografie); sortowanie naturalne (`ls -v`, `sort -V`).
- **Pobranie Opolskiego zakończone:** `<HOST_DATA_DIR>/nmt/nmt_5m/` — 3233 arkusze, 4,5 GB (932 z pilotażu + 2301 pobrane). 487 braków to arkusze całkowicie poza Polską (Czechy — Kartograf dobiera arkusze po bboxie województwa) — legit. 3 braki w Polsce były fałszywe (błędy sieci WMS) — pobrane ponownie przez `--sheets`. Log: `<HOST_DATA_DIR>/nmt/opolskie.log`.
- **Problemy z GUGiK:** `mapy.geoportal.gov.pl` (WMS skorowidzów) zrywał połączenia (173× `WMS query failed`, szczyt 12:30–12:40, potem spadek); pobieranie plików z OpenData bez błędów. Bardziej przeciążenie niż blokada (brak 429/403, tylko jedna usługa), niepewne.
- **Bug w Kartografie 0.6.1:** `_get_opendata_url()` przy błędzie sieci przechodzi do starszej warstwy skorowidza → możliwe ciche pobranie starszej edycji (92 arkusze pobrane po błędzie warstwy 2025, lista: `<HOST_DATA_DIR>/nmt/opolskie_suspect_older_2025_layer_failed.txt` — NIE zweryfikowane) albo fałszywe "No NMT 5m data" (potwierdzone: 3 przypadki).
- Backlog: 3 punkty Kartograf 0.7.0 (błąd sieci ≠ brak arkusza; sesja HTTP per zapytanie; zwracanie pełnego rekordu metadanych) + **ADR do decyzji: wersjonowanie arkuszy NMT** (manifest z pełnym rekordem skorowidza + czas pobrania; archiwum `<HOST_DATA_DIR>/nmt/archive/<produkt>/<hierarchia godła>/<aktualnoscRok>_<godło>.asc`, bez przyrostka kolizji — decyzje usera).
- Rekord skorowidza (WMS GetFeatureInfo) zawiera: `url`, `aktualnosc`, `aktualnoscRok`, `numerZgloszeniaPracy`, `zrDanych`, `bladSredniWysokosci`, `dt_pzgik` i in.; `MetadataCache` Kartografa przechowuje tylko URL.

### Nastepne kroki
- Zweryfikować 92 arkusze Opolskiego pobrane po błędzie warstwy 2025 (odpytać skorowidz, porównać `aktualnosc`/URL) i przy okazji zbudować pierwszy manifest wersji dla Opolskiego.
- Przyjąć ADR wersjonowania NMT (nadać numer 058) i zaimplementować manifest + archiwum.
- Przed pobraniem całej Polski: wspólna `requests.Session` + `MetadataCache` w `download_dem.py`, rozważyć pauzę między arkuszami / uruchomienie w nocy, ponowny przebieg na braki. → `MetadataCache` zrealizowane w etapie K (s97); wspólna sesja HTTP zapewniona wewnętrznie przez Kartograf 0.7.0 (SessionPerThread); pauza między arkuszami — niezrealizowana.
- ~~Zacommitować reorganizację docs usera~~ — zrobione w s96.
- `<HOST_DATA_DIR>/nmt/pilot_opolskie/` (32 pliki spoza Opolskiego + log) — do usunięcia, gdy user zdecyduje.

### Poprzednia sesja (2026-09-28, sesja 92 — deduplikacja logiki pobierania: wszystko przez Kartograf v0.6.1)

### Co zrobiono
- Audyt (subagenty Sonnet/Haiku): jedyne miejsca omijające Kartografa to `utils/sheet_finder.py` (własna matematyka godeł) i WFS PRG dla TERYT w `download_landcover.py`. Reszta (NMT, BDOT10k, CORINE, HSG, `cn_calculator`, bootstrap) już delegowała do Kartografa. `download_sewer.py` jest poza domeną Kartografa.
- **Krytyczny bug znaleziony przy okazji:** `sheet_finder` w skali 1:10000 dzielił arkusz 1:25000 na siatkę 2×4 zamiast zagnieżdżonego 2×2 (GUGiK/Kartograf). Ścieżki `download_dem --lat/--lon` i `prepare_area` pobierały **złe arkusze** (52.41N 16.915E, bufor 2 km: 6 starych godeł vs 9 poprawnych, zero części wspólnej). Ścieżka `--geometry` (bootstrap, pełne pobranie Polski) nie była dotknięta.
- `75dc859`: nowy `utils/sheet_lookup.py::sheets_for_point_buffer()` (WGS84→EPSG:2180 → `kartograf.find_sheets_for_bbox`), podmieniony w `download_dem.py` i `prepare_area.py`, 6 testów.
- `e9d940d`: usunięty `utils/sheet_finder.py` (~616 linii) + testy.
- `1524992`: fallback TERYT (`_discover_teryts_grid`) zależy od prywatnego `Bdot10kProvider._get_teryt_for_point`; w 0.6.1 nie ma publicznej alternatywy (publiczne metody pobierają cały GPKG powiatu). Dodano guard `RuntimeError` + test kontraktowy sygnatury.
- `6006085`: ADR-057 „Pozyskiwanie danych wyłącznie przez Kartograf” z 3 udokumentowanymi wyjątkami (WFS TERYT, post-processing merge/mozaika, sewer). Numer 057, bo 055/056 zajęte w historii przez wycofany dashboard. CHANGELOG, ARCHITECTURE, TECHNICAL_DEBT zaktualizowane. `docs/integrations/KARTOGRAF.md` zaktualizowany, ale **niezacommitowany** (część reorganizacji docs usera).
- Weryfikacja (Tester):
  - pytest 1144 passed, 1 pre-existing fail (integracyjny test bez DB na localhost);
  - dry-run `--geometry` Polska = 80 343 arkuszy (bez zmian);
  - realne pobranie 1 arkusza przez `--lat/--lon` OK.

- **Audyt `docs/integrations/KARTOGRAF.md`** (v5.1→5.2, **niezacommitowane** — część reorganizacji docs usera). Poprawione:
  - liczba kroków bootstrapu (10);
  - usunięty nieistniejący `--format`;
  - opis fallbacku TERYT;
  - §5 nomenklatura godeł (etykiety Kartografa przesunięte o poziom: `target_scale="1:10000"` = oficjalnie arkusze 1:5000; podział 2×2 zamiast błędnego 2×4; skala 1:200 000 usunięta na życzenie usera);
  - §6 przepisana na rzeczywistą ścieżkę OpenData (WMS skorowidze → ASC), WCS oznaczony jako nieużywany;
  - §9.2 test;
  - CN BUBD 77–92;
  - `soil_hsg.area_m2`;
  - przykład z `Path`.

  Stare linki do `docs/*_INTEGRATION.md` poprawione w `CLAUDE.md`, `README.md`, `CROSS_PROJECT_ANALYSIS.md`, `IMPLEMENTATION_PROMPT.md` (też niezacommitowane).

### Nastepne kroki
- Zacommitować reorganizację docs usera razem z poprawkami audytu (decyzja usera).
- Rozważyć podłączenie `MetadataCache` Kartografa w `download_dem.py` (dziś każdy arkusz = świeże zapytanie WMS GetFeatureInfo) — przed pobraniem całej Polski. → zrealizowane w etapie K (s97).
- **Dane pilotażu Opolskiego (`<HOST_DATA_DIR>/nmt/pilot_opolskie/`) z s91 pobrano błędną ścieżką `--lat/--lon`** → pokrycie niezgodne z zamierzonym; do usunięcia/ponownego pobrania, jeśli mają być użyte.
- Pełne pobranie Polski (komenda z s91 niżej) nadal czeka na zielone światło; nie wymaga zmian.
- Backlog: upstream `discover_teryts_for_bbox` + `mosaic_and_crop` przy przejściu na Kartograf 0.7.0. → ocenione w etapie K: `mosaic_and_crop` nieużyty (ADR-057 b); `discover_teryts_for_bbox` nadal brak w 0.7.0.
- Nic nie jest wypchnięte na origin.

### Poprzednia sesja (2026-09-28, sesja 91 — przygotowanie pobrania NMT 5m dla całej Polski przez Kartograf)

### Co zrobiono
- Oszacowanie rozmiaru pobrania NMT 5m dla całej Polski, zweryfikowane empirycznie na realnych danych (nie tylko teoretycznie): ~7,08 B/komórkę × 12,51 mld komórek ≈ 88 GB z geometrii kraju; ~118 GB z rzeczywistej liczby arkuszy (80 343 arkusze × ~1,47 MB) — druga wartość miarodajna dla planowania.
- Audyt miejsca na dysku: dysk systemowy za mały na to zadanie; dane NMT umieszczone na osobnym dysku danych hosta (`<HOST_DATA_DIR>/nmt`).
- **Pilotaż na Opolskiem** (tryb `--lat/--lon --buffer 55`): 964/1000 arkuszy pobrane w 24 min (1445s, ~1,45 s/arkusz), 36 legit braków pokrycia 5m przy granicy czeskiej (`vertical_crs=EVRF2007` w logu — brak danych GUGiK, nie throttling). Zero sygnałów blokowania ze strony GUGiK. Dane w `<HOST_DATA_DIR>/nmt/pilot_opolskie/` (~1,4 GB, niekompletne z powodu buga niżej — tańsze ponowne pobranie niż scalanie z pełnym przebiegiem).
- **Znalezione i naprawione 2 realne bugi** w ścieżce pobierania NMT (oba na `develop`, **niepushowane**):
  1. `backend/utils/sheet_finder.py::get_sheets_for_bbox()` — krok próbkowania w długości geograficznej (0,04°) większy od rzeczywistego arkusza 1:10000 (0,03125°), cicho gubił ~22% kolumn arkuszy bez żadnego błędu w logu. Fix: krok = połowa rozmiaru arkusza dla każdej z 4 skal. Commit `e9bfc55`.
  2. `backend/scripts/download_dem.py` (2 miejsca: `main()` gałąź `--dry-run` i `download_for_geometry()`) — `find_sheets_for_geometry()` z Kartografa wymaga `Path`, dostawał `str` → crash na starcie prawdziwego pobierania przez `--geometry` (dry-run przechodził, bo szedł inną gałęzią kodu — pierwszy fix subagenta naprawił tylko dry-run, drugie wystąpienie złapane przy własnej weryfikacji przed odpaleniem pełnego przebiegu). Fix zweryfikowany prawdziwym pobraniem end-to-end (9/9 arkuszy, nie tylko dry-run). Commit `382c5f3`.
- **Pobrano oficjalne granice województw (PRG, GUGiK):** `<HOST_DATA_DIR>/nmt/boundaries/wojewodztwa_polska.gpkg` (16 cech, EPSG:4258, atrybut nazwy `JPT_NAZWA_`, suma powierzchni 313 731 km² — zgodne z ~312 700 km² Polski, różnica z generalizacji granic). Ustalono: `kartograf.find_sheets_for_geometry()` obsługuje wiele cech w jednym pliku → **jeden przebieg na całą Polskę lepszy niż 16 osobnych** (80 343 arkuszy vs 132 169 przy 16 przebiegach osobno — arkusze graniczne liczone wielokrotnie).
- Zidentyfikowany dług techniczny dodany do Backlogu (priorytet niski): `sheet_finder.py` reimplementuje logikę bbox→arkusze, którą Kartograf ma wbudowaną i solidniejszą (`find_sheets_for_bbox()`, hierarchiczne przycinanie zamiast próbkowania punktowego) od v0.4.0/0.4.1 — właśnie tam siedział bug #1 wyżej. (→ ZREALIZOWANE w sesji naprawczej tego samego dnia: `sheet_finder.py` usunięty, zastąpiony `sheet_lookup.py` delegującym do Kartografa; zob. Backlog „Zrobione (archiwum)" i ADR-057.)

### Stan na koniec sesji — przygotowanie kompletne, pobranie NIE uruchomione
User przerwał sesję przed wydaniem zielonego światła na właściwy przebieg. Komenda gotowa do odpalenia w kolejnej sesji:
```
cd backend && .venv/bin/python -m scripts.download_dem --geometry <HOST_DATA_DIR>/nmt/boundaries/wojewodztwa_polska.gpkg --output <HOST_DATA_DIR>/nmt
```
(uruchomić w tle, log do pliku na `<HOST_DATA_DIR>/nmt`). Szacunek: **~118 GB, ~32h** ciągłego, jednowątkowego pobierania; wolne miejsce na dysku danych wystarczy. Wznawialne przez `skip_existing=True` — bezpiecznie przerwać/wznowić tą samą komendą. Working tree ma też niezwiązane, wcześniejsze niezacommitowane zmiany (config.py, bootstrap.py, process_dem.py, reorganizacja docs) — świadomie nietknięte przez wszystkie subagenty tej sesji.

> **Uwaga (Kartograf 0.7.0, etap K):** powyższa komenda pochodzi sprzed 0.7.0. Forma aktualna: `--output <HOST_DATA_DIR>` jest korzeniem danych Kartografa (pliki trafiają do `<HOST_DATA_DIR>/nmt/pl_1992_5m_evrf2007/...`) oraz wymagane `--metadata-cache <LOCAL_DIR>/kartograf_meta.db` na dysku LOKALNYM (nigdy udział sieciowy — SQLite WAL).

### Nastepne kroki
- **Uzyskać potwierdzenie usera i odpalić właściwe pobranie** (komenda wyżej) — jedyny brakujący krok.
- Po zakończeniu: zweryfikować kompletność (arkuszy pobranych vs 80 343 oczekiwanych, ile to legit braki pokrycia 5m na granicach kraju vs błędy), zdecydować o mozaikowaniu VRT / dalszym przetwarzaniu.
- (Zaległe bez zmian z poprzednich sesji): flaga `--thresholds` w bootstrapie; smoke test feedbacku; decyzja o pushu na origin; dalsza praca nad Hydraulikiem w `../Hydraulik`.

### Poprzednia sesja (2026-08-19, sesja 89 — research wykonalności pakietu Hydraulik: SFINCS/HydroMT-SFINCS)

### Co zrobiono
- **Czysta praca badawcza, zero kodu** (decyzja usera): badanie integracji modelu hydraulicznego 2D (Deltares SFINCS + HydroMT-SFINCS) jako czwartego pakietu rodziny („Hydraulik"). Cztery rundy subagentów Opus: (1) silnik SFINCS + builder HydroMT-SFINCS + mapa punktów integracji w Hydrografie, (2) siatka zmiennorozdzielcza (subgrid/quadtree) i tryb per-zlewnia z mozaiką wyników po max, (3) ograniczenia rain-on-grid, brak batymetrii NMT, założenie „zwierciadło NMT = stan odniesienia", (4) hydrogramy w zlewniach niekontrolowanych (metodyka SHP/KZGW 2020, korekta DCT, benchmarki Kłodzko 1997/2024).
- **Wniosek: integracja wykonalna i dobrze dopasowana do danych rodziny** (NMT 5 m, land_cover, HSG, PMAXTP, hydrogramy z `/api/generate-hydrograph` jako forcing 1:1). Główne ryzyka: skuteczność w małych stromych zlewniach (CSI 0.29 <50 km²), licencja GPL-3.0 hydromt_sfincs, przejście hydromt v1→v2, brak danych Manninga w Hydrografie, architektura uruchamiania silnika (kontener API read_only, bez socketa Dockera).
- **Decyzje kierunkowe usera:** cel główny = powodzie błyskawiczne w górach; CN bez recovery, bez przepływu bazowego; korekta batymetrii DCT (pomijalna numerycznie: SNq ~5 l/s/km² vs pik Q1% ~4 m³/s/km²); MVP = siatka jednolita + subgrid, model per zlewnia.
- **Utworzono projekt `../Hydraulik`** — szkielet wg schematu rodziny (CLAUDE.md, README, docs/PROGRESS.md, docs/research/, hydraulik/, tests/), git init na `main` bez commitów; celowo bez LICENSE (kwestia GPL nierozstrzygnięta) i bez pyproject (brak kodu). Raport kanoniczny: `Hydraulik/docs/research/2026-08-19-hydromt-sfincs-integracja-research.md` (kopia robocza: `notes/reports/2026-08-19-hydraulik-sfincs-research.md`).

### Nastepne kroki
- **Dalsza praca nad Hydraulikiem = dedykowany agent w repo `../Hydraulik`** (decyzja usera) — tam brainstorming → specyfikacja (`docs/superpowers/specs/`).
- Po stronie Hydrografa (dopiero gdy Hydraulik dojrzeje): tabela Manninga BDOT→n (wartości „overland"), rasteryzacja `land_cover` do 5 m, endpointy/joby scenariuszy, prezentacja map zalania (kafle XYZ / PNG overlay).
- (Zaległe bez zmian): flaga `--thresholds` w bootstrapie; docstring `watershed.py`; smoke test feedbacku; decyzja o pushu; wdrożenie planów bezpieczeństwa s87 (kolejność D → C → F+G → E1…).

### Poprzednia sesja (2026-08-10, sesja 88 — regeneracja danych: Kotlina Kłodzka, bez progu 1000)

### Co zrobiono
- **Diagnoza padu bootstrapu z 2026-08-10 17:19** (bbox `16.190–17.049°E, 50.070–50.467°N`, 560 arkuszy, 5m): proces zabity przez OOM killer w cgroupie kontenera `hydro_api` (limit 8G; `memory.peak` = limit, `oom_kill: 1` w `/sys/fs/cgroup/memory.events`) podczas polygonizacji 872 064 podzlewni progu 1000 m² na rastrze 113M komórek. 233/560 arkuszy bez pokrycia 5m (strona czeska, EVRF2007) — normalne dla bboxu przygranicznego.
- **Ponowny przebieg bez progu 1000** (drabinka retry ×3 z przesuwaniem progów o rząd wielkości nie była potrzebna — próba 1 udana): progi `[10000, 100000]`, ten sam bbox. Czas 7411 s (~2h04), wszystkie kroki ✓: 328/560 arkuszy (pobieranie z cache 171 s), 59,5M komórek w obszarze, 83 320 segmentów, landcover 59 713 obiektów (3 powiaty), HSG 58 poligonów, opady 690 punktów / 146 880 rekordów, 207 029 depresji, MVT OK, overlaye + 13 777 kafli DEM (150 MB). CatchmentGraph przeładowany automatycznie.
- **`DEFAULT_THRESHOLD_M2` 1000 → 10000** (`core/constants.py`) — hydrogram i domyślna delineacja precomputed muszą celować w najniższy istniejący próg. Hardcode progów w `bootstrap.py:540` zmieniony był tylko na czas przebiegu i wycofany (decyzja usera: edycja jednorazowa).
- **Weryfikacja usługi (finał sesji = działająca usługa):** `/health` 200; delineacja precomputed + precise OK (punkt k. Kłodzka); hydrogram pełny (SCS-CN, kompletna morfometria, area 0.06 km², CN 78); MVT streams (oba progi) / catchments / landcover z realnymi payloadami; `/api/tiles/thresholds` → `[10000, 100000]`; `dem.png` + frontend OK. Testy: **1165 passed** + znany fail środowiskowy (`test_select_stream`, brak DB na localhost).

### Nastepne kroki
- Rozważyć flagę `--thresholds` w `bootstrap.py` + pole w API admina (dziś progi hardcodowane w wywołaniu `process_dem` — bootstrap.py:540).
- Docstring `watershed.py` (linia 6) nadal mówi „BFS at 1000m²" dla trybu precise — kod używa `DEFAULT_THRESHOLD_M2`, docstring do poprawki przy okazji.
- (Zaległe): smoke test przeglądarki feedbacku; decyzja o pushu na origin; wdrożenie planów bezpieczeństwa s87 (kolejność D → C → F+G → E1…).

### Poprzednia sesja (2026-08-08, sesja 86 — audyt bezpieczeństwa całej publicznej powierzchni ataku + specyfikacja utwardzenia)

### Co zrobiono
- **Krytyczny bypass auth admina naprawiony** (wcześniejsza część sesji): `expected_key` jako query param → pełny bypass `/api/admin/*` z internetu. Fix `d7f6bd7` (`verify_admin_key` tylko `Header` + `_check_admin_key`/`_resolve_expected_key` + `secrets.compare_digest`), merge `fc6e2f2`, CHANGELOG `81312e7`. Zweryfikowany jako **kompletny** (12/12 testów, 0 ekspozycji w openapi). Raport: `notes/reports/2026-08-08-admin-security-audit.md`.
- **Niezależna weryfikacja raportu + audyt CAŁEJ publicznej powierzchni** (wieloagentowy Sonnet+Opus, workflow `wf_e9deb538-b24` / task `wodolg6s7`, 16 agentów): potwierdzono znaleziska raportu z korektami (**#4 LOW→MEDIUM** drugi wektor arbitrary-file-read; **#6 teza „brak sinka XSS" BŁĘDNA** — sink w `admin-sewer.js`; **#2 realnie aktywny**), wykryto **braki raportu**: **3× HIGH nieuwierzytelniony DoS** (delineacja precise bez limitu obszaru; kafle `2**z`; brak zoom-floor+`statement_timeout` na 3 trasach kaflowych) + MEDIUM (real_ip za tunelem, `worker_processes`/`limit_conn`, hasło DB w env, supply-chain git tagi, DoS panelu feedbacku). Sweep potwierdził **BRAK SQLi, BRAK anonimowego SSRF, brak sekretów w logach**.
- **Specyfikacja utwardzenia zapisana:** `notes/superpowers/specs/2026-08-08-public-security-hardening-spec.md` — 9 obszarów, każde znalezisko z wymaganiem naprawy (kryterium akceptacji) + wymaganiem testu, priorytetyzacją i zależnościami. To SPEC, **nie plan** — zgodnie z decyzją użytkownika niczego nie wdrażano.

### Decyzje ramowe (użytkownik, sesja 86)
- Zakres: cała publiczna powierzchnia ataku (nie tylko admin z raportu).
- **Dwa tory:** ta spec = pilne utwardzenie niezależne od modelu auth, forward-compatible; **system kont użytkowników + RBAC = OSOBNY przyszły projekt** (zastąpi klucz admina i localStorage).
- **Postura interim: BEZ bramki admina** — naprawa bugów + rate-limit + mocny klucz (zgodne z „public for now"). Panel admina świadomie osiągalny z internetu do czasu kont.

### Wpływ na przyszły dashboard ruchu
- **E1 (real_ip za tunelem) jest de facto prerekwizytem** przebudowy dashboardu: dziś `access_log` zapisuje IP tunelu dla całego ruchu z internetu → analiza per-IP ślepa. Po E1 logi niosą realny IP klienta (rozwiązuje pułapkę „realip" już odnotowaną pod rebuild). Do zaplanowania w projekcie dashboardu: anonimizacja/retencja IP (RODO), jawny `log_format` razem z real_ip, wzrost udziału 429/503 w logach (by design).

### Nastepne kroki
- **Kolejna sesja: napisanie planu naprawy** na podstawie specyfikacji (skill writing-plans) — decyzja użytkownika.
- Do potwierdzenia na żywym stacku przed naprawą: **E9** (`/docs`/`openapi.json` — sprzeczność audytorów, jeden `curl`); pomiary kosztu delineacji precise i kafli niskiego zoomu.
- Kolejność napraw wg spec: najpierw 3× HIGH DoS, potem E1 (real_ip), potem MEDIUM, na końcu LOW/INFO.
- (Zaległe z wcześniejszych sesji): smoke test przeglądarki feedbacku; decyzja o pushu na origin.

### Poprzednia sesja (2026-08-08, sesja 85 — całkowite wycofanie dashboardu ruchu: restrukturyzacja gałęzi, merge, reset usługi)

### Co zrobiono
- **Decyzja użytkownika:** dashboard ruchu (sesje 82 i 84: kontener GoAccess, dashboard `/traffic/`, proxy WebSocket `/ws`, Basic Auth, ograniczenie LAN-only, anonimizacja logów nginx, real IP z `CF-Connecting-IP`, rotacja logów, ADR-055/056) wycofany W CAŁOŚCI — do przebudowy od zera. Żaden z wycofanych commitów nie był wypchnięty na origin.
- **develop cofnięty** z `5a63519` do `3d4cff6` (ostatni commit sprzed trafficu, sesja 81). Stary czubek zachowany jako gałąź `backup/develop-pre-cleanup`.
- **Uratowane z sesji 83 (praca niezależna od trafficu):**
  - `feature/feedback` — 10 commitów formularza feedbacku (ADR-053, migracja 002) cherry-pickowanych na `3d4cff6`. Pliki kodu bit-w-bit identyczne ze starą historią (zweryfikowane diffem); różnice wyłącznie w docs (usunięte odniesienia do sesji 82) i nginx (bez stref trafficowych `ws_conn`).
  - `feature/hydraulic-length` — 8 commitów naprawy `hydraulic_length_km` (ADR-054, migracja 003) + domknięcie sesji 83. **Bazuje na `feature/feedback`** — łańcuch migracji 002→003 wymusza kolejność merge: najpierw feedback, potem hydraulic-length. Backend bit-w-bit identyczny ze starą historią.
- **Cherry-pick na develop (niezależne od trafficu):** `absolute_redirect off` w obu configach nginx (naprawa gubienia portu 8080 przy przekierowaniach katalogowych; przykład w komentarzu zmieniony na `/data`) + wpis backlogu o wolnych kaflach landcover MVT.
- **Porządki gałęzi:** usunięta wmergowana `fix/sewer-topology-rebuild`; `feat/wspolne-uwierzytelnianie` przestawiona na nowy czubek develop (nie miała własnych commitów). Bez pusha — decyzja użytkownika (wszystko lokalnie).
- **Weryfikacja:** `git grep -iE 'goaccess|traffic|htpasswd|ws_conn|logrotate|CF-Connecting'` pusty na drzewach feature/feedback, feature/hydraulic-length i develop sprzed niniejszego wpisu (sam ten opis wycofania siłą rzeczy wymienia usuwane elementy).

### Uwagi operacyjne
- Artefakty trafficu na stacku i na dysku posprzątane w trzeciej części sesji (patrz "Reset usługi" niżej) — na hoście nie zostało nic.
- **Baza ma nałożone migracje 002+003** (`alembic_version` = 003, kolumna `outlet_flow_dist_m` z backfillem, tabela `feedback` z ewentualnymi zgłoszeniami) — po wykonanych w tej sesji merge'ach kod na develop zna 001+002+003, stan zgodny (`alembic upgrade head` = no-op).

### Merge (druga część sesji, na polecenie użytkownika)
- `feature/feedback` → develop (`--no-ff`), następnie `feature/hydraulic-length` → develop (`--no-ff`) — kolejność wymuszona łańcuchem migracji 002→003. Konflikty tylko w `docs/PROGRESS.md` (sekcje sesji i backlog); nginx (absolute_redirect + strefa feedbacku) scalony automatycznie. Gałęzie feature zachowane po merge'u.

### Reset usługi (trzecia część sesji)
- Redeploy stacka z nowego develop (tryb dev z override): `docker compose up -d --remove-orphans` — kontener `hydro_goaccess` usunięty jako orphan, nginx odtworzony ze świeżym configiem (nowy kontener = świeży inode bind-mountu); db i api bez recreate (definicje bez zmian, kod API z bind-mountu `./backend`).
- Weryfikacja: `/health` i frontend 200; `/traffic/` wpada w standardowy fallback aplikacji (lokacja nie istnieje); `/api/admin/feedback` bez klucza → 401; `alembic current` w kontenerze = **003 (head)** — baza i kod zgodne.
- Usunięte pliki: `data/goaccess/` i `docker/traffic.htpasswd` (agent) oraz `data/logs/nginx/` i `/etc/logrotate.d/hydrograf` (użytkownik, sudo — potwierdzone).

### Nastepne kroki
- Smoke test przeglądarki z sesji 83 (modal "Zgłoś uwagę", panel /admin, poprawiona długość drogi spływu) — nadal zaległy.
- Decyzja o pushu na origin — cała restrukturyzacja istnieje wyłącznie lokalnie.
- Przebudowa dashboardu ruchu od zera (patrz `## Backlog` → Infrastruktura; przed startem brainstorming wymagań).

### Poprzednia sesja (2026-08-02, sesja 83 — formularz feedbacku z opt-in diagnostyka sesji + naprawa hydraulic_length_km)

### Co zrobiono
- **Spec + plan** (`.superpowers/sdd/2026-08-02-feedback-form/`, poza repo) — 9 zadan subagent-driven, realizacja pozycji backlogu J1 w wersji rozszerzonej (diagnostyka sesji zamiast prostego formularza).
- **feat(api) `21e832b`, `b9799a0`** — migracja Alembic 002: tabela `feedback` (id, created_at TIMESTAMPTZ, message TEXT CHECK 1-5000 znakow, contact TEXT CHECK <=200, page_url, user_agent, diagnostics JSONB, is_read BOOLEAN; indeks `idx_feedback_created_at` DESC), swiadomie BEZ adresu IP. `POST /api/feedback` (publiczny) — Pydantic `FeedbackRequest` z limitem 100 KB na `diagnostics`, `user_agent` z naglowka, jawny commit/rollback (pierwszy publiczny endpoint zapisujacy do bazy).
- **feat(api) `49ed5b9`** — endpointy admina: `GET /api/admin/feedback` (items+total+unread_count), `POST /api/admin/feedback/{id}/read` (od 2026-11-02 `PATCH /api/admin/feedback/{id}` z `{"is_read": bool}`), `DELETE /api/admin/feedback/{id}` za `X-Admin-Key`; CORS rozszerzony o DELETE.
- **fix(docker) `9ade8f7`** — strefa `feedback_limit` 1r/m burst=5 na `location = /api/feedback` (`docker/nginx.conf` i `docker/nginx-ssl.conf.template`).
- **feat(frontend) `2546a75`** — `frontend/js/diagnostics.js`: bufor 50 zdarzen (`map_click`/`mode_change`/`layer_change`/`api_call` z `X-Request-ID`/`js_error`) wylacznie w pamieci karty; `snapshot()` z pelna konfiguracja obszaru roboczego (mapa/tryb/zlewnia/parametry hydrogramu/linia profilu); wrapper `window.fetch` dla `/api/`.
- **feat(frontend) `a797c36`** — `frontend/js/feedback.js` + modal "Zglos uwage" w navbarze (checkbox opt-in diagnostyki, domyslnie zaznaczony, z podgladem JSON), `submitFeedback` w `api.js`, guard Escape w `app.js`.
- **feat(frontend) `4482074`** — panel `/admin`: sekcja "Zgloszenia testerow" (`admin-feedback.js` — rendering wylacznie `textContent`, XSS-safe; badge nieprzeczytanych; rozwijane szczegoly z osia czasu zdarzen; usuwanie z potwierdzeniem).
- **Testy:** 20 nowych (7 unit schematow, 6 integracyjnych POST, 7 unit admin).
- **docs `725e878`** — opis tabeli `feedback` w DATA_MODEL.md, wpis CHANGELOG.md (Unreleased/Dodane), ADR-053 w DECISIONS.md, odhaczenie pozycji J1 w tym pliku.

**Kontynuacja sesji 83 — naprawa `hydraulic_length_km` (feedback #11 z formularza uruchomionego wyzej w tej sesji):**
- **Diagnoza** (`notes/reports/2026-08-02-length-km-diagnosis.md`, zdiagnozowane i naprawione — sesja 83) — `CatchmentGraph.aggregate_stats()` liczyl `hydraulic_length_km` wzgledem zlej bazy: zlewnie zrodliskowe (~52% wszystkich podzlewni, wszystkie progi) zawyzone 3.8-19.5x (fallback bezwzgledny do ujscia calego basenu), zlewnie wielowezlowe zanizone (odejmowana zla wielkosc). Skazone: `length_km`, wskazniki ksztaltu Cw/Cf/Cl, `tc` (Kirpich) → cale hydrogramy. Granica zlewni i dane w bazie byly poprawne — blad wylacznie w interpretacji `max_flow_dist_m`.
- **feat(db) `dcee75a`** — migracja 003: kolumna `stream_catchments.outlet_flow_dist_m` (odleglosc splywu w PUNKCIE UJSCIA podzlewni [m], baza dla `hydraulic_length_km`).
- **fix(core) `aacb5f5`** — `aggregate_stats()`: `hydraulic_length_km = (max(max_flow_dist_m[indices]) − outlet_flow_dist_m[outlet]) / 1000`; fallback bezwzgledny usuniety; przy braku danych fallback ZANIZAJACY (`max_flow_dist_m[outlet]`) + warning w logu.
- **fix(core) `93a633f`** — etykieta `length_km` w GeoJSON drogi splywu liczona z tej samej bazy co morfometria (wczesniej niezalezna, niezgodna z narysowana linia).
- **feat(core) `fd184d7`** — pipeline (`_clip_and_build_path` + `db_bulk.py`) zapisuje `outlet_flow_dist_m` w przyszlych przebiegach.
- **feat(core) `fe5ab08`** — `scripts/backfill_outlet_flow_dist.py`: probkowanie `stream_distance.tif` w `ST_EndPoint(longest_flow_path_geom)`; 54390 rekordow, 0 NULL, 0 zawyzen — bez ponownego pipeline'u. Tryb precise naprawiony automatycznie (aproksymacja: baza = ujscie wezla zawierajacego klik).
- **E2E:** klik z feedbacku #11 — 6.7584 km przed naprawa, 1.6496 km po (zgodnosc z geometria 2.3%); drugi klik 2.9558 km (zgodnosc 5.4%); etykieta == `hydraulic_length_km` w obu.
- **Testy:** przepisane `TestHydraulicLength` (nowa semantyka + test regresyjny zlewni zrodliskowej), nowy `test_flow_path_geojson.py`; 1161 passed.
- **docs (ten commit)** — kolumna `outlet_flow_dist_m` w DATA_MODEL.md, wpis CHANGELOG.md (Unreleased/Naprawione), ADR-054 w DECISIONS.md, 2 nowe tickety backlogu (patrz `## Backlog`).
- **fix(core) `5a55f8d`** — porzadki po finalnym review - komentarze, docstringi, guard zerowej dlugosci (2 nowe testy, razem 1163 passed).

### Nastepne kroki
- **Wdrozenie produkcyjne (formularz feedbacku) wymaga:** `alembic upgrade head` (migracja 002) + force-recreate kontenera nginx (nowa strefa `feedback_limit` w `docker/nginx.conf`/`docker/nginx-ssl.conf.template`).
- **Wdrozenie produkcyjne (naprawa hydraulic_length_km) wymaga:** `alembic upgrade head` (migracja 003) + `python -m scripts.backfill_outlet_flow_dist` + restart API.
- **Manualny test w przegladarce** (modal "Zglos uwage" + panel admina, sekcja "Zgloszenia testerow") — nie byl mozliwy w srodowisku agentow (brak pelnego stacku/GUI w tej sesji).
- Patrz sekcja `## Backlog` — priorytet: diagnoza hietogram/hydrogram "brak danych" (jedyny twardy bug z feedbacku Kamila, bez zmian w tej sesji).

**Sesja zakonczona.** Stan stabilny (formularz feedbacku + naprawa hydraulic_length). Nastepne kroki: (1) manualny smoke test w przegladarce (modal "Zglos uwage", panel /admin sekcja zgloszen, poprawiona dlugosc drogi splywu na mapie), (2) decyzja o merge i push (checkpoint), (3) odpowiedz zglaszajacemu feedback #11.

### Poprzednia sesja (2026-07-31, sesja 81 — feedback testera Kamila, nomenklatura, naprawa DNS, konsolidacja backlogu)

### Co zrobiono
- **Analiza feedbacku testera** (`notes/feedback/Kamil.md`) — triaz 12 uwag: zadania UI/UX, kwestie danych, pomysly biznesowe. Research wykonalnosci (3 agentow): nomenklatura trywialna; zaglebienia maja pelne dane glebokosci w PostGIS (`max_depth_m` z indeksem) + ~80% logiki interakcji w martwym kodzie `depressions.js:63-146`; NMT — okno kolorow p5-p95 (81.8-114.1 m) pokrywa ~35% zakresu wysokosci, hillshade wypalony w pikselach kafelkow (rekolorowanie client-side niemozliwe).
- **feat(frontend) `c2adfd5`** — przemianowanie warstwy "Cieki" → "Linie splywu" (6 miejsc, w tym komunikat 404 w `catchment_graph.py`, ktory nadpisuje frontendowy; "Cieki BDOT10k" i etykiety morfometrii celowo bez zmian). Testy 1018/1018.
- **Diagnoza awarii pobierania NMT** (0/30 arkuszy, NameResolutionError) — zrodlo: srodowisko, nie kod. Embedded DNS Dockera z pusta lista upstream od bootu 2026-07-05 (wyscig dockerd vs dhcpcd, brak systemd-resolved). Kartograf i Hydrograf zadzialaly poprawnie.
- **fix(docker) `4e4fffc`** — `dns: [1.1.1.1, 9.9.9.9]` dla api w docker-compose.yml (celowo publiczne resolvery, bez adresow LAN) + recreate kontenera. Zweryfikowane: DNS dziala, HTTPS 200 do WMS geoportalu z kontenera. Mozna ponowic generowanie nowego obszaru.
- **docs `a6c3032`** — konsolidacja backlogu: sekcja `## Backlog` w PROGRESS.md jako jedyne zrodlo prawdy (kategorie; odhaczone nieaktualne wpisy CR4-CR11 i piramida kafelkow; striaz feedbacku Kamila; commit objal tez zalegle notatki sesji 80).
- **docs `2bd657e`** — brainstorm 14 pomyslow uzytkownika → nowa sekcja backlogu "Wlasne dane i nowe zrodla" (12 wpisow z uzasadnieniami, 3 aktualizacje istniejacych). Wizja rozstrzygnieta: tryb przegladowy nadrzedny, wlasne dane jako opcjonalne rozszerzenie projektowe. Pelna notatka: `notes/plans/2026-07-31-wlasne-dane-i-nowe-zrodla-wizja.md` (notes/ w gitignore, poza repo).
- **Decyzje uzytkownika:** morfometria — parametry sieci z faktycznych ciekow (wgrana warstwa lub BDOT10k), nie z generowanych linii splywu (realizacja odlozona); zadania stylistyczne (skala zaglebien, skala NMT) odlozone do backlogu.
- **Stan repo na koniec:** 4 commity na develop NIEPUSHOWANE (`c2adfd5`, `4e4fffc`, `a6c3032`, `2bd657e`); niezacommitowane README.md (zmiany sprzed sesji, 8 linii).

### Nastepne kroki
Patrz sekcja `## Backlog` — priorytet: diagnoza hietogram/hydrogram "brak danych" (jedyny twardy bug z feedbacku Kamila).

### Poprzednia sesja (2026-06-22, sesja 80 — naprawa EPERM przy czyszczeniu danych po migracji rootless→system Docker)
- **Diagnoza `[Errno 1] Operation not permitted: '/frontend/data/dem_tiles/8/140'`** w `/admin/cleanup` (komponent `overlays`).
- **Root cause** — pliki w `frontend/data/dem_tiles/` i `frontend/tiles/` byly wlasnoscia hostowego UID **100998** (pozostalosc po rootless Docker, gdzie kontenerowe UID 999 mapowalo sie do 100998). Po przesiadce na system dockerd (sesja 73, infra_docker_networking) kontener `hydro` startuje jako natywne UID 999. `_force_rmtree` w `backend/scripts/clean.py:106-112` robi `os.chmod()` w `onerror` — chmod wymaga zgodnosci UID lub `CAP_FOWNER`, a kontener ma `cap_drop: ALL`. Stad EPERM.
- **Fix jednorazowy** — chown w throwaway-kontenerze jako root:
  ```bash
  docker run --rm -v "$(pwd)/frontend/data:/d1" -v "$(pwd)/frontend/tiles:/d2" \
    alpine chown -R 999:999 /d1 /d2
  ```
- **Sanity-check**: `find frontend/data frontend/tiles -uid 100998` — bralo 0 wynikow po fixie. Czyszczenie z panelu admin dziala.
- **Pamiec zaktualizowana** — `lesson_docker_volume_migration.md`: poprawiono blednie oznaczone "bezpieczne" bind-mounty, dodano polecenie chown i sanity-check.

### Poprzednia sesja (2026-05-18, sesja 79 — naprawa cichej awarii reloadu CatchmentGraph po bootstrap)

- **Diagnoza 503 na `POST /api/delineate-watershed` po pomyslnym bootstrap z panelu admin** — endpoint twardo zwracal 503 gdy `cg.loaded == False`. W bazie 281,111 rekordow `stream_catchments`, ale graf in-memory nie zaladowany.
- **Root cause** — watek auto-reloadu w `admin._read_process_output` lapal wyjatki tylko do `state["log_lines"]` w pamieci procesu, nieaktywnych w `docker logs`. QueuePool timeout (15 polaczen zajetych przez polling panelu admin podczas konca bootstrap) zostawial graf w `_loaded=False` bez sladu w logach.
- **`core.catchment_graph.ensure_loaded(db)`** — nowa metoda z `threading.Lock` (double-check pattern). Endpointy doladowuja graf na zadanie gdy reload tla padnie — pierwszy user czeka ~5s zamiast dostac 503, kolejni z lockiem widza gotowy graf.
- **`watershed.py:363-368` + `hydrograph.py:72-77`** — przejscie z `if not cg.loaded:` na `if not cg.ensure_loaded(db):`. Self-heal po cichych awariach.
- **`admin._read_process_output`** — retry 3x z backoffem 1s/5s/15s na reload po bootstrap. Pokrywa transient QueuePool exhaustion. Sukces/porazka logowane przez `logger.info`/`logger.exception` — wyjatek juz widoczny w `docker logs`, nie tylko w pamieci.
- **Commit `555e801`** na `develop`: 4 pliki, +60/-17.

### Poprzednia sesja (2026-03-29, sesja 78 — naprawa admin panel + Docker permissions)

- **Fix timeout logowania do panelu admin** — dashboard `_dir_size_mb` skanowal 353k plikow przy kazdym uzyciu, dodano cache 30s (`@lru_cache` + `time.monotonic()`).
- **Fix shutil.rmtree PermissionDenied w rootless Docker** — dodano `onerror` handlery do wszystkich wywolan `shutil.rmtree` obslugujace pliki bez uprawnien zapisu.
- **Root cause: docker-compose.override.yml** — `user: "0:0"` nadpisywal `USER hydro` z Dockerfile. Root bez capabilities nie mogl modyfikowac plikow nalezacych do hydro (uid 999).
- **Pin hydro UID/GID** — ustawiono stale `UID=999`, `GID=999` w Dockerfile dla przewidywalnego ownership bind mountow.
- **Uproszczenie docker-compose.override.yml** — usunieto nieuzywane mapowania portow i nadpisanie `user: "0:0"`.
- **Audyt dokumentacji** — dalsze poprawki (kontynuacja z sesji 77).

### Poprzednia sesja (2026-03-29, sesja 77 — optymalizacja i porzadki)

- **BDOT stream matching timeout fix** — zamiana kolejnosci ST_Union/ST_Intersection w `update_stream_real_flags` (prawo rozdzielnosci). Dodano `update_stream_real_flags_all()` tworzaca temp buffer raz dla wszystkich progow. >600s timeout → 1s dla progu 100000.
- **Squash migracji** — 28 migracji Alembic (001-027 + merge) zredukowanych do jednej `001_initial_schema.py`. Usunieto 3 zduplikowane indeksy i martwa migracje 013.
- **Czyszczenie repo** — usunieto 3 deprecated skrypty (e2e_task9, export_pipeline_gpkg, export_task9_gpkg) referujace usuniety model cell_geometry (ADR-028).
- **Docker: NUMBA_CACHE_DIR** — dodano `NUMBA_CACHE_DIR=/tmp/numba_cache` w docker-compose.yml (read_only rootfs blokuje zapis do /app).
- **Audyt dokumentacji** — weryfikacja 12 plikow dokumentacji, naprawiono ~20 rozbieznosci.
- **Testy** — 1063 testow, 0 failures

### Poprzednia sesja (2026-03-28, sesja 76 — przebudowa topologii kanalizacji)

- **Przebudowa topologii sieci kanalizacyjnej (ADR-052)** — z automatycznej detekcji (snapping, kaskada kierunkow, heurystyczna detekcja outletow) na jawna topologie definiowana przez uzytkownika:
  - Nowy modul `core/sewer_topology.py` — parser + walidator topologii (ParsedTopology, parse_sewer_topology, validate_against_fdir)
  - 4 role wezlow: inlet, outlet, junction, storage (kompatybilnosc SWMM/HEC-RAS)
  - 2 formaty wejsciowe: Format A (punkty z downstream_id) i Format B (punkty + linie z from_node/to_node)
  - Walidacja strict z raportem — 11 regul + detekcja petli fdir
  - Pipeline dwufazowy: Faza 1 = czysty fdir (bez sewer) z walidacja petli, Faza 2 = burn inlets + pelna hydrologia
  - Usuniety heurystyczny kod z sewer_service.py (~530 linii): snapping, kaskada kierunkow, detekcja outletow
  - Nowy interfejs: `build_sewer_graph(topology: ParsedTopology)` zamiast starego z 4 parametrami
  - download_sewer.py: zwraca tuple `(points_gdf, lines_gdf | None)` zamiast jednego GeoDataFrame
  - config.py: nowe sekcje `field_mapping`, `role_mapping`, `source.format`
  - Migracja 027: CHECK constraint `node_type` zmieniony z `isolated` na `storage`
  - Admin API: upload zwraca `detected_format` i `layers`; config akceptuje `field_mapping`, `role_mapping`
- **Specyfikacja, plan, implementacja 13 taskow, code review, poprawki, test E2E**
- **Testy** — 1025 testow (1018 unit + 7 integration), 0 failures

### Poprzednia sesja (2026-03-27, sesja 75 — integration test sewer pipeline)

- **Integration test sewer pipeline** — 8 testow (6 in-memory + 2 DB) w `tests/integration/test_sewer_pipeline.py`
- **Bug fix: insert_sewer_data** — 2 bugi znalezione przez test integracyjny
- **Testy** — 1108 testow, 0 failures

### Poprzednia sesja (2026-03-27, sesja 74 — integracja kanalizacji deszczowej + review + pentest + audit DB)

- **Specyfikacja integracji kanalizacji deszczowej** — design doc z brainstormingiem, 15 pytan, review (23 znalezione problemy, 3 krytyczne naprawione)
- **Plan implementacji** — 12 zadan, subagent-driven development
- **Migracja DB (025)** — tabele sewer_nodes (18 kolumn), sewer_network (16 kolumn), kolumna is_sewer_augmented
- **Config** — sekcja sewer w _DEFAULT_CONFIG (enabled, burn_depth, snap_tolerance, source, attribute_mapping)
- **download_sewer.py** — modul pozyskiwania danych (file/WFS/DB/URL) z walidacja CRS
- **sewer_service.py** — SewerGraph + build_sewer_graph (snap, kaskada kierunku, scipy sparse) + burn_inlets + reconstruct_inlet_fa + route_fa_through_sewer + propagate_fa_downstream + insert_sewer_data
- **Integracja z process_dem.py** — kroki 3b i 4a-4c, sewer burning w preprocessing
- **Admin API endpoints** — `/api/admin/sewer/status`, `/upload`, `/delete`
- **MVT tiles sieci kanalizacyjnej** — `/api/tiles/sewer/{z}/{x}/{y}.pbf`
- **Frontend overlay + admin tab** — `sewer.js`, `admin-sewer.js`, warstwa na mapie
- **Code review** — 3 reviewery: spec compliance, backend quality, frontend+docs. 4 krytyczne + 9 waznych naprawionych
- **Pentest bezpieczenstwa** — 20 findings: 2 CRITICAL, 5 HIGH. SSRF protection dodana w load_from_url/wfs/database, path traversal fix w upload endpoint
- **Audyt bazy danych** — 26 findings: 2 CRITICAL, 5 HIGH. CHECK constraint bug (root_outlet_id != id), single-transaction insert, batch UPDATE is_sewer_augmented (N+1 → single spatial join), MVT query optimization
- **Testy** — 991 testow jednostkowych, 0 failures

### Poprzednia sesja (2026-03-25, sesja 73 — unified delineate-watershed endpoint)

- **Unified delineate-watershed endpoint (ADR-050)** — polaczenie `POST /api/select-stream` i `POST /api/delineate-watershed` w jeden endpoint z dwoma trybami:
  - **Precomputed** (z `threshold_m2`): snap-to-stream + BFS po grafie zlewni czastkowych (dotychczasowy select-stream)
  - **Precise** (bez `threshold_m2`): delimitacja rastrowa pyflwdir on-the-fly z RasterCache
- **RasterCache** — nowy modul `core/raster_service.py` z lazy-loading rastrow fdir/DEM/slope, thread-safe cache
- **Fix konwersji fdir** — poprawka enkodowania pit/nodata (DEM nodata mask) + wymuszenie pit dla pyflwdir.basins()
- **Frontend: jeden tryb "Wybierz zlewnię"** — usuniecie osobnego "Wygeneruj zlewnię", tryb precomputed/precise wybierany automatycznie
- **Usuniecie `to_confluence`** — parametr i metoda `traverse_to_confluence()` z CatchmentGraph
- **Pole `mode` zamiast `auto_selected`** — response zwraca `"mode": "precomputed"|"precise"`
- **Nowe parametry:** wskaznik lemniskaty Cl = π·L²/(4·A), spadek dzialu wodnego Rp = ΔH/P [‰], wspolczynnik asymetrii α (placeholder)
- **Poprawka wskaznika rzezby** — R = ΔH/√A [‰]

### Poprzednia sesja (2026-03-25, sesja 72 — aktualizacja dokumentacji)

- Refaktoryzacja code review (Wave 1-5): 14 commitow, fix duplikatu `flow_dist_m`, usuniecie martwego kodu, ekstrakcja helperow, deduplikacja watershed_service, unifikacja endpointow
- Fix WFS BBOX axis order, mosaic bbox, DEM auto-discovery (ADR-049)
- Aktualizacja dokumentacji (ARCHITECTURE, DATA_MODEL, HYDROLOG, KARTOGRAF, IMGWTOOLS, CROSS_PROJECT, SCOPE, DECISIONS, CHANGELOG)

### Poprzednia sesja (2026-03-24, sesja 70 — geometry simplification fix, CatchmentGraph invalidation, divide flow path)

- Per-polygon simplify usunięty ze stream_extraction, Invalidacja CatchmentGraph po cleanup
- Browser cache wyłączony dla danych pipeline, Divide flow path geometry (migracja 024)
- Wygładzanie Chaikin cieków w preprocessingu (ADR-047), ADR-048: Droga spływu z działu wód

### Poprzednia sesja (2026-03-24, sesja 69 — poprawki BDOT matching, main channel trace, hydraulic length, admin cleanup)

- BDOT ST_Within fix, Admin cleanup: single source of truth, DEM color mapping: percentile clipping
- Main channel trace: upstream_area_km2 (ADR-046), Hydraulic length wzgledem ujscia zlewni
- Kaskadowa eskalacja progu w select_stream
- Aktualizacja dokumentacji (ADR-046)

### Poprzednia sesja (2026-03-24, sesja 68 — finalizacja feat/bdot-stream-matching)

- WFS TERYT discovery (ADR-045), upgrade Kartograf v0.6.1, selektor rozdzielczosci NMT
- Drainage stats z BDOT, BDOT main channel tracing, GUI "brak ciekow BDOT"
- Fix overlay glownego cieku, fix DownloadManager resolution
- 899 testow, 0 failures

### Poprzednia sesja (2026-03-24, sesja 67 — BDOT matching + flow path tracing + naprawy tc)

- Upgrade Hydrolog v0.6.2 → v0.6.3 — nowe metody tc (FAA, Kerby, Kerby-Kirpich), 88 mypy fixes
- Migracja domyslnej Nash — `from_tc` (deprecated) → `from_lutz` (Lutz physiographic)
- 3 nowe metody Tc — FAA, Kerby, Kerby-Kirpich
- BDOT10k stream matching (ADR-044) — bufor 15m, overlap >= 50%, `real_channel_length_km`
- Hydraulic length preprocessing (migracja 022), sciezki splywu (migracja 023)
- 3 nowe parametry flow path: `longest_flow_path_km`, `divide_flow_path_km`, `centroid_flow_path_km`
- GUI: droga splywu, overlay cieku, informacje BDOT
- Optymalizacja BDOT matching — per-feature buffers (24s vs >90 min)
- 955+ testow, 0 regresji

### Poprzednia sesja (2026-03-23, sesja 66 — upgrade Hydrolog v0.6.3)

- Upgrade Hydrolog v0.6.2 → v0.6.3 — nowe metody tc (FAA, Kerby, Kerby-Kirpich), 88 mypy fixes, 28 nowych testów
- Migracja domyślnej Nash — `from_tc` (deprecated) → `from_lutz` (Lutz physiographic), label [deprecated] w UI
- 3 nowe metody Tc — FAA (spływ pow., C z CN), Kerby (retardance), Kerby-Kirpich (composite)
- 923 testy, 0 regresji

### Poprzednia sesja (2026-03-23, sesja 65 — hietogram split + weryfikacja + naprawa anomalii)

- Wydzielenie hietogramu do osobnej zakładki — akordeon, selektor rozkładu, parametry alfa/beta
- Auto-regeneracja wykresów (debounce 300ms), hietogram słupkowy z opadem efektywnym
- Bilans wodny przeniesiony do hietogramu, weryfikacja 72 testów
- Fix A2: imperviousness w Nash, Fix A3: tc NRCS zawyżone (channel_slope → mean_slope)
- 797 testów, 0 regresji

### Poprzednia sesja (2026-03-19, sesja 63 — fix topologii merge zlewni)

- Fix nieciągłości topologii — ST_SnapToGrid, buffer 2.0m, ST_Buffer(0) zamiast ST_MakeValid
- Fix brakujących kafli MVT — no-store dla pustych kafli, zawsze regeneruj DEM tiles
- 721 testów

### Poprzednia sesja (2026-03-18, sesja 62 — H4 monotonic stream smoothing)

- ADR-041: monotoniczne wygładzanie cieków — `smooth_streams_monotonic()`, running-minimum downstream
- Refaktoryzacja `burn_streams_into_dem()` — wydzielenie `_load_stream_geometries()`
- Integracja w `process_dem.py`: krok 3b, `--no-smooth-streams` flag
- Zmiana `burn_depth_m` z 10/5m na 2.0m
- 28 testów (16 helpers + 12 main)

### Poprzednia sesja (2026-03-17, sesja 61 — optymalizacja select-stream + pipeline fixes)

- ADR-042: Optymalizacja select-stream dla duzych zlewni — batched union z pre-simplifikacja, uproszczona granica dla LC/HSG, indeks kompozytowy. 95 km²: 24s → 7s, 674 km²: timeout → 7s
- CatchmentGraph auto-reload po zakonczeniu bootstrap z panelu admin
- Fix brakujacych arkuszy NMT — `bootstrap.py` uzywa `kartograf.find_sheets_for_bbox()` (91 → 192 arkuszy)
- Tippecanoe zoom limit — threshold 1000 catchments: Z14-18 zamiast Z8-18 (7.5h → 6.5 min)
- H4 design spec — monotoniczne wygladzanie ciekow (ADR-041, backlog, zatwierdzony)
- Migracja 018: indeks `(threshold_m2, segment_idx)` na `stream_catchments`
- 686 testow jednostkowych, 0 regresji

### Poprzednia sesja (2026-03-09, sesja 59 — vector boundary file support ADR-040)

- ADR-040: obsługa plików wektorowych jako obszar analizy
- Nowy moduł `core/boundary.py`: ładowanie SHP/GPKG/GeoJSON, walidacja, union, reprojekcja WGS84
- CLI: `--boundary-file` / `--boundary-layer` w bootstrap.py
- API: `POST /api/admin/bootstrap/upload-boundary`
- Frontend admin: toggle bbox/boundary, upload z podglądem

### Poprzednia sesja (2026-03-03, sesja 56 — release CP4 v0.4.0)

- Fix 35 błędów ruff lint w 15 plikach (E501, I001, F841, F401, SIM105, UP024)
- Aktualizacja wersji na v0.4.0 w `pyproject.toml`
- Aktualizacja CHANGELOG.md — zamknięcie sekcji [Unreleased] jako [0.4.0]
- Merge `develop` → `main`, tag `v0.4.0`
- 778 testów jednostkowych, 0 regresji, 0 błędów ruff

### Poprzednia sesja (2026-03-03, sesja 55 — code review CR5/CR9/CR10)

- CR10: zamiana `traceback.print_exc()` na `logger.error(exc_info=True)`
- CR9: fix cascade threshold mismatch — re-agregacja statystyk po eskalacji progu
- CR5: implementacja analizy GeoPackage land cover w `get_land_cover_stats()`
- 778 testów (było 644), 134 nowe testy

### Poprzednia sesja (2026-03-02, sesja 54 — cleanup extension + HSG Poland-wide cache)

- Fix: dodano `*.geojson` do wzorców czyszczenia overlays (panel admin)
- Feat: nowy target cleanup `processed_data` (typ `multi_dir`) dla `data/nmt/` i `data/hydro/`
- Feat: HSG Poland-wide cache — jednorazowe pobranie `hsg_poland.tif` dla całej Polski (~2-5 MB)
- ADR-038: HSG Poland-wide cache + cleanup extension
- 644 testów jednostkowych, 0 regresji

### Poprzednia sesja (2026-03-02, sesja 53 — separacja cache/data + Kartograf v0.5.0)

- Upgrade Kartograf z v0.4.1 na v0.5.0 (usunięcie parametru `category`, filtrowanie warstw hydro w merge)
- Separacja cache/data w bootstrap.py (surowe dane → `/cache/`, przetworzone → `/data/`)
- Deduplikacja pobierania BDOT10k (1x zamiast 2x)
- Docker: volume mount `/cache` (ro prod, rw dev)
- ADR-037, fix OT_ prefix, fix cache_dir resolution
- Test e2e: pełny pipeline dla 1 arkusza 1:25k, 10912 segmentów

### Poprzednia sesja (2026-03-02, sesja 52 — hardening kontenerow Docker)

Hardening konteneryzacji Docker (ADR-036). Wszystkie zmiany czysto infrastrukturalne — bez zmian logiki biznesowej. 633 testow przechodzi.

### Poprzednia sesja (2026-03-02, sesja 51 — uzupelnienie konteneryzacji)

Analiza i uzupelnienie brakujacych elementow konteneryzacji. Multi-stage Dockerfile, entrypoint.sh, healthcheck, dev/prod overrides, ADR-035.

### Poprzednia sesja (2026-03-02, sesja 50)

Redesign bbox input w panelu administracyjnym — 4 pola kompasowe (N/S/W/E) + interaktywny map picker (Leaflet w modalu Bootstrap). 8 commitow na develop.

### Poprzednia sesja (2026-03-02, sesja 49)

Naprawa 6 krytycznych bugow (CR4, CR6, CR7, CR8, S5.3, Auth) w trybie rownoleglych zespolow subagentow (3 feature branches + merger). 13 nowych testow, 742 lacznie. 12 commitow na develop.

### Poprzednia sesja (2026-03-01, sesja 48)

Panel administracyjno-diagnostyczny (ADR-034): 8 nowych endpointow `/api/admin/*`, frontend `/admin`, 48 nowych testow, 729 lacznie. 12 commitow na develop.

### Poprzednia sesja (2026-03-01, sesja 47)

Realizacja 6 zadan sredniego priorytetu w trybie subagent-driven development (6 galezi feature, merge do develop). 109 nowych testow, 672 lacznie.

- **Team 1 — Testy scripts/ (83 nowe testy jednostkowe):**
  - `test_dem_color.py` (15 testow): `build_colormap()`, `compute_hillshade()` — weryfikacja numpy outputs, wymiary, zakresy wartosci
  - `test_sheet_finder.py` (32 testy): `get_sheet_1to10k_id()`, `get_sheet_1to25k_id()`, koordynaty ark. map polskich (graniczne, srodki, zakresy)
  - `test_import_landcover.py` (16 testow): `map_bdot_class()`, `extract_landcover_polygons()` — mapowanie klas BDOT10k na kategorie CN
  - `test_bootstrap.py` (20 testow): `parse_bbox()`, `StepTracker` — walidacja bbox, next/skip/retry, sekwencje krokow

- **Team 2 — Wygladzanie granic zlewni (ADR-032):**
  - `ST_SimplifyPreserveTopology(5.0)` + `ST_ChaikinSmoothing(3 iteracje)` w `merge_catchment_boundaries()` (watershed_service.py)
  - Eliminacja schodkowych krawedzi rastrowych, gladkie krzywe zamiast ortogonalnych krokow 5m
  - Tolerancja simplify w `stream_extraction.py`: `cellsize` → `2*cellsize`
  - 4 testy w `test_boundary_smoothing.py`, ADR-032

- **Team 5 — Warstwa tematyczna: pokrycie terenu (BDOT10k):**
  - Nowy endpoint MVT `/api/tiles/landcover/{z}/{x}/{y}.pbf` (tiles.py)
  - Frontend: `loadLandCoverVector()` w map.js, `addBdotOverlayEntry()` w layers.js
  - 8 kategorii kolorow, legenda, suwak przezroczystosci, lazy-load, pane z-index 260
  - 4 testy w `test_tiles_landcover.py`

- **Team 6 — Konfiguracja YAML pipeline:**
  - `load_config()`, `_deep_merge()`, `get_database_url_from_config()` w `core/config.py`
  - Szablon `config.yaml.example` (database, DEM, paths, steps, custom sources)
  - Flaga `--config` w `bootstrap.py`, `config.yaml` w `.gitignore`
  - 14 testow w `test_yaml_config.py`

- **Team 3 — Piramida kafelkow DEM + multi-directional hillshade:**
  - `compute_hillshade()` w `utils/dem_color.py`: 4 kierunki oswietlenia (NW 40%, NE 20%, SE 20%, SW 20%)
  - `generate_dem_tiles` wlaczony do `step_overlays()` w `bootstrap.py` (step 9)
  - Domyslny max zoom: 18→16, cache (pomija jesli kafelki istnieja)

- **Team 4 — Podniesienie budynkow w NMT (ADR-033):**
  - `raise_buildings_in_dem()` w `core/hydrology.py` (+5m pod obrysami budynkow z BDOT10k BUBD)
  - Nowy parametr `building_gpkg` w `process_dem()`
  - 4 testy w `test_building_raising.py`, ADR-033

- **Dokumentacja:** ADR-032, ADR-033, CHANGELOG, PROGRESS
- **Git:** 6 feature branches merged do develop, 3 konflikty CHANGELOG + 1 DECISIONS rozwiazane

### Regeneracja danych (kontynuacja sesji 47)

Usuniecie starych danych generowanych (frontend/data, frontend/tiles, dem_mosaic, hydro_merged) + TRUNCATE 6 tabel DB. Bootstrap z bbox `16.9279,52.3729,17.3825,52.5870`:

| Krok | Czas | Wynik |
|------|------|-------|
| Pobieranie NMT | 125s | 91 arkuszy (43 nowe, 48 z cache) |
| Przetwarzanie NMT | 1949s | 54.5M komorek (6626×8218 @5m), 246,357 segmentow |
| Pokrycie terenu | 154s | 112,313 obiektow, 6 powiatow |
| Dane glebowe HSG | 2s | 197 poligonow |
| Opady IMGW | 141s | 192 stacje, 8,064 rekordow |
| Depresje | 45s | 338,690 depresji |
| Kafelki MVT | 214s | 3 progi (1k, 10k, 100k) |
| Overlay PNG | 93s | DEM + DEM tiles + streams |
| **Razem** | **2724s** (~45 min) | |

### Nastepne kroki
1. CP5: MVP — pelna integracja, deploy
2. Code review CR4-CR11 (wazne)
3. Rozwazyc podwojna analize NMT (z/bez bezodplywowych) — nowy punkt backlog

### Poprzednia sesja (2026-02-25, sesja 46)

- **Flaga `--waterbody-mode` do sterowania obsluga zbiornikow wodnych (ADR-031):**
  - Nowe parametry `waterbody_mode` i `waterbody_min_area_m2` w `classify_endorheic_lakes()` (core/hydrology.py)
  - 3 tryby: `auto` (istniejace zachowanie BDOT10k), `none` (pomin klasyfikacje), sciezka do custom `.gpkg`/`.shp` (wszystkie endoreiczne)
  - `min_area_m2` filtruje male zbiorniki po powierzchni (dziala z auto i custom)
  - Parametry propagowane przez: `process_dem.py`, `bootstrap.py`, `prepare_area.py` (CLI + sygnatury funkcji)
  - 5 nowych testow w `test_lake_drain.py::TestWaterbodyMode`, 563 testow passed
  - Dokumentacja: ADR-031, scripts/README.md, PROGRESS, CHANGELOG
- **Backlog: punkt o podwojnej analizie NMT (z/bez obszarow bezodplywowych)**

### Poprzednia sesja (2026-02-24, sesja 45)

- **Usuniecie progu FA 100 m² z systemu (ADR-030):**
  - Prog 100 m² generowal ~2.5M segmentow ciekow (90% tabeli stream_network), bez odpowiednich zlewni czastkowych (usuniete w ADR-026), wydluzal pipeline o ~50%, zajmowal ~2 GB w bazie
  - Zmiana: `DEFAULT_THRESHOLDS_M2 = [100, 1000, 10000, 100000]` → `[1000, 10000, 100000]` (3 progi)
  - Domyslny `stream_threshold` zmieniony z 100 na 1000 we wszystkich skryptach i modulach core (10 plikow produkcyjnych)
  - Migracja Alembic 017: `DELETE FROM stream_network WHERE threshold_m2 = 100` + `DROP INDEX idx_stream_geom_t100/idx_catchment_geom_t100`
  - Testy zaktualizowane (4 pliki testowe), 558 testow passed
  - Dokumentacja: ADR-030, CHANGELOG, PROGRESS, README, scripts/README

### Poprzednia sesja (2026-02-24, sesja 44)

- **Fix statement_timeout dla bulk INSERT (2.5M segmentow stream):**
  - Dodano `override_statement_timeout(600s)` wrapper w `insert_stream_segments()` i `insert_catchments()` w `core/db_bulk.py` — domyslny timeout 30s byl za krotki przy 2.5M+ rekordow
- **Pelny bootstrap pipeline (10 arkuszy, 5m NMT):**
  - 18.9M komorek (4610×6059 przy 5m), mozaika VRT ze 100 plikow ASC
  - pyflwdir ukonczony w ~8 min (vs OOM przy rozdzielczosci 1m z 698M komorek)
  - DB: stream_network 2,780,056 segmentow (4 progi), stream_catchments 264,548, depressions 385,567, land_cover 101,237, precipitation 7,560, soil_hsg 121
  - Kafelki MVT wygenerowane (tippecanoe), overlay PNG (DEM + streams)
  - Calkowity czas pipeline: 2969s (~49 min)

### Poprzednia sesja (2026-02-22, sesja 42)

- **Naprawa 5 bugow UX (E1, E4, E12, E13, F2) — 3 rownolegle zespoly + 1 sekwencyjny:**
  - **E1 — Dziury na granicach zlewni:** `merge_catchment_boundaries()` w `watershed_service.py` — usunieto `ST_SnapToGrid(geom, 0.01)` (przesuwalo wierzcholki tworzac mikro-luki), zastapione buffer-debuffer (0.1m/-0.1m) ktory zamyka luki zachowujac rozmiar. `MIN_HOLE_AREA_M2`: 1000→100 m² (agresywniejsze usuwanie artefaktow merge).
  - **E4 — Outlet poza granica zlewni:** nowa funkcja `ensure_outlet_within_boundary()` w `watershed_service.py` — snap outleta do najblizszego punktu na granicy gdy wypada poza (tolerancja 1m). Zastosowanie w `select_stream.py` i `watershed.py`.
  - **E12 — Legenda HSG:** `createHsgLegend()`/`removeHsgLegend()` w `map.js` — 4 pozycje (A/B/C/D) z kolorami HSG_FILL, auto show/hide. Callbacki `onShow`/`onHide` w `addBdotOverlayEntry()` w `layers.js`.
  - **E13 — Fill brakujacych pikseli HSG:** `distance_transform_edt` nearest-neighbor fill w `step_soil_hsg()` w `bootstrap.py` — wypelnia luki w rasterze HSG na terenach zurbanizowanych przed polygonizacja.
  - **F2 — Snap-to-stream hybrydowy:** nowa funkcja `find_nearest_stream_segment_hybrid()` w `watershed_service.py` — priorytet: `ST_Contains` na `stream_catchments` (zlewnia pod kursorem), fallback: globalny `ST_Distance` snap. Zastosowanie w `select_stream.py`.
  - **Testy:** 8 nowych testow (4 outlet boundary, 2 hybrid snap, 1 HSG fill, 1 SQL inspect), 558 passed total, ruff clean
  - **4 commity** na feature branch, merge do develop

### Poprzednia sesja (2026-02-22, sesja 41)

- **CR3 — Cursor leak w `CatchmentGraph.load()` (catchment_graph.py):**
  - Named cursor `catchment_graph_load` nie byl zamykany gdy wyjatek wystapil w petli fetchmany — trzymal otwarta transakcje PostgreSQL
  - Opakowanie w `try/finally` z `cursor.close()` w `finally`
  - 550 testow passed, ruff clean

### Poprzednia sesja (2026-02-22, sesja 40)

- **CR2 — O(n²) → O(n) w `compute_downstream_links()` (stream_extraction.py):**
  - Zamiana `segments.index(seg) + 1` na `enumerate(segments, start=1)` — eliminacja ~1.6 mld porównan dla ~40k segmentów
  - 550 testów passed, ruff clean

- **CR1 — Naprawa krytycznego bugu: channel_slope z dlugosci glownego cieku (ADR-029):**
  - **Problem:** `channel_slope_m_per_m` obliczany z calkowitej dlugosci sieci rzecznej (suma WSZYSTKICH segmentow upstream) zamiast z dlugosci glownego cieku. Spadek zanizony 2-10x → czas koncentracji zawyZony → szczyt wezbrania zanizony.
  - **Rozwiazanie:** Nowa metoda `CatchmentGraph.trace_main_channel()` — traweruje upstream od outletu wg rzedu Strahlera (tie-break: max stream_length, max area). O(path_length), <1ms.
  - **Naprawione 3 miejsca:** `catchment_graph.py`, `watershed_service.py`, `select_stream.py`
  - **Testy:** 6 nowych testow (5 w test_catchment_graph.py, 1 w test_watershed_service.py), 550 passed total
  - `aggregate_stats()["stream_length_km"]` nadal zwraca sume calej sieci (drainage density)

### Poprzednia sesja (2026-02-22, sesja 39)

- **Audyt dokumentacji (16 plikow, ~35 problemow naprawionych):**
  - 5 rownoleglych subagentow: architektura+data model, PRD+SCOPE+CHANGELOG, DECISIONS+TECH_DEBT+QA, integracje+README, spojnosc krzyzowa+CLAUDE.md
  - **Krytyczne naprawy (8):**
    - `flow_graph.py`: DEPRECATED → USUNIETY (ADR-028) w CLAUDE.md, ARCHITECTURE.md, QA_REPORT.md, COMPUTATION_PIPELINE.md
    - `flow_network`: oznaczona jako USUNIETA w schematach DB (ARCHITECTURE.md, COMPUTATION_PIPELINE.md)
    - Dodano `soil_hsg.py` i `bootstrap.py` do struktur modulow (CLAUDE.md, scripts/README.md)
    - CatchmentGraph stats: ~117k/5MB → ~44k/0.5MB (CLAUDE.md, ARCHITECTURE.md)
    - ADR-024/025 oznaczone jako Superseded przez ADR-026 (DECISIONS.md)
    - Dodano `segment_idx` do schematu stream_network (ARCHITECTURE.md)
    - Dodano 7 brakujacych endpointow API do PRD.md
  - **Wazne naprawy (10):**
    - Liczba testow: 538/559 → 544 (QA_REPORT.md, PROGRESS.md)
    - Profil terenu przeniesiony z OUT do IN scope (SCOPE.md)
    - P1.x flow_network oznaczone jako ZREALIZOWANE (TECHNICAL_DEBT.md)
    - Dodano ADR-026/027/028 do tabeli QA_REPORT.md
    - Migracje 13 → 16, endpointy 7 → 10 (QA_REPORT.md)
    - Nowa sekcja soil_hsg w DATA_MODEL.md (migracja 016)
    - Dodano bootstrap.py do scripts/README.md
  - **Srednie naprawy (12):** CHANGELOG duplikat [Unreleased], daty SCOPE/HYDROLOG, Hydrolog v0.5.1→v0.5.2 w CROSS_PROJECT, uproszczenie isinstance w KARTOGRAF, CP4 emoji w README

- **Testy:** 544 passed, 0 failures (zweryfikowane pytest --collect-only)
- **1 commit** w sesji

### Poprzednia sesja (2026-02-17, sesja 37)

- **Naprawa 3 bugów po teście E2E (10 arkuszy):**
  - **Bug A — BDOT10k spacing:** `spacing_m` w `discover_teryts_for_bbox()` zmniejszony z 5000 na 2000m (gęstsza siatka punktów → lepsza detekcja małych TERYT-ów). Logi point→TERYT podniesione z DEBUG na INFO.
  - **Bug B — cieki MVT znikają przy oddaleniu:** 4-częściowa naprawa:
    - tippecanoe: `--drop-densest-as-needed` → `--coalesce-densest-as-needed` + `--simplification=10` (łączenie features zamiast usuwania)
    - Nowa funkcja `extract_mbtiles_to_pbf()` — ekstrakcja .mbtiles do statycznych `{z}/{x}/{y}.pbf` z dekompresją gzip
    - `tiles_metadata.json`: format `"mbtiles"` → `"pbf"`
    - `map.js`: `getTileUrl()` obsługa formatu `"pbf"` → `/tiles/{layer}_{threshold}/{z}/{x}/{y}.pbf`
  - **Bug C — wygładzony profil terenu:** `tension: 0.2` → `tension: 0` w charts.js (wyłączenie interpolacji Béziera)

- **Re-run BDOT10k hydro + regeneracja kafelków:**
  - Hydro: TERYT 3021 (8.0 MB) + 3064 (1.4 MB) → merged 12,321 features (bez zmian — dane 3064 faktycznie uboższe w obszarze miejskim)
  - Kafelki: 64,533 PBF tiles (4 progi × streams + catchments), 18 min (dominuje threshold 100: 390k features → 16 min tippecanoe)
  - Fix krytyczny: pliki PBF z mbtiles są gzip-compressed — dodano dekompresję w `extract_mbtiles_to_pbf()`

- **Testy:** 538 passed, 0 failures

### Poprzednia sesja (2026-02-17, sesja 36)

- **Test E2E bootstrap.py z rozszerzonym obszarem NMT (10 arkuszy):**
  - Reset bazy danych (`docker compose down -v`) + pełny bootstrap od zera
  - 10 arkuszy wejściowych → 16 arkuszy 1:10k (2 nowe arkusze 1:25k rozwinięte na 4+4)
  - Raster: 9500×8754 = 83.2M komórek (vs 43.5M poprzednio, +91%)
  - Czas całkowity: **1741.4s (~29 min)** vs 657.6s (~11 min) dla 8 arkuszy
  - NMT processing: 975.3s (sublinearny: +91% danych → +48% czasu)
  - Baza: 434,877 stream segments, 44,593 catchments, 2,239,703 depresji, 50,406 land cover, 1,050 precipitation
  - Health check OK, serwer pod http://localhost:8080
  - Raport: `data/e2e_report_sesja36.md`

### Poprzednia sesja (2026-02-17, sesja 35)

- **Naprawa 6 bugów UX (E5, E6, E9, E10, E11, F3) — 5 równoległych subagentów:**
  - **E5+E10 — Chart.js resize w ukrytych kontenerach:** `resizeChart()` w charts.js, accordion handler z 50ms setTimeout, profil terenu: d-none usunięte PRZED renderowaniem, canvas owinięty w `.chart-container`
  - **E6 — Liquid glass na panelu profilu:** dodane tokeny CSS (`--liquid-bg`, `--liquid-blur`, `--liquid-border`, `--liquid-shadow`, `--liquid-highlight`) do `#profile-panel` w style.css
  - **E9 — Usunięcie wpisu "Zlewnia" z panelu warstw:** ~101 linii usunięte z layers.js (zmienne, blok budowy, eksport), 3 wywołania `notifyWatershedChanged()` usunięte z app.js
  - **E11 — Dyskretna skala kolorów zagłębień:** YlOrRd paleta (żółty→pomarańczowy→czerwony) z 5 progami wg `volume_m3` (<1, <10, <100, <1000, ≥1000 m³) w depressions.js
  - **F3 — Fallback progu 100→1000 w select-stream:** automatyczna eskalacja progu gdy `threshold < DEFAULT_THRESHOLD_M2`, nowe pole `info_message` w `SelectStreamResponse`, banner informacyjny w app.js
  - Wszystkie 538 testów przechodzą, ruff clean

- **Naprawa krytycznego bugu CDN:**
  - Hash integralności Chart.js 4.4.7 był nieprawidłowy — blokował ładowanie WSZYSTKICH wykresów (profil terenu, pokrycie terenu, hipsometria)
  - Naprawiony hash w index.html, pozostałe 4 CDN hashe (Leaflet, Bootstrap CSS/JS, VectorGrid) zweryfikowane OK

- **Skrypt weryfikacji hashów SRI (`scripts/verify_cdn_hashes.sh`):**
  - Parsuje index.html (perl), pobiera zasoby CDN, oblicza hash (openssl), porównuje z deklarowanym
  - Tryb `--fix` automatycznie naprawia nieprawidłowe hashe
  - Exit code 1 przy niezgodności — gotowy do CI

- **Integracja CDN w bootstrap.py (krok 1d):**
  - Weryfikacja hashów SRI jako część kroku infrastruktury
  - Warning-only (nie blokuje pipeline), loguje "CDN HASH MISMATCH" przy niezgodności

- **9 commitów** w sesji, branch `develop`

### Poprzednia sesja (2026-02-17, sesja 34)

- **Reset bazy danych + pelny bootstrap (8 arkuszy NMT):**
  - `docker compose down -v` → pelny bootstrap z `scripts/bootstrap.py --sheets ...`
  - Czas calkowity: 657.6s (~11 min)
  - Wyniki: 39.4M cells, 220944 stream segments, 50406 land cover, 630 precipitation, 1125699 depressions
  - Serwer uruchomiony: http://localhost:8080, health OK

- **Instalacja tippecanoe via pip + poprawki skryptow:**
  - `pip install tippecanoe` (v2.72.0) — zainstalowany w `.venv/bin/`
  - `bootstrap.py`: szuka tippecanoe w `.venv/bin/` oprócz systemowego PATH
  - `generate_tiles.py`: szuka tippecanoe w `.venv/bin/`, przekazuje pelna sciezke do `run_tippecanoe()`, pomija puste eksporty (0 features — np. catchments dla progu 100 m² zgodnie z ADR-026)

- **Generacja kafelkow MVT (tippecanoe):**
  - 4 progi: 100, 1000, 10000, 100000 m²
  - 7 plikow `.mbtiles` (streams × 4, catchments × 3 — brak catchments dla progu 100)
  - Czas: 95.2s

### Poprzednia sesja (2026-02-17, sesja 33)

- **Eliminacja tabeli flow_network (ADR-028, migracja 015):**
  - Tabela `flow_network` przechowywala ~39.4M rekordow (dane kazdego piksela DEM) — zadne API endpoint nie czytalo z niej w runtime
  - Migracja 015: `DROP TABLE flow_network`
  - Pipeline DEM pomija krok INSERT flow_network — oszczednosc ~17 min (58% czasu pipeline)
  - Pipeline 8 arkuszy: ~29 min → ~12 min

- **Usuniecie ~1000 linii martwego kodu:**
  - `core/flow_graph.py` — caly modul (~360 linii, DEPRECATED od ADR-022)
  - `core/db_bulk.py` — 4 funkcje flow_network: `create_flow_network_tsv()`, `create_flow_network_records()`, `insert_records_batch()`, `insert_records_batch_tsv()` (~580 linii)
  - `core/watershed.py` — 5 legacy CLI functions: `find_nearest_stream()`, `check_watershed_size()`, `traverse_upstream()`, `_traverse_upstream_inmemory()`, `_traverse_upstream_sql()`
  - ~43 testow powiazanych z flow_network/flow_graph

- **Aktualizacja 4 skryptow CLI** z zapytaniami SQL na flow_network:
  - `analyze_watershed.py`, `e2e_task9.py`, `export_pipeline_gpkg.py`, `export_task9_gpkg.py` — przepisane na stream_network

- **Testy:** 538 testow (bylo 581), 0 failures, ruff clean
- **8 commitow** w sesji

### Poprzednia sesja (2026-02-17, sesja 32)

- **Naprawa blednej selekcji zlewni (ADR-027, 6 plikow, 581 testow):**
  - **Przyczyna glowna (2 bugi):**
    1. `find_nearest_stream_segment()` uzywala `id` (auto-increment PK) zamiast `segment_idx` — lookup w grafie zawisze zwracal None
    2. `ST_Contains` na `stream_catchments` moze trafic w sasiednia zlewnie przy kliknieciu blisko konfluencji
  - **Naprawa:** snap-to-stream (`ST_Distance` na `stream_network`) → `lookup_by_segment_idx()` O(1) → BFS, z ST_Contains jako fallback
  - **Nowe metody CatchmentGraph:** `lookup_by_segment_idx()`, `verify_graph()` (diagnostyka przy starcie)
  - **Usuniety martwy kod:** `find_stream_catchment_at_point()` w `watershed_service.py`
  - **Testy:** 581 testow, 0 failures, ruff clean

- **Reset bazy danych + pelny bootstrap:**
  - `docker compose down -v` → `docker compose up -d db`
  - `bootstrap.py --sheets` z istniejacymi 8 arkuszami NMT (~30 min)
  - Dane: flow_network 39.4M, stream_network ~221k (4 progi), stream_catchments ~22.6k (3 progi)

### Poprzednia sesja (2026-02-16, sesja 31)

- **Stream burning w bootstrap.py (rozszerzenie kroku 3):**
  - `step_process_dem()` pobiera teraz hydro BDOT10k (per-TERYT) i scala pliki przed przetwarzaniem DEM
  - Nowa funkcja `merge_hydro_gpkgs()` w `download_landcover.py` — scala multi-layer GeoPackage z zachowaniem warstw (SWRS, SWKN, SWRM, PTWP)
  - Graceful degradation: jesli download/merge fail → process_dem bez burning
  - Pipeline re-run: 1763s (~29.4 min), 706143 komorek wypalonych, 12321 features hydro z 2 powiatow (3021, 3064)
  - 5 nowych testow `merge_hydro_gpkgs`, lacznie 577 testow, 0 failures
  - Udokumentowane waskie gardla w `TECHNICAL_DEBT.md` (P1.x): bulk INSERT 58% czasu, pyflwdir 16%

- **`scripts/bootstrap.py` — jednokomendowy setup srodowiska (~460 linii):**
  - Nowy skrypt orkiestratora: 9 krokow pipeline'u od zera do dzialajacego systemu
  - Dwa tryby wejscia: `--bbox "min_lon,min_lat,max_lon,max_lat"` lub `--sheets GODLO1 GODLO2`
  - 7 flag `--skip-*`, `--dry-run`, `--port`

- **`docker-compose.yml` — konfigurowalny port nginx:**
  - `"8080:80"` → `"${HYDROGRAF_PORT:-8080}:80"`

- **Testy:** 560 testow, 0 failures, ruff clean.

### Poprzednia sesja (2026-02-16, sesja 30)

- **Auto-selekcja dużych zlewni w trybie "Wygeneruj":**
  - Gdy powierzchnia zlewni > 10 000 m² (0.01 km²), endpoint automatycznie przełącza wyświetlanie na styl selekcji (pomarańczowa granica + podświetlone zlewnie cząstkowe MVT) z banerem informacyjnym.
  - Nowa stała `DELINEATION_MAX_AREA_M2 = 10_000` w `core/constants.py`.
  - 4 nowe pola w `DelineateResponse`: `auto_selected`, `upstream_segment_indices`, `display_threshold_m2`, `info_message`.
  - Kaskadowe progi merge (>500 segmentów) w `watershed.py` — wzorzec z `select_stream.py`.
  - Banner `#panel-auto-select-info` w `index.html`, obsługa `auto_selected` w `app.js` (`onWatershedClick`, `closeResults`).
  - 3 nowe testy integracyjne: small area (5000 m²) → not auto-selected, large area (50000 m²) → auto-selected, boundary (10000 m²) → not auto-selected (≤ not <).
  - **Testy:** 560 testów, 0 failures, ruff clean.

### Poprzednia sesja (2026-02-16, sesja 29)

- **Naprawa niespójnych przebiegów cieków między zoomami MVT:**
  - **Przyczyna:** `ST_SimplifyPreserveTopology` z tolerancjami per-zoom (1-10m) tworzył dyskretne skoki w kształcie geometrii. 78% segmentów stawało się prostymi liniami (2 punkty) przy tolerancji 10m (zoomy 0-5), a przy 1m (zoomy 10+) miały 13+ punktów. Powodowało to co najmniej 3 wizualnie różne wersje sieci rzecznej.
  - **Rozwiązanie:** usunięcie jawnej `ST_SimplifyPreserveTopology` z zapytań MVT (streams + catchments). Geometria jest pre-simplifikowana do 1m w pipeline, a `ST_AsMVTGeom` kwantyzuje współrzędne do siatki 4096×4096 kafla — płynna redukcja szczegółów bez skoków.
  - **Efekty:** spójne przebiegi cieków na wszystkich zoomach, 2.5× szybsze generowanie kafli (355→139ms na zoom 8, 10k features), prostszy kod (usunięta tabela `_MVT_SIMPLIFY_TOLERANCE`).
  - **Testy:** 557 testów, 0 failures, ruff clean.

### Poprzednia sesja (2026-02-16, sesja 28)

- **Redesign selekcji zlewni cząstkowych (ADR-026):**
  - Selekcja oparta o poligon (`ST_Contains`), usunięcie progu 100 m², migracja 014 (`segment_idx`), uproszczenie API, pipeline re-run (801.6s).

- **Naprawa wizualizacji MVT (częściowa):**
  - `ST_Simplify` → `ST_SimplifyPreserveTopology`, tolerancje ograniczone do max 10m.

### Poprzednia sesja (2026-02-16, sesja 27)

- **Diagnostyka i ochrona przed "zielonymi" zlewniami (DO WERYFIKACJI):**
  - Problem: po selekcji cieku pojawiaja sie zielone zlewnie czastkowe o duzej powierzchni, niezwiazane z zaznaczeniem. Bug na progach 10000 i 100000 m².
  - Hipoteza: `segment_idx` naklada sie miedzy progami (threshold 100 → [1..105492], threshold 10000 → [1..1101]). Jesli indeksy trafia na MVT z innego progu — zielone zlewnie "losowe".
  - Implementacja: `display_threshold_m2` w response, walidacja progu w highlight, tooltip diagnostyczny
  - 559 testow, 0 failures, ruff clean

### Poprzednia sesja (2026-02-16, sesja 26)

- **F2 — warunkowy prog selekcji cieku (ADR-025):**
  - Snap-to-stream i BFS na progu wyswietlanym na mapie (1000, 10000, 100000) zamiast zawsze na progu 100 m²
  - Fine-BFS (ADR-024) aktywny tylko gdy display_threshold==100
  - Eliminuje snap do niewidocznych doplywow przy grubszych progach
  - Rename: `fine_threshold` → `bfs_threshold`, `fine_segment_idxs` → `bfs_segment_idxs`
  - 2 nowe testy + 1 zaktualizowany (559 testow lacznie, 0 failures)
  - Dokumentacja: ADR-025, CHANGELOG

### Poprzednia sesja (2026-02-16, sesja 25)

- **F1 — precyzyjna selekcja cieku — kontynuacja:**
  - **Re-run pipeline:** 105492 segmentow (prog 100, bylo 78829, +34%), lacznie 117228 across 4 progi. CatchmentGraph: 117228 nodes, 5.1 MB RAM, 1.5s startup.
  - **Fix wydajnosci duzych zlewni:** kaskadowe progi merge (100→1000→10000→100000) gdy fine segments >500 — zapobiega timeout ST_UnaryUnion na 30s.
  - **Weryfikacja F1:** dwa klikniecia na tym samym cieku daja rozne wyniki (precyzja miedzykonfluencyjna). Response time: 0.5-1.1s.
  - **Weryfikacja duzych zlewni:** threshold 100000 → 8.23 km², 73 segs, 18s (bylo timeout).

### Poprzednia sesja (2026-02-15, sesja 24)

- **F1 — precyzyjna selekcja cieku (ADR-024):**
  - **Czesc A (preprocessing):** dodano warunek konfluencji w `vectorize_streams()` — segmenty lamia sie przy kazdym polaczeniu doplywow, nie tylko przy zmianie Strahlera.
  - **Czesc B (query):** BFS na progu 100 m² zamiast display threshold. Nowe funkcje: `find_stream_catchment_at_point()` (snap-to-stream), `map_boundary_to_display_segments()` (mapowanie fine→display). Optymalizacja SQL: `ST_UnaryUnion + ST_SnapToGrid`. Fallback do display threshold.
  - **Testy:** 557 testow, 0 failures (+3 nowe: confluence segmentation, multi-threshold BFS, fallback)
  - **Dokumentacja:** ADR-024, CHANGELOG, PROGRESS

### Poprzednia sesja (2026-02-15, sesja 23)

- **Liquid glass:**
  - Panele "Warstwy" i "Parametry zlewni" + toggle buttons + legendy uzywaja stylu liquid glass
  - Nowe tokeny CSS: `--liquid-bg`, `--liquid-border`, `--liquid-blur`, `--liquid-shadow`, `--liquid-highlight`
  - Kolory czcionek zmienione na czarne (`--color-text: #000`, `--color-text-secondary: #1d1d1f`)
  - Czarne czcionki na osiach i etykietach wykresow Chart.js

- **Panel wynikow — zmiany UX:**
  - Panel na pelna wysokosc okna (`top: 0; bottom: 0`), zaokraglone rogi tylko po lewej
  - Akordeony domyslnie zwiniete (poza "Parametry podstawowe")
  - "Punkt ujsciowy" przeniesiony do "Parametry podstawowe" (ujscie φ, λ, H)
  - Usuniety akordeon `acc-outlet`

- **Tryby klikniecia:**
  - Nowy tryb "Przegladanie" (domyslny) — klikniecie nic nie robi, kursor `grab`
  - Zmienione nazwy: "Wygeneruj zlewnię", "Wybierz zlewnię", "Profil terenu"
  - Kolejnosc: Przegladanie → Wybierz → Wygeneruj → Profil
  - Przelaczanie trybow nie czysci warstw z mapy
  - Anulowanie rysowania profilu przy zmianie trybu

- **Warstwy domyslnie wysunięte** (bez klasy `layers-hidden` na starcie)

- **Bug E4 udokumentowany:** punkt ujsciowy poza granica zlewni (oba tryby)

### Poprzednia sesja (2026-02-15, sesja 22)

- **E3 — Panel wynikow dokowany z prawej (fix zoom overlap):**
  - `#results-panel` przeniesiony wewnatrz `#map-wrapper` z `position: absolute; right: 0`
  - Slide in/out z CSS transition (`translateX(400px)`, `opacity`)
  - Przycisk toggle (chevron `‹`/`›`) przy krawedzi panelu — zachowanie jak panel "Warstwy"
  - Kontrolki zoom Leaflet przesuwaja sie automatycznie (`#map-wrapper.results-visible .leaflet-bottom.leaflet-right { right: 390px }`)
  - Usuniety draggable na panelu wynikow, usuniety `#results-restore`, usuniety przycisk minimize
  - Ikony: layers toggle `☰` → `›`/`‹` (chevron kierunkowy)
  - Escape: pojedynczy = zwin panel (overlay zostaje), podwojny (400ms) = zamknij jak `×`
  - Mobile: bottom-sheet zachowany, toggle btn ukryty
  - Zoom control przeniesiony z `topright` na `bottomright`

- **Wynik:** 449 testow unit, 0 failures

### Poprzednia sesja (2026-02-15, sesja 21)

- **Naprawa 4 bugow panelu warstw i danych (G1-G4):**
  - **G1:** Wysokosc histogramu `.chart-container` zwiekszona z 160px do 240px
  - **G2:** Import pokrycia terenu BDOT10k — naprawiono parsowanie nazw warstw GeoPackage (OT_PTLZ_A → PTLZ); 38560 rekordow z 12 warstw, 7 kategorii (las, grunt_orny, zabudowa_mieszkaniowa, woda, droga, inny, laka)
  - **G3:** "Podklady kartograficzne" przeniesione na dol panelu warstw (nowa kolejnosc: Warstwy podkladowe → Wyniki analiz → Podklady kartograficzne)
  - **G4a:** Zaglbienia przeniesione do grupy "Warstwy podkladowe" (nowy kontener `#overlay-group-entries`)
  - **G4b:** Checkbox zlewni — auto-check tylko przy pierwszym wykryciu; flaga `_watershedFirstDetection` resetowana po usunieciu warstwy

- **Krzywa hipsometryczna:** sekcja "Rzezba terenu" zmieniona z histogramu na krzywa hipsometryczna — os Y: wysokosc [m n.p.m.], os X: % powierzchni powyzej (0–100, co 20)

- **Wynik:** 550 testow, 0 failures, 6 commitow

### Poprzednia sesja (2026-02-15, sesja 20)

- **Naprawa 4 bugow profilu terenu (D1-D4):**
  - D2: Guard duplikatow dblclick, styl linii solid
  - D1: showProfileError z canvasId, panel pokazywany w catch
  - D3: cancelDrawing czysci profileLine, re-aktywacja rysowania
  - D4: Usuniety acc-profile, btn-profile-auto
- **Interaktywny profil terenu:** hover → marker na mapie + crosshair
- **DEM w Docker:** volume mount data/e2e_test → /data/dem
- **Wynik:** 550 testow, 0 failures, 6 commitow

### Poprzednia sesja (2026-02-14, sesja 19)

#### Co zrobiono

- **Profil terenu jako osobny panel + UX drawing (plan z sesji 19):**
  - Nowy floating panel `#profile-panel` (left: 16px, bottom: 16px, 420px, z-index 1050) — niezalezny od panelu "Parametry zlewni"
  - `profile.js` refaktor: `activateDrawProfile()` renderuje w `#chart-profile-standalone`, pokazuje `#profile-panel`; dodana `hideProfilePanel()`
  - `map.js`: nowa funkcja `undoLastVertex()` — cofanie ostatniego wierzcholka (Backspace)
  - Banner rysowania zaktualizowany: "Klik = wierzcholek, Podwojny klik = zakoncz, Backspace = cofnij, Esc = anuluj"
  - Chart.js fix: canvasy (#chart-hypsometric, #chart-landcover, #chart-profile) owiniete w `.chart-container` (height: 160px) — zapobiega rozciaganiu wykresow
  - `app.js`: init close/draggable na `#profile-panel`, `hideProfilePanel()` przy zmianie trybu i zamknieciu panelu wynikow
  - Mobile responsive: `#profile-panel` fullwidth na ekranach < 768px
  - **Wynik:** 550 testow, 0 failures

- **Zapisano 13 nowych bugów/uwag do naprawy (D1-D4, E1-E3, F1, G1-G4)**

### Poprzednia sesja (2026-02-14, sesja 18)

- **Naprawa 10 bugów (zgłoszenie 2026-02-14, A1-A5, B1-B4, C1):**
  - **A1:** Przycisk "×" w panelu wyników czyści warstwę zlewni z mapy (clearWatershed + clearSelectionBoundary + clearCatchmentHighlights + clearProfileLine)
  - **A2:** Domyślny min_area zagłębień 0 → 100 m² (API + frontend)
  - **A3:** Domyślny próg FA 10000 → 100000 m² (tiles.py + app.js + layers.js)
  - **A4:** Wysokość canvas histogramu 20 → 140px
  - **A5:** Zbiorniki BDOT ukryte przy opacity=0 (weight + fillOpacity + opacity)
  - **B1:** Inline alert-warning zamiast alert() gdy DEM niedostępny
  - **B2:** Nowy przycisk "Profil" w toolbar — rysowanie profilu terenu niezależne od zlewni
  - **B3:** Sekcja hydrogramu ukryta z badge "w przygotowaniu"
  - **B4:** Nowa metoda traverse_to_confluence w CatchmentGraph + parametr to_confluence w select-stream
  - **C1:** Usunięcie cell_count z WatershedResponse, 3 endpointów, frontendu i dokumentacji
  - **Wynik:** 550 testów, 0 failures, ruff check+format clean, 10 commitów

### Poprzednia sesja (2026-02-14, sesja 17)

- **Eliminacja FlowGraph z runtime API (ADR-022, 10 faz):**
  - **Faza 1:** Nowy modul `core/watershed_service.py` (~400 linii) — reużywalne funkcje wyekstrahowane z `select_stream.py`: find_nearest_stream_segment, merge_catchment_boundaries, get_segment_outlet, compute_watershed_length, get_main_stream_geojson, build_morph_dict_from_graph
  - **Faza 2:** Rewrite `watershed.py` — FlowGraph BFS (19.7M) → CatchmentGraph BFS (87k) + watershed_service
  - **Faza 3:** Rewrite `hydrograph.py` — j.w., morph_dict → WatershedParameters.from_dict()
  - **Faza 4:** Refactor `select_stream.py` — 6 lokalnych funkcji zastąpionych importami z watershed_service
  - **Faza 5:** Rewrite `profile.py` — SQL LATERAL JOIN → rasterio DEM sampling + pyproj
  - **Faza 6:** Usunięcie FlowGraph z `api/main.py` lifespan
  - **Faza 7:** Cleanup `watershed.py` (legacy functions zachowane dla CLI), deprecation notice w `flow_graph.py`
  - **Faza 8:** 29 nowych testów (25 unit + 4 integracyjne) — łącznie 548 testów, 0 failures
  - **Faza 9:** Docker config — API memory 3G → 512M, DEM_PATH env var
  - **Faza 10:** Dokumentacja — ADR-022, CHANGELOG, PROGRESS
  - **Efekty:** RAM -96% (1.1 GB → 40 MB), startup -97% (93s → 3s), flow_network runtime queries: 0, main_stream_geojson naprawiony

- **Audyt dokumentacji post-ADR-022 (4 pliki):**
  - ARCHITECTURE.md v1.5: diagram "Flow Graph" → "Catchment Graph", +watershed_service.py, przepływ danych ADR-022, testy 548
  - COMPUTATION_PIPELINE.md v1.2: flow_graph DEPRECATED, Faza 2/6 zaktualizowane
  - CLAUDE.md: +watershed_service.py, flow_graph.py DEPRECATED
  - QA_REPORT.md: warning 519 → 548 testów, +ADR-022

### Poprzednia sesja (2026-02-13, sesja 16)

- **Audyt dokumentacji — spojnosc, aktualnosc, wzajemne odwolania (9 plikow):**
  - ARCHITECTURE.md: `parameters.py`→`morphometry.py`, zaktualizowane sygnatury, +catchment_graph.py/constants.py, v1.4
  - CLAUDE.md: +2 moduly core, +2 endpointy, +5 skryptow w drzewie
  - DATA_MODEL.md: +migracja 013, fix nazwy 010
  - SCOPE.md: status zatwierdzony, data 2026-02-13
  - QA_REPORT.md: nota deprecation (175→519 testow, CORS fixed, CI/CD)
  - TECHNICAL_DEBT.md: constants.py ZREALIZOWANE, +CI/CD, data
  - COMPUTATION_PIPELINE.md: +faza CatchmentGraph (ADR-021), LOC fix (~2800→~700)
  - README.md: CP3→CP4, +6 endpointow w tabeli
  - PROGRESS.md: 7→10 endpointow
  - **Wynik:** 9 plikow, 151 linii dodanych / 45 usunietych, 7/7 weryfikacji grep

- **Wdrozenie aktualizacji:**
  - Migracja 013 zastosowana (`alembic upgrade head`)
  - Obraz API przebudowany (`docker compose build api`)
  - Kontener zrestartowany, CatchmentGraph zaladowany (86913 nodes, 3.0s)
  - Weryfikacja: health OK, scenarios OK, thresholds OK

### Poprzednia sesja (2026-02-13, sesja 15)

- **Audyt QA — Wydajnosc i Efektywnosc Workflow (4 fazy):**
  - **Faza 1 (Quick Wins):** LATERAL JOIN w profile.py, Cache-Control headers na 4 endpointach, dedup `_compute_shape_indices()` (-30 LOC), SessionLocal.configure() jednorazowo
  - **Faza 2 (Backend Perf):** TTLCache na traverse_upstream (128 wpisow, 1h), migracja 013 partial GiST index `WHERE is_stream=TRUE`, PG tuning (effective_cache_size=1536MB, random_page_cost=1.1, jit=off), land cover query merge w hydrograph.py
  - **Faza 3 (Frontend Perf):** Client-side Map cache w api.js (50 wpisow, 5min TTL), defer na 13 script tagow + preconnect CDN, force-cache na DEM metadata fetch
  - **Faza 4 (DevOps):** GitHub Actions CI (lint+test+security), pre-commit hooks (ruff+format), structured logging (structlog JSON + request_id middleware), core/constants.py, naprawiono 19 ruff warnings, ruff format 19 plikow
  - **Wynik:** 519 testow, 0 failures, ruff check+format clean, 4 commity

### Poprzednia sesja (2026-02-13, sesja 14)

- **Graf zlewni czastkowych — ADR-021 (7 faz, caly plan zaimplementowany):**
  - **Faza 1:** Migracja 012 — 6 nowych kolumn w `stream_catchments` (downstream_segment_idx, elevation_min/max, perimeter_km, stream_length_km, elev_histogram JSONB)
  - **Faza 2:** `compute_downstream_links()` w stream_extraction.py — follow fdir z outlet cell kazdego segmentu, `_outlet_rc` w vectorize_streams()
  - **Faza 3:** `zonal_min()` + `zonal_elevation_histogram()` w zonal_stats.py, rozszerzenie `polygonize_subcatchments()` o nowe stats
  - **Faza 4:** Rozszerzenie `insert_catchments()` w db_bulk.py o 6 nowych kolumn + JSONB histogram
  - **Faza 5:** Nowy modul `core/catchment_graph.py` — in-memory graf (~87k wezlow, ~8 MB), BFS via scipy sparse, agregacja stats z numpy arrays, krzywa hipsometryczna z mergowania histogramow
  - **Faza 6:** Calkowity rewrite `select_stream.py` — graf zlewni zamiast rastra, ST_Union boundary, derived indices (Kc, Rc, Re, Ff)
  - **Faza 7:** 19 testow catchment_graph, 7 testow zonal_stats, 8 testow integracyjnych select-stream (przepisane), dokumentacja (DATA_MODEL, DECISIONS, CHANGELOG)
  - **Wynik:** 519 testow, 0 failures, lint clean

- **Re-run pipeline + deploy CatchmentGraph:**
  - Migracja 012 zastosowana (`alembic upgrade head`)
  - Pipeline re-run: 1114s (~18.5 min), 86913 zlewni z pelnym zestawem danych
  - Nowe kolumny: downstream_segment_idx 99%, elevation/perimeter/histogram 100%
  - Obraz API przebudowany (`docker compose build api`), kontener zrestartowany
  - CatchmentGraph zaladowany: 86913 nodes, 86178 edges, 3.0s, 3.8 MB RAM
  - Weryfikacja `select-stream`: 16 upstream segments, area 0.26 km², pelna morfometria + krzywa hipsometryczna (21 pkt)

### Poprzednia sesja (2026-02-13, sesja 13b)

- **Audyt i poprawki frontend (13 taskow, 3 fazy)**

### Poprzednia sesja (2026-02-13, sesja 13)

- **Naprawa 4 krytycznych bledow (post-e2e):**
  1. **Stream burning (KRYTYCZNY):** `hydrology.py` `burn_streams_into_dem()` — wykrywanie multi-layer GeoPackage via `fiona.listlayers()`, ladowanie warstw liniowych (SWRS, SWKN, SWRM) + poligonowych (PTWP), `pd.concat`. Wczesniej czytalo domyslna warstwe (jeziora poligonowe) zamiast ciekow liniowych.
  2. **select-stream 500:** `select_stream.py` — `segment_idx` → `id` w SQL SELECT (kolumna nie istniala w `stream_network`)
  3. **Wydajnosc MVT:** GZip middleware (`GZipMiddleware, minimum_size=500`), migracja 011 (czesciowe indeksy GIST per threshold), cache TTL 86400s, `minZoom: 12` dla catchments, nginx `gzip_types` protobuf
  4. **UI diagnostyka:** `console.warn` w BDOT catch blocks, CSP `img-src` += `mapy.geoportal.gov.pl`

- **Re-run pipeline z poprawionym stream burning:**
  - process_dem: 927.6s, 19.67M records, 4 warstwy BDOT10k zaladowane (10726 features), 1,073,455 cells burned
  - max_acc: 8,846,427 (vs 3.45M przed — poprawa o 156% dzieki poprawnemu stream burning)
  - generate_depressions: 602,092 zaglebie w 59.9s
  - export_pipeline_gpkg: 9 warstw, 777,455 features
  - generate_dem_tiles: 267 kafelkow, 15.5 MB
  - BDOT GeoJSON: 3529 jezior, 7197 ciekow

- **Weryfikacja endpointow:**
  - `/health` — 200, `select-stream` — 200 (brak 500), MVT streams — 44 KB → 26 KB z GZip (41%), catchments — 394 KB → 146 KB (64%)

- **Laczny wynik:** 493 testy, wszystkie przechodza

### Poprzednia sesja (2026-02-13, sesja 12)

- **Select-stream z pelnymi statystykami zlewni, siec rzeczna BDOT10k, naprawy UI**
- **8 testow integracyjnych select-stream**
- 492 testy

### Poprzednia sesja (2026-02-13, sesja 11)

- **DEM tile pyramid (`scripts/generate_dem_tiles.py`):**
  - Nowy skrypt: koloryzacja DEM + hillshade → RGBA GeoTIFF w EPSG:3857 → `gdal2tiles.py --xyz`
  - Zoom 8–18, nearest-neighbor (ostre krawedzie komorek 1m przy duzym zoomie)
  - Metadane JSON (bounds, zoom range, elevation stats)
  - Argumenty: `--input`, `--output-dir`, `--meta`, `--source-crs`, `--min-zoom`, `--max-zoom`, `--no-hillshade`

- **Wspolny modul `utils/dem_color.py`:**
  - Wyekstrahowane z `generate_dem_overlay.py`: `COLOR_STOPS`, `build_colormap()`, `compute_hillshade()`
  - Stary skrypt zrefaktoryzowany na importy — backwards compatible

- **Frontend — custom panes + L.tileLayer:**
  - Custom panes z-index: demPane (250) → catchmentsPane (300) → streamsPane (350)
  - `loadDemOverlay()`: L.tileLayer z `/data/dem_tiles/{z}/{x}/{y}.png`, fallback na L.imageOverlay
  - MVT layers: `pane: 'streamsPane'` i `pane: 'catchmentsPane'`

- **Laczny wynik:** 484 testy (teraz 492), wszystkie przechodza

### Poprzednia sesja (2026-02-12, sesja 10)

- **Frontend — 7 poprawek UX (przeprojektowanie, sesja 9):**
  - **Zoom controls** przeniesione do topright (nie koliduja z layers panel)
  - **Przezroczystosc zlewni czastkowych** naprawiona (fillOpacity=1.0 initial, bez ×0.5)
  - **Histogram wysokosci** zamiast krzywej hipsometrycznej — `renderElevationHistogram()` w charts.js
  - **Cieki kolorowane po flow accumulation** — gradient log10 (upstream_area_km2) zamiast Strahlera
  - **Osobna strefa nginx** `tile_limit` 30r/s dla kafelkow, `api_limit` 10r/s dla reszty API
  - **Debounce 300ms** na klikniecie mapy — zapobiega podwojnym wywolaniom
  - **Tryb wyboru obiektow** — toolbar "Zlewnia/Wybor", state.clickMode routing

- **Backend — endpoint `POST /api/select-stream`:**
  - Nowy plik `api/endpoints/select_stream.py`
  - Selekcja segmentu cieku z `stream_network`, traversal upstream, budowa granicy
  - Zwraca StreamInfo + upstream_segment_indices + boundary_geojson
  - 3 nowe schematy w `models/schemas.py`: SelectStreamRequest, StreamInfo, SelectStreamResponse

- **Frontend — podswietlanie zlewni czastkowych:**
  - `highlightUpstreamCatchments()` / `clearCatchmentHighlights()` w map.js
  - `showSelectionBoundary()` / `clearSelectionBoundary()` — warstwa boundary z dash
  - `selectStream()` w api.js — POST /api/select-stream

- **5 bugfixow (sesja 10):**
  - **Blad serwera select-stream**: dodano try/except ValueError + Exception (wzorzec z watershed.py), uzycie snapped outlet coords
  - **Flicker przezroczystosci**: setCatchmentsOpacity/setStreamsOpacity uzywaja CSS container opacity zamiast redraw()
  - **Legendy warstw**: L.control legendy dla ciekow (gradient flow acc) i zlewni (paleta Strahler), auto show/hide
  - **Zoom do danych na starcie**: fitBounds po zaladowaniu metadanych DEM
  - **Warstwa "Zlewnia" reaktywna**: wpis w panelu warstw aktywuje sie automatycznie po wyznaczeniu zlewni (polling 500ms)

- **Laczny wynik:** 484 testy, wszystkie przechodza

### Stan bazy danych (sesja 44 — 10 arkuszy, 5m NMT)
| Tabela | Rekordy | Uwagi |
|--------|---------|-------|
| flow_network | **USUNIETA** | Wyeliminowana w ADR-028, migracja 015 (DROP TABLE) |
| stream_network | ~263,791 | 3 progi: 1000, 10000, 100000 (prog 100 usuniety — ADR-030, migracja 017) |
| stream_catchments | 264,548 | 3 progi (bez progu 100, ADR-026) |
| land_cover | 101,237 | 2 powiaty (3021, 3064), 7 kategorii |
| depressions | 385,567 | pelny zestaw po bootstrap sesji 44 |
| precipitation_data | 77,760 | 180 punktow × 432 scenariusze |
| soil_hsg | 121 | grupy glebowe HSG |

### Znane problemy (infrastruktura)
- `generate_tiles.py` wymaga tippecanoe (`pip install tippecanoe` w .venv)
- FlowGraph (core/flow_graph.py) — USUNIETY w ADR-028 (sesja 33)
- ~~15 segmentow stream_network (prog 100 m²) odrzuconych przez geohash collision~~ — nieaktualne po usunieciu progu 100 (ADR-030)
- Endpoint `profile.py` wymaga pliku DEM (VRT/GeoTIFF) pod sciezka `DEM_PATH` — zwraca 503 gdy brak
- `bootstrap.py` nie importuje pokrycia terenu (land cover) — po pelnym bootstrap tabela `land_cover` jest pusta (0 rekordow), brak danych w UI. Wymaga dodania kroku importu land cover (skrypt `import_landcover.py`) do pipeline bootstrap. Priorytet: niski.

### Bledy do naprawy (zgloszenie sesja 18 — ZAMKNIETE)

**Status: ✅ Wszystkie 10 bugów naprawione (sesja 18, A1-A5, B1-B4, C1)**

### Bledy do naprawy (zgloszenie 2026-02-14, sesja 19)

**Status: ⏳ D1-D4 naprawione (sesja 20), G1-G4 naprawione (sesja 21), E2 naprawione (sesja 18 jako A1), E3 naprawione (sesja 22), F1 naprawione (sesja 24, ADR-024), E5+E6+E9+E10+E11 naprawione (sesja 35), F3 naprawione (sesja 35), E7+E8 naprawione (sesja 38), E1+E4+E12+E13+F2 naprawione (sesja 42). Pozostaje: H**

#### D. Frontend — profil terenu — ✅ NAPRAWIONE (sesja 20)

**D1. ✅ Profil terenu nadal nie dziala** → showProfileError z canvasId, panel pokazywany w catch
**D2. ✅ Dwuklik do zakonczenia rysowania zle dziala** → guard duplikatow, styl linii solid brown
**D3. ✅ Po Escape nie da sie usunac linii** → cancelDrawing czysci profileLine, re-aktywacja rysowania
**D4. ✅ Kontener "Profil terenu" nadal w panelu zlewni** → acc-profile usuniety, btn-profile-auto w profile-panel

#### E. Frontend — zlewnia i mapa

**E1. ✅ "Dziury" na granicach zlewni** → buffer-debuffer (0.1m/-0.1m) zamiast ST_SnapToGrid w merge_catchment_boundaries(), MIN_HOLE_AREA_M2: 1000→100 — sesja 42

**E2. ✅ Brak mozliwosci odznaczenia zlewni** → naprawione w sesji 18 jako A1 (closeResults czysci wszystkie warstwy)

**E3. ✅ Panel "Parametry zlewni" zaslania przyciski zoom** → panel dokowany z prawej (slide in/out), zoom przesuwa sie automatycznie (sesja 22)

**E4. ✅ Punkt ujsciowy poza granica zlewni** → ensure_outlet_within_boundary() snap do granicy (tolerancja 1m), zastosowanie w select_stream.py i watershed.py — sesja 42

**E5. ✅ Profil terenu nie generuje wykresu** → Chart.js resize w ukrytych kontenerach (d-none PRZED renderowaniem, resizeChart() z 50ms timeout, canvas w .chart-container) — sesja 35

**E6. ✅ Panel profilu terenu — styl liquid glass** → tokeny CSS liquid glass dodane do #profile-panel w style.css — sesja 35

**E7. ✅ Brak informacji o gruntach (HSG) w panelu wynikow** → grupy glebowe HSG w panelu i na mapie — sesja 38

**E8. ✅ Zbiorniki i cieki BDOT10k nie zaladowane do UI** → eksport BDOT10k GeoJSON dla frontendu — sesja 38

**E10. ✅ Brak wykresu hipsometrii w sekcji "Rzezba terenu"** → przyczyna ta sama co E5 (Chart.js nie załadowany przez zły hash CDN + resize w collapsed accordion). Naprawione hashami CDN + resizeChart() — sesja 35

**E11. ✅ Zmiana kolorystyki zaglebien na dyskretne progi** → YlOrRd paleta (5 progów wg volume_m3) w depressions.js — sesja 35

**E9. ✅ Usunac wpis "Zlewnia" z panelu Warstwy** → ~101 linii usunięte z layers.js + 3 wywołania z app.js — sesja 35

**E12. ✅ Brak legendy dla warstwy HSG** → createHsgLegend()/removeHsgLegend() w map.js, callbacki onShow/onHide w addBdotOverlayEntry() — sesja 42

**E13. ✅ Nieciaglosc danych HSG na terenach zurbanizowanych** → nearest-neighbor fill (distance_transform_edt) w step_soil_hsg() przed polygonizacja — sesja 42

#### F. Logika zlewni czastkowych

**F1. ✅ Selekcja cieku zaznacza cala zlewnię zamiast czesci miedzy doplywami** → ADR-024: segmentacja konfluencyjna + fine-threshold BFS (sesja 24). Wymaga re-run pipeline.

**F3. ✅ Automatyczny fallback na prog 1000 m² przy selekcji cieku z progu 100 m²** → eskalacja progu w select_stream.py gdy threshold < DEFAULT_THRESHOLD_M2, nowe pole `info_message` w SelectStreamResponse, banner w app.js — sesja 35

**F2. ✅ Snap-to-stream moze wybrac zlewnię sasiednia zamiast kliknietej** → find_nearest_stream_segment_hybrid(): ST_Contains na stream_catchments (priorytet) + fallback do globalnego ST_Distance snap — sesja 42

#### G. Frontend — panel warstw i dane — ✅ NAPRAWIONE (sesja 21)

**G1. ✅ Histogram "Rzezba terenu" za maly** → `.chart-container` height 160px → 240px
**G2. ✅ Brak informacji o pokryciu terenu** → naprawiono parsowanie warstw GeoPackage (OT_PTLZ_A → PTLZ); import 38560 rekordow BDOT10k
**G3. ✅ Podklady kartograficzne na dole panelu warstw** → przeniesione na koniec init(), nowa kolejnosc: Warstwy podkladowe → Wyniki analiz → Podklady kartograficzne
**G4. ✅ Reorganizacja wynikow analiz** → zaglbienia do #overlay-group-entries; checkbox zlewni: auto-check tylko przy 1. wykryciu, reset po usunieciu

#### I. Wizualizacja

**I1. Ścieżka spływu z punktu ujścia zlewni** (priorytet: niski)
- Po wyznaczeniu zlewni (tryb "Wybierz" lub "Wygeneruj") wyświetlić na mapie ścieżkę spływu wody od punktu ujścia zaznaczonej zlewni w dół cieku — pokazuje dokąd płynie woda opuszczająca zlewnię.
- Ścieżka wyznaczana na podstawie sieci cieków (`stream_network`) lub grafu przepływu (downstream traversal od outlet do granicy analizowanego obszaru).
- Wizualizacja jako linia na mapie (np. niebieska strzałka / animowana linia kierunku przepływu).
- **Lokalizacja:** `core/catchment_graph.py` (downstream traversal), `core/watershed_service.py` (outlet point), `frontend/js/map.js` (wizualizacja linii), `frontend/js/app.js` (wywołanie po wyznaczeniu zlewni)

**I2. Najdłuższa ścieżka spływu w zlewni** (priorytet: niski)
- Po wyznaczeniu zlewni wyświetlić na mapie najdłuższą ścieżkę spływu (longest flow path) — od najdalszego punktu działu wodnego do ujścia zlewni. Parametr hydrologicznie istotny: długość zlewni (watershed length) używana do obliczenia czasu koncentracji.
- Wymaga wyznaczenia najdalszej komórki od outletu wzdłuż sieci przepływu (upstream BFS z pomiarem odległości) lub geometrycznie (najdalszy punkt granicy zlewni mierzony wzdłuż cieku głównego + stoku).
- Wizualizacja jako linia na mapie (np. przerywana linia z zaznaczeniem punktu startowego i ujścia).
- **Lokalizacja:** `core/catchment_graph.py` (BFS z odległością), `core/watershed_service.py` (główny ciek + longest path), `frontend/js/map.js` (wizualizacja linii)

**I3. Poprawa jakości wyświetlania NMT** (priorytet: średni)
- Obecna piramida kafelków DEM (zoom 8–16, 267 plików, 15.5 MB) ma ograniczoną jakość — widoczna pikselizacja przy dużym zoomie, ograniczony zakres zoomów.
- Możliwe usprawnienia: rozszerzenie zakresu zoomów (do 18), lepsza rampa kolorów (np. terrain-classic), poprawa hillshade (multi-directional zamiast single azimuth 315°), antyaliasing przy downsamplingu (bilinear/lanczos zamiast nearest-neighbor na niższych zoomach), wyższa rozdzielczość kafelków (512×512 zamiast 256×256).
- Rozważyć dynamiczne generowanie kafelków DEM z serwera (endpoint XYZ z rasterio) zamiast pre-generowanych PNG — lepsza jakość kosztem wydajności.
- **Lokalizacja:** `scripts/generate_dem_tiles.py` (generacja piramidy), `utils/dem_color.py` (rampa kolorów, hillshade), `frontend/js/map.js` (L.tileLayer konfiguracja)

**I5. Pasek współrzędnych kursora (WGS 84 + PUWG 1992)** (priorytet: niski)
- Cienki pasek na samym dole strony (wzór: Geoportal) wyświetlający aktualną pozycję kursora na mapie w dwóch układach: WGS 84 (φ, λ) i EPSG:2180 (X, Y).
- Aktualizacja na zdarzeniu `mousemove` mapy Leaflet. Transformacja WGS 84 → PUWG 1992 po stronie klienta (proj4js lub prosta formuła Gaussa-Krügera).
- Styl liquid glass (tokeny CSS `--liquid-bg`, `--liquid-blur`, `--liquid-border`) — spójność z panelami warstw i wyników.
- **Lokalizacja:** `frontend/index.html` (nowy element `#coord-bar`), `frontend/css/style.css` (styl paska), `frontend/js/map.js` (nasłuch `mousemove`, transformacja współrzędnych)

**I4. Eksport profilu podłużnego do CSV** (priorytet: niski)
- Przycisk eksportu w panelu profilu terenu (`#profile-panel`) — pobieranie pliku CSV z danymi profilu.
- Format: `X;Y;Station;Elevation` (separator średnik), współrzędne domyślnie w EPSG:2180. Station = odległość wzdłuż profilu od pierwszego punktu [m].
- Dane dostępne po stronie frontendu (odpowiedź z `POST /api/terrain-profile` zawiera punkty z współrzędnymi i wysokościami). Transformacja WGS 84 → PUWG 1992 po stronie klienta lub rozszerzenie endpointu o opcjonalny parametr CRS.
- **Lokalizacja:** `frontend/js/profile.js` (przycisk eksportu, generacja CSV, download), `frontend/index.html` (przycisk w `#profile-panel`), `api/endpoints/profile.py` (opcjonalnie: współrzędne w EPSG:2180 w response)

#### J. Funkcjonalności użytkowe

**J1. ✅ Formularz feedbacku zapisywany do bazy** (priorytet: niski) — zrealizowane w wersji rozszerzonej (diagnostyka sesji), sesja 83, 2026-08-02
- Prosty formularz na stronie umożliwiający użytkownikom zgłaszanie uwag / błędów / sugestii.
- Dane zapisywane do tabeli w PostgreSQL (np. `feedback`: id, message, email (opcjonalny), created_at, user_agent, page_url).
- Endpoint `POST /api/feedback` z walidacją (max długość, rate limiting).
- Frontend: przycisk w navbarze lub floating button, modal z polem tekstowym + opcjonalnym emailem.
- **Lokalizacja:** nowa tabela `feedback` (migracja Alembic), `api/endpoints/feedback.py` (nowy endpoint), `frontend/index.html` (modal), `frontend/js/app.js` (obsługa formularza)

**J2. Wgrywanie własnych warstw wektorowych** (priorytet: niski)
- Użytkownik może wgrać plik wektorowy (SHP, GPKG, GeoJSON, KML) i wyświetlić go jako warstwę na mapie.
- Preferowane rozwiązanie: przetwarzanie po stronie frontendu (bez wysyłania na serwer). Kandydaci do zbadania: biblioteka `shpjs` (SHP→GeoJSON), `gdal3.js` / `ogr2ogr WASM` (GPKG/KML→GeoJSON), natywne parsowanie GeoJSON. Leaflet obsługuje GeoJSON natively — wystarczy konwersja do tego formatu.
- Pliki SHP wymagają ZIP (`.shp` + `.dbf` + `.shx` + opcjonalnie `.prj`) — obsługa via `JSZip` lub drag-and-drop folderu.
- Warstwa dodawana do panelu warstw z checkboxem, suwakiem przezroczystości i zoom-to-extent.
- **Lokalizacja:** `frontend/js/layers.js` (dodawanie warstwy użytkownika), `frontend/js/map.js` (rendering GeoJSON), `frontend/index.html` (przycisk upload / drag-and-drop zone)

**J3. Dodawanie własnych serwisów WMS/WMTS/WFS** (priorytet: niski)
- Użytkownik podaje URL serwisu OGC i wybiera warstwę do wyświetlenia — obsługa wyłącznie po stronie frontendu.
- WMS: `L.tileLayer.wms(url, { layers, format, transparent })` — Leaflet natywnie.
- WMTS: `L.tileLayer(templateUrl)` z parametrami z GetCapabilities.
- WFS: pobranie GeoJSON przez `fetch(url + '&outputFormat=application/json')` → `L.geoJSON()`.
- Formularz: pole URL + przycisk "Pobierz warstwy" (GetCapabilities) → lista warstw do wyboru → dodanie do panelu warstw z checkboxem i przezroczystością.
- **Lokalizacja:** `frontend/js/layers.js` (dodawanie serwisu, parsowanie GetCapabilities XML), `frontend/js/map.js` (tworzenie warstw L.tileLayer.wms / L.tileLayer / L.geoJSON), `frontend/index.html` (modal z formularzem URL)

**J4. Mapy glebowe i użytkowanie terenu w warstwach podkładowych** (priorytet: średni)
- Dodanie warstw tematycznych do panelu "Warstwy podkładowe": mapa glebowa i użytkowanie/pokrycie terenu.
- **Gleby:** serwis WMS z Geoportalu (mapy glebowo-rolnicze) lub dane SoilGrids (już pobierane przez Kartograf dla HSG). Alternatywnie: import danych glebowych do bazy i serwowanie jako MVT/GeoJSON z kolorowaniem wg typów gleb / grup HSG.
- **Użytkowanie terenu:** dane BDOT10k pokrycia terenu (już w tabeli `land_cover` — 50406 rekordów) lub Corine Land Cover (CLC) z serwisu WMS. Wizualizacja z paletą kolorów wg kategorii (las, łąka, grunt orny, zabudowa, woda, droga, inny).
- Obie warstwy z checkboxem, suwakiem przezroczystości i legendą kolorów w panelu warstw.
- **Lokalizacja:** `frontend/js/layers.js` (wpisy warstw + legenda), `frontend/js/map.js` (rendering), `api/endpoints/tiles.py` (opcjonalnie: MVT endpoint dla land_cover), `core/land_cover.py` (dane)

#### CR. Wyniki code review (2026-02-22)

**Status: ⏳ W trakcie — 16 pozycji (3/3 krytyczne naprawione ✅, 8 ważne, 5 sugestii)**

##### Krytyczne (must fix)

**CR1. ✅ `channel_slope_m_per_m` obliczany z całkowitej długości sieci rzecznej zamiast głównego cieku** (NAPRAWIONE)
- Nowa metoda `CatchmentGraph.trace_main_channel()` — tracing upstream wg Strahlera. ADR-029, 6 nowych testów.

**CR2. ✅ O(n^2) lookup segmentów w `compute_downstream_links()`** (NAPRAWIONE)
- `stream_extraction.py`: `segments.index(seg) + 1` → `enumerate(segments, start=1)`. 550 testów passed.

**CR3. ✅ Server-side cursor niezamykany na wyjątek w `CatchmentGraph.load()`** (NAPRAWIONE)
- Opakowanie w `try/finally` z `cursor.close()` w `finally`. 550 testów passed.

##### Ważne (should fix)

**CR4. `traverse_to_confluence` BFS z `list.pop(0)` — O(n^2)** (priorytet: średni)
- `catchment_graph.py:410-411`: `list.pop(0)` jest O(n), powinno być `collections.deque` + `popleft()`.
- **Lokalizacja:** `core/catchment_graph.py`

**CR5. `get_land_cover_stats()` zawsze zwraca pusty dict (TODO)** (priorytet: średni)
- `cn_calculator.py:196-200`: pobiera pokrycie terenu ale nie analizuje go — zawsze fallback do domyślnych wartości (hardcoded średnia centralna Polska).
- Cała ścieżka Kartograf CN de facto produkuje `CN = weighted_cn(default_land_cover, "B")`.
- **Lokalizacja:** `core/cn_calculator.py`

**CR6. Bezpośredni dostęp do prywatnego `cg._segment_idx` w 3 endpointach** (priorytet: średni)
- `watershed.py:128`, `hydrograph.py:139`, `select_stream.py:114` — wszystkie robią `int(cg._segment_idx[clicked_idx])`.
- **Rozwiązanie:** dodać publiczną metodę `CatchmentGraph.get_segment_idx(internal_idx: int) -> int`.
- **Lokalizacja:** `core/catchment_graph.py`, `api/endpoints/watershed.py`, `api/endpoints/hydrograph.py`, `api/endpoints/select_stream.py`

**CR7. Singleton `CatchmentGraph` bez thread safety** (priorytet: średni)
- `catchment_graph.py:625-633`: brak `threading.Lock` — race condition w thread pool executor (sync endpointy FastAPI).
- **Rozwiązanie:** double-check locking z `threading.Lock`.
- **Lokalizacja:** `core/catchment_graph.py`

**CR8. Terrain profile — wyciek ścieżki DEM + porównanie nodata z `==`** (priorytet: średni)
- `profile.py:84-88`: pełna ścieżka serwera (`/data/dem/dem.vrt`) trafia do klienta (information disclosure).
- `profile.py:95-96`: porównanie float z `==` jest zawodne; `0.0` jako replacement maskuje prawdziwą elewację poziomu morza.
- **Lokalizacja:** `api/endpoints/profile.py`

**CR9. Cascade threshold escalation — boundary vs stats mogą opisywać różne zlewnie** (priorytet: średni)
- `select_stream.py:137-161`: przy eskalacji progu statystyki pochodzą z fine-threshold BFS, ale boundary z coarse-threshold merge — mogą opisywać różne ekstenty.
- **Lokalizacja:** `api/endpoints/select_stream.py`

**CR10. `traceback.print_exc()` zamiast `logger.error(..., exc_info=True)`** (priorytet: niski)
- `cn_calculator.py:333`, `analyze_watershed.py:416,1312` — bypass logowania strukturalnego.
- **Lokalizacja:** `core/cn_calculator.py`, `scripts/analyze_watershed.py`

**CR11. CLAUDE.md — nieaktualna struktura modułów** (priorytet: niski)
- `core/flow_graph.py` wymieniony jako DEPRECATED ale usunięty (commit `a65c25d`).
- Brakuje: `core/soil_hsg.py`, `scripts/bootstrap.py`.
- **Lokalizacja:** `CLAUDE.md`

##### Sugestie (nice to have)

**CR12. Duplikacja logiki morfometrycznej** — `select_stream.py:193-314` reimplementuje `build_morph_dict_from_graph()` z `watershed_service.py`.

**CR13. `_MAX_MERGE = 500` zdefiniowane inline** w `watershed.py:152` i `select_stream.py:133` — powinno być w `core/constants.py`.

**CR14. Inline import `soil_hsg` w endpoint** — `watershed.py:263-264` i `select_stream.py:274-275` importują wewnątrz try-except zamiast na górze pliku.

**CR15. Integer division `n_bins` w `aggregate_hypsometric`** — `catchment_graph.py:578` używa `//` co może obciąć ostatni bin. Powinno być `math.ceil()`.

**CR16. Caching POST response** — `select_stream.py:343` ustawia `Cache-Control: public, max-age=3600` na POST — niestandardowe i ignorowane przez wiele proxy.

#### H. Do rozważenia (koncepcyjne)

**H1. Zlewnie bezposrednie jezior przeplywowych i bezodplywowych** (priorytet: do ustalenia)
- Jak wyznaczac zlewnię bezposrednia jeziora przeplywowego? Czy laczyc ze soba zlewnie czastkowe, zeby unikac ich nadmiernego rozdrobnienia?
- Jak traktowac jeziora bezodplywowe (endorheic)? Powoduja one "dziury" w zlewniach rzecznych, a dwa blisko polozone obok siebie zborniki nie maja wyznaczonych swoich zlewni.
- Jak wdrozyc zlewnie kanalizacyjne i przekazywac ich doplywu do wyplywu w innym miejscu analizowanego obszaru?
- Powiazanie z istniejaca klasyfikacja jezior (ADR-020: 45 endorheic, 18 exorheic) i drain points
- **Kontekst:** `core/hydrology.py` (classify_endorheic_lakes), `catchment_graph.py` (traverse_upstream)

**H2. Narzucenie kierunku splywu na podstawie warstwy wektorowej** (priorytet: do ustalenia)
- Mozliwosc wymuszenia kierunku splywu (flow direction) w oparciu o zewnetrzna warstwe wektorowa (np. BDOT10k cieki, OSM waterways)
- Przypadki uzycia: korygowanie bledow DEM na terenach plaskich (delty, polesia), kanaly, rowy melioracyjne
- Mozliwe podejscia: stream burning (juz zaimplementowane w `hydrology.py` — `burn_streams_into_dem()`), flow direction forcing (nadpisywanie fdir w komorkach pokrywajacych sie z wektorem)
- Pytanie: czy obecny stream burning jest wystarczajacy, czy potrzebna jest pelna kontrola fdir?
- **Kontekst:** `core/hydrology.py` (burn_streams_into_dem, process_hydrology_pyflwdir), `scripts/process_dem.py`

**H3. Podniesienie budynkow BDOT10k w NMT (building raising)** (priorytet: sredni)
- Obecnie budynki sa usuwane z NMT (lub nieuwzgledniane), wiec woda moze swobodnie przeplywac przez nie. Prowadzi to do nierealistycznych kierunkow splywu i akumulacji — cieki "przechodzace" przez zabudowe.
- Rozwiazanie: pobranie warstwy budynkow z BDOT10k i podniesienie wartosci NMT w obrebie ich footprintow o domyslna wartosc +5 m. Operacja powinna byc wykonywana **przed** wypalaniem ciekow (stream burning), aby cieki mogly nadpisac podniesione komorki tam, gdzie to konieczne.
- Kolejnosc preprocessingu NMT: (1) fill sinks → (2) **building raising** → (3) stream burning → (4) flow direction → (5) flow accumulation.
- Wymaga pobrania warstwy BUBD (budynki) z BDOT10k przez Kartograf — analogicznie do istniejacego pobierania warstw hydro (SWRS, SWKN, SWRM, PTWP).
- Parametr `building_raise_m` (domyslnie 5.0) jako stala w `core/constants.py` lub argument CLI.
- **Kontekst:** `core/hydrology.py` (burn_streams_into_dem, process_hydrology_pyflwdir), `scripts/process_dem.py` (orchestrator), `scripts/bootstrap.py` (step_process_dem)

**H4. Monotoniczne wygladzanie ciekow zamiast stalego wypalania (stream gradient enforcement)** (priorytet: niski)
- Obecny stream burning obniza NMT o stala wartosc wzdluz cieku. Problem: gdy ciek przechodzi przez obiekt o znacznej wysokosci (most, wiadukt, nasyp), nawet duze wypalenie moze byc niewystarczajace. Jednoczesnie stale wypalenie w normalnych odcinkach tworzy nadmierne obnizenia, ktore potem wymagaja duzego fill sinks — wypelnienie zaglebia moze zalewac okoliczne komorki.
- Rozwiazanie: zamiast obnizania o stala wartosc, wygladazac wartosci NMT wzdluz linii cieku tak, aby wysokosci monotonicznie malaly w kierunku splywu. Kazda komorka na cieku powinna miec wartosc <= poprzedniej komorki w gore cieku. Jesli napotkana wartosc jest wyzsza (most, nasyp), zostaje zastapiona wartoscia poprzedniej komorki (lub interpolacja liniowa miedzy znanymi punktami po obu stronach przeszkody).
- Algorytm: (1) pobranie profilu wysokosci wzdluz geometrii cieku (ordered vertices), (2) przejscie od zrodla do ujscia z wymuszeniem monotonicznosci (running minimum), (3) zapis wygladzonych wartosci do rastra NMT.
- Zaleta: eliminuje problem mostow/nasypow bez tworzenia sztucznych zaglebie w normalnych odcinkach. Wypalanie stalą wartoscia pozostaje jako fallback tam, gdzie brak geometrii ciekow.
- **Kontekst:** `core/hydrology.py` (burn_streams_into_dem), `scripts/process_dem.py`

**H5. Symplifikacja granic zlewni** (priorytet: sredni)
- Granice zlewni generowane z polygonizacji rastra maja ksztalt schodkowy (pikselowy) — kazda komorka rastra tworzy prostokatny fragment granicy. Przy duzym zoomie wyglada to nieatrakcyjnie i nierealistycznie.
- Mozliwe podejscia: (1) `ST_SimplifyPreserveTopology` post-hoc na wynikowej granicy z tolerancja np. 1-2× cellsize, (2) wygladzanie Chaikin/Bezier na granicy zlewni, (3) symplifikacja juz na etapie polygonizacji zlewni czastkowych (pipeline).
- Trzeba zachowac topologiczna spojnosc — symplifikacja nie moze tworzyc luk miedzy sasiednimi zlewniami ani nakładek. `ST_SimplifyPreserveTopology` jest bezpieczniejsza niz `ST_Simplify`.
- **Kontekst:** `core/stream_extraction.py` (polygonize_subcatchments), `core/watershed_service.py` (merge_catchment_boundaries), `core/watershed.py` (build_boundary)

**H6. Format danych HSG: wektor o uproszczonej geometrii vs raster** (priorytet: do ustalenia)
- Obecnie dane HSG (SoilGrids) sa pobierane jako raster (resolucja 250m) przez Kartograf i uzywane do obliczen CN. Do frontendu trafiaja jako warstwa wektorowa (GeoJSON z polygonami per-grupa glebowa).
- Pytanie: czy dane HSG powinny byc przekazywane do frontendu jako (a) wektor o uproszczonej geometrii (mniejszy rozmiar, szybsze renderowanie, ale wymaga polygonizacji + symplifikacji rastra) czy (b) raster/overlay PNG (prostsza generacja, ale brak interaktywnosci i tooltipow).
- Wektor: zalety — tooltips, klikanie, legenda dynamiczna, mozliwosc filtrowania; wady — duzy GeoJSON przy rozdzielczosci 250m, koniecznosc symplifikacji.
- Raster: zalety — prosty pipeline (analogicznie do DEM overlay), maly rozmiar, szybkie renderowanie; wady — brak interaktywnosci, statyczna legenda.
- Podejscie hybrydowe: raster jako warstwa podkladowa + wektor z uproszczona geometria dla tooltipow i statystyk.
- **Kontekst:** `core/cn_calculator.py` (dane HSG), `scripts/bootstrap.py` (pipeline), `frontend/js/layers.js` (renderowanie warstw)

### Nastepne kroki
1. ~~**Naprawa krytycznych bledow z code review:** CR1, CR2, CR3~~ ✅ (wszystkie 3 naprawione)
2. Naprawa waznych bledow z code review: CR4-CR9 (BFS deque, land cover TODO, enkapsulacja _segment_idx, thread safety, profile info disclosure)
3. ~~Naprawa pozostalych bugow UX: E1, E4, E12, E13, F2~~ ✅ (wszystkie 5 naprawione, sesja 42)
4. ~~Aktualizacja CLAUDE.md (CR11): usunac flow_graph.py, dodac soil_hsg.py i bootstrap.py~~ ✅ (sesja 39)
5. Weryfikacja podkladow GUGiK WMTS (czy URL-e dzialaja z `EPSG:3857:{z}`)
6. Usuniecie hardcoded secrets z config.py i migrations/env.py
7. CP5: MVP — pelna integracja, deploy

## Backlog

Otwarte pozycje są w [BACKLOG.md](BACKLOG.md) (po angielsku, sekcje Bugs and diagnoses, Features — Kamil's feedback, Own data and new sources, Features — other, Infrastructure and code quality, Ideas outside the deployment): to jedyne źródło prawdy dla rzeczy do zrobienia. Pozycje dopisane tu na `feature/visual-identity` (m.in. pamięć `process_dem`, B1–B15 z raportu testów GPT, przycinanie do granicy zakresu, MZP) przeniesiono tam przy scaleniu z `feature/producer-heads` 2026-11-02. Tu zostaje tylko archiwum zrobionych pozycji.

### Zrobione (archiwum)

- [x] Fix traverse_upstream resource exhaustion (ADR-015: pre-flight check, CTE LIMIT, statement_timeout, Docker limits)
- [x] CP4 Faza 1: Frontend — mapa + zlewnia + parametry (Leaflet.js, Bootstrap 5)
- [x] CP4: Warstwa NMT — naprawiona (L.imageOverlay → tile pyramid XYZ + fallback)
- [x] CP4: Warstwa ciekow (Strahler) — L.imageOverlay z dylatacja morfologiczna → zamieniona na MVT
- [x] CP4: DEM tile pyramid + kolejnosc warstw (demPane/catchmentsPane/streamsPane)
- [x] CP4 Faza 2: Redesign glassmorphism + Chart.js + hydrogram + profil + zaglebie
- [x] CP4 Faza 3: Wektoryzacja ciekow MVT, multi-prog FA, hillshade, zaglbienia preprocessing
- [x] CP4 Faza 4: Select-stream pelne statystyki, GUGiK WMTS, UI fixes (492 testy)
- [x] Graf zlewni czastkowych (ADR-021): CatchmentGraph in-memory, migracja 012, pipeline re-run, select-stream rewrite
- [x] Podzial NMT na kafle (tile pyramid) — zrealizowane jako dem_tiles piramida XYZ zoom 8-16 (wpis byl blednie otwarty)
- [x] Naprawa bledow frontend/backend (zgloszenie 2026-02-14, 10 pozycji — A1-A5, B1-B4, C1)
- [x] Utworzenie backend/core/constants.py (M_PER_KM, M2_PER_KM2, CRS_*)
- [x] Problem jezior bezodplywowych (endorheic basins) — ADR-020: klasyfikacja + drain points
- [x] CI/CD pipeline (GitHub Actions)
- [x] Audyt QA wydajnosci: LATERAL JOIN, cache headers, TTL cache, partial index, PG tuning, client cache, defer, structlog
- [x] Eliminacja FlowGraph z runtime API (ADR-022): RAM -96%, startup -97%, 548 testow
- [x] Code review CR1-CR3 (krytyczne): channel_slope, O(n^2) segments.index, cursor leak
- [x] Code review CR4-CR11 (wazne) — zamkniete w sesjach 39/49/55 (2026-03-03); wpis byl blednie otwarty
- [x] Nomenklatura: warstwa "Cieki" → "Linie splywu" (feedback Kamila 2026-07) — commit c2adfd5, sesja 2026-07-31
- [x] `backend/utils/sheet_finder.py` duplikowal funkcjonalnosc Kartografa (`find_sheets_for_bbox()`) — usuniety (~616 linii + testy), zastapiony `utils/sheet_lookup.py` (cienki wrapper delegujacy do Kartografa). Przy okazji naprawiony bug w sciezce punkt+bufor (siatka 2×4 zamiast zagniezdzonego 2×2 dla 1:10000 — bledne godla, zero pokrycia wspolnego z poprawnym wynikiem). Polityka „pozyskiwanie danych wylacznie przez Kartograf" z udokumentowanymi wyjatkami: ADR-057. Commity: `75dc859`, `e9d940d`, `1524992`.
- [x] Kartograf 0.7.0 — `_get_opendata_url()` traktowal blad sieci jak brak arkusza (sesja 93, pobranie Opolskiego): rozwiazane w 0.7.0 (DownloadError zamiast przejscia do starszej warstwy; warstwy z GetCapabilities) — etap K.
- [x] Kartograf 0.7.0 — `requests.Session()` per zapytanie: 0.7.0 - jeden transport HTTP — etap K.
- [x] (czesciowo) Kartograf 0.7.0 — pelny rekord metadanych arkusza: sidecar `.meta.json` (`extra.source`: url, layer, acquisition_date/year, pzgik_date, survey_work_id, data_source, full_sheet) — etap K; BRAK w sidecarze: bladSredniWysokosci, bladSredniPolozenia, modulArchiwizacji, sha256 — do ADR-058/backlogu Kartografa.
- [x] Zoom kółkiem myszy zatrzymuje się po przestaniu kręcenia (uwagi testerów 2026-11-02, `feature/store-ui`)
- [x] Objaśnienia (i) po kliknięciu, nie po najechaniu (uwagi testerów 2026-11-02, `feature/store-ui`)
- [x] „Próg FA” → „Próg akumulacji spływu”, wartości w ha i km² (uwagi testerów 2026-11-02, `feature/store-ui`)
- [x] „Administracja” → „Logowanie”, „Instrukcja” na lewej szynie (uwagi testerów 2026-11-02, `feature/store-ui`)
- [x] „Usługi działają” tylko w panelu admina (uwagi testerów 2026-11-02, `feature/store-ui`)
