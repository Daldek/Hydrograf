# Hydrolog v0.6.3 Upgrade — Plan implementacji

> **Dla agentow:** Kazdy Task realizowany przez dedykowany zespol subagentow koordynowanych przez glownego agenta. Workflow zespolu: Researcher → Developer → Tester → UI/UX Reviewer.

**Cel:** Pelna adaptacja Hydrograf do Hydrolog v0.6.3 — podbicie wersji, migracja deprecated `from_tc`, nowe metody tc (FAA, Kerby, Kerby-Kirpich), aktualizacja UI/UX i dokumentacji.

**Architektura:** Zmiany dotycza 4 warstw: (1) zaleznosc pip, (2) backend API + schemas, (3) frontend selektory + logika widocznosci, (4) dokumentacja. Kazda warstwa testowana niezaleznie.

**Tech Stack:** Python 3.12, FastAPI, Hydrolog v0.6.3, Vanilla JS, Chart.js, Bootstrap 5

**Obecna wersja:** v0.6.2 (requirements.txt linia 59)

---

## Kontekst zmian Hydrolog v0.6.2 → v0.6.3

| Zmiana | Typ | Wplyw na Hydrograf |
|--------|-----|-------------------|
| `ConcentrationTime.faa()` | Nowa metoda | Nowa opcja tc do integracji |
| `ConcentrationTime.kerby()` | Nowa metoda | Nowa opcja tc do integracji |
| `ConcentrationTime.kerby_kirpich()` | Nowa metoda | Nowa opcja tc (composite) do integracji |
| `_SCS_LAG_*` → `_NRCS_*` (internal) | Refactoring | Brak — wewnetrzne stale |
| 28 nowych testow tc | Testy | Brak — wewnetrzne |
| 88 mypy fixes | Quality | Brak — wewnetrzne |

**Uwaga:** `NashIUH.from_tc()` deprecated od v0.6.2 — Hydrograf nadal uzywa jako domyslnej. Ten plan migruje domyslna na `from_lutz`.

---

## Task 1: Podbicie wersji i weryfikacja regresji

**Pliki:**
- Modify: `backend/requirements.txt:59`
- Test: caly suite (`backend/tests/`)

### Kroki

- [ ] **1.1: Zmien pin wersji w requirements.txt**

```
# BYLO:
hydrolog @ git+https://github.com/Daldek/Hydrolog.git@v0.6.2

# MA BYC:
hydrolog @ git+https://github.com/Daldek/Hydrolog.git@v0.6.3
```

- [ ] **1.2: Zainstaluj nowa wersje**

```bash
cd backend && .venv/bin/pip install -r requirements.txt --upgrade
```

Expected: Successfully installed hydrolog-0.6.3

- [ ] **1.3: Zweryfikuj import nowych metod**

```bash
cd backend && .venv/bin/python -c "
from hydrolog.morphometry import ConcentrationTime
print('faa:', hasattr(ConcentrationTime, 'faa'))
print('kerby:', hasattr(ConcentrationTime, 'kerby'))
print('kerby_kirpich:', hasattr(ConcentrationTime, 'kerby_kirpich'))
print('nrcs:', hasattr(ConcentrationTime, 'nrcs'))
"
```

Expected: wszystkie True

- [ ] **1.4: Uruchom pelny suite testow (w tym pliki korzystajace z Hydrologa)**

Pliki Hydrologa w scope regresji:
- `backend/api/endpoints/hydrograph.py` — glowna integracja
- `backend/scripts/analyze_watershed.py` — CLI (importuje SCSCN, SCSUnitHydrograph)
- `backend/core/morphometry.py` — referencje WatershedParameters w docstringu
- `backend/tests/unit/test_morphometry.py` — test `test_hydrolog_compatibility`
- `backend/tests/unit/test_snyder_uh.py` — testy UH modeli

```bash
cd backend && .venv/bin/python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: ~797 passed, 0 failed

- [ ] **1.5: Sprawdz deprecation warning z from_tc**

```bash
cd backend && .venv/bin/python -W all -c "
from hydrolog.runoff import NashIUH
nash = NashIUH.from_tc(tc_min=60.0, n=3.0)
print('OK: n=', nash.n, 'k=', nash.k_min)
"
```

Expected: DeprecationWarning + poprawne wyniki

- [ ] **1.6: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore(deps): upgrade Hydrolog v0.6.2 → v0.6.3"
```

---

## Task 2: Migracja domyslnej estymacji Nash (from_tc → from_lutz)

**Pliki:**
- Modify: `backend/models/schemas.py:357` — zmiana domyslnej
- Modify: `backend/api/endpoints/hydrograph.py:549-553` — aktualizacja /scenarios
- Modify: `frontend/index.html:243-247` — zmiana domyslnej opcji w select
- Modify: `frontend/js/hydrograph.js:301-305` — aktualizacja labeli
- Test: `backend/tests/unit/test_snyder_uh.py`
- Test: `backend/tests/integration/test_hydrograph.py`

### Kroki

- [ ] **2.1: Zbadaj sygnatury `from_tc` vs `from_lutz` w Hydrolog**

```bash
cd backend && .venv/bin/python -c "
from hydrolog.runoff import NashIUH
import inspect
print('from_tc:', inspect.signature(NashIUH.from_tc))
print('from_lutz:', inspect.signature(NashIUH.from_lutz))
print('from_urban_regression:', inspect.signature(NashIUH.from_urban_regression))
"
```

Zapisz parametry — potrzebne do walidacji czy istniejacy kod `_estimate_nash_params()` jest kompletny.

- [ ] **2.2: Zmien domyslna estymacje w schema**

Plik: `backend/models/schemas.py:357`

```python
# BYLO:
nash_estimation: Literal["from_tc", "from_lutz", "from_urban_regression"] = Field(
    "from_tc",
    description="Nash parameter estimation method",
)

# MA BYC:
nash_estimation: Literal["from_tc", "from_lutz", "from_urban_regression"] = Field(
    "from_lutz",
    description="Nash parameter estimation method",
)
```

- [ ] **2.3: Oznacz from_tc jako deprecated w opisie**

Plik: `backend/models/schemas.py:357`
Dodaj `(deprecated)` do opisu from_tc w docstringu klasy `HydrographRequest`.

- [ ] **2.4: Zaktualizuj /scenarios endpoint**

Plik: `backend/api/endpoints/hydrograph.py:553`

```python
# BYLO:
"nash_estimation_methods": ["from_tc", "from_lutz", "from_urban_regression"],

# MA BYC:
"nash_estimation_methods": ["from_lutz", "from_urban_regression", "from_tc"],
```

Zmiana kolejnosci — from_lutz jako pierwszy (domyslny), from_tc na koncu.

- [ ] **2.5: Zaktualizuj domyslna opcje w HTML**

Plik: `frontend/index.html:243-247`

```html
<!-- BYLO: -->
<option value="from_tc">z Tc (SCS)</option>
<option value="from_lutz">Lutz</option>
<option value="from_urban_regression">Regresja urban.</option>

<!-- MA BYC: -->
<option value="from_lutz">Lutz</option>
<option value="from_tc">z Tc (SCS) ⚠</option>
<option value="from_urban_regression">Regresja urban.</option>
```

Uwaga: `⚠` sygnalizuje deprecated. from_lutz jako pierwszy = domyslny.

- [ ] **2.6: Zaktualizuj label from_tc w JS**

Plik: `frontend/js/hydrograph.js:301-305`

```javascript
// BYLO:
var NASH_EST_LABELS = {
    'from_tc': 'z Tc',
    'from_lutz': 'Lutz',
    'from_urban_regression': 'Regresja urban.',
};

// MA BYC:
var NASH_EST_LABELS = {
    'from_tc': 'z Tc (deprecated)',
    'from_lutz': 'Lutz',
    'from_urban_regression': 'Regresja urban.',
};
```

- [ ] **2.7: Zaktualizuj logike widocznosci tc-method**

Plik: `frontend/js/hydrograph.js:387`

Obecna logika juz jest poprawna: `needsTc = model !== 'nash' || estimation === 'from_tc'`.
Ale po zmianie domyslnej na `from_lutz`, po wyborze Nash tc-method bedzie ukryte — to poprawne zachowanie.

Weryfikacja: po wybraniu Nash, domyslnie NIE widac "Metoda Tc". Widoczne tylko po recznym wyborze `from_tc`.

- [ ] **2.8: Zaktualizuj testy domyslnych wartosci**

Plik: `backend/tests/unit/test_snyder_uh.py` — test `test_accepts_uh_model_nash` (linia ~239):

```python
# BYLO:
assert req.nash_estimation == "from_tc"

# MA BYC:
assert req.nash_estimation == "from_lutz"
```

Plik: `backend/tests/integration/test_hydrograph.py` — test `test_metadata_structure`:

```python
# Sprawdz czy test waliduje domyslna estymacje Nash — jesli tak, zmien na "from_lutz"
```

**KRYTYCZNE:** Plik `backend/tests/integration/test_hydrograph.py` — mock `_make_morph_dict`:
Po zmianie domyslnej na `from_lutz`, kazdy test ktory triggeruje Nash z domyslnymi parametrami
wywola `_estimate_nash_params()` z `from_lutz`, co wymaga `length_to_centroid_km` w morph_dict.
Jesli brakuje tego klucza, endpoint zwroci HTTP 400.

Sprawdz i dodaj do mock morph_dict:
```python
"length_to_centroid_km": 3.5,  # potrzebne dla Nash from_lutz
```

- [ ] **2.9: Dodaj test deprecation warning**

Plik: `backend/tests/unit/test_snyder_uh.py` (nowa klasa lub metoda)

```python
def test_nash_from_tc_emits_deprecation_warning():
    """Verify that NashIUH.from_tc() emits DeprecationWarning."""
    import warnings
    from hydrolog.runoff import NashIUH
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        nash = NashIUH.from_tc(tc_min=60.0, n=3.0)
        assert any(issubclass(x.category, DeprecationWarning) for x in w)
```

- [ ] **2.10: Uruchom testy**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_snyder_uh.py tests/integration/test_hydrograph.py -v --tb=short
```

Expected: all passed

- [ ] **2.11: Commit**

```bash
git add backend/models/schemas.py backend/api/endpoints/hydrograph.py \
       frontend/index.html frontend/js/hydrograph.js \
       backend/tests/unit/test_snyder_uh.py backend/tests/integration/test_hydrograph.py
git commit -m "feat(api): migrate Nash default from deprecated from_tc to from_lutz"
```

---

## Task 3: Nowe metody Tc (FAA, Kerby, Kerby-Kirpich)

**Pliki:**
- Modify: `backend/api/endpoints/hydrograph.py:15-18,381-391,546-549`
- Modify: `backend/models/schemas.py:326-329`
- Modify: `frontend/index.html:232-237`
- Modify: `frontend/js/hydrograph.js:191-204,291-295,370-389,393-398`
- Create: `backend/tests/unit/test_tc_methods.py`

### Uwagi projektowe

Nowe metody tc z Hydrologa v0.6.3 to **statyczne metody** klasy `ConcentrationTime`:

```python
ConcentrationTime.faa(length_km, slope_m_per_m, runoff_coeff) -> float  # [min]
ConcentrationTime.kerby(length_km, slope_m_per_m, retardance) -> float  # [min]
ConcentrationTime.kerby_kirpich(
    overland_length_km, overland_slope_m_per_m, retardance,
    channel_length_km, channel_slope_m_per_m
) -> float  # [min]
```

**Kluczowe roznice wobec istniejacych metod:**
- Istniejace (kirpich/nrcs/giandotti): wywolywane przez `WatershedParameters.calculate_tc(method=...)`
- Nowe (faa/kerby/kerby_kirpich): wywolywane bezposrednio jako `ConcentrationTime.xxx()`
- FAA wymaga `runoff_coeff` (wspolczynnik splywu, 0.0-1.0)
- Kerby wymaga `retardance` (wspolczynnik oporow, 0.02-0.8)
- Kerby-Kirpich wymaga rozdzielenia dlugosci na overland + channel

**Strategia integracji:**
- Parametry `runoff_coeff` i `retardance` jako opcjonalne pola w `HydrographRequest`
- Kerby-Kirpich: `overland_length_km` = reszta (length_km - channel_length_km), `overland_slope_m_per_m` = mean_slope, channel params z morph_dict
- FAA: `runoff_coeff` moze byc estymowany z CN: `C ≈ 1 - (S / (S + 25.4))` gdzie `S = 25400/CN - 254`

### Kroki

- [ ] **3.1: Zbadaj dokladne sygnatury nowych metod**

```bash
cd backend && .venv/bin/python -c "
from hydrolog.morphometry import ConcentrationTime
import inspect
for m in ['faa', 'kerby', 'kerby_kirpich']:
    sig = inspect.signature(getattr(ConcentrationTime, m))
    print(f'{m}{sig}')
"
```

Sprawdz tez czy `WatershedParameters.calculate_tc()` obsluguje nowe metody:

```bash
cd backend && .venv/bin/python -c "
from hydrolog.morphometry import WatershedParameters
import inspect
print(inspect.signature(WatershedParameters.calculate_tc))
# Sprawdz docstring dla dozwolonych metod
help(WatershedParameters.calculate_tc)
"
```

- [ ] **3.2: Dodaj nowe parametry do HydrographRequest**

Plik: `backend/models/schemas.py` (po linii 366, przed `morphometry`)

```python
    # TC method parameters (for FAA, Kerby, Kerby-Kirpich)
    tc_runoff_coeff: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Runoff coefficient C for FAA method [0-1]. "
        "If not provided, estimated from CN.",
    )
    tc_retardance: float | None = Field(
        None,
        ge=0.02,
        le=0.8,
        description="Kerby retardance coefficient N (0.02=smooth, 0.8=dense forest). "
        "Default 0.4 (grass/crops).",
    )
```

- [ ] **3.3: Rozszerz walidacje tc_method**

Plik: `backend/models/schemas.py:326-329`

```python
# BYLO:
tc_method: str = Field(
    "nrcs",
    pattern=r"^(kirpich|nrcs|giandotti)$",
    description="Time of concentration method",
)

# MA BYC:
tc_method: str = Field(
    "nrcs",
    pattern=r"^(kirpich|nrcs|giandotti|faa|kerby|kerby_kirpich)$",
    description="Time of concentration method",
)
```

- [ ] **3.4: Dodaj import ConcentrationTime w hydrograph.py**

Plik: `backend/api/endpoints/hydrograph.py:16`

```python
# BYLO:
from hydrolog.morphometry import WatershedParameters

# MA BYC:
from hydrolog.morphometry import ConcentrationTime, WatershedParameters
```

- [ ] **3.5: Dodaj logike obliczania tc dla nowych metod**

Plik: `backend/api/endpoints/hydrograph.py` — w bloku `if request.uh_model != "nash" or nash_needs_tc:` (linie 380-391)

Zastap istniejacy blok obliczania tc nowa funkcja lub rozszerzonym if/elif:

```python
        if request.uh_model != "nash" or nash_needs_tc:
            tc_method = request.tc_method
            tc_min = _calculate_tc(
                tc_method, watershed_params, morph_dict, request
            )
            logger.debug(f"Time of concentration: {tc_min:.1f} min ({tc_method})")
        else:
            tc_method = None
            tc_min = None
```

Nowa funkcja `_calculate_tc()` (przed `_estimate_nash_params`):

```python
def _calculate_tc(
    method: str,
    wp: WatershedParameters,
    morph_dict: dict,
    request,
) -> float:
    """Calculate time of concentration using the specified method."""
    if method == "nrcs" and wp.channel_slope_m_per_m is not None:
        # NRCS formula uses average watershed slope (Y), not channel slope
        saved = wp.channel_slope_m_per_m
        wp.channel_slope_m_per_m = None
        tc = wp.calculate_tc(method=method)
        wp.channel_slope_m_per_m = saved
        return tc

    if method in ("kirpich", "giandotti"):
        return wp.calculate_tc(method=method)

    if method == "faa":
        runoff_coeff = request.tc_runoff_coeff
        if runoff_coeff is None:
            # Estimate from CN: C ≈ 1 - S/(S+25.4)
            cn = morph_dict.get("cn") or 75
            s_mm = (25400.0 / cn - 254.0) if cn < 100 else 0.0
            runoff_coeff = 1.0 - s_mm / (s_mm + 25.4) if s_mm > 0 else 0.95
        slope = morph_dict.get("mean_slope_m_per_m") or 0.01
        length = morph_dict.get("length_km") or morph_dict.get("channel_length_km") or 1.0
        return ConcentrationTime.faa(
            length_km=length, slope_m_per_m=slope, runoff_coeff=runoff_coeff,
        )

    if method == "kerby":
        retardance = request.tc_retardance or 0.4
        slope = morph_dict.get("mean_slope_m_per_m") or 0.01
        length = morph_dict.get("length_km") or 1.0
        return ConcentrationTime.kerby(
            length_km=length, slope_m_per_m=slope, retardance=retardance,
        )

    if method == "kerby_kirpich":
        retardance = request.tc_retardance or 0.4
        channel_length = morph_dict.get("channel_length_km") or 1.0
        channel_slope = morph_dict.get("channel_slope_m_per_m") or 0.01
        total_length = morph_dict.get("length_km") or channel_length
        overland_length = max(total_length - channel_length, 0.1)
        overland_slope = morph_dict.get("mean_slope_m_per_m") or 0.01
        return ConcentrationTime.kerby_kirpich(
            overland_length_km=overland_length,
            overland_slope_m_per_m=overland_slope,
            retardance=retardance,
            channel_length_km=channel_length,
            channel_slope_m_per_m=channel_slope,
        )

    raise ValueError(f"Unknown tc method: {method}")
```

- [ ] **3.6: Zaktualizuj /scenarios endpoint**

Plik: `backend/api/endpoints/hydrograph.py:549`

```python
# BYLO:
"tc_methods": ["kirpich", "nrcs", "giandotti"],

# MA BYC:
"tc_methods": ["nrcs", "kirpich", "giandotti", "faa", "kerby", "kerby_kirpich"],
```

- [ ] **3.7: Dodaj opcje tc w HTML**

Plik: `frontend/index.html:232-237`

```html
<!-- BYLO: -->
<select id="hydro-tc-method" class="form-select form-select-sm">
    <option value="nrcs">NRCS (SCS Lag)</option>
    <option value="kirpich">Kirpich</option>
    <option value="giandotti">Giandotti</option>
</select>

<!-- MA BYC: -->
<select id="hydro-tc-method" class="form-select form-select-sm">
    <option value="nrcs">NRCS (SCS Lag)</option>
    <option value="kirpich">Kirpich</option>
    <option value="giandotti">Giandotti</option>
    <option value="faa">FAA (splyw pow.)</option>
    <option value="kerby">Kerby</option>
    <option value="kerby_kirpich">Kerby-Kirpich</option>
</select>
```

- [ ] **3.8: Dodaj pola parametrow FAA/Kerby w HTML**

Plik: `frontend/index.html` — po zamknieciu wiersza `row g-1 mb-1` (po linii 239, nie 238!), dodaj nowy wiersz wewnatrz `hydrograph-form`:

```html
<div id="tc-extra-params" class="row g-1 mb-1 d-none">
    <div id="tc-runoff-coeff-col" class="col-6 d-none">
        <label class="form-label small mb-0">C (splyw) 0–1</label>
        <input id="hydro-tc-runoff-coeff" type="number"
               class="form-control form-control-sm"
               value="" min="0" max="1" step="0.05"
               placeholder="auto z CN">
    </div>
    <div id="tc-retardance-col" class="col-6 d-none">
        <label class="form-label small mb-0">N (opor) 0.02–0.8</label>
        <input id="hydro-tc-retardance" type="number"
               class="form-control form-control-sm"
               value="0.4" min="0.02" max="0.8" step="0.02">
    </div>
</div>
```

- [ ] **3.9: Zaktualizuj logike widocznosci dla nowych metod**

Plik: `frontend/js/hydrograph.js` — nowa funkcja `updateTcExtraParams()`:

```javascript
function updateTcExtraParams() {
    var method = document.getElementById('hydro-tc-method').value;
    var extraRow = document.getElementById('tc-extra-params');
    var runoffCol = document.getElementById('tc-runoff-coeff-col');
    var retardanceCol = document.getElementById('tc-retardance-col');

    // Ukryj extra params gdy tc-method jest ukryty (np. Nash + from_lutz)
    var tcMethodParams = document.getElementById('tc-method-params');
    var tcVisible = !tcMethodParams.classList.contains('d-none');

    var needsRunoff = tcVisible && (method === 'faa');
    var needsRetardance = tcVisible && (method === 'kerby' || method === 'kerby_kirpich');
    var needsExtra = needsRunoff || needsRetardance;

    extraRow.classList.toggle('d-none', !needsExtra);
    runoffCol.classList.toggle('d-none', !needsRunoff);
    retardanceCol.classList.toggle('d-none', !needsRetardance);
}
```

Wywolaj w `init()`, podepnij do eventow `hydro-tc-method`, ORAZ wywolaj na koncu `updateNashVisibility()` (bo zmiana UH model/estymacji moze ukryc tc-method, co powinno tez ukryc extra params).

- [ ] **3.10: Zaktualizuj generateHydrograph() — przekazanie nowych parametrow**

Plik: `frontend/js/hydrograph.js` (w okolicy linii 192-204)

Dodaj WEWNATRZ warunku `needsTc` (tam gdzie ustawiane jest `opts.tc_method`):

```javascript
// Istniejacy warunek:
if (uhModel !== 'nash' || document.getElementById('hydro-nash-estimation').value === 'from_tc') {
    opts.tc_method = document.getElementById('hydro-tc-method').value;
    // NOWE — TC extra params (tylko gdy tc_method jest ustawiane):
    if (opts.tc_method === 'faa') {
        var cVal = document.getElementById('hydro-tc-runoff-coeff').value;
        if (cVal) opts.tc_runoff_coeff = parseFloat(cVal);
    }
    if (opts.tc_method === 'kerby' || opts.tc_method === 'kerby_kirpich') {
        opts.tc_retardance = parseFloat(
            document.getElementById('hydro-tc-retardance').value
        ) || 0.4;
    }
}
```

- [ ] **3.11: Zaktualizuj api.js — przekazanie nowych pol**

Plik: `frontend/js/api.js` (w okolicy linii 124-152, w generateHydrograph)

Dodaj:
```javascript
if (opts.tc_runoff_coeff != null) payload.tc_runoff_coeff = opts.tc_runoff_coeff;
if (opts.tc_retardance != null) payload.tc_retardance = opts.tc_retardance;
```

- [ ] **3.12: Zaktualizuj TC_METHOD_LABELS w JS**

Plik: `frontend/js/hydrograph.js:291-295`

```javascript
// BYLO:
var TC_METHOD_LABELS = {
    'kirpich': 'Kirpich',
    'nrcs': 'NRCS',
    'giandotti': 'Giandotti',
};

// MA BYC:
var TC_METHOD_LABELS = {
    'kirpich': 'Kirpich',
    'nrcs': 'NRCS',
    'giandotti': 'Giandotti',
    'faa': 'FAA',
    'kerby': 'Kerby',
    'kerby_kirpich': 'Kerby-Kirpich',
};
```

- [ ] **3.13: Dodaj nowe input IDs do auto-regeneracji**

Plik: `frontend/js/hydrograph.js:393-398`

```javascript
// BYLO:
var _INPUT_IDS = [
    'hydro-duration', 'hydro-probability', 'hydro-hietogram-type',
    'hydro-alpha', 'hydro-beta',
    'hydro-uh-model', 'hydro-tc-method',
    'hydro-nash-estimation', 'hydro-nash-n',
    'hydro-snyder-ct', 'hydro-snyder-cp',
];

// MA BYC:
var _INPUT_IDS = [
    'hydro-duration', 'hydro-probability', 'hydro-hietogram-type',
    'hydro-alpha', 'hydro-beta',
    'hydro-uh-model', 'hydro-tc-method',
    'hydro-nash-estimation', 'hydro-nash-n',
    'hydro-snyder-ct', 'hydro-snyder-cp',
    'hydro-tc-runoff-coeff', 'hydro-tc-retardance',
];
```

- [ ] **3.14: Napisz testy jednostkowe dla nowych metod tc**

Plik: `backend/tests/unit/test_tc_methods.py` (NOWY)

```python
"""Tests for new tc methods integration (FAA, Kerby, Kerby-Kirpich)."""
import pytest
from hydrolog.morphometry import ConcentrationTime


class TestFAAMethod:
    """Test FAA time of concentration method."""

    def test_faa_returns_positive(self):
        tc = ConcentrationTime.faa(length_km=1.0, slope_m_per_m=0.02, runoff_coeff=0.5)
        assert tc > 0

    def test_faa_shorter_with_steeper_slope(self):
        tc_flat = ConcentrationTime.faa(length_km=1.0, slope_m_per_m=0.01, runoff_coeff=0.5)
        tc_steep = ConcentrationTime.faa(length_km=1.0, slope_m_per_m=0.05, runoff_coeff=0.5)
        assert tc_steep < tc_flat

    def test_faa_shorter_with_higher_runoff_coeff(self):
        tc_low = ConcentrationTime.faa(length_km=1.0, slope_m_per_m=0.02, runoff_coeff=0.3)
        tc_high = ConcentrationTime.faa(length_km=1.0, slope_m_per_m=0.02, runoff_coeff=0.8)
        assert tc_high < tc_low


class TestKerbyMethod:
    """Test Kerby time of concentration method."""

    def test_kerby_returns_positive(self):
        tc = ConcentrationTime.kerby(length_km=0.5, slope_m_per_m=0.03, retardance=0.4)
        assert tc > 0

    def test_kerby_longer_with_higher_retardance(self):
        tc_smooth = ConcentrationTime.kerby(length_km=0.5, slope_m_per_m=0.03, retardance=0.1)
        tc_rough = ConcentrationTime.kerby(length_km=0.5, slope_m_per_m=0.03, retardance=0.6)
        assert tc_rough > tc_smooth


class TestKerbyKirpichMethod:
    """Test composite Kerby-Kirpich method."""

    def test_kerby_kirpich_returns_positive(self):
        tc = ConcentrationTime.kerby_kirpich(
            overland_length_km=0.3, overland_slope_m_per_m=0.05,
            retardance=0.4,
            channel_length_km=2.0, channel_slope_m_per_m=0.01,
        )
        assert tc > 0

    def test_kerby_kirpich_sum_of_components(self):
        """Kerby-Kirpich tc >= pure Kirpich tc (adds overland component)."""
        tc_composite = ConcentrationTime.kerby_kirpich(
            overland_length_km=0.3, overland_slope_m_per_m=0.05,
            retardance=0.4,
            channel_length_km=2.0, channel_slope_m_per_m=0.01,
        )
        tc_kirpich = ConcentrationTime.kirpich(
            length_km=2.0, slope_m_per_m=0.01,
        )
        assert tc_composite >= tc_kirpich
```

- [ ] **3.15: Napisz testy integracyjne API dla nowych metod**

Plik: `backend/tests/unit/test_tc_methods.py` (kontynuacja)

```python
class TestTcMethodInSchema:
    """Test HydrographRequest accepts new tc methods."""

    def test_accepts_faa(self):
        from models.schemas import HydrographRequest
        req = HydrographRequest(
            latitude=52.0, longitude=17.0,
            duration="1h", probability=10,
            tc_method="faa",
        )
        assert req.tc_method == "faa"

    def test_accepts_kerby(self):
        from models.schemas import HydrographRequest
        req = HydrographRequest(
            latitude=52.0, longitude=17.0,
            duration="1h", probability=10,
            tc_method="kerby",
        )
        assert req.tc_method == "kerby"

    def test_accepts_kerby_kirpich(self):
        from models.schemas import HydrographRequest
        req = HydrographRequest(
            latitude=52.0, longitude=17.0,
            duration="1h", probability=10,
            tc_method="kerby_kirpich",
        )
        assert req.tc_method == "kerby_kirpich"

    def test_runoff_coeff_optional(self):
        from models.schemas import HydrographRequest
        req = HydrographRequest(
            latitude=52.0, longitude=17.0,
            duration="1h", probability=10,
            tc_method="faa",
            tc_runoff_coeff=0.6,
        )
        assert req.tc_runoff_coeff == 0.6

    def test_retardance_optional(self):
        from models.schemas import HydrographRequest
        req = HydrographRequest(
            latitude=52.0, longitude=17.0,
            duration="1h", probability=10,
            tc_method="kerby",
            tc_retardance=0.4,
        )
        assert req.tc_retardance == 0.4

```

Dodaj do `backend/tests/integration/test_hydrograph.py` (klasa `TestScenariosEndpoint`):

```python
    def test_scenarios_includes_new_tc_methods(self, client):
        """Verify /scenarios endpoint lists new tc methods."""
        response = client.get("/api/scenarios")
        data = response.json()
        tc_methods = data["tc_methods"]
        for method in ["faa", "kerby", "kerby_kirpich"]:
            assert method in tc_methods, f"Missing tc method: {method}"
```

Dodaj tez do `backend/tests/integration/test_hydrograph.py` test E2E dla nowej metody tc:

```python
    def test_generate_hydrograph_with_faa_tc(self, client, mock_dependencies):
        """Test hydrograph generation with FAA tc method."""
        response = client.post("/api/generate-hydrograph", json={
            "latitude": 52.4, "longitude": 17.1,
            "duration": "1h", "probability": 10,
            "tc_method": "faa",
            "tc_runoff_coeff": 0.5,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["metadata"]["tc_method"] == "faa"
        assert data["metadata"]["tc_min"] > 0
```

- [ ] **3.16: Uruchom testy**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_tc_methods.py -v --tb=short
cd backend && .venv/bin/python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

- [ ] **3.17: Commit**

```bash
git add backend/models/schemas.py backend/api/endpoints/hydrograph.py \
       frontend/index.html frontend/js/hydrograph.js frontend/js/api.js \
       backend/tests/unit/test_tc_methods.py
git commit -m "feat(api): add FAA, Kerby, Kerby-Kirpich tc methods from Hydrolog v0.6.3"
```

---

## Task 4: Przeglad UI/UX — spojnosc i przejrzystosc

**Cel:** Przeglad calego interfejsu pod katem spojnosci etykiet, logiki widocznosci, informacji zwrotnych dla uzytkownika.

### Checklist UI/UX

- [ ] **4.1: Spojnosc jezykowa etykiet**

Sprawdz, ze wszystkie etykiety w selektorach sa w jezyku polskim lub uzywaja jednolicie nazw wlasnych metod:
- Metody tc: nazwy wlasne (NRCS, Kirpich, Giandotti, FAA, Kerby, Kerby-Kirpich) — OK
- Estymacja Nash: "Lutz", "z Tc (SCS)", "Regresja urban." — sprawdz spojnosc

- [ ] **4.2: Logika widocznosci parametrow**

Przetestuj kazda kombinacje:
| UH Model | Nash Estimation | Widoczne |
|----------|-----------------|----------|
| SCS | - | tc-method |
| Snyder | - | tc-method, snyder-params (Ct, Cp) |
| Nash | from_lutz | nash-params |
| Nash | from_tc | nash-params, nash-n-row, tc-method |
| Nash | from_urban_regression | nash-params |

Dla tc-method gdy widoczne:
| Tc Method | Widoczne extra |
|-----------|---------------|
| nrcs/kirpich/giandotti | brak |
| faa | tc-runoff-coeff |
| kerby | tc-retardance |
| kerby_kirpich | tc-retardance |

- [ ] **4.3: Metadata display — nowe metody**

Sprawdz ze `displayMetadata()` poprawnie wyswietla:
- "Metoda Tc: FAA" / "Kerby" / "Kerby-Kirpich" (z TC_METHOD_LABELS)
- Wartosc Tc w minutach

- [ ] **4.4: Placeholder i domyslne wartosci**

- `tc_runoff_coeff`: placeholder "auto z CN" — jasny dla uzytkownika?
- `tc_retardance`: domyslna 0.4 — czy label "N (opor) 0.02–0.8" jest zrozumialy?
- Rozwazyc tooltip lub krotki opis typowych wartosci retardance

- [ ] **4.5: Auto-regeneracja z nowymi polami**

Sprawdz ze zmiana `hydro-tc-runoff-coeff` i `hydro-tc-retardance` triggeruje regeneracje (debounce 300ms).

- [ ] **4.6: Commit po poprawkach UI/UX**

```bash
git add frontend/
git commit -m "fix(frontend): UI/UX polish for new tc methods and Nash deprecation"
```

---

## Task 5: Aktualizacja dokumentacji

**Pliki:**
- Modify: `docs/CHANGELOG.md`
- Modify: `docs/HYDROLOG_INTEGRATION.md`
- Modify: `docs/CROSS_PROJECT_ANALYSIS.md`
- Modify: `docs/PROGRESS.md`

### Kroki

- [ ] **5.1: Zaktualizuj CHANGELOG.md**

Dodaj do sekcji `[Unreleased]`:

```markdown
### Zmienione
- Upgrade Hydrolog z v0.6.2 do v0.6.3 (nowe metody tc: FAA, Kerby, Kerby-Kirpich)
- Domyslna estymacja Nash zmieniona z `from_tc` (deprecated) na `from_lutz`

### Dodane
- 3 nowe metody czasu koncentracji: FAA (Federal Aviation Agency), Kerby (1959), Kerby-Kirpich (composite)
- Parametry `tc_runoff_coeff` i `tc_retardance` w HydrographRequest
- Selektor Tc rozszerzony o FAA, Kerby, Kerby-Kirpich z parametrami kontekstowymi
```

- [ ] **5.2: Zaktualizuj HYDROLOG_INTEGRATION.md**

Dodaj nowe metody tc do sekcji "Metody Tc":
- FAA: splyw powierzchniowy, wymaga C (runoff coefficient)
- Kerby: splyw powierzchniowy z retardance
- Kerby-Kirpich: metoda zlozzona (overland + channel)

Zaktualizuj wersje: v0.6.2 → v0.6.3

Zaktualizuj sekcje o deprecjacji `from_tc`.

- [ ] **5.3: Zaktualizuj CROSS_PROJECT_ANALYSIS.md**

Zmien wersje w tabeli zaleznosci:

```markdown
| **Hydrograf** | Hydrolog | bezposrednia (requirements.txt) | v0.6.3 |
```

- [ ] **5.4: Zaktualizuj PROGRESS.md**

Sekcja "Ostatnia sesja" — opisz co zrobiono w tej sesji.

- [ ] **5.5: Commit**

```bash
git add docs/CHANGELOG.md docs/HYDROLOG_INTEGRATION.md \
       docs/CROSS_PROJECT_ANALYSIS.md docs/PROGRESS.md
git commit -m "docs: update documentation for Hydrolog v0.6.3 upgrade"
```

---

## Kolejnosc realizacji

```
Task 1 (Version Bump) → Task 2 (Nash Default) → Task 3 (New TC Methods) → Task 4 (UI/UX Review) → Task 5 (Docs)
```

- Task 1 musi byc pierwszy (instalacja nowej wersji)
- **Task 2 i Task 3 MUSZA byc sekwencyjne** — oba modyfikuja te same pliki (schemas.py, hydrograph.py, index.html, hydrograph.js) w sasiadujacych liniach. Rownolegle wykonanie spowoduje konflikty merge.
- Task 4 po zakonczeniu Task 2 i 3 (przeglad calosciowy)
- Task 5 na koncu (finalna dokumentacja)

## Zespoly subagentow

Kazdy Task realizowany przez zespol:
1. **Researcher** (`subagent_type=Explore`) — analiza aktualnego kodu i nowego API Hydrologa
2. **Developer** (`subagent_type=general-purpose`) — implementacja zmian (Edit/Write)
3. **Tester** (`subagent_type=general-purpose`) — uruchomienie testow, weryfikacja
4. **UI/UX Reviewer** (`subagent_type=general-purpose`) — przeglad spojnosci interfejsu

Glowny agent koordynuje: przekazuje kontekst z Researchera do Developera, wyniki Developera do Testera, itd.
