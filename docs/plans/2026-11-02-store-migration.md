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
- **Magazyn:** do S3 prywatny magazyn Hydrografa `<cache_dir>/kartograf` (ADR-061), w zielonym stosie `${HYDROGRAF_STAGING_ROOT}/cache/kartograf`. **Od S4 (decyzja autora 2026-11-02) magazyn wspólny z Archiwistą:** `~/data/archiwista-public/store`, w zielonym stosie pod `/kartograf` (`HYDROGRAF_KARTOGRAF_ROOT`, ADR-066). **Od H1 (wariant B autora 2026-11-02, ADR-067) tylko do odczytu:** pisze do niego wyłącznie Archiwista, a Hydrograf czyta go tylko przez zamknięty zestaw projektu Archiwisty (`bootstrap --project … --set …`); każde pobieranie Hydrografa przy ustawionym `HYDROGRAF_KARTOGRAF_ROOT` jest odrzucane (`forbidden`).

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

`docker-compose.staging.yml`, sprawdzony `docker compose config` 2026-11-02 (Compose v5.3.0). Wynik: port 8081 na `127.0.0.1` i (od S3, polecenie autora; do S7) na adresie LAN `192.168.88.9`, montowania w worktree, w `HYDROGRAF_STAGING_ROOT` i (od S4) magazyn wspólny z Archiwistą `HYDROGRAF_KARTOGRAF_STORE` pod `/kartograf`, od H1 tylko do odczytu dla każdego kontenera (ADR-067; montowania pod ścieżkami hosta i katalog projektu dochodzą w H2). `ports: !override` jest konieczne, bo Compose dokleja listę portów zamiast ją zastąpić.
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
      # The Kartograf store shared with Archiwista (ADR-066), mounted below.
      HYDROGRAF_KARTOGRAF_ROOT: /kartograf
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
      # Read-only for every container, the bootstrap included: Archiwista alone writes the
      # shared store (ADR-067); the host-path mounts and the project mount come with H2.
      - ${HYDROGRAF_KARTOGRAF_STORE:?Set HYDROGRAF_KARTOGRAF_STORE}:/kartograf:ro

  nginx:
    container_name: hydro_staging_nginx
    # Localhost (the port S7 moves to 8080) and, until S7, the home network for testers
    # (the LAN binding is removed after S7); production (hydro_nginx) stays on 127.0.0.1.
    ports: !override
      - "127.0.0.1:${HYDROGRAF_STAGING_PORT:-8081}:80"
      - "192.168.88.9:8081:80"
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
| Port | `127.0.0.1:8080` (tylko localhost) | `127.0.0.1:8081` (8080 dopiero w S7) i `192.168.88.9:8081` (sieć domowa, do S7) |
| Magazyn i cache | `./cache` (układ 0.7.0) | do S3 `${HYDROGRAF_STAGING_ROOT}/cache` (`kartograf/` + `kartograf_meta.db`); od S4 magazyn wspólny z Archiwistą `~/data/archiwista-public/store` pod `/kartograf`, `kartograf_meta.db` nadal w `${HYDROGRAF_STAGING_ROOT}/cache` |
| Dane | `./data`, `./frontend/{data,tiles}` | `${HYDROGRAF_STAGING_ROOT}/<zestaw>/{data,frontend-data,frontend-tiles}` |

- `HYDROGRAF_STAGING_ROOT=/data/nmt/hydrograf-staging`. To dysk `/data` z 237 GB wolnego; na `/` zostaje około 8 GB (12 GB 2026-11-02 przed S5), a `/data/nmt` jest jedynym zapisywalnym katalogiem na `/data`. Magazyn wspólny z Archiwistą leży na `/`, więc to, co Archiwista dopisze do niego dla zestawu autora (krok A5 planu Nogata: BDOT10k dziesięciu powiatów, SoilGrids i raster HSG, około 0,83 GB), zajmie miejsce na `/`; S5 niczego do magazynu nie dopisuje.
- Uprawnienia katalogów jak w produkcji (777), bo kontener pracuje jako `hydro`, UID 999.
- Zestawy danych (`HYDROGRAF_STAGING_SET` razem z bazą `HYDROGRAF_STAGING_DB`):
  - `copy` / `hydro_db`: kopia produkcji (S2);
  - `s3` / `hydro_s3`: zlewnia Kamiennika (S3);
  - `s5` / `hydro_s5`: obszar produkcji z zamkniętego zestawu Archiwisty (S5).
- Wszystkie trzy bazy leżą w jednym serwerze `hydro_staging_db`.
- **Staging w sieci domowej** (2026-11-02, polecenie autora w trakcie S3): zielony nginx słucha także na `192.168.88.9:8081`, więc testerzy w LAN widzą nową wersję pod `http://192.168.88.9:8081/`. Produkcja (`hydro_nginx`) nadal tylko na `127.0.0.1:8080`, z LAN niedostępna. Zmiana dotknęła wyłącznie `hydro_staging_nginx` (`scripts/staging-compose.sh up -d --no-deps --force-recreate nginx`), K0 przed i po bez zmian. Wiązanie LAN ma stały port 8081, a S7 (`HYDROGRAF_STAGING_PORT=8080`) przenosi tylko wiązanie localhost. **Decyzja autora w S4 (2026-11-02): wiązanie LAN usuwamy po S7** (krok 2 przełączenia w S7, sprawdzenie w „Po przełączeniu”), bo po przełączeniu zielony nginx podaje produkcję, a ta ma zostać tylko na localhost.
- **Magazyn wspólny z Archiwistą** (decyzja autora w S4, ADR-066; od H1 ADR-067): `HYDROGRAF_KARTOGRAF_STORE=/home/claude-agent/data/archiwista-public/store` montowany pod `/kartograf`, `HYDROGRAF_KARTOGRAF_ROOT=/kartograf`, tylko do odczytu dla każdego kontenera, także bootstrapu: pisze do niego wyłącznie Archiwista. Panel admina odpowiada na start bootstrapu `403` (bootstrap z zestawu w panelu jest poza zakresem, D8 planu Nogata). W H2 magazyn i katalog projektu (`HYDROGRAF_PROJECT_DIR=…/projects/kaczawa`) montowane tylko do odczytu pod ścieżkami hosta, a ACL UID 999 zawężone do odczytu (`rX`). Rodzice katalogu bez zmian.
- **`.env.staging`** (dopisać do `.gitignore` w S2, bo zawiera sekrety):
  - nowe `POSTGRES_PASSWORD` i `ADMIN_API_KEY`, inne niż produkcyjne;
  - `POSTGRES_DB=hydro_db`, `POSTGRES_USER=hydro_user`;
  - `LOG_LEVEL`, `IMGW_*` i `HYDROGRAF_*_HOST` przepisane z produkcyjnego `.env`;
  - `HYDROGRAF_STAGING_ROOT`, `HYDROGRAF_STAGING_SET`, `HYDROGRAF_STAGING_DB`, `HYDROGRAF_STAGING_PORT=8081`;
  - od S4: `HYDROGRAF_KARTOGRAF_STORE` (montowany zawsze `ro`, ADR-067); w H2 dochodzi `HYDROGRAF_PROJECT_DIR`.
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

- [x] W worktree uruchomić `git merge --no-ff feature/producer-heads` i rozwiązać 18 konfliktów:

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

- [x] Dostosować kod VI, który scalił się bez konfliktów, do bramki PH:
  - `core/analysis_results.py`, MZP, `generate_tiles.py`: rejestr błędów (`HydrografError`), mypy strict, ruff, docstringi numpy;
  - z próbnego scalenia znane są: 10 błędów mypy w 4 plikach (m.in. `tests/unit/test_hydrograph_inputs.py`, `api/endpoints/tiles.py:317`, `core/watershed_service.py:532`), 4 pliki do `ruff format` i 3× D102.
- [x] Testy VI dostosować, nie kasować:
  - przyczyny 21 porażek z próby to utracone funkcje VI (preview, AMC) i `test_request_logging`;
  - kasować wolno tylko testy funkcji, które PH usunęło (`core/watershed.py`, część `morphometry.py`), z listą w opisie commita.
- [x] Piny w `backend/pyproject.toml` i `uv lock`:
  - Kartograf `26ee45924b719b4f357ab02c88cda58aa806843f`, ten sam co Archiwista; zawiera wybór arkuszy po obiektach `--geometry`;
  - `affine>=2.4,<3` zostaje (ADR-062, pyflwdir 0.5.12);
  - Hydrolog `5fa22b3` i IMGWTools `6bd35a4` bez zmian, chyba że bramka wymusi IMGWTools `4bf8bb0`.
- [x] Bramka offline w worktree: `uv sync --locked --all-extras`, potem `bash scripts/gate.sh` (ruff, mypy strict, pytest offline, pokrycie, commity).
- [x] Commity zgodne z Conventional Commits, autor `Daldek <git@debever.pl>`, bez stopek AI (`check-commits.sh`). Bez push.

**Kryteria akceptacji:**
- `git diff --name-only --diff-filter=U` jest pusty;
- `git grep -nE '^(<<<<<<<|>>>>>>>)'` nic nie znajduje;
- `uv lock --check` przechodzi, a `uv.lock` zawiera kartograf@26ee459, affine 2.x i pyflwdir 0.5.12;
- `scripts/gate.sh` jest zielony: ruff czysty, mypy strict czysty, pokrycie ≥ 85%, liczba testów offline ≥ 1360 plus testy VI, 0 porażek;
- funkcje VI są w kodzie i w testach: preview zlewni, AMC i własny szereg opadu, request-id, wyniki analiz, `water_levels` profilu, wersjonowanie zasobów;
- `python3 scripts/bump_asset_versions.py --check` jest zielony;
- K0 bez zmian.

### S2: zielony stos na kopii produkcji (1 sesja)

- [x] Commit plików stagingu: `docker-compose.staging.yml`, `scripts/staging-compose.sh`, `.env.staging` w `.gitignore`. Utworzyć `.env.staging` i katalogi `${HYDROGRAF_STAGING_ROOT}/{cache,copy,s3,s5,dump}`.
- [x] K0 i zapis bazy porównawczej.
- [x] `docker builder prune -f`, potem `df -h /`. Budowę obrazu (`scripts/staging-compose.sh build api`) najlepiej robić po K1. Wcześniej tylko wtedy, gdy swap nie rośnie.
- [x] Baza:
  - świeży zrzut `docker exec hydro_db pg_dump -U hydro_user -d hydro_db -Fc > ${HYDROGRAF_STAGING_ROOT}/dump/hydro_db-<data>.dump`;
  - zrzut z 2026-11-01 (`/data/nmt/hydrograf-backup-2026-11-01/hydro_db.dump`) jest sprzed przycięcia, więc nie pasuje do dzisiejszych `data/` i `frontend/`. Służy tylko jako awaryjny, a wtedy dane trzeba wziąć z tarów tej samej kopii;
  - `scripts/staging-compose.sh up -d db`, potem `pg_restore --no-owner` przez `docker exec -i hydro_staging_db`.
- [x] Dane zestawu `copy`: `cp -a` produkcyjnych `data/`, `frontend/data/` i `frontend/tiles/` (około 2,9 GB) do `${HYDROGRAF_STAGING_ROOT}/copy/{data,frontend-data,frontend-tiles}`. Źródło tylko do odczytu, bez twardych dowiązań.
- [x] `scripts/staging-compose.sh up -d`. Entrypoint uruchamia `alembic upgrade head`; migracje 001–003 różnią się w PH tylko formatowaniem.
- [x] Testy `db` jak w CI PH, na jednorazowej bazie, nigdy na `hydro_db` stagingu:
  - `docker run -d --rm --name hydro_staging_testdb -p 127.0.0.1:55432:5432 -e POSTGRES_DB=hydro_test ... postgis/postgis:16-3.4`;
  - z `backend/`: `alembic upgrade head`, potem `pytest tests -m "db and not benchmark"`;
  - na koniec `docker stop hydro_staging_testdb`.
- [x] Smoke API na 127.0.0.1:8081. Te same żądania wysłać do produkcji (8080) i porównać:
  - `/health`, `/api/scenarios`, `/api/tiles/thresholds`, kafle `streams`/`catchments`/`landcover` (200, rozmiar ±), `/api/depressions`;
  - `POST /api/delineate-watershed` w 51,0376/16,1723: 15,16 km²;
  - przekrój Kamiennika: 37,23 km²;
  - punkt poza granicą: 404 jako `application/problem+json` z `type`/`title`/`status`/`detail`;
  - `POST /api/generate-hydrograph` dla tych zlewni: SCS-CN i Nash jak w produkcji, Snyder ze szczytem o 11–12% wyższym i 25–70 min wcześniej (ADR-060);
  - `POST /api/terrain-profile` z `result_ids` (dzisiejsza funkcja): `water_levels` dla przekroju czaszy, 277,48 m n.p.m., głębokość przy zaporze 12,33 m;
  - `POST /api/feedback`: wiersz z prefiksem `[staging-smoke]`, usunąć po teście;
  - admin z kluczem stagingu, tylko GET: `dashboard`, `resources`, `bootstrap/status`, `sewer/status`, `cleanup/estimate`, `feedback`.
- [x] Smoke frontendu w przeglądarce na 8081:
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

- [x] Zestaw `s3`:
  - baza `hydro_s3` w `hydro_staging_db` (`CREATE DATABASE`, `CREATE EXTENSION postgis`);
  - katalogi `s3/{data,frontend-data,frontend-tiles}`;
  - `s3/data/boundary/kamiennik_37km2_sfincs.gpkg` skopiowany z produkcyjnego `data/boundary/` (37,22 km², ta sama domena co model SFINCS).
- [x] Bootstrap w osobnym kontenerze `run --rm` projektu stagingu. Działający `hydro_staging_api` (zestaw `copy`) nie zmienia się.
  ```bash
  HYDROGRAF_STAGING_SET=s3 HYDROGRAF_STAGING_DB=hydro_s3 \
    scripts/staging-compose.sh run --rm --no-deps --name hydro_staging_bootstrap_s3 api \
    python -m scripts.bootstrap --boundary-file /data/boundary/kamiennik_37km2_sfincs.gpkg \
      --cache-dir /cache --skip-infra --skip-serve
  ```
  Krok 1 bootstrapu woła `uv sync` i `docker compose`, więc w kontenerze musi być pominięty. Nie używać bootstrapu z panelu admina.
- [x] Sprawdzić magazyn (`${HYDROGRAF_STAGING_ROOT}/cache`):
  - jest znacznik `kartograf/kartograf-store.json` (`kartograf-store/1`);
  - `list_segments` zwraca `pl_1992_5m_evrf2007` z arkuszami z logu kroku 2;
  - sidecary `kartograf-meta/1` mają SHA-256 zgodne z plikami;
  - jest BDOT10k powiatów 0205 i 0226 oraz raster HSG (`0-5cm`);
  - `kartograf_meta.db` leży obok magazynu, poza nim;
  - nie ma starego układu `cache/nmt`, `cache/bdot10k`, `cache/soil_hsg`.
- [x] Sprawdzić wyjścia pipeline'u:
  - wszystkie kroki `done`, kod 0;
  - niepuste `stream_network`, `stream_catchments`, `land_cover`, `soil_hsg`, `precipitation_data`, `depressions`;
  - rastry `s3/data/nmt` pokrywają granicę;
  - kafle i nakładki są wygenerowane.
- [x] Porównanie z produkcją w tych samych punktach:
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

- [x] Autor dostaje raport S1–S3: konflikty, bramka, smoke, magazyn, tabela porównań, zmiana Snydera.
- [x] **Dalej tylko po wyraźnym potwierdzeniu autora.** Decyzje autora 2026-11-02:
  1. przed S5 naprawić dwie wady z S2/S3: pliki `.prj` Hydrografa w magazynie i „nan” jako nazwa cieku;
  2. magazyn **wspólny z Archiwistą** (`~/data/archiwista-public/store`); aneks do ADR-061 to ADR-066;
  3. wiązanie LAN stagingu (`192.168.88.9:8081`) usunąć po S7.
- [x] Przygotowanie S5 (wyniki „S4 i przygotowanie S5”): obie poprawki z testami, ADR-066, `HYDROGRAF_KARTOGRAF_ROOT`, strażnik zapisu w kroku 2 bootstrapu (usunięty w H1, ADR-067), ACL dla UID 999, montowanie w stagingu, obraz przebudowany, bramka i testy `db` zielone.

### S5: bootstrap z zestawu, przycięcie, ponowna publikacja wyników (1 sesja)

Krok przepisany według S5 planu Nogata `docs/plans/2026-11-02-archiwista-sets-for-hydrograf.md` (repozytorium Nogat, gałąź `plan/archiwista-sets-hydrograf`, commit `d2f17ac` i następne): wariant B autora z 2026-11-02, ADR-067. Bootstrap czyta dane Kartografa wyłącznie z zamkniętego zestawu projektu Kaczawa w Archiwiście i niczego nie pobiera.

Warunki: S4 potwierdzone; H1 i H2 zrobione; Kaczawa w `/home/claude-agent/data/archiwista-public/projects/kaczawa` (A4) i zestaw zbudowany oraz zamknięty przez autora (A5), zweryfikowany w Archiwiście („Weryfikuj”); K1 spełnione; `free -g` pokazuje co najmniej 9 GB dostępnej pamięci, `df -h /` co najmniej 5 GB wolnego. Reguła z ADR-066, że w Archiwiście nie może trwać żadne pobieranie, odpada: zamknięty zestaw się nie zmienia, a bootstrap sprawdza każdy pin (rozmiar i SHA-256) na starcie.

- [ ] Zestaw `s5`:
  - baza `hydro_s5` z PostGIS;
  - katalogi `s5/...`;
  - z produkcji do `s5/data/` tylko `boundary/zlewnia_kaczawy_790km2_przyciecie.gpkg` (do przycięcia) oraz `sewer_network.gpkg` i `sewer/`.
- [ ] Bootstrap w `run --rm` z `HYDROGRAF_STAGING_SET=s5 HYDROGRAF_STAGING_DB=hydro_s5 HYDROGRAF_STAGING_API_MEM=8G`, bez trybu magazynu (magazyn i katalog projektu tylko do odczytu; `--cache-dir /cache` zostaje, bo tam leży `kartograf_meta.db`):
  - najpierw `--project /home/claude-agent/data/archiwista-public/projects/kaczawa --set "<nazwa zestawu autora>" --dry-run`: kod 0, 205 arkuszy obszaru, dziesięć powiatów, jeden raster HSG i `pins_sha256` zestawu; potem to samo bez `--dry-run`;
  - ta sama konfiguracja pipeline'u (log: „Konfiguracja zaladowana z”, sekcja `sewer`);
  - punkt odniesienia z 2026-10-30: 4478 s dla 827,7 km²; pobierania nie ma;
  - odmowa kończy się kodem z rejestru i dokumentem błędu w ostatnim wierszu stderr; wskazówka mówi, co poprawić w Archiwiście (np. „Otwórz do edycji”, „Przywróć brakujące”, „Zamknij zestaw”); niczego nie poprawiać w magazynie ręcznie.
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
- bootstrap kończy się kodem 0; log pokazuje `205/205 arkuszy z zestawu`, dziesięć powiatów (0205, 0206, 0207, 0209, 0218, 0219, 0221, 0226, 0261, 0262) i `pins_sha256` zestawu, a `bootstrap_set.json` (`hydrograf-bootstrap-set/1`, `status: ok`) zostaje z wynikami w zestawie `s5`;
- magazyn bez zmian: liczby `iter_store` i indeks Archiwisty dla magazynu `zespol` takie same przed i po, nic nowego w `versions/.incoming`;
- zlewnia liczona z mozaiki 205 arkuszy (D3): stara granica przycięcia wchodzi na około 935 m² w arkusz `M-33-45-B-c-1-1` spoza zestawu (do pominięcia); kryterium pokrycia to granica przycięcia wewnątrz mozaiki (poza co najwyżej około 0,001 km² przy dziale wód w `M-33-45-B-c-1-1`), a `land_cover` i `soil_hsg` pokrywają część granicy przycięcia leżącą w mozaice, nie 100% starej granicy;
- powierzchnia granicy przycięcia 790,57 km² ±0,5%;
- `is_sewer_augmented` = 0 jak w produkcji;
- delineacja 51,0376/16,1723 ≈ 15,16 km² (±2%), przekrój Kamiennika ≈ 37,23 km², punkt poza granicą zwraca 404 problem+json;
- warstwy w przeglądarce kończą się na granicy;
- wyniki SFINCS i woda na profilu działają;
- pokrycie terenu i CN porównane z produkcją, różnice opisane w raporcie (dzisiejsze paczki BDOT10k mogą różnić się od pobranych przez produkcję między 2026-03-24 a 2026-10-29);
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
  2. Usunąć z `docker-compose.staging.yml` wiązanie `"192.168.88.9:8081:80"` (decyzja autora z S4: wiązanie LAN znika po S7), potem `HYDROGRAF_STAGING_PORT=8080 scripts/staging-compose.sh up -d --no-deps nginx`. Odtworzony nginx słucha więc tylko na `127.0.0.1:8080`, a produkcja z zielonego stosu nie trafia do LAN. Zmianę pliku zapisać commitem po przełączeniu.
  3. Wpisać `HYDROGRAF_STAGING_PORT=8080` do `.env.staging`, żeby kolejne `up` nie wróciło na 8081.
  4. Tunel Cloudflare wskazuje 127.0.0.1:8080, więc nic w nim nie zmieniamy.
- [ ] Po przełączeniu:
  - `/health` przez 8080 i przez publiczny host;
  - `curl` na `http://192.168.88.9:8081/` nie łączy się (brak wiązania LAN);
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
- [ ] Docs: PROGRESS, CHANGELOG, instrukcja (Snyder). Aneks do ADR-061 o magazynie wspólnym to ADR-066 (zrobione przed S5).

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
| **Razem** | **5,25–5,75**; +0,5 przy magazynie wspólnym z Archiwistą (wybrany w S4, przygotowanie zrobione przed S5) |

S4 i S6 to punkty kontrolne autora, bez kosztu agenta, ale czas oczekiwania wydłuża kalendarz.

## Ograniczenia

- S3 i S5 nie startują, dopóki przebieg 3 SFINCS liczy (K1: `run_24h.exit` w `~/hydraulik-work/kamiennik-12h-p1/`). Budowa obrazu także najlepiej po K1.
- Na `/` jest około 8 GB wolnego (12 GB 2026-11-02 przed S5). Przed budową wolno wykonać tylko `docker builder prune -f`, a dane stagingu idą na `/data/nmt/hydrograf-staging`; wyjątek to magazyn wspólny z Archiwistą, który leży na `/`.
- Limity pamięci: staging db 1,5 GB, api 3 GB, a w S5 8 GB tylko po K1 i przy ≥ 9 GB dostępnej pamięci. Swap jest prawie pełny, więc S5 nie może iść równolegle z SFINCS ani z inną ciężką pracą.
- Hydraulik (SFINCS) czyta `cache/bdot10k` i `cache/soil_hsg` produkcji. Migracja ich nie dotyka: produkcyjny `cache/` zostaje, a zielony stos ma własny. `clean --include-cache` uruchamiamy tylko w zielonym stosie.
- Push wyłącznie za zgodą autora.

## Otwarte decyzje autora

1. **Magazyn prywatny czy wspólny z Archiwistą.** Rozstrzygnięte w S4 (2026-11-02): **wspólny** (`~/data/archiwista-public/store`, 205 z 207 arkuszy obszaru produkcji już w nim jest), aneks do ADR-061 to ADR-066. **Zmienione tego samego dnia wariantem B autora (ADR-067, H1, plan Nogata `docs/plans/2026-11-02-archiwista-sets-for-hydrograf.md`):**
   - pisze do magazynu wyłącznie Archiwista; Hydrograf czyta go tylko przez zamknięty zestaw projektu Archiwisty (`--project`, `--set`), ściśle: każde wejście Kartografa to pin zestawu sprawdzony SHA-256;
   - przy ustawionym `HYDROGRAF_KARTOGRAF_ROOT` każde pobieranie Hydrografa jest odrzucane (`forbidden`), panel admina odpowiada `403`, montowanie zawsze `ro`; czyszczenie cache nie rusza magazynu wspólnego;
   - uprawnienia UID 999 przez ACL zawężone w H2 do odczytu (`rX`) na magazynie i na katalogu projektu (bez grupy `hydro-readers`: umask 077 Archiwisty odbiera grupie nowe pliki);
   - reguła „nikt nie pobiera w Archiwiście w czasie bootstrapu” i strażnik `writes_in_progress` w kroku 2 usunięte: przy jednym piszącym nie ma czego pilnować.
2. **Zmiana Snydera widoczna dla testerów.** Hydrolog 1.0 daje szczyt o 11–12% wyższy i 25–70 min wcześniej. Do ustalenia, czy testerzy dostają informację (ekran powitalny lub notka w panelu wyników), czy wystarczy CHANGELOG.
3. **Aktualizacja instrukcji** (`frontend/instrukcja`, prezentacja PDF): slajdy o Snyderze i komunikaty błędów, które teraz pochodzą z `detail` problem+json. Do ustalenia, czy w S7, czy osobno.
4. **Docelowe miejsce produkcji po S8:** zielony stos zostaje w `Hydrograf-store` albo produkcja wraca do `~/workspace/Hydrograf` po scaleniu gałęzi, drugim przełączeniem według S7.
5. **Kolejność scaleń i push** (pytanie 3 z analizy). Nie blokuje S1–S7.

## Wyniki

### S1 (2026-11-02): zrobione

- Commity na `feature/store-migration` (bez push): `a514f7f` scalenie `feature/producer-heads` (18 konfliktów, opis rozstrzygnięć w komunikacie), `4d12f34` `Accept-Language: pl` w sekcji kanalizacji panelu admina, `24c691d` pin `26ee459` w ADR-060/061, `integrations/KARTOGRAF.md` i `CROSS_PROJECT_ANALYSIS.md`, potem commit z zapisem sesji w PROGRESS i tymi wynikami.
- Kryteria akceptacji:
  - brak ścieżek `U` i znaczników konfliktu;
  - `uv lock --check` zielony; w `uv.lock` kartograf `26ee459` (0.8.0.dev0, gałąź `feature/archiwista-projects`), affine 2.4.0, pyflwdir 0.5.12; Hydrolog `5fa22b3`, IMGWTools `6bd35a4` bez zmian (bramka nie wymagała `4bf8bb0`);
  - `bash scripts/gate.sh` zielony (GATE OK, 30 s): ruff format i check czyste, mypy strict czysty (167 plików), 1351 testów offline zaliczonych, 0 porażek, 19 pominiętych (11 `db`, 8 `benchmark`), pokrycie 86,52%, wersje `?v=` aktualne, krok commitów zielony;
  - liczba testów: kryterium „≥ 1360 plus testy VI” wzięło liczbę z PROGRESS PH sprzed `9101547` (usunięcie testów martwego kodu); `feature/producer-heads` ma 1302 testy offline. Po scaleniu 1351 = 1302 − 1 (test tekstu źródła, usunięty na VI) + 45 testów VI + 3 testy VI przepisane z 422 na 400 + 2 przypadki kontraktu OpenAPI dla nowych tras VI. Żaden test VI nie zginął;
  - funkcje VI w kodzie i testach: podgląd zlewni (`TestDelineateWatershedPreview`), AMC i własny szereg opadu (`test_hydrograph_inputs.py`), request-id (`test_request_logging.py`), wyniki analiz (`test_analysis_results.py`), `water_levels` profilu (`TestTerrainProfileWaterLevels`), wersjonowanie zasobów (`scripts/bump_asset_versions.py`, krok bramki i zadanie CI `frontend-assets`);
  - `python3 scripts/bump_asset_versions.py --check` zielony;
  - K0: część git sprawdzona (checkout produkcji na `1a3e3be`, `git status --short` = `?? .claude/` przed i po); część Dockera nie była uruchamiana, bo S1 z założenia jej nie używa — pierwszy pełny K0 na początku S2.
- Do wiadomości przed S2:
  - `docs/ARCHITECTURE.md` §2.2.2 nadal podaje „422: Validation”, a §11.2 opisuje CI z `pip install -r requirements.txt` — tekst PH sprzed problem+json i uv, nie z tego scalenia;
  - Hydrolog typuje `cn: int` w `HydrographGenerator` i `SCSCN`, a Hydrograf (VI) podaje CN z jednym miejscem po przecinku; w czasie wykonania działa (tylko kontrola zakresu 1–100), mypy tego nie wykrywa, bo `cn` pochodzi z `dict[str, Any]`. Kandydat na zgłoszenie `request` w Hydrologu (DEV-17.5);
  - testy `db`, obraz, smoke API i frontendu oraz prawdziwe pobieranie Kartografa należą do S2/S3.

### Uwagi testerów 1–6 przed S3 (2026-11-02): scalone

- Commity na `feature/store-migration` (bez push): `5207813` scalenie `feature/store-ui` (pozycje 1–5: zoom kółkiem, (i) tylko po kliknięciu, „Próg akumulacji spływu” w ha/km², szyna Mapa · Instrukcja · Logowanie, status usług tylko w `/admin`; bez konfliktów), `eada999` scalenie `feature/store-identify` (pozycja 6: tryb „Identyfikuj”, `POST /api/identify-point`; jeden konflikt w `frontend/index.html`, tylko hashe `?v=`), potem commit z PDF prezentacji, zapisem w PROGRESS i tymi wynikami.
- Sprawdzone po scaleniu: `js/app.js` ma `MODE_HINTS` z podpowiedzią „Identyfikuj”, bez funkcji statusu usług, Esc zamyka kartę punktu przed panelami; karta punktu nie ma (i), a jej „Próg akumulacji spływu” jest w ha/km² (ta sama reguła co `Hydrograf.layers.formatThreshold`); `docs/ARCHITECTURE.md` 25 modułów (19 strony głównej, 6 `admin/`), zgodnie z `frontend/js`.
- `docs/Hydrograf-prezentacja.pdf` wydrukowany raz po scaleniu (Chromium, 16:9, 30 slajdów 960 × 540 pt); slajdy 8–12, 26 i 29 obejrzane. Zrzut telefonu na slajdzie 29 i zrzut na slajdzie 8 mają jeszcze trzy tryby na pasku (środek zrzutów sprzed pozycji 6) — do podmiany razem ze zrzutami slajdów 10 i 13 po S3.
- `GATE_COMMIT_RANGE=4d510a6..HEAD bash scripts/gate.sh` zielony: 1381 testów offline, 24 pominięte (`db`, `benchmark`), pokrycie 86,64%, wersje `?v=` aktualne, krok commitów zielony. 5 testów SQL trybu „Identyfikuj” (`test_identify_point_db.py`) czeka na S2.
- Smoke w Chromium na serwerze statycznym worktree z atrapami API (`~/scratch/store-ui/landing/devserver.py`, bez Dockera i bez bazy): szyna Mapa · Instrukcja · Logowanie na mapie, w `/instrukcja/` i `/admin`; na stronie mapy brak plakietki statusu; (i) nie otwiera się po najechaniu ani fokusie, otwiera po kliknięciu, zamyka Esc; „Próg akumulacji spływu” 0,1 ha / 1 ha / 10 ha; cztery tryby z „Identyfikuj”, karta punktu z progiem 10 ha i po zmianie progu 0,1 ha, Esc zamyka kartę; syntetyczny ogon kółka (`~/scratch/store-ui/ui/wheel-lab.js`, DPR 1, start z poziomu 10): muśnięcia z ogonem kończą się po 1 poziomie w ok. 0,3 s, przeciągnięcie 1 s z ogonem → 14, ząbki jak w `wheel-after.json` (5 × 120 ms → 14, Firefox 5 × 3 linie → 12); telefon 390 px bez poziomego przewijania; oba motywy; konsola bez błędów. Zrzuty w `~/scratch/store-ui/landing/`.
- Produkcja nietknięta: checkout `~/workspace/Hydrograf` na `1a3e3be`, `git status --short` = `?? .claude/`; bez Dockera.

### S2 (2026-11-02): zrobione

- Commity na `feature/store-migration` (bez push): `eddf1d7` pliki stagingu (`docker-compose.staging.yml` i `scripts/staging-compose.sh` jak w planie, `.env.staging` w `.gitignore`), potem commit z zapisem w PROGRESS (sesja S2, tabela porównań) i tymi wynikami.
- Środowisko:
  - `.env.staging` (tryb 600, poza gitem): nowe `POSTGRES_PASSWORD` i `ADMIN_API_KEY`, różne od produkcyjnych; `LOG_LEVEL`, `IMGW_*` i `HYDROGRAF_*_HOST` z produkcyjnego `.env`; `HYDROGRAF_STAGING_ROOT=/data/nmt/hydrograf-staging`, `HYDROGRAF_STAGING_SET=copy`, `HYDROGRAF_STAGING_DB=hydro_db`, `HYDROGRAF_STAGING_PORT=8081`;
  - w `${HYDROGRAF_STAGING_ROOT}`: `cache`, `copy`, `s3`, `s5` (777), `dump` (700, zrzut z danymi zgłoszeń), `prod-baseline.txt` (K0);
  - w worktree puste katalogi poza gitem pod montowania z `docker-compose.yml`: `docker/init_scripts` (w produkcji też pusty; bez niego Docker utworzyłby go jako root) oraz `frontend/data` i `frontend/tiles` (punkty montowania zagnieżdżone w `./frontend:ro` nginx);
  - `scripts/staging-compose.sh config` pokazuje wyłącznie nazwy z tabeli i jeden port `127.0.0.1:8081`; źródła montowań leżą tylko w worktree i w `/data/nmt/hydrograf-staging`, żadne w `~/workspace/Hydrograf/`. `docker inspect`: db 1,5 GB i 1 CPU, api 3 GB i 2 CPU, api z `read_only`.
- Obraz:
  - `docker builder prune -f` odzyskał 11,22 GB (`/`: 8,1 → 19 GB wolnego);
  - budowa po K1 (`run_24h.exit` = `exit=0`, brak kontenera `hydraulik-sfincs`) trwała 7 min 57 s;
  - `hydrograf-api:store-staging` = `sha256:ce03f2f4f201…`, 1,94 GB. W obrazie: kartograf 0.8.0.dev0 (`26ee459`), hydrolog 1.0.0.dev0 (`5fa22b3`), imgwtools 3.0.0 (`6bd35a4`), affine 2.4.0, pyflwdir 0.5.12, GDAL 3.10.3, tippecanoe 2.79.0. Kryterium mówi „imgwtools 3.0.0.dev0”, ale `uv.lock` od S1 ma 3.0.0 przy tym samym commicie, więc to omyłka w kryterium;
  - `hydrograf-api:latest` bez zmian. Po budowie na `/` jest 12 GB wolnego, a cache budowania zajmuje 7,3 GB (3,2 GB do odzyskania).
- Baza:
  - zrzut `dump/hydro_db-2026-11-02.dump`: 99 MB w 24 s, SHA-256 w pliku `.sha256`; liczby wierszy produkcji przed zrzutem i po nim takie same;
  - `pg_restore --no-owner` w 33 s bez błędów, potem `ANALYZE`;
  - 12 tabel równych w produkcji i stagingu: `alembic_version` 1, `bdot_streams` 3812, `depressions` 214 907, `feedback` 3, `land_cover` 14 594, `precipitation_data` 134 352, `sewer_network` 0, `sewer_nodes` 0, `soil_hsg` 8, `spatial_ref_sys` 8500, `stream_catchments` 45 769, `stream_network` 45 769;
  - `alembic current` = `003 (head)` (entrypoint bez migracji), PostGIS 3.4.3; baza stagingu ma 319 MB wobec 645 MB produkcji (bez rozdęcia);
  - zgłoszenia: maks. `id` 13 w obu bazach. Po smoke sekwencja stagingu stoi na 14; S7 i tak ustawia `setval` na `max(id)`.
- Dane zestawu `copy`: `cp -a` w 2 min 30 s. Liczby plików i rozmiary pozorne są równe źródłu: `data` 37 plików (1 149 975 370 B), `frontend-data` 8360 (90 253 370 B), `frontend-tiles` 359 297 (496 221 138 B).
- Testy `db` na jednorazowej `hydro_staging_testdb` (`alembic upgrade head` 001 → 003, na koniec `docker stop`): 15 zaliczonych, 0 porażek, 1 pominięty. Pominięty `test_st_contains_vs_production_data` wymaga zlewni progu 1000, których produkcja nie ma (progi 10000 i 100000). Wszystkie 5 testów SQL trybu „Identyfikuj” zaliczone.
- Smoke API (te same żądania do 8080 i 8081; do produkcji tylko GET i obliczeniowe POST; zgłoszenie i admin z kluczem tylko do stagingu). Tabela jest w PROGRESS (sesja S2). Wyniki:
  - równe:
    - `/health`, `scenarios`, `thresholds`, `layers`;
    - 21 plików statycznych (SHA-256), w tym `results/index.json`, rastry wyniku i kafle;
    - kafle MVT: te same obiekty, a rozmiar różni się o −472…+18 B przez kolejność obiektów (produkcja też zmienia rozmiar między wywołaniami);
    - `depressions`;
    - delineacja 51,0376/16,1723: 15,16 km², CN 70,5; przekrój Kamiennika: 37,23 km², CN 67,9, ujście 51,01544/15,88984; podgląd zlewni;
    - SCS-CN i Nash: 12 hydrogramów identycznych;
    - profil czaszy z `result_ids`: zwierciadło 277,48 m n.p.m.;
  - oczekiwane:
    - Snyder: przy opadzie 1 h szczyt +11,9–12,2% i 40–65 min wcześniej; przy 24 h +5,5–7,8% i 45–65 min wcześniej; objętość równa;
    - błędy jako `application/problem+json`: 404 z `detail` i `hint` po polsku, walidacja 400 zamiast 422, 401 admina;
    - nowa trasa `identify-point` (produkcja: 404);
    - admin: 6 GET z kluczem stagingu dało 200; wiersz `[staging-smoke]` (id 14) dodany, widoczny w panelu i usunięty przez `DELETE`.
- Smoke frontendu w Chromium (1440 × 900 oraz telefon 390 px; ta sama ścieżka na 8080):
  - na mapie: warstwy, SFINCS z legendą i kryciem, nakładka MZP (żądania do `wody.isok.gov.pl` 200), profil z wodą, ekran powitalny (też z „Instrukcji” na szynie), `/instrukcja/` (17 obrazów), `/admin` z kluczem (same GET);
  - komunikat błędu poza granicą = `detail` + `hint`;
  - wszystkie własne zasoby z `?v=`, 0 błędów JS. 404 kafli poza zasięgiem danych są takie same w produkcji;
  - uwagi testerów 1–6 działają na prawdziwym API:
    - kółko, syntetyczne zdarzenia od poziomu 10, bez podkładu: muśnięcia z ogonem kończą się na 11 (produkcja 14/15/17), przeciągnięcie 1 s na 12 (produkcja 16–17), ząbki 5 × 120 ms dają 12 w obu;
    - (i) otwiera tylko kliknięcie (w produkcji najechanie);
    - „Próg akumulacji spływu” 1 ha / 10 ha (w produkcji „Próg FA” w m²);
    - szyna Mapa · Instrukcja · Logowanie;
    - „Usługi działają” tylko w `/admin`;
    - tryb „Identyfikuj”: czasza 4,04 m wody, zwierciadło 277,48 m n.p.m.
- K0:
  - baza zapisana o 12:00:49 przed pierwszą zmianą;
  - diff pusty i `/health` 200 po każdym kroku: pliki i katalogi, prune, zrzut, kopia, testy `db`, budowa, `up`, oba smoke, commit;
  - `git status` w K0 wołany z `--no-optional-locks`, więc nie odświeża indeksu checkoutu produkcji.
- Otwarte:
  - **„nan” zamiast „bez nazwy” w karcie punktu** dla cieków BDOT10k bez nazwy (3436 z 3812 wierszy `bdot_streams` ma `name = 'nan'`, także w produkcji):
    - przyczyna: `core/db_bulk.py:383` (`if row[col]` przepuszcza NaN, `str(NaN)`);
    - poprawka: loader (`pd.notna`) i dane (`NULLIF(name, 'nan')` albo ponowny import), ewentualnie osłona w `core/point_info.py`;
    - nie naprawiane w S2, decyzja przed S3/S5;
  - Snyder przy 24 h odbiega od zakresu 11–12% z ADR-060, liczonego dla krótkich opadów; kierunek i przesunięcie się zgadzają;
  - „głębokość przy zaporze 12,33 m” to odczyt kursora na innej linii. Na linii przez najgłębszą komórkę NMT wychodzi 12,6 m, tak samo w produkcji i stagingu;
  - punkt 51,01544/15,88984 (wyświetlane ujście Kamiennika) trafia w zlewnię cząstkową Kaczawy (134,97 km² w obu stosach). 37,23 km² daje punkt na odcinku 21911/2477 (51,01538/15,890496);
  - po błędzie wyznaczania pasek kontekstu i tytuł panelu pokazują poprzednią zlewnię; tak samo w produkcji.
- Stan: zielony stos działa na 8081 (zestaw `copy`), K1 spełnione. S3 nie rozpoczęty.

### S3 (2026-11-02): zrobione

- Commity na `feature/store-migration` (bez push): `0f913a2` nginx stagingu także na `192.168.88.9:8081` (polecenie autora w trakcie S3, opis w „Zasadach izolacji”), potem commit z zapisem w PROGRESS (sesja S3, tabele porównań) i tymi wynikami.
- Zestaw `s3`: `CREATE DATABASE hydro_s3` i `CREATE EXTENSION postgis` (PostGIS 3.4.3), migracje 001 → 003 z entrypointu kontenera bootstrapu; katalogi `s3/{data,frontend-data,frontend-tiles}` (777); granica `s3/data/boundary/kamiennik_37km2_sfincs.gpkg` skopiowana z produkcji (SHA-256 równe, 37,2234 km²).
- Bootstrap poleceniem z planu; dodane tylko `-T` i `-e PYTHONUNBUFFERED=1`, żeby wiersze logu szły po kolei:
  - kod 0, 372,4 s (377,7 s z kontenerem), obraz `hydrograf-api:store-staging` (`ce03f2f4f201…`); `hydro_staging_api` (zestaw `copy`) bez zmian;
  - limity kontenera z `docker inspect`: 3 GiB RAM (+3 GiB swap), 2 CPU, `read_only`, `/tmp` 2G;
  - logi w `${HYDROGRAF_STAGING_ROOT}`: `bootstrap-s3-20261102.log`, `.ts.log` (czas hosta), `-mem.tsv` (cgroup co 1 s), `.exit`;
  - kroki (czas z bootstrapu, szczyt `memory.current` cgroup, w nawiasie pamięć anonimowa): 2 NMT 15/15 arkuszy 27,4 s, 214 MiB (110); 3 przetwarzanie NMT 3 048 412 komórek, 4437 odcinków, wypalanie BDOT10k 210,6 s, 1306 MiB (729); 4 pokrycie terenu 18 305 obiektów, 2 powiaty 4,8 s, 1116 MiB (539); 5 HSG z rastra Polski (`calculate_hsg`) 1 poligon B 41,0 s, 2059 MiB (1446); 6 opady 24/24 punkty, 10 368 rekordów 31,7 s, 1180 MiB (565); 7 depresje 13 173 2,3 s, 1249 MiB (631); 8 kafle MVT 36,4 s, 1553 MiB (754); 9 nakładki PNG i 850 kafli NMT 18,1 s, 1775 MiB (853). Szczyt całego przebiegu 2,09 GiB (`memory.peak`), swap 0;
  - ostrzeżenia w logu tylko trzy, te same co w bootstrapie produkcji z 2026-10-30: `GDAL not available, falling back to rasterio.merge`, `POSTGRES_PASSWORD is empty`, `16 segments dropped by unique constraint (threshold=10000 m²)` (w produkcji 65 i 4).
- Magazyn (`${HYDROGRAF_STAGING_ROOT}/cache`, 256 MB):
  - znacznik `kartograf/kartograf-store.json` = `kartograf-store/1` (producer 0.8.0.dev0);
  - `list_segments`: `nmt/pl_1992_5m_evrf2007` z 15 arkuszami, tymi samymi co w logu kroku 2 (14 z kampanii 2020-04-18, 1 z 2025-06-13), `landcover/pl_bdot10k_gpkg` z powiatami 0205 (49,9 MB) i 0226 (161,3 MB), `hsg/global_soilgrids_0-5cm_mean` (raster Polski `167000_29000_860000_814000.tif`) oraz `soil/global_soilgrids_{clay,sand,silt}_0-5cm_mean`;
  - 57 sidecarów `kartograf-meta/1`, SHA-256 i rozmiar zgodne z plikami we wszystkich;
  - `kartograf_meta.db` obok magazynu; w `cache/` są tylko `kartograf/` i `kartograf_meta.db`, bez `cache/nmt`, `cache/bdot10k`, `cache/soil_hsg`;
  - **niezgodność:** `iter_store` zgłasza 15 × `missing_sidecar`. To pliki `<arkusz>.prj` obok `.asc` w ścieżkach standardowych segmentu NMT, zapisane w kroku 3 przez Hydrografa (`utils/raster_utils.py`, `_ensure_prj_sidecar` w `normalize_crs`), nie przez Kartografa. Kolejnym zapisom Kartografa nie przeszkadzają (magazyn ma znacznik), ale magazyn nie jest czysty w sensie ADR-061, a przy magazynie wspólnym z Archiwistą obce pliki byłyby błędem. Decyzja przed S5: CRS bez pliku obok arkusza (np. `crs=EPSG:2180` przy odczycie albo `.prj` w `data/nmt/`) i usunięcie tych 15 plików.
- Wyjścia pipeline'u: kroki 2–9 `done`, 1 i 10 pominięte; `hydro_s3` (70 MB): `stream_network` 4421 (395 przy progu 100000, 4026 przy 10000), `stream_catchments` 4437, `land_cover` 18 305, `soil_hsg` 1, `precipitation_data` 10 368, `depressions` 13 173, `bdot_streams` 4915. NMT pokrywa granicę w 100% (37,2234 km², bez nodata), `land_cover` i `soil_hsg` też w 100%, zlewnie progu 100000 w 99,98%. Są kafle MVT `streams`/`catchments` dla obu progów (33 829 plików), `dem.png`, `dem_tiles/` (850), `streams.png`, `depressions.png`, `bdot_*.geojson`, `soil_hsg.geojson`.
- Porównanie (tabele w PROGRESS, sesja S3). API zestawu `s3` w `hydro_staging_api_s3` bez portu, zapytania przez `docker exec`; po porównaniu kontener usunięty. Przekroje K1–T3 brane z punktów delineacji `x_delin`/`y_delin` z `cross_sections.gpkg`, hydrogramy 12 h, p = 1%.
  - Kamiennik (ujście na odcinku 21911/2477 i K1–T3): powierzchnie i CN w `s3` identyczne z produkcją i `copy` (Δ 0,0%, ΔCN 0), IoU granic 1,000 (przy ujściu różnica symetryczna 0 m²). Te same arkusze i kampanie GUGiK oraz ten sam BDOT10k do wypalania dają tę samą sieć. IoU z domeną SFINCS wynosi 0,998 w obu stosach;
  - wyświetlane ujście 51,015442/15,889836 trafia w zlewnię cząstkową Kaczawy (jak w S2): produkcja i `copy` 134,97 km², `s3` 40,22 km² (IoU 0,298). Obszar `s3` kończy się na arkuszach Kamiennika, więc Kaczawa ma w nim tylko około 3 km² własnej zlewni. To efekt krawędzi obszaru testowego, nie danych magazynu;
  - PMAXTP: źródło jest to samo, ale siatka 2 km w `s3` jest przesunięta o 815 m względem produkcji (jej początek to narożnik bbox obszaru). IDW w centroidzie daje więc −0,8…+0,8% (102,41–104,23 mm). W S5 obszar, bbox i siatka będą jak w produkcji;
  - SCS-CN i Nash: `s3` względem `copy` −1,7…+1,6% szczytu, cała różnica z opadu; `copy` = produkcja co do wartości;
  - Snyder, efekt kodu (Hydrolog 1.0, ADR-060): `copy` względem produkcji +3,5…+9,6% szczytu i 15–45 min wcześniej przy 12 h (mniej w małych zlewniach T2/T3), objętość równa; w `s3` tak samo jak w `copy` (±1,7%). Zakres „+11–12%, 25–70 min” z kryterium dotyczy krótkich opadów (S2: 1 h +11,9–12,2%). To oczekiwana zmiana, nie błąd;
  - drobna różnica morfometrii przy ujściu: `divide_flow_path_km` 17,59 → 16,04 (w `s3` równa najdłuższej drodze spływu), `length_km` 16,048 → 16,042. Drogi spływu z działu ma około 5% zlewni cząstkowych w obu bazach; tu inaczej wypadła jedna zlewnia czołowa. Na hydrogramy wpływ pomijalny.
- Kryteria akceptacji:
  - magazyn kompletny i zweryfikowany, kod 0: tak, z niezgodnością `.prj` opisaną wyżej;
  - powierzchnie ≤ 2%: tak (0,0%); wyświetlane ujście odstaje przez krawędź obszaru (opisane);
  - CN ≤ 2: tak (0);
  - opad PMAXTP równy: źródło tak, wartość ±0,8% przez przesuniętą siatkę;
  - SCS-CN i Nash ±5% `s3`–`copy`: tak (≤ 1,7%);
  - Snyder `copy`–produkcja: kierunek zgodny z ADR-060, wielkość przy 12 h +3,5…+9,6% i 15–45 min, czyli poniżej zakresu dla krótkich opadów; opisane;
  - tabela w PROGRESS, `hydro_staging_api_s3` usunięty: tak;
  - K0 bez zmian: tak.
- Smoke w przeglądarce na 8081 z danymi `s3`, 12:54:31–12:57:55. `HYDROGRAF_STAGING_SET=s3 HYDROGRAF_STAGING_DB=hydro_s3 scripts/staging-compose.sh up -d --no-deps api nginx`, potem powrót tym samym poleceniem bez zmiennych (zestaw `copy`):
  - warstwy: NMT, zbiorniki i cieki BDOT10k, HSG, pokrycie terenu, zagłębienia, linie spływu 1 ha i 10 ha, wynik SFINCS 24 h (opublikowany w `s3` przez równoległą sesję, nie przez bootstrap), MZP (`wody.isok.gov.pl` 200);
  - (i) otwiera tylko kliknięcie, Esc zamyka; „Próg akumulacji spływu” 1 ha / 10 ha; szyna Mapa · Instrukcja · Logowanie;
  - Identyfikuj: w czaszy 264,88 m n.p.m., woda 16,55 m i zwierciadło 281,43 m (wynik 24 h), Kamiennik 0,1 m, HSG B, odcinek 37,11 km² (te same wartości co w `copy`); na Kamienniku przy K3 326,10 m i 15,53 km²;
  - profil przez czaszę: 1,04 km z linią wody; wyznaczenie zlewni w ujściu: 37,23 km², CN 67,9;
  - 0 błędów JS (raz `ERR_ABORTED` przerwanego kafla MZP przy zmianie widoku); zrzuty w `~/scratch/store-s3/`.
- Staging w sieci domowej (`0f913a2`): odtworzony tylko `hydro_staging_nginx`; `curl -sI http://192.168.88.9:8081/` daje 200 z CSP. Strona przez adres LAN działa: zasoby z `?v=`, API, kafle, 0 błędów JS. Produkcja z LAN niedostępna.
- K0: pusty diff i `/health` 200 przed każdą czynnością i po niej (od 12:36 do końca kroku), w tym przed i po bootstrapie, kontenerze `hydro_staging_api_s3`, oknie `s3` na 8081 i zmianie nginx.
- Do S4 (poza decyzjami z „Otwartych decyzji”):
  - pliki `.prj` Hydrografa w magazynie Kartografa (wyżej);
  - „nan” w karcie punktu odtwarza się na danych z bootstrapu: T2 pokazuje „nan (rzeka)”, a w `hydro_s3` 4410 z 4915 wierszy `bdot_streams` ma `name = 'nan'`. Winny jest loader (`core/db_bulk.py`), więc bez poprawki S5 zapisze to samo;
  - siatka PMAXTP zależy od bbox obszaru; w S5 ten sam bbox co w produkcji;
  - wynik SFINCS 12 h zastąpiła w obu zestawach stagingu (`copy`, `s3`) publikacja wyniku 24 h z równoległej sesji, więc smoke z S2 z 277,48 m dotyczy teraz 281,43 m.
- Stan: zielony stos na `127.0.0.1:8081` i `192.168.88.9:8081` z zestawem `copy` (API na bazie `hydro_db`); zestaw `s3` i baza `hydro_s3` gotowe do ponownego użycia; S4 czeka na autora.

### S4 i przygotowanie S5 (2026-11-02): zrobione

- Decyzje autora (S4): dwie wady naprawić przed S5; magazyn wspólny z Archiwistą; wiązanie LAN stagingu usunąć po S7 (wpisane w „Zasadach izolacji” i w S7).
- Commity na `feature/store-migration` (bez push): `625089e` CRS mozaiki zamiast plików `.prj` w magazynie, `059f44a` brak nazwy cieku BDOT10k jako `NULL` zamiast `'nan'`, `ac06921` magazyn wspólny (ADR-066, `HYDROGRAF_KARTOGRAF_ROOT`, strażnik kroku 2, czyszczenie), `c519a98` montowanie magazynu w stagingu, potem commit z zapisem w PROGRESS i tymi wynikami.
- **`.prj`:** `normalize_crs(files, output_dir)` niczego nie zapisuje obok arkuszy (`output_dir` wymagany, bez domyślnego `reprojected/` w magazynie), CRS mozaiki nadaje `create_vrt_mosaic(target_crs="EPSG:2180")`: `gdalbuildvrt -a_srs … -allow_projection_difference` (bez tej flagi GDAL 3.10.3 pomija arkusz o innym lub brakującym CRS, sprawdzone) albo GeoTIFF zapasowego `rasterio.merge`, którego używa kontener (nie ma narzędzi GDAL). Magazyn stagingu (`${HYDROGRAF_STAGING_ROOT}/cache/kartograf`) oczyszczony w `run --rm` jako UID 999: `iter_store` przed — 15 × `missing_sidecar` (wszystkie to `<arkusz>.prj` obok `.asc` w ścieżkach standardowych), usunięte dokładnie te pliki, po — 0 problemów (21 `link`, 21 `version`, 15 `full_sheet`, 6 segmentów).
- **„nan”:** loader (`core/db_bulk.py`) zapisuje brak lub pustą nazwę jako `NULL` i przycina nazwy; GeoJSON-y BDOT10k już miały `null` (test), `land_cover` nie bierze tekstu z GeoPackage. Polecenie dla baz sprzed poprawki: `UPDATE bdot_streams SET name = NULL WHERE btrim(name) IN ('', 'nan');` — wykonane w stagingu w transakcji: `hydro_s3` 4410 wierszy (zostaje 505 nazw), `hydro_db` zestawu `copy` 3436 (zostaje 376); produkcyjnej bazy nie ruszano, S5 zbuduje `hydro_s5` poprawionym loaderem. `POST /api/identify-point` na 8081 przy cieku bez nazwy zwraca `name: null`, karta w Chromium: „Ciek: bez nazwy (rzeka)”, 0 błędów JS.
- **Magazyn wspólny (ADR-066):** `~/data/archiwista-public/store` (`kartograf-store/1`, 4 segmenty NMT, 735 wersji, 205 z 207 arkuszy `mniejszy_sheets.txt`; brakuje `M-33-33-C-b-2-1` i `M-33-45-B-c-1-1`). Kartograf `26ee459` nie ma blokad: wersje i sidecary publikuje wyłączne `os.link`, ścieżki standardowe przestawia `os.replace`, równoległe zapisy tej samej treści dają jedną wersję. Reguła: bootstrap Hydrografa pisze tylko wtedy, gdy nie trwa zadanie pobierania Archiwisty; strażnik w kroku 2 (`writes_in_progress`: wpis `versions/.incoming` zmieniony w ostatnich 10 min) zatrzymuje go przed pierwszym zapisem. Archiwista nie sprawdza zapisów Hydrografa, więc w czasie S5 nikt nie uruchamia pobierań w Archiwiście.
- **Uprawnienia (ACL), wykonane jako właściciel `claude-agent` o 13:50:48Z:** na hoście nie ma pakietu `acl` ani sudo, więc `setfacl`/`getfacl` 2.3.2 z paczki Debiana (`apt-get download acl`, `dpkg-deb -x` do `~/scratch/store-pre-s5/acl/`):
  ```bash
  setfacl -R -m u:999:rwX /home/claude-agent/data/archiwista-public/store
  setfacl -R -d -m u:999:rwX,u:claude-agent:rwX /home/claude-agent/data/archiwista-public/store
  ```
  Przed: 3827 katalogów 700 i 4041 plików 600 `claude-agent`, bez ACL (ext4, ACL działa). Po: wszystkie 7868 obiektów mają `user:999` (katalogi `rwx`, pliki `rw-`), 3827 katalogów ma domyślne wpisy `999` i `claude-agent` (zastępują umask 077 Archiwisty i 022 kontenera). Rodzice (`/home/claude-agent` 700, `.../archiwista-public` 700) bez zmian: kontener widzi magazyn przez bind mount i nie przechodzi przez rodziców (sprawdzone jako UID 999). Próba na katalogu testowym z tym samym ACL i rodzicem 700: UID 999 czyta, tworzy, dowiązuje plik `claude-agent` i przestawia ścieżkę standardową; `claude-agent` z umask 077 czyta i dowiązuje pliki UID 999 (`fs.protected_hardlinks = 1`). Ograniczenie: paczki BDOT10k Kartograf rozpakowuje w `/tmp` i przenosi z trybem pliku tymczasowego, więc dostają maskę `---` (Archiwista) albo `r--` (Hydrograf); naprawa to ponowne pierwsze `setfacl`, kandydat na zgłoszenie do Kartografa. Wycofanie: `setfacl -R -b` na magazynie.
- **Archiwista po zmianie (bez restartu i bez sesji w imieniu autora):** proces 408498 działa od 1 d 4 h; `GET /` 200 i `GET /api/v1/session/methods` 200 (z nagłówkami proxy HTTPS); `index.sqlite` czytany tylko do odczytu: skan `07d9d4c2114afb3e` o 13:56:41Z (pierwszy po ACL) `succeeded`, magazyn `zespol` `available`, 735 wersji, 4 segmenty, 2 problemy (te same `stale_incoming` z 2026-11-01), brak zadań w kolejce.
- **Staging:** `docker-compose.staging.yml` montuje `${HYDROGRAF_KARTOGRAF_STORE}` pod `/kartograf` (domyślnie `:ro`, `HYDROGRAF_KARTOGRAF_STORE_MODE=rw` tylko dla kontenera bootstrapu) i ustawia `HYDROGRAF_KARTOGRAF_ROOT=/kartograf`; `.env.staging` ma `HYDROGRAF_KARTOGRAF_STORE`. `config` pokazuje `read_only: true` domyślnie i montowanie rw z `MODE=rw`. Obraz `hydrograf-api:store-staging` przebudowany z tym kodem (`sha256:2a8b1eb4fc68…`, 3,6 s z cache warstw); `hydrograf-api:latest` bez zmian. Działający `hydro_staging_api` (zestaw `copy`) nie był odtwarzany: nowe montowanie dostanie przy `up` w S5.
- **Smoke** `scripts/staging-compose.sh run --rm --no-deps -T --entrypoint python -e PYTHONPATH=/app --name hydro_staging_store_smoke … api /smoke_store.py` (bez migracji i bazy): UID 999, `store_dir(/cache)` = `/kartograf`, metadane w `/cache/kartograf_meta.db`, zapis do magazynu niemożliwy (ro); `list_segments` = `nmt/pl_1992_1m_evrf2007`, `nmt/pl_1992_1m_kron86`, `nmt/pl_1992_5m_evrf2007`, `nmt/pl_1992_xyz_5m_evrf2007`; `iter_store` 642 `link`, 642 `full_sheet`, 735 `version`, 2 `stale_incoming`; `writes_in_progress` = []; mozaika dwóch arkuszy magazynu bez `.prj` (`M-33-32-D-d-3-1`, `-3-2`) → `dem_mosaic.tif` EPSG:2180 897 × 500, katalogi arkuszy bez zmian; kontener usunięty.
- **Bramka i testy:** `GATE_COMMIT_RANGE=04d4550..HEAD bash scripts/gate.sh` zielona: 1389 testów offline (było 1381: +14 nowych, −6 testów usuniętych funkcji `.prj`), pokrycie 86,64%; testy `db` na jednorazowej `hydro_staging_testdb` (migracje 001 → 003): 15 zaliczonych, 1 pominięty jak w S2, kontener zatrzymany.
- K0: pusty diff i `/health` 200 przed każdą czynnością i po niej (ACL, usuwanie `.prj`, SQL, budowa obrazu, smoke, commity).
- Stan: zielony stos na `127.0.0.1:8081` i `192.168.88.9:8081` z zestawem `copy`; magazyn wspólny gotowy dla S5 (ACL, montowanie, obraz). S5 nie rozpoczęty.

### H1 (2026-11-02): zrobione

Krok H1 planu Nogata `docs/plans/2026-11-02-archiwista-sets-for-hydrograf.md` (gałąź `plan/archiwista-sets-hydrograf`): zestaw Archiwisty jako jedyne wejście Kartografa, ADR-067 (ADR-066 zastąpiony w części: decyzje 2 i 4).

- **Bootstrap z zestawu:** `python -m scripts.bootstrap --project PATH --set NAZWA [--dry-run]` (`PATH` to katalog projektu albo jego `archiwista-project.json`; wyklucza się z `--bbox`, `--sheets`, `--boundary-file`; nazwa zestawu porównywana po NFC, przycięciu i case-fold). Przed krokiem 1, po kolei: plik projektu (`archiwista-project/1`), plik obszaru (`obszary/…`) i jego SHA-256, zestaw zamknięty (`state` brak albo `closed`; `open` odrzucany), zapisany `pins_sha256` równy obliczonemu, magazyn Kartografa projektu (`store_state` = `marked`; przy ustawionym `HYDROGRAF_KARTOGRAF_ROOT` ten sam katalog, `os.path.samefile`), każdy pin Kartografa czytany w całości (rozmiar i SHA-256), potem wymagania:
  - arkusze obszaru projektu (`find_sheets_for_geometry(<obszar>, "1:10000", sheet_system="1992")`) wśród pinów segmentu `nmt/pl_1992_<--resolution>_evrf2007/versions/` (D3: 205 arkuszy, które Kartograf wybiera z obszaru; przypięte arkusze spoza obszaru też wchodzą do mozaiki);
  - bez `--skip-landcover`: powiaty, które PRG podaje dla prostokąta ramek przypiętych arkuszy (`Bdot10kProvider.teryts_for_area`), wśród pinów BDOT10k;
  - bez `--skip-hsg`: dokładnie jeden pin HSG, którego zamówiony prostokąt z sidecara Kartografa (`read_sidecar(...).request`, przeliczony do EPSG:2180) pokrywa prostokąt mozaiki NMT (D4: zestaw ma prostokąt Polski + 100 km; ścieżka magazynu prywatnego zostaje przy `167000 29000 860000 814000`);
  - jedna wersja na jednostkę (arkusz, TERYT, prostokąt); inne piny Kartografa (wejścia SoilGrids) sprawdzone, nieużywane; piny innych producentów nie są czytane.
- **Kroki 2–5 z zestawu:** krok 2 niczego nie pobiera i podaje `N/N arkuszy z zestawu`, krok 3 wypala cieki z przypiętych paczek BDOT10k, krok 4 je importuje, krok 5 przycina przypięty raster HSG do mozaiki; kroki 6–10 bez zmian (IMGW PMAXTP poza zestawami, siatka opadów z prostokąta WGS84 obszaru). `--dry-run` kończy się po wszystkich sprawdzeniach i wypisuje projekt, stan (`closed_at`, `closed_by`), SHA-256 obszaru, `pins_sha256`, magazyn, piny i kroki 2–5.
- **Tożsamość zestawu:** jeden wiersz INFO `Bootstrap from a set: {json}` i plik `<output>/bootstrap_set.json` (`hydrograf-bootstrap-set/1`: projekt, zestaw z `pins_sha256`, magazyn, wejścia, `started_at`, `finished_at`, `status` running → ok albo failed); przebieg bez zestawu usuwa plik. Panel admina go nie pokazuje (poza zakresem).
- **Odmowy:** ostatni wiersz stderr to dokument błędu `hydrograf-error/1`, przed nim polskie `BŁĄD:` i `Wskazówka:`; kod wyjścia z rejestru (tabela w ADR-067: m.in. `set_open` 4, `pin_missing` 3, `pin_changed` i `set_digest_mismatch` 7, `store_missing` 8, `pin_unreadable` 9, `shared_store_read_only` 12, `set_sheets_missing`/`set_counties_missing`/`set_hsg_missing` 14). Wszystkie kody są w rejestrze, nowych nie ma; nowe klasy `InvalidDataError` (`data_error`) i `SourceUnavailableError` (`source_unavailable`), teksty EN i PL w `core/messages.py`.
- **Tylko odczyt (D8, D11):** `refuse_shared_store()` i `private_store_dir(cache_dir)` w `utils/kartograf_store.py`; przy ustawionym `HYDROGRAF_KARTOGRAF_ROOT` odmawiają `download_bdot10k`, `download_dem.download_sheets`, `download_landcover.fetch_landcover` i kroki 2 i 5 ścieżki prywatnej, więc także `download_dem`, `download_landcover`, `prepare_area`, `analyze_watershed --download` i zapasowe CN (błąd w logu, CN domyślne). `POST /api/admin/bootstrap/start` odpowiada `403` problem+json przed uruchomieniem procesu. Usunięte bez podkładek: `writes_in_progress`, `ACTIVE_WRITE_WINDOW_S`, `STAGING_GLOB`, strażnik kroku 2, `HYDROGRAF_KARTOGRAF_STORE_MODE` w `docker-compose.staging.yml`. `describe_error` opisuje też `HydrografError`.
- **Moduły i testy:** `utils/archiwista_project.py` (czytnik projektu i zestawu, `pins_digest`, `verify_pins`), `utils/kartograf_set.py` (`set_inputs` → `SetInputs`); `tests/unit/test_bootstrap_set.py` (prawdziwy Kartograf, magazyn offline: zamknięty zestaw, każda odmowa z tabeli, powiaty, PRG, arkusze, HSG, niejednoznaczność, opcje obszaru przy magazynie wspólnym, wektor testowy skrótu), `test_kartograf_store.py` (brak pobierania przy magazynie wspólnym), `test_admin_bootstrap.py` (403); test kontraktowy `test_messages.py` przegląda też `utils` i `scripts`.
- **Poprawka ADR-066 (fakt 4):** wada trybu pliku (`mkdtemp` + `shutil.move` zawęża maskę ACL) jest w RCN `_unpack_checked_layers` i WFS `_fetch_features` Kartografa, nie w BDOT10k; paczki BDOT10k są kopiowane treścią (`shutil.copyfile`) do katalogu roboczego magazynu i publikowane `os.replace`, więc UID 999 je czyta. Naprawa w Kartografie później, w jego sesji (D10).
- **Smoke `--dry-run` (2026-11-02, kod worktree), magazyn jednorazowy:** kopia prywatnego magazynu S3 (15 arkuszy, BDOT10k 0205 i 0226, HSG Polski, 3 wejścia SoilGrids; 21 wersji) w `/home/claude-agent/data/tmp/h1-smoke/`, projekt z czterema zestawami:
  - zamknięty zestaw: kod 0, 15/15 arkuszy obszaru, PRG odpowiedział 0205 i 0226, raster HSG, skrót z pliku;
  - zestaw otwarty: kod 4 `set_open`; brakujący pin: kod 3; zestaw bez BDOT10k: kod 14 `set_counties_missing` (0205, 0226);
  - kopia z jednym zmienionym SHA-256: kod 7 `pin_changed` (zestaw bez skrótu) i kod 7 `set_digest_mismatch` (zamknięty zestaw ze skrótem);
  - nieznany zestaw: kod 3 (lista zestawów); `--bbox` przy `HYDROGRAF_KARTOGRAF_ROOT`: kod 12 `forbidden`; `--project` bez `--set`: kod 2; inny `HYDROGRAF_KARTOGRAF_ROOT`: kod 2 `store_mismatch`;
  - magazyn bez zmian (272 wpisy).
- **Smoke na prawdziwym magazynie wspólnym** (tylko odczyt) z kopią pliku projektu Kaczawy (zestaw „2020”, 205 pinów, bez `state`): `--skip-landcover --skip-hsg --dry-run` kod 0, 205/205 pinów zweryfikowanych, 205 arkuszy obszaru (około 3 s); bez pominięć kod 14 `set_counties_missing` z dziesięcioma powiatami 0205, 0206, 0207, 0209, 0218, 0219, 0221, 0226, 0261, 0262 (zestaw „2020” ma tylko NMT, zestaw dla S5 zbuduje autor w A5). Magazyn bez zmian (7868 wpisów).
- **Testy `db`** na jednorazowej bazie PostGIS `hydro_h1_testdb` (127.0.0.1:55432, migracje 001 → 003): 15 zaliczonych, 1 pominięty.
- **Pełny przebieg kroków 2–5 z zestawu** (bez `--dry-run`, kopia kodu w `/home/claude-agent/data/tmp/h1-smoke/app`, baza `hydro_h1_smoke` w `hydro_h1_testdb`, `HYDROGRAF_KARTOGRAF_ROOT` = magazyn jednorazowy, `--skip-infra`, kroki 6–10 pominięte): kod 0 w 110 s; krok 2 `15/15 arkuszy z zestawu`, krok 3 3 048 412 komórek i 4437 odcinków z wypalaniem przypiętego BDOT10k, krok 4 18 305 obiektów z 2 powiatów, krok 5 raster HSG zestawu (1 poligon B) — te same liczby co bootstrap S3 (`stream_network` 4421, `stream_catchments` 4437, `land_cover` 18 305, `soil_hsg` 1); `bootstrap_set.json` ze statusem `ok`, `started_at` i `finished_at`; magazyn bez zmian. Kontener bazy zatrzymany (`--rm`).
- **Bramka:** `GATE_COMMIT_RANGE=04d4550..HEAD bash scripts/gate.sh` zielona: 1416 testów offline, pokrycie 86,84%.
- Montowania pod ścieżkami hosta, katalog projektu i ACL `rX` to krok H2 (po A3 i A4).
