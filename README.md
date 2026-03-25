# Hydrograf

System analizy hydrologicznej — wyznaczanie zlewni, obliczanie parametrów fizjograficznych i generowanie hydrogramów odpływu.

## Co robi Hydrograf?

- **Wyznaczanie zlewni** — kliknij na mapę, a system wyznaczy granicę zlewni w kilka sekund
- **Parametry fizjograficzne** — powierzchnia, spadki, pokrycie terenu, CN, grupy glebowe HSG
- **Hydrogram odpływu** — scenariusze opadowe z IMGW, modele SCS/Nash/Snyder
- **Mapa interaktywna** — cieki, zlewnie, pokrycie terenu, DEM z hillshade
- **Panel administracyjny** — uruchamianie pipeline, monitoring, czyszczenie danych

## Stack technologiczny

| Warstwa | Technologia |
|---------|-------------|
| Backend | Python 3.12+, FastAPI, SQLAlchemy, GeoAlchemy2 |
| Baza danych | PostgreSQL 16 + PostGIS 3.4 |
| Frontend | Vanilla JS, Leaflet.js, Chart.js, Bootstrap 5 |
| Infrastruktura | Docker Compose, Nginx |
| Biblioteki własne | [Hydrolog](https://github.com/Daldek/Hydrolog), [Kartograf](https://github.com/Daldek/Kartograf), [IMGWTools](https://github.com/Daldek/IMGWTools) |

## Szybki start (Docker Compose)

```bash
git clone https://github.com/Daldek/Hydrograf.git
cd Hydrograf
cp .env.example .env
# Ustaw POSTGRES_PASSWORD w .env

docker compose up -d
```

Aplikacja dostępna pod:
- **Frontend:** http://localhost
- **API:** http://localhost/api
- **Admin:** http://localhost/admin

## Szybki start (Development)

```bash
# Baza danych w Docker
docker compose up -d db

# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade head
.venv/bin/python -m uvicorn api.main:app --reload
```

## Preprocessing danych

Przed użyciem systemu wymagane jest jednorazowe przetworzenie danych NMT (Numeryczny Model Terenu). Najprościej z panelu administracyjnego (`/admin`) — podaj bounding box i kliknij Start.

Alternatywnie z CLI:

```bash
cd backend
.venv/bin/python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4"
```

Pipeline automatycznie pobiera NMT z GUGiK, pokrycie terenu z BDOT10k, grupy glebowe z SoilGrids i dane opadowe z IMGW.

## Testy

```bash
cd backend
.venv/bin/python -m pytest tests/ -q
```

## Struktura projektu

```
Hydrograf/
├── backend/           # API FastAPI
│   ├── api/           # Endpointy REST
│   ├── core/          # Logika biznesowa
│   ├── scripts/       # Pipeline preprocessingu
│   └── tests/         # Testy
├── frontend/          # Aplikacja webowa (Vanilla JS)
├── docker/            # Konfiguracja Docker/Nginx
└── docs/              # Dokumentacja projektowa
```

## Dokumentacja

- [Zakres projektu](docs/SCOPE.md)
- [Architektura systemu](docs/ARCHITECTURE.md)
- [Model danych](docs/DATA_MODEL.md)
- [Wymagania produktowe](docs/PRD.md)
- [Decyzje architektoniczne](docs/DECISIONS.md)
- [Historia zmian](docs/CHANGELOG.md)
- Integracje: [Kartograf](docs/KARTOGRAF_INTEGRATION.md), [Hydrolog](docs/HYDROLOG_INTEGRATION.md), [IMGWTools](docs/IMGWTOOLS_INTEGRATION.md)
- [Analiza zależności](docs/CROSS_PROJECT_ANALYSIS.md)
- [Deploy na VPS](docs/DEPLOYMENT_VPS.md) *(planowane)*

## Licencja

MIT — szczegóły w pliku `LICENSE`.

## Autor

[Piotr de Bever](https://www.linkedin.com/in/piotr-de-bever/)
