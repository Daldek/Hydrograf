# Multi-Tenancy: Operatorzy, Uzytkownicy i Przestrzenie Robocze

**Data:** 2026-03-26
**Status:** Draft
**Branch:** `feature/multi-tenancy`

## 1. Cel

Wprowadzenie do Hydrografa pojec: operator (organizacja), uzytkownik i przestrzen robocza (workspace). Kazdy workspace to niezalezny obszar analizy hydrologicznej z wlasnym pipeline'em i danymi. System pelny open-source, komercjalizacja wylacznie na hostingu SaaS, supportcie i szkoleniach.

## 2. Model deploymentu

- **On-premise** — jedna organizacja, pelna kontrola nad danymi
- **SaaS** — wiele organizacji na jednej instancji, hosting i utrzymanie po stronie dostawcy
- Ten sam codebase, roznica tylko w konfiguracji

## 3. Hierarchia rol

| Rola | Zakres | Uprawnienia |
|------|--------|-------------|
| `platform_admin` | Cala instancja | Superuser — pelny dostep do wszystkiego |
| `org_admin` | Organizacja | Zarzadza organizacja: uzytkownicy, goscie, domeny, limity, ustawienia |
| `org_moderator` | Grupy w organizacji | Zaprasza/usuwa userow z domen org (bez gosci), zarzadza czlonkami swoich grup, wglad w workspace'y czlonkow grup |
| `user` | Wlasne workspace'y | Tworzy workspace'y, uruchamia pipeline, analizuje, udostepnia |
| `guest` | Udostepnione workspace'y | Read-only na workspace'ach udostepnionych przez innych |

## 4. Organizacje

- Tworzone przez admina platformy (brak self-service)
- Kazda organizacja ma >= 1 domene email (`organization_domains`)
- Multi-domena: np. uczelnia z kilkoma wydzialami, kazdy z wlasna domena
- Admin operatora zaprosi uzytkownikow — email z domeny org = rola `user`, email spoza = rola `guest`
- Brak publicznej rejestracji — bez zaproszenia nie ma dostepu

## 5. Grupy

Mechanizm delegowania zarzadzania uzytkownikami:

- Grupa nalezy do organizacji
- `manager` grupy = moderator tej grupy (moze byc wielu)
- `member` grupy = zwykly uzytkownik
- Uzytkownik moze byc w wielu grupach
- Manager grupy moze: zapraszac/dezaktywowac czlonkow, ustawiac limity, przeglac workspace'y czlonkow, usuwac workspace'y czlonkow

Przyklad: dwoch prowadzacych ten sam przedmiot — obaj sa managerami grupy studenckiej.

## 6. Workspace'y

### 6.1 Definicja

Workspace = niezalezny fragment terenu z wlasnym pipeline'em i danymi. Pelna autonomia uzytkownika — operator nie ingeruje w prace specjalistow.

### 6.2 Cykl zycia

```
created → queued → processing → ready
                              → failed (retry do 3x dla bledow transient)
ready → deleted (soft delete: deleted_at != NULL)
deleted → hard delete (admin platformy: DROP SCHEMA)
```

### 6.3 Limity

| Limit | Domyslna wartosc | Konfigurowany przez |
|-------|-------------------|---------------------|
| Max workspace'ow per user | 10 | org_admin, moderator (per grupa) |
| Max powierzchnia bbox | 500 km² | org_admin |
| Max rownolegych pipeline'ow per org | 2 | admin platformy |
| Max rownolegych pipeline'ow globalnie | 5 | admin platformy |
| Timeout pipeline'u | 4h | admin platformy |

### 6.4 Udostepnianie

- Wewnatrz organizacji i cross-organizacja
- Uprawnienia: `read_only` lub `edit`
- Goscie z innej org musza miec konto (zaproszeni gdziekolwiek)
- Soft delete workspace'u dezaktywuje wszystkie udostepnienia

### 6.5 API keys (per workspace)

- Scope: jeden klucz = jeden workspace
- Prefix: `hg_ws_`
- Hashowane w bazie (SHA-256), widoczne tylko raz przy tworzeniu
- Opcjonalny `expires_at`
- Uprawnienia klucza = uprawnienia usera do workspace'u
- Zastosowanie: integracja z Python, QGIS, R, wlasne skrypty

## 7. Izolacja danych — schematy PostgreSQL

```
hydro_db
├── public/                     ← tabele systemowe
│   ├── organizations
│   ├── organization_domains
│   ├── users
│   ├── invitations
│   ├── groups
│   ├── group_members
│   ├── workspaces
│   ├── workspace_shares
│   ├── workspace_api_keys
│   └── alembic_version
│
├── shared_cache/               ← dane zrodlowe, globalne dla instancji
│   ├── nmt_tiles               (arkusze NMT z GUGiK)
│   ├── bdot_source             (surowe BDOT10k)
│   └── hsg_source              (surowe HSG)
│
└── ws_{uuid_short}/            ← dane przetworzone per workspace
    ├── stream_network
    ├── stream_catchments
    ├── depressions
    ├── land_cover
    ├── soil_hsg
    ├── bdot_streams
    └── precipitation_data
```

- Pipeline czyta z `shared_cache`, pisze do `ws_{uuid}`
- Pierwszy uzytkownik pobiera arkusz NMT — zapisuje do cache. Kolejni korzystaja
- Migracje workspace'ow: osobny zestaw, aplikowany przy tworzeniu + upgrade dla istniejacych
- Rastery workspace'u na dysku: `data/workspaces/{uuid}/`

## 8. Model danych

### 8.1 organizations

| Kolumna | Typ | Opis |
|---------|-----|------|
| id | UUID PK | |
| name | VARCHAR(255) | Nazwa organizacji |
| slug | VARCHAR(100) UNIQUE | URL-friendly identyfikator |
| max_workspaces_per_user | INT DEFAULT 10 | |
| max_workspace_area_km2 | INT DEFAULT 500 | |
| is_active | BOOL DEFAULT true | |
| approved_by | UUID FK→users.id | Admin platformy ktory zatwierdzil |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

### 8.2 organization_domains

| Kolumna | Typ | Opis |
|---------|-----|------|
| id | UUID PK | |
| organization_id | UUID FK | |
| domain | VARCHAR(255) UNIQUE | np. `pw.edu.pl` |
| created_at | TIMESTAMP | |

### 8.3 users

| Kolumna | Typ | Opis |
|---------|-----|------|
| id | UUID PK | |
| email | VARCHAR(255) UNIQUE | Identyfikator uzytkownika |
| password_hash | VARCHAR(255) NULLABLE | NULL do momentu akceptacji zaproszenia |
| organization_id | UUID FK | |
| role | ENUM | platform_admin, org_admin, org_moderator, user, guest |
| is_active | BOOL DEFAULT true | |
| invited_by | UUID FK→users.id NULLABLE | Audit trail |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

### 8.4 invitations

| Kolumna | Typ | Opis |
|---------|-----|------|
| id | UUID PK | |
| email | VARCHAR(255) | |
| organization_id | UUID FK | |
| role | ENUM | Rola po akceptacji |
| invited_by | UUID FK→users.id | |
| token | VARCHAR(255) UNIQUE | Token w linku zaproszenia |
| expires_at | TIMESTAMP | |
| accepted_at | TIMESTAMP NULLABLE | NULL = oczekujace |
| created_at | TIMESTAMP | |

### 8.5 groups

| Kolumna | Typ | Opis |
|---------|-----|------|
| id | UUID PK | |
| organization_id | UUID FK | |
| name | VARCHAR(255) | np. "Hydrologia 2026 — lato" |
| created_by | UUID FK→users.id | |
| created_at | TIMESTAMP | |

### 8.6 group_members

| Kolumna | Typ | Opis |
|---------|-----|------|
| group_id | UUID FK (composite PK) | |
| user_id | UUID FK (composite PK) | |
| role | ENUM: manager, member | |
| created_at | TIMESTAMP | |

### 8.7 workspaces

| Kolumna | Typ | Opis |
|---------|-----|------|
| id | UUID PK | |
| name | VARCHAR(255) | |
| description | TEXT NULLABLE | |
| owner_id | UUID FK→users.id | |
| organization_id | UUID FK | |
| bbox | GEOMETRY(Polygon, 4326) | Obszar analizy (WGS84) |
| schema_name | VARCHAR(50) UNIQUE | np. `ws_a1b2c3d4` |
| status | ENUM | created, queued, processing, ready, failed |
| pipeline_started_at | TIMESTAMP NULLABLE | |
| pipeline_finished_at | TIMESTAMP NULLABLE | |
| deleted_at | TIMESTAMP NULLABLE | Soft delete |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

### 8.8 workspace_shares

| Kolumna | Typ | Opis |
|---------|-----|------|
| id | UUID PK | |
| workspace_id | UUID FK | |
| shared_with_user_id | UUID FK→users.id | Moze byc z innej organizacji |
| permission | ENUM: read_only, edit | |
| created_at | TIMESTAMP | |

### 8.9 workspace_api_keys

| Kolumna | Typ | Opis |
|---------|-----|------|
| id | UUID PK | |
| workspace_id | UUID FK | |
| user_id | UUID FK | |
| key_hash | VARCHAR(64) UNIQUE | SHA-256 hash klucza |
| name | VARCHAR(255) | Opis klucza (np. "QGIS skrypt") |
| last_used_at | TIMESTAMP NULLABLE | |
| expires_at | TIMESTAMP NULLABLE | |
| created_at | TIMESTAMP | |

## 9. Autentykacja

### 9.1 Mechanizm: API key

Jeden mechanizm dla GUI i dostepu programatycznego:

- **GUI login:** email + haslo → serwer generuje sesyjny API key (wygasa po 7 dniach nieaktywnosci)
- **Dostep programatyczny:** uzytkownik generuje staly API key per workspace w panelu
- **Header:** `X-API-Key: hg_ws_...` lub `X-API-Key: hg_session_...`
- Serwer sprawdza klucz w bazie (cache w Redis)

### 9.2 Endpointy auth

```
POST /api/auth/login              → {api_key}
POST /api/auth/set-password       ← z tokena zaproszenia
POST /api/auth/reset-password
POST /api/auth/reset-password/confirm
```

## 10. Architektura — monolit + worker

### 10.1 Komponenty

```
┌──────────┐     ┌───────┐     ┌──────────┐     ┌────────────┐
│ API      │────>│ Redis │────>│ Worker   │────>│ PostgreSQL │
│ (FastAPI)│     │(queue)│     │ (ARQ)    │     │ + dysk     │
└──────────┘     └───────┘     └──────────┘     └────────────┘
```

- **API** — FastAPI, obsluguje auth + CRUD + analityke
- **Worker** — ten sam codebase, entry point `python -m worker`, przetwarza pipeline'y
- **Redis** — kolejka zadan ARQ + cache API keys
- Kolejka FIFO, limity rownoleglosci per org i globalnie
- Worker raportuje postep przez Redis → API udostepnia SSE stream

### 10.2 Docker Compose

```yaml
services:
  db:        # PostgreSQL + PostGIS
  api:       # FastAPI
  worker:    # python -m worker (ten sam image co api)
  redis:     # ARQ queue + key cache
  nginx:     # Frontend + reverse proxy
```

### 10.3 Zmienne srodowiskowe (nowe)

```
SECRET_KEY                    ← hashowanie API keys
SESSION_EXPIRY_DAYS=7
MAX_CONCURRENT_PIPELINES=2
PIPELINE_TIMEOUT_HOURS=4
SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
WORKSPACE_DATA_DIR=/data/workspaces
SHARED_CACHE_DIR=/data/shared_cache
```

## 11. API — nowe endpointy

```
# Auth
POST   /api/auth/login
POST   /api/auth/set-password
POST   /api/auth/reset-password
POST   /api/auth/reset-password/confirm

# Organizacje (platform_admin)
POST   /api/organizations
GET    /api/organizations
PUT    /api/organizations/{id}
POST   /api/organizations/{id}/domains

# Uzytkownicy (org_admin, moderator)
POST   /api/organizations/{id}/invitations
GET    /api/organizations/{id}/users
PUT    /api/users/{id}
DELETE /api/users/{id}                        # org_admin only

# Grupy (org_admin, moderator)
POST   /api/groups
GET    /api/groups
PUT    /api/groups/{id}
POST   /api/groups/{id}/members
DELETE /api/groups/{id}/members/{user_id}

# Workspace'y
POST   /api/workspaces
GET    /api/workspaces
GET    /api/workspaces/{id}
PUT    /api/workspaces/{id}
DELETE /api/workspaces/{id}                   # soft delete
POST   /api/workspaces/{id}/run-pipeline
GET    /api/workspaces/{id}/pipeline-status   # SSE stream

# Udostepnianie
POST   /api/workspaces/{id}/shares
GET    /api/workspaces/{id}/shares
DELETE /api/workspaces/{id}/shares/{share_id}

# API keys
POST   /api/workspaces/{id}/api-keys
GET    /api/workspaces/{id}/api-keys
DELETE /api/workspaces/{id}/api-keys/{key_id}

# Analityka (w scope workspace'u)
POST   /api/workspaces/{id}/delineate-watershed
POST   /api/workspaces/{id}/generate-hydrograph
POST   /api/workspaces/{id}/terrain-profile
GET    /api/workspaces/{id}/depressions
GET    /api/workspaces/{id}/tiles/{layer}/{z}/{x}/{y}.pbf
GET    /api/workspaces/{id}/scenarios
```

## 12. Frontend — nowe widoki

| Sciezka | Opis | Dostep |
|---------|------|--------|
| `/login` | Email + haslo | Publiczny |
| `/set-password?token=...` | Ustawianie hasla z zaproszenia | Publiczny (z tokenem) |
| `/reset-password` | Reset hasla | Publiczny |
| `/workspaces` | Lista workspace'ow (kafelki z minimapa) | user+ |
| `/workspaces/new` | Kreator: nazwa, opis, rysowanie bbox | user+ |
| `/workspaces/{id}` | Obecna aplikacja (mapa + analityka) | wlasciciel, udostepnieni |
| `/workspaces/{id}/settings` | Udostepnianie, API keys, usuniecie | wlasciciel |
| `/admin/org` | Panel org_admina: uzytkownicy, grupy, limity | org_admin |
| `/admin/platform` | Panel admina platformy: organizacje, pipeline'y | platform_admin |

**Podejscie techniczne:**
- Routing: hash router (`#/workspaces`, `#/workspaces/{id}`)
- Nowe moduly JS obok istniejacych
- Istniejace moduly analityczne bez zmian — ladowane w widoku workspace'u
- CSS: rozszerzenie `glass.css`

## 13. Migracja z obecnego stanu

**Istniejace przetworzone dane (cieki, zlewnie, depresje, etc.) sa zbedne — nie migrujemy ich.**

Migrujemy tylko:
- **shared_cache** — pobrane arkusze NMT, BDOT, HSG (jesli istnieja na dysku)

Kroki:
1. Alembic migracja: nowe tabele systemowe w `public`
2. Utworzenie schematu `shared_cache` + przeniesienie/podlinkowanie istniejacych danych zrodlowych
3. Skrypt: domyslna organizacja + admin platformy
4. Stare tabele w `public` (stream_network, stream_catchments, etc.) — do usuniecia po weryfikacji

## 14. Kolejnosc implementacji

1. **Faza 0: Makieta frontendowa** — statyczne widoki HTML/CSS/JS bez backendu. Zatwierdzenie wygladu przed implementacja.
2. **Faza 1: Auth + tabele systemowe** — login, API keys, tabele users/organizations/invitations
3. **Faza 2: Workspace CRUD + izolacja schematow** — tworzenie workspace'ow, schematy PostgreSQL
4. **Faza 3: Pipeline worker** — ARQ + Redis, uruchamianie pipeline'u per workspace
5. **Faza 4: Frontend integracja** — podlaczenie makiety do backendu
6. **Faza 5: Organizacje, grupy, zaproszenia, panele admin**
