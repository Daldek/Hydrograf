# Design: Naprawa krytycznych bugow — zespoly subagentow

**Data:** 2026-03-01
**Bugi:** CR4, CR6, CR7, CR8, S5.3, Auth

## Analiza zaleznosci

| Bug | Pliki do zmiany | Pliki testowe |
|-----|-----------------|---------------|
| CR7 (race condition singleton) | `core/catchment_graph.py` | `tests/unit/test_catchment_graph.py` |
| CR4 (BFS deque) | `core/catchment_graph.py` | `tests/unit/test_catchment_graph.py` |
| CR8 (info disclosure + float) | `api/endpoints/profile.py` | `tests/integration/test_profile.py` |
| CR6 (enkapsulacja _segment_idx) | `core/catchment_graph.py` + 3 endpointy | `tests/unit/test_catchment_graph.py` |
| S5.3 (hardcoded secrets) | `core/config.py`, `migrations/env.py` | nowe testy |
| Auth (generuj losowy klucz) | `api/dependencies/admin_auth.py`, `core/config.py` | `tests/unit/test_admin_auth.py` |

CR4, CR6, CR7 dotykaja tego samego pliku (`catchment_graph.py`) — musza byc w jednym zespole.

## Zespoly

### Team 1 — `feature/fix-catchment-graph` (CR4 + CR6 + CR7)
- CR7: `threading.Lock` z double-check locking w `get_catchment_graph()`
- CR4: `collections.deque` + `popleft()` w `traverse_to_confluence()`
- CR6: publiczna metoda `get_segment_idx(idx)` + update 3 endpointow
- Testy: nowe testy singletona + thread safety, istniejace testy BFS

### Team 2 — `feature/fix-profile-security` (CR8)
- Usuniecie sciezki serwera z error detail
- `math.isclose()` zamiast `==` dla nodata
- Testy: update + nowe

### Team 3 — `feature/fix-secrets-auth` (S5.3 + Auth)
- `config.py`: usuniecie hardcoded `hydro_password`
- `migrations/env.py`: usuniecie fallback connection string
- `admin_auth.py`: generowanie `uuid4` klucza jesli brak konfiguracji
- Testy: nowe + update

### Team 4 — `merge-critical-fixes` (po Team 1-3)
- Merge 3 feature branches do `develop`
- Rozwiazanie konfliktow
- Pelny suite testow
