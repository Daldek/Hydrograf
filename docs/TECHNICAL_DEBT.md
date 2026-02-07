# Technical Debt - Hydrograf

Lista znanych problemów technicznych do naprawy w przyszłych iteracjach.

---

## Hardcoded Values (Q3.9)

### Stałe jednostek konwersji

| Wartość | Lokalizacja | Rekomendacja |
|---------|-------------|--------------|
| `1000.0` (m/km) | `core/morphometry.py` ×3 | Stała `M_PER_KM = 1000.0` |
| `1_000_000` (m²/km²) | `core/watershed.py`, `core/morphometry.py` | Stała `M2_PER_KM2 = 1_000_000` |

### Parametry algorytmów

| Wartość | Lokalizacja | Opis | Rekomendacja |
|---------|-------------|------|--------------|
| `0.3` | `core/watershed.py:300` | Concave hull ratio | Stała `CONCAVE_HULL_RATIO` |
| `4` | `core/precipitation.py:163` | IDW neighbors count | Stała `IDW_NUM_NEIGHBORS` |
| `75` | `core/morphometry.py` | Default CN value | Implementacja `land_cover.py` |

### Identyfikatory CRS

| Wartość | Lokalizacja | Rekomendacja |
|---------|-------------|--------------|
| `"EPSG:2180"` | `utils/geometry.py`, `models/schemas.py` | Stała `CRS_PL1992` |
| `"EPSG:4326"` | `utils/geometry.py` | Stała `CRS_WGS84` |

### Inne

| Wartość | Lokalizacja | Rekomendacja |
|---------|-------------|--------------|
| `"Hydrograf"` | `core/morphometry.py:304` | Config setting `app.name` |

**Akcja:** Utworzyć `backend/core/constants.py` z wszystkimi stałymi.

---

## Hardcoded Secrets (S5.3)

### S5.3a - Default password w config.py

```python
# backend/core/config.py:36
postgres_password: str = "hydro_password"
```

**Problem:** Domyślne hasło w kodzie źródłowym.

**Rekomendacja:**
- Usunąć domyślną wartość
- Wymagać zmiennej środowiskowej `POSTGRES_PASSWORD`
- Dodać walidację w `Settings`

### S5.3b - Connection string w migrations/env.py

```python
# backend/migrations/env.py:27
config.set_main_option(
    "sqlalchemy.url",
    "postgresql://hydro_user:hydro_password@localhost:5432/hydro_db"
)
```

**Problem:** Hardcoded connection string jako fallback.

**Rekomendacja:**
- Wymagać zmiennej `DATABASE_URL`
- Rzucać błąd jeśli brak konfiguracji

---

## Brakujące testy dla scripts/ (T4.8)

**Problem:** Większość skryptów preprocessingu (`scripts/*.py`) ma niskie pokrycie testami.

**Stan testów:**
- `scripts/process_dem.py` — **46 testów** (compute_slope, compute_aspect, compute_twi, compute_strahler, burn_streams, fill_sinks, pyflwdir)
- `scripts/import_landcover.py` — 0% pokrycia
- `utils/raster_utils.py` — 0% pokrycia
- `utils/sheet_finder.py` — 0% pokrycia

**Priorytet:** MEDIUM (process_dem pokryty, pozostałe do zrobienia)

---

## Dokumentacja vs Kod (C2.x)

**Problem:** Dokumentacja API jest nieaktualna względem kodu.

**Rozbieżności:**
| Element | Dokumentacja | Kod |
|---------|--------------|-----|
| `outlet_coords` | `[lon, lat]` array | `outlet.latitude/longitude` objects |
| `parameters` | sekcja `parameters` | `morphometry` |
| `water_balance` | BRAK | nowa sekcja w response |

**Akcja:** Zaktualizować `docs/ARCHITECTURE.md` sekcja API endpoints.

---

*Ostatnia aktualizacja: 2026-02-07*
