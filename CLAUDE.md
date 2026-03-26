# Instrukcje dla Claude Code

Hydrograf — hub hydrologiczny (FastAPI + PostGIS + Hydrolog + Kartograf + IMGWTools). Szczegoly: `docs/PRD.md`, architektura: `docs/ARCHITECTURE.md`.

## Srodowisko Python

Uzywaj srodowiska wirtualnego z `backend/.venv`:
- Python: `backend/.venv/bin/python`
- Pip: `backend/.venv/bin/pip`
- Wymagany Python: 3.12+

## Uruchamianie uslugi

Uzytkownik `claude-agent` nie jest w grupie `docker` — korzysta z **rootless Docker**:

```bash
# 1. Uruchom rootless daemon (jesli nie dziala)
dockerd-rootless.sh &>/tmp/dockerd-rootless.log &
sleep 3

# 2. Ustaw socket
export DOCKER_HOST=unix:///home/claude-agent/.docker/run/docker.sock

# 3. Pelny stack (frontend + API + DB) na porcie 8080
docker compose up -d
```

**Dostep z sieci lokalnej** wymaga reguly UFW (rootless Docker nie modyfikuje iptables):
```bash
sudo ufw allow from 192.168.88.0/24 to any port 8080 proto tcp
```

**Dostep zewnetrzny** przez Cloudflare Tunnel (bez otwierania portow):
```bash
cloudflared tunnel --url http://localhost:8080
```

## Dokumentacja

**Przeczytaj w kolejnosci:**
1. `docs/PROGRESS.md` — aktualny stan projektu i zadania
2. `docs/SCOPE.md` — zakres projektu (co IN/OUT)
3. `docs/PRD.md` — wymagania produktowe
4. `docs/ARCHITECTURE.md` — architektura systemu
5. `docs/DECISIONS.md` — rejestr decyzji architektonicznych (ADR)
6. `docs/CHANGELOG.md` — historia zmian per-release

Dodatkowa dokumentacja:
- `docs/DATA_MODEL.md` — schemat bazy danych PostGIS
- `docs/KARTOGRAF_INTEGRATION.md` — integracja z Kartografem (NMT, Land Cover)
- `docs/HYDROLOG_INTEGRATION.md` — integracja z Hydrologiem (obliczenia)
- `docs/IMGWTOOLS_INTEGRATION.md` — integracja z IMGWTools (opady)
- `docs/CROSS_PROJECT_ANALYSIS.md` — analiza zaleznosci miedzy projektami

## Struktura modulow

Pelna mapa modulow: `docs/ARCHITECTURE.md` §2.1 (backend) i §4.1 (frontend).

- `backend/api/endpoints/` — endpointy REST API (FastAPI)
- `backend/core/` — logika biznesowa
- `backend/scripts/` — skrypty CLI preprocessingu (bootstrap.py orchestrator)
- `backend/models/schemas.py` — modele Pydantic
- `frontend/js/` — moduly JS (IIFE na `window.Hydrograf`)

## Podejscie wieloagentowe

Glowny agent pelni role **nadzorcy zespolu** — oszczedza wlasny kontekst i deleguje prace do sub-agentow (Task tool). Kazde zadanie dziel na male, logiczne kawalki wykonywane w cyklu:

1. **Researcher** (subagent_type=Explore) — analiza kodu, szukanie plikow, zrozumienie kontekstu
2. **Developer** (subagent_type=general-purpose) — implementacja zmian (Edit/Write)
3. **Tester** (subagent_type=general-purpose) — uruchomienie testow, lint, weryfikacja

Przejscie dalej dopiero po potwierdzeniu od Testera. Jesli testy nie przechodza — Developer poprawia, Tester weryfikuje ponownie.

**Zasady delegowania:**
- Kazdy sub-agent dostaje pelny kontekst zadania (cel, pliki, ograniczenia)
- Jawnie informuj sub-agenta o dostepnych narzedziach i sciezkach (`.venv`, Docker)
- Niezalezne zadania uruchamiaj rownolegle (wiele Task w jednej wiadomosci)
- Glowny agent NIE czyta plikow ani nie pisze kodu sam — deleguje i weryfikuje wyniki

## Workflow sesji

### Poczatek sesji
1. Przeczytaj `docs/PROGRESS.md` — sekcja "Ostatnia sesja"
2. `git status` + `git log --oneline -5`
3. Sprawdz na ktorej jestes galezi (`git branch --show-current`) — pracuj na `develop`

### W trakcie sesji
- Commituj czesto (male zmiany)
- Aktualizuj `docs/CHANGELOG.md` na biezaco
- W razie watpliwosci — pytaj

### Koniec sesji
**OBOWIAZKOWO zaktualizuj** `docs/PROGRESS.md`:
- Co zostalo zrobione
- Co jest w trakcie (plik, linia, kontekst)
- Nastepne kroki

### Git Workflow

**Galecie:**
- **main** — stabilna wersja (tylko merge z develop po checkpoincie)
- **develop** — domyslna galaz robocza (zadania trywialne, brak ryzyka konfliktow)
- **feature/*** — gdy wiele zespolow agentow pracuje rownolegle lub istnieje ryzyko konfliktu

**Strategia branchowania:**
- Jedno zadanie, jeden zespol → commituj na `develop`
- Wiele zespolow rownolegle → kazdy zespol na osobnej `feature/*`, po zakonczeniu pracy dedykowany agent rozwiazuje konflikty i merguje do `develop`

**Commity:** Conventional Commits z scope:
- `feat(api): ...` — nowa funkcjonalnosc
- `fix(core): ...` — naprawa bledu
- `docs(readme): ...` — dokumentacja
- `refactor(db): ...` — refactoring
- `test(unit): ...` — testy

Scope: `api`, `core`, `db`, `frontend`, `tests`, `docs`, `docker`

## Priorytety kodu

1. **Bezpieczenstwo danych** — walidacja inputow, parametryzowane SQL, brak wyciekow danych
2. **Przejrzystosc i prostosc** — kod czytelny bez komentarzy, proste struktury, brak przedwczesnych abstrakcji
3. **Efektywnosc** — optymalizuj dopiero gdy jest udowodniony problem wydajnosciowy

Jesli prostsze rozwiazanie jest wolniejsze, wybierz prostsze. Jesli bezpieczniejsze rozwiazanie jest mniej czytelne, wybierz bezpieczniejsze.

## Specyfika projektu

### Biblioteki wlasne
- **Hydrolog**, **Kartograf**, **IMGWTools** — dostepne z GitHub, nie z PyPI
- Wersje: `backend/requirements.txt`
- Szczegoly integracji: `docs/*_INTEGRATION.md`, `docs/CROSS_PROJECT_ANALYSIS.md`

### Kluczowe ograniczenia
- PostGIS jest **wymagany** — cala logika oparta na SQL spatial queries
- Metoda SCS-CN ograniczona do zlewni <= 250 km²
- Frontend: statyczny HTML/JS, brak frameworka (Vanilla JS)
- API memory limit: 512M (CatchmentGraph ~0.5 MB)

### Konwencje nazewnictwa z jednostkami
```python
area_km2 = 45.3
elevation_m = 150.0
discharge_m3s = 12.5
time_concentration_min = 68.5
slope_percent = 3.2
precipitation_mm = 25.0
length_km = 12.3
```
