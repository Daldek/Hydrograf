# Design: Hardening kontenerow Hydrograf

Data: 2026-03-02
Status: Zatwierdzony
Podejscie: A — Hardening kontenerow (bez zmian logiki biznesowej)

## Kontekst

Aktualny setup Docker (ADR-035, sesja 51) ma solidne fundamenty (multi-stage build, healthchecki, dev/prod separation), ale krytyczne luki bezpieczenstwa przed wdrozeniem produkcyjnym:
- Kontener API dziala jako root
- Hardcoded credentials w docker-compose.yml i config.py
- Brak HTTPS/TLS (Nginx tylko HTTP)
- Nginx dostepny z sieci (0.0.0.0:8080)
- Brak rate limiting na admin endpoints
- Brak security context (capabilities, read-only rootfs)

Docelowy model: VPS + Docker Compose, 5-50 uzytkownikow w organizacji.

## Decyzje projektowe

### 1. Non-root user w Dockerfile

Kontener API bedzie dzialal jako dedykowany uzytkownik `hydro` (UID systemowy).

```dockerfile
# Runtime stage
FROM python:3.12-slim

RUN groupadd -r hydro && useradd -r -g hydro -d /app -s /sbin/nologin hydro

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY . .

RUN chown -R hydro:hydro /app

USER hydro

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Uzasadnienie:
- UID/GID systemowy (`-r`) — bez powloki logowania
- Katalogi danych (`/data`, `/frontend/data`, `/frontend/tiles`) montowane jako volume
- `entrypoint.sh` dziala jako `hydro` (nie potrzebuje root)

### 2. Security context w Docker Compose

Ograniczenia bezpieczenstwa na poziomie Compose:

**API:**
- `no-new-privileges:true` — blokuje eskalacje uprawnien
- `cap_drop: ALL` — usuwa wszystkie Linux capabilities
- `read_only: true` — readonly rootfs
- `tmpfs: /tmp:size=100M` — jedyny zapisywalny katalog tymczasowy

**Database (PostgreSQL):**
- `no-new-privileges:true`
- `cap_drop: ALL` + `cap_add: CHOWN, SETUID, SETGID, FOWNER, DAC_READ_SEARCH`
- PostgreSQL wymaga kilku capabilities do init i zmiany usera

**Nginx:**
- `no-new-privileges:true`
- `cap_drop: ALL` + `cap_add: NET_BIND_SERVICE` (bind port 80)
- `read_only: true`
- `tmpfs: /tmp:10M, /var/cache/nginx:50M, /var/run:1M`

### 3. Secrets management

Dwa poziomy: `.env` (dev/VPS) + Docker secrets (produkcja).

**3a. Plik `.env.example` (commitowany):**
- Wszystkie zmienne z komentarzami, pogrupowane tematycznie
- Operator kopiuje do `.env` i uzupelnia wartosci

**3b. Usuniecie hardcoded defaults:**
- `docker-compose.yml`: `${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}` — failuje bez ustawienia
- `config.py`: usuniecie domyslnego hasla, walidacja na starcie

**3c. Docker secrets (plikowe):**
```yaml
secrets:
  db_password:
    file: ./secrets/db_password.txt    # .gitignore'd
  admin_api_key:
    file: ./secrets/admin_api_key.txt  # .gitignore'd
```

**3d. Admin key:**
- Usuniecie logowania wygenerowanego klucza
- Wymuszenie jawnego ustawienia (raise jesli brak w produkcji)
- Katalog `secrets/` w `.gitignore`

### 4. TLS/HTTPS (opcjonalny — dev HTTP, prod HTTPS)

**Struktura plikow:**
```
docker/
├── nginx.conf              # Bazowy (HTTP)
├── nginx-ssl.conf.template # SSL config (produkcja)
└── certs/                  # .gitignore'd
    ├── fullchain.pem
    └── privkey.pem
```

**Dev:** Bez zmian — HTTP jak dotychczas.

**Produkcja (`docker-compose.prod.yml`):**
- Nginx nadpisany: port 443 (HTTPS) + 80 (redirect)
- `nginx-ssl.conf.template` z env substitution (`$SERVER_NAME`)
- TLS 1.2+, strong ciphers, OCSP stapling
- Certyfikaty: Let's Encrypt (rekomendowane) lub reczne

Kluczowe: TLS jest opcjonalny — nie zmienia dev workflow.

### 5. Porty, rate limiting, dokumentacja

**5a. Nginx na localhost:**
```yaml
ports:
  - "127.0.0.1:${HYDROGRAF_PORT:-8080}:80"
```
Operator otwiera port przez firewall lub stawia zewnetrzny reverse proxy.

**5b. Rate limiting admin:**
```nginx
limit_req_zone $binary_remote_addr zone=admin_limit:1m rate=5r/s;
```
Osobna strefa — 5 req/s (surowsza niz ogolne API 10 req/s).

**5c. `.env.example`:**
Pelna dokumentacja zmiennych srodowiskowych — jedyne zrodlo prawdy.

## Czego NIE robimy (swiadomie)

- System uzytkownikow (auth/JWT) — osobny etap po hardeningu
- Zmiana reverse proxy (Traefik) — Nginx jest dobrze skonfigurowany
- Kubernetes/Swarm — target to VPS + Docker Compose
- Certbot jako kontener — operator zarzadza certyfikatami
- Zmiana logiki biznesowej — czysto infrastrukturalne zmiany

## Wplyw na istniejacy kod

| Plik | Zmiana |
|------|--------|
| `backend/Dockerfile` | Dodanie USER hydro, chown |
| `docker-compose.yml` | Security context, secrets, port binding |
| `docker-compose.override.yml` | Minimalny update (kompatybilnosc) |
| `docker-compose.prod.yml` | TLS, production secrets |
| `docker/nginx.conf` | Rate limiting admin, drobne poprawki |
| `docker/nginx-ssl.conf.template` | NOWY — konfiguracja SSL |
| `backend/core/config.py` | Usuniecie hardcoded password default |
| `backend/api/admin_auth.py` | Usuniecie logowania klucza |
| `.env.example` | NOWY — dokumentacja zmiennych |
| `.gitignore` | Dodanie secrets/, certs/ |
