# Panel Administracyjno-Diagnostyczny — Design

## Cel

Panel webowy `/admin` do zarządzania pipeline'em Hydrograf: uruchamianie bootstrap.py, śledzenie postępu, diagnostyka systemu, czyszczenie danych.

## Architektura

- **Frontend**: osobna strona `/admin` (admin.html), Vanilla JS (IIFE), glassmorphism CSS
- **Backend**: nowy router `/api/admin/*` w FastAPI, middleware API key
- **Auth**: zmienna `ADMIN_API_KEY` w .env, header `X-Admin-Key`
- **Bootstrap**: subprocess + SSE (Server-Sent Events) do real-time logów

## Sekcje panelu

### 1. Dashboard
- Status zdrowia API + DB, wersja
- Liczba rekordów w tabelach (stream_network, catchments, depressions, land_cover, soil_hsg, precipitation)
- Zużycie dysku (data/, tiles/, dem_tiles/)

### 2. Bootstrap
- Formularz: bbox / nazwy arkuszy, checkboxy skip-steps, waterbody-mode
- Start/Cancel bootstrap jako subprocess
- Real-time log SSE z progresem kroków
- Historia ostatnich uruchomień (in-memory)

### 3. Zasoby
- CPU/RAM procesu API (psutil)
- Rozmiar bazy PostgreSQL
- Pool połączeń DB (active/idle/max)
- Cache CatchmentGraph (nodes, memory, load time)

### 4. Czyszczenie danych
- Przyciski z potwierdzeniem: tiles MVT, overlays PNG, dem_mosaic, TRUNCATE tabel
- Estymacja rozmiaru do odzyskania per-target

## Endpointy API

| Endpoint | Method | Opis |
|----------|--------|------|
| `/api/admin/dashboard` | GET | Status, wersja, uptime, row counts, disk |
| `/api/admin/bootstrap/start` | POST | Uruchom bootstrap (bbox, options) |
| `/api/admin/bootstrap/stream` | GET | SSE stream logów |
| `/api/admin/bootstrap/status` | GET | Status (running/idle, step, pid) |
| `/api/admin/bootstrap/cancel` | POST | Zatrzymaj subprocess |
| `/api/admin/resources` | GET | CPU, RAM, DB pool, graph cache |
| `/api/admin/cleanup` | POST | Usuń wybrane dane (body: targets[]) |
| `/api/admin/cleanup/estimate` | GET | Estymacja rozmiaru do usunięcia |

## Nowe pliki

```
backend/api/endpoints/admin.py       — router /api/admin/*
backend/api/middleware/auth.py        — middleware API key
frontend/admin.html                   — strona panelu
frontend/css/admin.css                — style admina
frontend/js/admin/admin-app.js        — główna logika
frontend/js/admin/admin-api.js        — klient API
frontend/js/admin/admin-bootstrap.js  — obsługa SSE + formularz
```

## Decyzje

- **SSE zamiast WebSocket**: prostsze, jednokierunkowe (serwer→klient), wystarczające dla logów
- **API key zamiast JWT**: minimum bezpieczeństwa bez złożoności; JWT w przyszłości z użytkownikami
- **Subprocess zamiast Celery**: jeden długi proces, nie potrzeba task queue
- **In-memory historia**: ostatnie N uruchomień bootstrap, bez persystencji (restart czyści)
