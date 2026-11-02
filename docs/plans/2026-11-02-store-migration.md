# Migracja Hydrografa na układ magazynu Kartografa (wariant A, blue/green): plan wykonania

**Zatwierdzono:** 2026-11-02, autor. Wybrany wariant A, wdrożenie blue/green, produkcja zamrożona do jawnego przełączenia (S7).

**Cel:** Hydrograf działa na kodzie `feature/producer-heads` (magazyn Kartografa wg ADR-061, Nogat 2.1, problem+json, Hydrolog 1.0) połączonym z całą pracą `feature/visual-identity`. Dane pochodzą z bootstrapu do magazynu, przyciętego do zlewni Kaczawy jak 2026-11-01. Przełączenie trwa sekundy i ma gotowy rollback. Do chwili przełączenia produkcja (port 8080) działa bez żadnej zmiany.

**Architektura:** Kod: gałąź `feature/store-migration` od `feature/visual-identity` (HEAD `1a3e3be`), do której scalamy `feature/producer-heads` (`9dfa3a8`). Środowisko: worktree `~/workspace/Hydrograf-store`, w którym działa osobny stos Compose `hydrograf-staging` (zielony): własne kontenery, obraz, wolumen bazy, sieć, port 8081 i katalogi danych na `/data`. Produkcyjny stos `hydrograf` (niebieski) pracuje dalej bez zmian. Przełączenie polega na zatrzymaniu niebieskiego nginx i wystawieniu zielonego nginx na 127.0.0.1:8080, a rollback na operacji odwrotnej.

**Podstawa:** analiza kosztów migracji magazynu z 2026-11-02 (stan `feature/producer-heads`, 18 konfliktów, piny, obraz, lokalizacja magazynu, ryzyka, szacunek), ADR-060/061/062 z `feature/producer-heads`, `docs/PROGRESS.md` (sesja 2026-11-01/02: kopia produkcji, przycięcie, wyniki SFINCS, MZP, profil).

**Dlaczego `docs/plans/`:** robocze plany repo leżą w `notes/superpowers/plans/`, a ten katalog jest w `.gitignore`. Ten plan steruje zmianą produkcji, więc musi być w historii gałęzi `feature/store-migration`.

---

## Decyzja

- **Wariant A.** `feature/producer-heads` scalamy w całości do gałęzi wyprowadzonej z `feature/visual-identity`. Wariantu B (przeniesienie samej migracji Kartografa do VI) nie wybieramy: oznaczałby podwójne testy i dokumentację oraz późniejsze scalenie PH.
- **Blue/green.** Niebieski to obecna produkcja: checkout `~/workspace/Hydrograf`, projekt `hydrograf`. Zielony to staging w worktree `Hydrograf-store`, projekt `hydrograf-staging`. Do kroku S7 zielony nie dostaje żadnego ruchu produkcyjnego.
- **Zamrożenie produkcji do S7:**
  - zero zmian w niebieskim stosie, w checkoucie produkcyjnym i w danych produkcyjnych;
  - nowe funkcje VI, jeśli w ogóle, wchodzą tylko przez worktree i są dodatkowo scalane do `feature/store-migration` (warunek wejścia S7);
  - panel admina na produkcji tylko do odczytu: bez bootstrapu, czyszczenia i kanalizacji. Jeśli w panelu coś się zapisze po zrzucie bazy z S2, zrzut trzeba powtórzyć.
- **Magazyn:** domyślnie prywatny magazyn Hydrografa `<cache_dir>/kartograf` (ADR-061), w zielonym stosie `${HYDROGRAF_STAGING_ROOT}/cache/kartograf`. Magazyn wspólny z Archiwistą jest otwartą decyzją (niżej) i nie blokuje S1–S3.

## Zasady izolacji (obowiązują w każdym kroku)

**Nie wolno ruszać:**
- checkoutu `~/workspace/Hydrograf`. Zakaz obejmuje `git checkout`, `git switch`, `git merge`, `git pull`, `git stash` i edycję plików. Wyjątek: `git worktree add|list|prune` wydawane z checkoutu, bo tylko dopisują katalogi. `hydro_api` działa tam z `--reload` na `./backend`, więc każda zmiana pliku od razu zmienia produkcję (przerwa 2,5 min 2026-11-01 miała właśnie taką przyczynę);
- kontenerów `hydro_db`, `hydro_api`, `hydro_nginx`, obrazu `hydrograf-api:latest`, wolumenu `hydrograf_postgres_data`, sieci `hydrograf_default` i portu `127.0.0.1:8080`;
- katalogów produkcji `data/`, `cache/`, `frontend/data/`, `frontend/tiles/`. Wolno je wyłącznie czytać, np. `cp -a` do stagingu;
- `docker compose` w katalogu produkcyjnym (do S8) i Compose bez projektu stagingu.

**Dozwolone odczyty produkcji:**
- `docker exec hydro_db pg_dump` lub `psql` z samymi `SELECT`;
- `docker inspect`, `docker stats`;
- zapytania do API przez 127.0.0.1:8080 jak zwykły użytkownik.

**Zielony stos:** wyłącznie przez `scripts/staging-compose.sh` (S2):
```bash
#!/usr/bin/env bash
# Compose of the green (staging) stack of the store migration, docs/plans/2026-11-02-store-migration.md.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "$(git rev-parse --abbrev-ref HEAD)" == feature/store-migration ]] || { echo "not the store worktree" >&2; exit 1; }
exec docker compose -p hydrograf-staging -f docker-compose.yml -f docker-compose.staging.yml --env-file .env.staging "$@"
```

`docker-compose.staging.yml`, sprawdzony `docker compose config` 2026-11-02 (Compose v5.3.0). Wynik: jeden port 8081, wszystkie montowania w worktree lub w `HYDROGRAF_STAGING_ROOT`. `ports: !override` jest konieczne, bo Compose dokleja listę portów zamiast ją zastąpić.
```yaml
# Staging (green) stack of the store migration: docs/plans/2026-11-02-store-migration.md.
# Use only through scripts/staging-compose.sh (project hydrograf-staging, this file, .env.staging).
services:
  db:
    container_name: hydro_staging_db
    deploy:
      resources:
        limits:
          memory: 1536M
          cpus: "1.0"

  api:
    image: hydrograf-api:store-staging
    container_name: hydro_staging_api
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-hydro_user}:${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD}@db:5432/${HYDROGRAF_STAGING_DB:-hydro_db}
    deploy:
      resources:
        limits:
          memory: ${HYDROGRAF_STAGING_API_MEM:-3G}
          cpus: "2.0"
    volumes:
      - ${HYDROGRAF_STAGING_ROOT:?Set HYDROGRAF_STAGING_ROOT}/cache:/cache
      - ${HYDROGRAF_STAGING_ROOT:?}/${HYDROGRAF_STAGING_SET:-copy}/data:/data
      - ${HYDROGRAF_STAGING_ROOT:?}/${HYDROGRAF_STAGING_SET:-copy}/frontend-data:/frontend/data
      - ${HYDROGRAF_STAGING_ROOT:?}/${HYDROGRAF_STAGING_SET:-copy}/frontend-tiles:/frontend/tiles

  nginx:
    container_name: hydro_staging_nginx
    ports: !override
      - "127.0.0.1:${HYDROGRAF_STAGING_PORT:-8081}:80"
    volumes:
      - ${HYDROGRAF_STAGING_ROOT:?}/${HYDROGRAF_STAGING_SET:-copy}/frontend-data:/usr/share/nginx/html/data:ro
      - ${HYDROGRAF_STAGING_ROOT:?}/${HYDROGRAF_STAGING_SET:-copy}/frontend-tiles:/usr/share/nginx/html/tiles:ro

volumes:
  postgres_data:
    name: hydrograf_staging_postgres_data

networks:
  default:
    name: hydrograf_staging_default
```

**Nazwy zielonego stosu:**

| Element | Niebieski (produkcja) | Zielony (staging) |
|---|---|---|
| Projekt Compose | `hydrograf` | `hydrograf-staging` |
| Kontenery | `hydro_db`, `hydro_api`, `hydro_nginx` | `hydro_staging_db`, `hydro_staging_api`, `hydro_staging_nginx` |
| Obraz API | `hydrograf-api:latest` (+ tag rollbacku `vi-0.7.0` w S7) | `hydrograf-api:store-staging` |
| Wolumen bazy | `hydrograf_postgres_data` | `hydrograf_staging_postgres_data` |
| Sieć | `hydrograf_default` | `hydrograf_staging_default` |
| Port | `127.0.0.1:8080` | `127.0.0.1:8081` (8080 dopiero w S7) |
| Magazyn i cache | `./cache` (układ 0.7.0) | `${HYDROGRAF_STAGING_ROOT}/cache` (`kartograf/` + `kartograf_meta.db`) |
| Dane | `./data`, `./frontend/{data,tiles}` | `${HYDROGRAF_STAGING_ROOT}/<zestaw>/{data,frontend-data,frontend-tiles}` |

- `HYDROGRAF_STAGING_ROOT=/data/nmt/hydrograf-staging`. To dysk `/data` z 237 GB wolnego; na `/` zostaje około 8 GB, a `/data/nmt` jest jedynym zapisywalnym katalogiem na `/data`.
- Uprawnienia katalogów jak w produkcji (777), bo kontener pracuje jako `hydro`, UID 999.
- Zestawy danych (`HYDROGRAF_STAGING_SET` razem z bazą `HYDROGRAF_STAGING_DB`):
  - `copy` / `hydro_db`: kopia produkcji (S2);
  - `s3` / `hydro_s3`: zlewnia Kamiennika (S3);
  - `s5` / `hydro_s5`: obszar produkcji z magazynu (S5).
- Wszystkie trzy bazy leżą w jednym serwerze `hydro_staging_db`.
- **`.env.staging`** (dopisać do `.gitignore` w S2, bo zawiera sekrety):
  - nowe `POSTGRES_PASSWORD` i `ADMIN_API_KEY`, inne niż produkcyjne;
  - `POSTGRES_DB=hydro_db`, `POSTGRES_USER=hydro_user`;
  - `LOG_LEVEL`, `IMGW_*` i `HYDROGRAF_*_HOST` przepisane z produkcyjnego `.env`;
  - `HYDROGRAF_STAGING_ROOT`, `HYDROGRAF_STAGING_SET`, `HYDROGRAF_STAGING_DB`, `HYDROGRAF_STAGING_PORT=8081`.
- Worktree nie ma `.env`. Zwykłe `docker compose` w worktree padnie więc na `POSTGRES_PASSWORD:?` i nie podmieni produkcji. To jednak tylko siatka bezpieczeństwa; regułą pozostaje wrapper.

**Kontrola produkcji (K0)** wykonywana na początku S2 (zapis bazowy do `${HYDROGRAF_STAGING_ROOT}/prod-baseline.txt`) i po każdym kroku S2–S6. Kryterium: `diff` z bazą jest pusty, a `/health` zwraca 200.
```bash
export DOCKER_HOST=unix:///var/run/docker.sock
docker inspect -f '{{.Name}} {{.Id}} {{.State.StartedAt}} {{.State.Status}}' hydro_db hydro_api hydro_nginx
docker image inspect -f '{{.Id}}' hydrograf-api:latest
git -C ~/workspace/Hydrograf rev-parse HEAD; git -C ~/workspace/Hydrograf status --short
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/health
```

**Okno SFINCS (K1):** S3 i S5 (oraz budowa obrazu, jeśli się da) ruszają dopiero wtedy, gdy przebieg 3 SFINCS jest zakończony:
```bash
test -e ~/hydraulik-work/kamiennik-12h-p1/run_24h.exit && [ -z "$(docker ps -q --filter name=hydraulik-sfincs)" ]
```
Stan 2026-11-02 rano: `run_24h.exit` jeszcze nie istnieje, przebieg trwa (koniec około 13:00). Katalogu roboczego Hydraulika w trakcie przebiegu nie dotykamy, również czytaniem przekrojów.

**Docker, dysk, pamięć:**
- Przed budową wolno wykonać tylko `docker builder prune -f`, czyli usunąć cache budowania (13,4 GB, z czego 11,2 GB do odzyskania). Potem `docker system df` i `df -h /`; cel to co najmniej 15 GB wolnego na `/`.
- Nigdy: `docker system prune`, `docker image prune`, `docker volume prune`, `docker network prune`, `docker rm`/`rmi` na nazwach produkcyjnych.
- Na `/` przybędzie: obraz (około 2 GB), wolumen bazy stagingu (około 1 GB), `backend/.venv` worktree (uv, twarde dowiązania z cache).
- Host ma 15 GB RAM, swap 11 GB, z czego 2026-11-02 było zajęte 10 GB. Produkcja zużywa około 0,8 GB.
- Limity zielonego stosu:
  - db: 1,5 GB, 1 CPU;
  - api: domyślnie 3 GB (`HYDROGRAF_STAGING_API_MEM`), wystarcza na serwowanie i S3;
  - S5: 8 GB, i tylko gdy K1 jest spełnione, a `free -g` pokazuje co najmniej 9 GB dostępnej pamięci.
- Na czas S5 nie zmieniamy limitów produkcji (`hydro_api` 12 GB).

---

## Kroki

Szacunek w sesjach agenta. Ścieżka krytyczna: S1 → S2 → S3 → S4 → S5 → S6 → S7. S1 to sam kod, więc może iść w trakcie przebiegu SFINCS.

### S1: scalenie `feature/producer-heads`, konflikty, piny, bramka (2–2,5 sesji)

- [ ] W worktree uruchomić `git merge --no-ff feature/producer-heads` i rozwiązać 18 konfliktów:

| Plik | Rozstrzygnięcie |
|---|---|
| `backend/api/endpoints/watershed.py` (8 bloków / 142 linie) | szkielet PH (problem+json, typy). Zachować preview zlewni z VI. |
| `backend/api/endpoints/hydrograph.py` (6 / 60) | błędy i typy Hydrologa 1.0 z PH. Zachować AMC i własny szereg opadu z VI (`PrecipitationInfo.source`). |
| `backend/api/endpoints/profile.py` (2 / 20) | `ProfileWaterLevel` z VI razem z `core.errors`; `HTTPException 404` zamienić na `NoDataError` |
| `backend/api/main.py` (1 / 14) | oba elementy: middleware logowania żądań z request-id (VI) i handler problem+json (PH) |
| `backend/core/morphometry.py` (327 linii) | wersja PH (usunięte funkcje). `cn: float` z VI dopisać tylko tam, gdzie funkcja przetrwała. |
| `backend/tests/integration/test_profile.py` (53) | testy poziomów wody z VI przepisane na problem+json |
| `.env.example` | suma zmiennych obu stron |
| `.github/workflows/ci.yml` | CI Nogata z PH plus zadanie `frontend-assets` z VI (`bump_asset_versions.py --check`) |
| `.pre-commit-config.yaml` | usunięty jak w PH. Hook `bump_asset_versions` przenieść do CI lub bramki. |
| `README.md`, `docs/ARCHITECTURE.md`, `docs/CHANGELOG.md`, `docs/SCOPE.md`, `docs/TECHNICAL_DEBT.md`, `docs/PROGRESS.md` | struktura i język PH (angielski, Nogat 2.1), do tego treść VI: sesje 2026-10-30 do 11-02, wyniki analiz, MZP, profil, Backlog B1–B15 |
| `docs/DECISIONS.md` | ADR-065 przenieść do `docs/decisions/0065-*.md` (układ PH) |
| `docs/DEVELOPMENT_STANDARDS.md` | usunięty jak w PH. Reguły VI (wersjonowanie `?v=`) przenieść do odpowiednika w PH. |
| `frontend/js/api.js` (4 linie) | `apiFetch` z `Accept-Language` (PH) plus zmiany VI. Komunikat błędu brać z pola `detail` problem+json. |

- [ ] Dostosować kod VI, który scalił się bez konfliktów, do bramki PH:
  - `core/analysis_results.py`, MZP, `generate_tiles.py`: rejestr błędów (`HydrografError`), mypy strict, ruff, docstringi numpy;
  - z próbnego scalenia znane są: 10 błędów mypy w 4 plikach (m.in. `tests/unit/test_hydrograph_inputs.py`, `api/endpoints/tiles.py:317`, `core/watershed_service.py:532`), 4 pliki do `ruff format` i 3× D102.
- [ ] Testy VI dostosować, nie kasować:
  - przyczyny 21 porażek z próby to utracone funkcje VI (preview, AMC) i `test_request_logging`;
  - kasować wolno tylko testy funkcji, które PH usunęło (`core/watershed.py`, część `morphometry.py`), z listą w opisie commita.
- [ ] Piny w `backend/pyproject.toml` i `uv lock`:
  - Kartograf `26ee45924b719b4f357ab02c88cda58aa806843f`, ten sam co Archiwista; zawiera wybór arkuszy po obiektach `--geometry`;
  - `affine>=2.4,<3` zostaje (ADR-062, pyflwdir 0.5.12);
  - Hydrolog `5fa22b3` i IMGWTools `6bd35a4` bez zmian, chyba że bramka wymusi IMGWTools `4bf8bb0`.
- [ ] Bramka offline w worktree: `uv sync --locked --all-extras`, potem `bash scripts/gate.sh` (ruff, mypy strict, pytest offline, pokrycie, commity).
- [ ] Commity zgodne z Conventional Commits, autor `Daldek <git@debever.pl>`, bez stopek AI (`check-commits.sh`). Bez push.

**Kryteria akceptacji:**
- `git diff --name-only --diff-filter=U` jest pusty;
- `git grep -nE '^(<<<<<<<|>>>>>>>)'` nic nie znajduje;
- `uv lock --check` przechodzi, a `uv.lock` zawiera kartograf@26ee459, affine 2.x i pyflwdir 0.5.12;
- `scripts/gate.sh` jest zielony: ruff czysty, mypy strict czysty, pokrycie ≥ 85%, liczba testów offline ≥ 1360 plus testy VI, 0 porażek;
- funkcje VI są w kodzie i w testach: preview zlewni, AMC i własny szereg opadu, request-id, wyniki analiz, `water_levels` profilu, wersjonowanie zasobów;
- `python3 scripts/bump_asset_versions.py --check` jest zielony;
- K0 bez zmian.

### S2: zielony stos na kopii produkcji (1 sesja)

- [ ] Commit plików stagingu: `docker-compose.staging.yml`, `scripts/staging-compose.sh`, `.env.staging` w `.gitignore`. Utworzyć `.env.staging` i katalogi `${HYDROGRAF_STAGING_ROOT}/{cache,copy,s3,s5,dump}`.
- [ ] K0 i zapis bazy porównawczej.
- [ ] `docker builder prune -f`, potem `df -h /`. Budowę obrazu (`scripts/staging-compose.sh build api`) najlepiej robić po K1. Wcześniej tylko wtedy, gdy swap nie rośnie.
- [ ] Baza:
  - świeży zrzut `docker exec hydro_db pg_dump -U hydro_user -d hydro_db -Fc > ${HYDROGRAF_STAGING_ROOT}/dump/hydro_db-<data>.dump`;
  - zrzut z 2026-11-01 (`/data/nmt/hydrograf-backup-2026-11-01/hydro_db.dump`) jest sprzed przycięcia, więc nie pasuje do dzisiejszych `data/` i `frontend/`. Służy tylko jako awaryjny, a wtedy dane trzeba wziąć z tarów tej samej kopii;
  - `scripts/staging-compose.sh up -d db`, potem `pg_restore --no-owner` przez `docker exec -i hydro_staging_db`.
- [ ] Dane zestawu `copy`: `cp -a` produkcyjnych `data/`, `frontend/data/` i `frontend/tiles/` (około 2,9 GB) do `${HYDROGRAF_STAGING_ROOT}/copy/{data,frontend-data,frontend-tiles}`. Źródło tylko do odczytu, bez twardych dowiązań.
- [ ] `scripts/staging-compose.sh up -d`. Entrypoint uruchamia `alembic upgrade head`; migracje 001–003 różnią się w PH tylko formatowaniem.
- [ ] Testy `db` jak w CI PH, na jednorazowej bazie, nigdy na `hydro_db` stagingu:
  - `docker run -d --rm --name hydro_staging_testdb -p 127.0.0.1:55432:5432 -e POSTGRES_DB=hydro_test ... postgis/postgis:16-3.4`;
  - z `backend/`: `alembic upgrade head`, potem `pytest tests -m "db and not benchmark"`;
  - na koniec `docker stop hydro_staging_testdb`.
- [ ] Smoke API na 127.0.0.1:8081. Te same żądania wysłać do produkcji (8080) i porównać:
  - `/health`, `/api/scenarios`, `/api/tiles/thresholds`, kafle `streams`/`catchments`/`landcover` (200, rozmiar ±), `/api/depressions`;
  - `POST /api/delineate-watershed` w 51,0376/16,1723: 15,16 km²;
  - przekrój Kamiennika: 37,23 km²;
  - punkt poza granicą: 404 jako `application/problem+json` z `type`/`title`/`status`/`detail`;
  - `POST /api/generate-hydrograph` dla tych zlewni: SCS-CN i Nash jak w produkcji, Snyder ze szczytem o 11–12% wyższym i 25–70 min wcześniej (ADR-060);
  - `POST /api/terrain-profile` z `result_ids` (dzisiejsza funkcja): `water_levels` dla przekroju czaszy, 277,48 m n.p.m., głębokość przy zaporze 12,33 m;
  - `POST /api/feedback`: wiersz z prefiksem `[staging-smoke]`, usunąć po teście;
  - admin z kluczem stagingu, tylko GET: `dashboard`, `resources`, `bootstrap/status`, `sewer/status`, `cleanup/estimate`, `feedback`.
- [ ] Smoke frontendu w przeglądarce na 8081:
  - mapa, warstwy, grupa „Wyniki analiz” (SFINCS z `results/index.json`, legenda, krycie);
  - nakładka MZP (CSP `img-src` z `wody.isok.gov.pl`);
  - profil z wodą, ekran powitalny, instrukcja;
  - błąd z API (punkt poza granicą) pokazuje treść `detail`;
  - zero błędów JS;
  - adresy zasobów z `?v=`.

**Kryteria akceptacji:**
- `scripts/staging-compose.sh config` pokazuje wyłącznie nazwy z tabeli i port 8081, a żadne źródło montowania nie leży w `~/workspace/Hydrograf/`;
- w obrazie `hydrograf-api:store-staging` są kartograf 0.8.0.dev0 (26ee459), hydrolog 1.0.0.dev0, imgwtools 3.0.0.dev0, affine 2.4.x i pyflwdir 0.5.12;
- liczby wierszy w 12 tabelach są równe w produkcji i stagingu, `alembic current` = `003`;
- testy `db` są zielone;
- smoke API i frontendu bez rozbieżności poza oczekiwanymi (Snyder, format błędów), a różnice zapisane w tabeli w PROGRESS;
- K0 bez zmian.

### S3: bootstrap do magazynu, tylko obszar testowy Kamiennika (0,5 sesji)

Warunek: K1 spełnione.

- [ ] Zestaw `s3`:
  - baza `hydro_s3` w `hydro_staging_db` (`CREATE DATABASE`, `CREATE EXTENSION postgis`);
  - katalogi `s3/{data,frontend-data,frontend-tiles}`;
  - `s3/data/boundary/kamiennik_37km2_sfincs.gpkg` skopiowany z produkcyjnego `data/boundary/` (37,22 km², ta sama domena co model SFINCS).
- [ ] Bootstrap w osobnym kontenerze `run --rm` projektu stagingu. Działający `hydro_staging_api` (zestaw `copy`) nie zmienia się.
  ```bash
  HYDROGRAF_STAGING_SET=s3 HYDROGRAF_STAGING_DB=hydro_s3 \
    scripts/staging-compose.sh run --rm --no-deps --name hydro_staging_bootstrap_s3 api \
    python -m scripts.bootstrap --boundary-file /data/boundary/kamiennik_37km2_sfincs.gpkg \
      --cache-dir /cache --skip-infra --skip-serve
  ```
  Krok 1 bootstrapu woła `uv sync` i `docker compose`, więc w kontenerze musi być pominięty. Nie używać bootstrapu z panelu admina.
- [ ] Sprawdzić magazyn (`${HYDROGRAF_STAGING_ROOT}/cache`):
  - jest znacznik `kartograf/kartograf-store.json` (`kartograf-store/1`);
  - `list_segments` zwraca `pl_1992_5m_evrf2007` z arkuszami z logu kroku 2;
  - sidecary `kartograf-meta/1` mają SHA-256 zgodne z plikami;
  - jest BDOT10k powiatów 0205 i 0226 oraz raster HSG (`0-5cm`);
  - `kartograf_meta.db` leży obok magazynu, poza nim;
  - nie ma starego układu `cache/nmt`, `cache/bdot10k`, `cache/soil_hsg`.
- [ ] Sprawdzić wyjścia pipeline'u:
  - wszystkie kroki `done`, kod 0;
  - niepuste `stream_network`, `stream_catchments`, `land_cover`, `soil_hsg`, `precipitation_data`, `depressions`;
  - rastry `s3/data/nmt` pokrywają granicę;
  - kafle i nakładki są wygenerowane.
- [ ] Porównanie z produkcją w tych samych punktach:
  - punkty: ujście Kamiennika (segment 21911) i przekroje z `~/hydraulik-work/kamiennik-12h-p1/inputs/cross_sections.gpkg` (K1–K4: 29,35 / 18,71 / 15,53 / 10,06 km², C1: 8,67, T2: 3,96, T3: 2,43 km²);
  - API zestawu `s3` w tymczasowym kontenerze bez publikowania portu: `run --rm -d --name hydro_staging_api_s3 ... api`, zapytania przez `docker exec`;
  - trzy porównania: produkcja (stary kod, stare dane), zestaw `copy` (nowy kod, stare dane: efekt samego kodu) i zestaw `s3` (nowy kod, dane z magazynu: efekt danych).

**Kryteria akceptacji:**
- magazyn jest kompletny i zweryfikowany jak wyżej, a bootstrap kończy się kodem 0;
- powierzchnie przekrojów różnią się o ≤ 2% względem produkcji (inne naloty i wersje arkuszy; ujście może odstawać przez krawędź obszaru, co trzeba opisać);
- CN różni się o ≤ 2;
- opad PMAXTP jest równy;
- SCS-CN i Nash: szczyt ±5% między `s3` a `copy`;
- Snyder: między `copy` a produkcją +11–12% szczytu i 25–70 min wcześniej, czyli zmiana Hydrologa 1.0 opisana w ADR-060. Musi to być opisane w raporcie, nie traktujemy tego jako błędu;
- raport porównania (tabela) w PROGRESS, `hydro_staging_api_s3` usunięty;
- K0 bez zmian.

### S4: punkt kontrolny autora

- [ ] Autor dostaje raport S1–S3: konflikty, bramka, smoke, magazyn, tabela porównań, zmiana Snydera.
- [ ] **Dalej tylko po wyraźnym potwierdzeniu autora.** Przy okazji autor rozstrzyga magazyn prywatny czy wspólny (patrz „Otwarte decyzje”); przy wspólnym przed S5 dochodzi aneks ADR-061.

### S5: bootstrap obszaru produkcji, przycięcie, ponowna publikacja wyników (1 sesja)

Warunki: S4 potwierdzone, K1 spełnione, `free -g` pokazuje co najmniej 9 GB dostępnej pamięci.

- [ ] Zestaw `s5`:
  - baza `hydro_s5` z PostGIS;
  - katalogi `s5/...`;
  - do `s5/data/` skopiować z produkcji `boundary/` (`mniejszy_sheets.txt`, `obszar_mniejszy.gpkg`, `zlewnia_kaczawy_790km2_przyciecie.gpkg`) oraz `sewer_network.gpkg` i `sewer/`.
- [ ] Bootstrap w `run --rm` z `HYDROGRAF_STAGING_SET=s5 HYDROGRAF_STAGING_DB=hydro_s5 HYDROGRAF_STAGING_API_MEM=8G`:
  - ten sam zasięg co bootstrap produkcji z 2026-10-30, czyli 207 arkuszy z `mniejszy_sheets.txt` (`--sheets`) albo `--boundary-file obszar_mniejszy.gpkg`; log musi pokazać 207;
  - ta sama konfiguracja pipeline'u (log: „Konfiguracja zaladowana z”, sekcja `sewer`);
  - punkt odniesienia z 2026-10-30: 4478 s dla 827,7 km²; oczekiwane około 75 min plus pobieranie 15–40 min.
- [ ] Przycięcie jak 2026-11-01 do zlewni Kaczawy powyżej węzła 51,222825 N; 16,179380 E (790,57 km²):
  - skopiować `~/scratch/hydrograf-clip/clip_hydrograf.py` do `~/scratch/hydrograf-clip-staging/` i dostosować;
  - `OUTLET` liczony na nowo w `hydro_s5`: segmenty przy progach 100000 i 10000 najbliższe węzłowi (stare 159/870 nie obowiązują);
  - `_clip_boundary` w `hydro_s5` to pierścień zewnętrzny sumy zlewni cząstkowych w górę od nowego ujścia. Zapisać go do `s5/data/boundary/zlewnia_kaczawy_przyciecie_s5.gpkg` i porównać z granicą z 2026-11-01;
  - importy skryptu (`scripts.generate_dem_tiles`, `generate_overlay`, `scripts.generate_tiles`) sprawdzić względem kodu po scaleniu;
  - `DATABASE_URL` do `hydro_s5`, `/staging` montowane z `s5/clip-staging`;
  - fazy `rasters db vectors frontend` w `run --rm --no-deps` projektu stagingu z `-v` na skrypt;
  - podmiana katalogów `rename` wpis po wpisie wewnątrz `s5/`.
- [ ] Ponowna publikacja wyników:
  - `frontend/data/results/` (manifest `index.json`, warstwy SFINCS `sfincs-kamiennik-12h-p1` z `wse_max.tif`) i `data/results/` skopiować z produkcji do `s5`;
  - przebieg 3, jeśli autor zdążył go opublikować w produkcji, wchodzi tą samą kopią;
  - sprawdzić, że `index.json` jest zgodny z `hydrograf-results/1`.
- [ ] Przełączyć zielony stos na `s5`: w `.env.staging` ustawić `HYDROGRAF_STAGING_SET=s5`, `HYDROGRAF_STAGING_DB=hydro_s5`, potem `scripts/staging-compose.sh up -d api nginx`. Powtórzyć smoke z S2 na 8081. Zestaw `copy` zostaje jako zapasowy.

**Kryteria akceptacji:**
- bootstrap kończy się kodem 0 z 207/207 arkuszami w magazynie (205 z nich jest też w magazynie Archiwisty, co służy do kontroli SHA);
- powierzchnia granicy przycięcia 790,57 km² ±0,5%;
- `land_cover` i `soil_hsg` pokrywają granicę w 100%;
- `is_sewer_augmented` = 0 jak w produkcji;
- delineacja 51,0376/16,1723 ≈ 15,16 km² (±2%), przekrój Kamiennika ≈ 37,23 km², punkt poza granicą zwraca 404 problem+json;
- warstwy w przeglądarce kończą się na granicy;
- wyniki SFINCS i woda na profilu działają;
- K0 bez zmian.

### S6: punkt kontrolny autora

- [ ] Autor dostaje: raport S5, porównanie `s5` z produkcją, wybór zestawu do przełączenia (`s5` domyślnie, `copy` awaryjnie) i termin okna przełączenia.
- [ ] **S7 tylko po wyraźnym potwierdzeniu autora.**

### S7: przełączenie i rollback (0,5 sesji, przerwa liczona w sekundach)

Warunki wejścia:
- S6 potwierdzone;
- `git merge-base --is-ancestor feature/visual-identity feature/store-migration`, czyli nic z produkcji nie zostało pominięte;
- K0 zgodne z bazą;
- zielony zdrowy na 8081.

- [ ] Tag rollbacku (operacja niedestrukcyjna): `docker tag hydrograf-api:latest hydrograf-api:vi-0.7.0`. Zapisać ID obrazu. Niebieski `hydro_api` bierze kod z `./backend` checkoutu, a obraz daje mu zależności; tag chroni je przed przypadkowym przebudowaniem `latest`.
- [ ] Ostatnia synchronizacja:
  - zgłoszenia (delta `feedback`): tabela jest mała (2026-11-02: 2 wiersze, maks. `id` 12). Skopiować ją w całości z `hydro_db` niebieskiego do bazy zielonego (`TRUNCATE feedback` w zielonym, `pg_dump -t feedback --data-only` z niebieskiego, `setval` sekwencji na `max(id)`). Tak przechodzą zarówno nowe wiersze, jak i `is_read`. Zapisać `M = max(id)` w chwili przełączenia;
  - `frontend/data/results/` porównać sumami z produkcją i w razie różnicy skopiować.
- [ ] Przełączenie:
  1. `docker stop hydro_nginx`. Niebieski nginx zostaje zatrzymany, nie usunięty; `hydro_api` i `hydro_db` działają dalej.
  2. `HYDROGRAF_STAGING_PORT=8080 scripts/staging-compose.sh up -d --no-deps nginx`.
  3. Wpisać `HYDROGRAF_STAGING_PORT=8080` do `.env.staging`, żeby kolejne `up` nie wróciło na 8081.
  4. Tunel Cloudflare wskazuje 127.0.0.1:8080, więc nic w nim nie zmieniamy.
- [ ] Po przełączeniu:
  - `/health` przez 8080 i przez publiczny host;
  - smoke z S2 (skrócony);
  - zasoby z nowym `?v=` przez Cloudflare (HTML ma `no-cache`);
  - logi `hydro_staging_api` bez błędów przez 15 min.
- [ ] **Rollback** (sekundy):
  1. `scripts/staging-compose.sh stop nginx`, potem `docker start hydro_nginx`;
  2. zgłoszenia z zielonego z `id > M` dopisać do `hydro_db` niebieskiego (jedyny zapis do produkcji w procedurze, wykonywany tylko przy rollbacku);
  3. w `.env.staging` przywrócić `HYDROGRAF_STAGING_PORT=8081`.

  Kod i dane niebieskiego są zamrożone od początku migracji, więc stan po rollbacku jest identyczny z tym sprzed przełączenia (plus dopisane zgłoszenia).

**Kryteria akceptacji:**
- przerwa wynosi ≤ 10 s, zmierzona pętlą `curl` co 1 s przez cały czas przełączania;
- produkcja odpowiada z zielonego stosu: `docker ps` pokazuje `hydro_staging_nginx` na 127.0.0.1:8080, a `hydro_nginx` jest w stanie `exited`;
- zgłoszenia są kompletne (liczba i maks. `id` zgodne z niebieskim);
- procedura rollbacku jest sprawdzona na sucho: polecenia i nazwy zweryfikowane `docker inspect`/`config`, bez wykonywania;
- PROGRESS jest zaktualizowany.

### S8: sprzątanie po okresie stabilności (0,25 sesji)

Warunek: co najmniej 7 dni bez rollbacku i zgoda autora.

- [ ] Zrzut końcowy niebieskiej bazy do `/data/nmt/...`, potem `docker rm` kontenerów `hydro_nginx`, `hydro_api`, `hydro_db`. Wolumen `hydrograf_postgres_data` i tag `vi-0.7.0` usuwamy dopiero po kolejnej zgodzie autora.
- [ ] Zestawy `copy` i `s3`, bazy `hydro_db` i `hydro_s3` stagingu, `hydro_staging_testdb` i katalog `clip-staging` usunąć. `docker builder prune -f` po budowach.
- [ ] Git (decyzja autora): kolejność scaleń do `develop` (VI, `chore/nogat-2.1`, PH, `feature/store-migration`), los `feature/kartograf-wykorzystanie`, push, usunięcie worktree dnia (`Hydrograf-guide`, `-isok`, `-results`, `-wse`).
- [ ] Docelowe miejsce produkcji (decyzja autora, patrz niżej). Jeśli wraca do `~/workspace/Hydrograf`, odbywa się to drugim przełączeniem według procedury S7.
- [ ] Docs: PROGRESS, CHANGELOG, ADR-061 (aneks, jeśli magazyn będzie wspólny), instrukcja (Snyder).

**Kryteria akceptacji:** na hoście działa jeden stos produkcyjny, nie ma osieroconych kontenerów, wolumenów ani katalogów stagingu (poza świadomie zachowanymi kopiami), a dokumentacja zgadza się ze stanem.

---

## Szacunek

| Krok | Sesje |
|---|---|
| S1 scalenie, konflikty, piny, bramka | 2–2,5 |
| S2 zielony stos na kopii produkcji | 1 |
| S3 bootstrap Kamiennika i porównanie | 0,5 |
| S5 bootstrap obszaru produkcji, przycięcie, publikacja | 1 |
| S7 przełączenie | 0,5 |
| S8 sprzątanie | 0,25 |
| **Razem** | **5,25–5,75**; +0,5 przy magazynie wspólnym z Archiwistą |

S4 i S6 to punkty kontrolne autora, bez kosztu agenta, ale czas oczekiwania wydłuża kalendarz.

## Ograniczenia

- S3 i S5 nie startują, dopóki przebieg 3 SFINCS liczy (K1: `run_24h.exit` w `~/hydraulik-work/kamiennik-12h-p1/`). Budowa obrazu także najlepiej po K1.
- Na `/` jest około 8 GB wolnego. Przed budową wolno wykonać tylko `docker builder prune -f`, a dane stagingu idą na `/data/nmt/hydrograf-staging`.
- Limity pamięci: staging db 1,5 GB, api 3 GB, a w S5 8 GB tylko po K1 i przy ≥ 9 GB dostępnej pamięci. Swap jest prawie pełny, więc S5 nie może iść równolegle z SFINCS ani z inną ciężką pracą.
- Hydraulik (SFINCS) czyta `cache/bdot10k` i `cache/soil_hsg` produkcji. Migracja ich nie dotyka: produkcyjny `cache/` zostaje, a zielony stos ma własny. `clean --include-cache` uruchamiamy tylko w zielonym stosie.
- Push wyłącznie za zgodą autora.

## Otwarte decyzje autora

1. **Magazyn prywatny czy wspólny z Archiwistą.**
   - Domyślnie prywatny: `${HYDROGRAF_STAGING_ROOT}/cache/kartograf`, zgodnie z ADR-061.
   - Wspólny (`~/data/archiwista-public/store` zawiera już 205 z 207 arkuszy obszaru produkcji) wymaga:
     - +0,5 sesji;
     - aneksu do ADR-061 (konfigurowalny root zamiast `store_dir()`);
     - uprawnień dla UID 999 (dziś katalog ma tryb 700 claude-agent; do wyboru grupa `hydro-readers` lub ACL);
     - decyzji rw/ro i ograniczenia bootstrapu z panelu;
     - sprawdzenia blokad przy dwóch zapisujących.
   - Nierozstrzygnięte. Decyzja potrzebna najpóźniej w S4.
2. **Zmiana Snydera widoczna dla testerów.** Hydrolog 1.0 daje szczyt o 11–12% wyższy i 25–70 min wcześniej. Do ustalenia, czy testerzy dostają informację (ekran powitalny lub notka w panelu wyników), czy wystarczy CHANGELOG.
3. **Aktualizacja instrukcji** (`frontend/instrukcja`, prezentacja PDF): slajdy o Snyderze i komunikaty błędów, które teraz pochodzą z `detail` problem+json. Do ustalenia, czy w S7, czy osobno.
4. **Docelowe miejsce produkcji po S8:** zielony stos zostaje w `Hydrograf-store` albo produkcja wraca do `~/workspace/Hydrograf` po scaleniu gałęzi, drugim przełączeniem według S7.
5. **Kolejność scaleń i push** (pytanie 3 z analizy). Nie blokuje S1–S7.
