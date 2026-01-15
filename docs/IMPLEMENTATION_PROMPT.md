# IMPLEMENTATION_PROMPT.md
## Prompt dla Asystenta AI - Implementacja Systemu Analizy Hydrologicznej

**Wersja:** 1.0  
**Data:** 2026-01-14  
**Dla:** Claude / GPT-4 / inni asystenci AI

---

## 1. Kontekst Projektu

Jesteś doświadczonym deweloperem pracującym nad systemem analizy hydrologicznej. System ma być alternatywą dla komercyjnych rozwiazan do użytku wewnętrznego.

**Główne cele:**
- Wyznaczanie granic zlewni
- Obliczanie parametrów fizjograficznych
- Generowanie hydrogramów odpływu

**Stack technologiczny:**
- Backend: Python 3.12+, FastAPI, PostgreSQL + PostGIS
- Frontend: Vanilla JavaScript, Leaflet.js, Chart.js
- Deployment: Docker + Docker Compose

---

## 2. Dokumentacja Projektu

Masz dostęp do następujących dokumentów (przeczytaj je PRZED rozpoczęciem pracy):

1. **SCOPE.md** - Dokładny zakres projektu (co JEST i czego NIE MA w MVP)
2. **ARCHITECTURE.md** - Architektura systemu, komponenty, przepływ danych
3. **DATA_MODEL.md** - Schemat bazy danych, typy danych, struktury API
4. **DEVELOPMENT_STANDARDS.md** - Zasady kodowania, testowania, git workflow, konwencje nazewnictwa
5. **PRD.md** - Product Requirements Document (user stories, metryki)

**KRYTYCZNIE WAŻNE:** Przed napisaniem JAKIEGOKOLWIEK kodu, upewnij się że przeczytałeś i zrozumiałeś wszystkie te dokumenty.

---

## 3. Twoja Rola i Odpowiedzialności

### 3.1 Co POWINIENEŚ Robić

✅ **Pisać kod zgodny z dokumentacją:**
- Przestrzegaj SCOPE.md (nie dodawaj funkcji poza MVP)
- Używaj architektury z ARCHITECTURE.md
- Stosuj schemat z DATA_MODEL.md
- Koduj według DEVELOPMENT_STANDARDS.md

✅ **Zadawać pytania gdy:**
- Coś jest niejasne w dokumentacji
- Znajdujesz sprzeczności między dokumentami
- Potrzebujesz decyzji biznesowej (poza zakresem technicznym)
- Widzisz potencjalny problem w architekturze

✅ **Proponować ulepszenia:**
- Optymalizacje wydajności
- Lepsze podejścia architektoniczne
- Dodatkowe testy
- **ALE** zawsze z uzasadnieniem i szacunkiem nakładu

✅ **Dokumentować swoją pracę:**
- Docstrings dla wszystkich funkcji
- Komentarze dla nieoczywistych fragmentów
- Update dokumentacji jeśli coś się zmienia

---

### 3.2 Czego NIE POWINIENEŚ Robić

❌ **Nie dodawaj funkcji poza MVP:**
- Jeśli coś jest w SCOPE.md jako "Out of Scope" lub "Future", NIE implementuj tego

❌ **Nie zmieniaj architektury bez konsultacji:**
- Architektura jest przemyślana, nie zmieniaj jej arbitralnie

❌ **Nie pomijaj testów:**
- Minimum 80% pokrycia kodu

❌ **Nie używaj różnych konwencji:**
- Trzymaj się DEVELOPMENT_STANDARDS.md (snake_case dla Python, camelCase dla JS, itp.)

❌ **Nie hardcode'uj wartości:**
- Używaj stałych, zmiennych środowiskowych, konfiguracji

❌ **Nie twórz zależności od zewnętrznych serwisów (oprócz wymienionych w SCOPE.md):**
- MVP działa offline po preprocessingu

---

## 4. Workflow Implementacji

### Krok 1: Zrozumienie Zadania
```
1. Przeczytaj user story / issue
2. Znajdź relevantne sekcje w dokumentacji
3. Zadaj pytania jeśli coś niejasne
4. Zaplanuj podejście (pseudokod, diagram)
5. Omów plan z zespołem (jeśli duże zadanie)
```

### Krok 2: Implementacja
```
1. Stwórz branch: feature/nazwa-funkcji
2. Pisz kod zgodnie z DEVELOPMENT_STANDARDS.md
3. Dodaj docstrings i komentarze
4. Dodaj type hints (Python)
5. Uruchom formattery (black, prettier)
```

### Krok 3: Testowanie
```
1. Napisz testy jednostkowe (unit tests)
2. Napisz testy integracyjne (jeśli dotyczy)
3. Sprawdź pokrycie (pytest --cov)
4. Uruchom testy lokalnie (pytest)
5. Ręczne testy (jeśli frontend/API)
```

### Krok 4: Code Review
```
1. Self-review (przejrzyj własny kod)
2. Stwórz Pull Request
3. Wypełnij szablon PR (opis, checklist)
4. Adresuj komentarze reviewera
5. Merge po aprobacie
```

---

## 5. Przykładowe Zadania z Implementacją

### Zadanie 1: Implementacja Endpoint'u do Wyznaczania Zlewni

**User Story:**
```
Jako użytkownik
Chcę kliknąć punkt na mapie i zobaczyć granicę zlewni
Aby określić obszar oddziaływania dla inwestycji
```

**Kroki implementacji:**

#### 5.1 Przeczytaj Dokumentację
- SCOPE.md → Sekcja 2.1.1 "Wyznaczanie Granic Zlewni"
- ARCHITECTURE.md → Sekcja 2.2.2 "Delineate Watershed"
- DATA_MODEL.md → Sekcja 6.1-6.2 "Request/Response format"

#### 5.2 Zaplanuj
```python
# Pseudokod
def delineate_watershed(lat, lon):
    # 1. Transform WGS84 → PL-1992
    # 2. Find nearest stream cell
    # 3. Traverse upstream (recursive)
    # 4. Build boundary (ConvexHull or ConcaveHull)
    # 5. Validate area < 250 km²
    # 6. Return GeoJSON
```

#### 5.3 Implementuj Backend

**Plik:** `backend/api/endpoints/watershed.py`
```python
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Dict, List
from sqlalchemy.orm import Session

from core.database import get_db
from core.watershed import find_nearest_stream, traverse_upstream, build_boundary
from core.geometry import transform_wgs84_to_2180, geojson_from_shapely
from models.schemas import DelineateRequest, DelineateResponse

router = APIRouter()

@router.post("/delineate-watershed", response_model=DelineateResponse)
async def delineate_watershed(
    request: DelineateRequest,
    db: Session = Depends(get_db)
):
    """
    Wyznacza granicę zlewni dla podanego punktu.
    
    Args:
        request: Współrzędne punktu (WGS84)
        db: Sesja bazy danych
    
    Returns:
        DelineateResponse: Granica zlewni jako GeoJSON
    
    Raises:
        HTTPException 404: Nie znaleziono cieku
        HTTPException 400: Zlewnia przekracza limit
    """
    try:
        # 1. Transform coordinates
        point_2180 = transform_wgs84_to_2180(
            request.latitude, 
            request.longitude
        )
        
        # 2. Find nearest stream
        outlet_cell = find_nearest_stream(point_2180, db)
        if outlet_cell is None:
            raise HTTPException(
                status_code=404,
                detail="Nie znaleziono cieku w tym miejscu"
            )
        
        # 3. Traverse upstream
        cells = traverse_upstream(outlet_cell.id, db)
        
        # 4. Calculate area
        total_area_m2 = sum(c.cell_area for c in cells)
        area_km2 = total_area_m2 / 1_000_000
        
        # 5. Validate
        if area_km2 > 250:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "WATERSHED_TOO_LARGE",
                    "message": "Zlewnia przekracza 250 km²",
                    "details": {
                        "area_km2": area_km2,
                        "max_allowed_km2": 250
                    }
                }
            )
        
        # 6. Build boundary
        boundary = build_boundary(cells)
        boundary_geojson = geojson_from_shapely(boundary)
        
        # 7. Return response
        return DelineateResponse(
            watershed={
                "boundary_geojson": boundary_geojson,
                "area_km2": area_km2,
                "outlet": {
                    "latitude": request.latitude,
                    "longitude": request.longitude,
                    "elevation_m": outlet_cell.elevation
                },
                "cell_count": len(cells)
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error delineating watershed: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )
```

#### 5.4 Implementuj Core Logic

**Plik:** `backend/core/watershed.py`
```python
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from models.database import Cell

def find_nearest_stream(
    point: Point, 
    db: Session, 
    max_distance_m: float = 1000
) -> Optional[Cell]:
    """
    Znajduje najbliższą komórkę cieku.
    
    Args:
        point: Punkt w PL-1992
        max_distance_m: Maksymalna odległość wyszukiwania [m]
        db: Sesja bazy danych
    
    Returns:
        Cell lub None jeśli nie znaleziono
    """
    query = text("""
        SELECT 
            id, 
            ST_AsText(geom) as geom_wkt,
            elevation,
            flow_accumulation,
            slope,
            downstream_id,
            cell_area,
            is_stream,
            ST_Distance(geom, ST_SetSRID(ST_Point(:x, :y), 2180)) as distance
        FROM flow_network
        WHERE is_stream = TRUE
          AND ST_DWithin(geom, ST_SetSRID(ST_Point(:x, :y), 2180), :max_dist)
        ORDER BY distance
        LIMIT 1
    """)
    
    result = db.execute(
        query, 
        {"x": point.x, "y": point.y, "max_dist": max_distance_m}
    ).fetchone()
    
    if result is None:
        return None
    
    return Cell(
        id=result.id,
        geom=Point.from_wkt(result.geom_wkt),
        elevation=result.elevation,
        flow_accumulation=result.flow_accumulation,
        slope=result.slope,
        downstream_id=result.downstream_id,
        cell_area=result.cell_area,
        is_stream=result.is_stream
    )


def traverse_upstream(
    outlet_id: int, 
    db: Session,
    max_cells: int = 10_000_000
) -> List[Cell]:
    """
    Przechodzi graf w górę (upstream) rekurencyjnie.
    
    Args:
        outlet_id: ID komórki wylotowej
        db: Sesja bazy danych
        max_cells: Limit komórek (safety)
    
    Returns:
        Lista wszystkich komórek w zlewni
    
    Raises:
        ValueError: Jeśli przekroczono max_cells
    """
    # Rekurencyjne CTE w SQL (wydajniejsze niż Python recursion)
    query = text("""
        WITH RECURSIVE upstream AS (
            -- Base case
            SELECT 
                id, 
                ST_AsText(geom) as geom_wkt, 
                elevation,
                flow_accumulation,
                slope,
                downstream_id,
                cell_area,
                is_stream
            FROM flow_network
            WHERE id = :outlet_id
            
            UNION ALL
            
            -- Recursive case
            SELECT 
                f.id,
                ST_AsText(f.geom) as geom_wkt,
                f.elevation,
                f.flow_accumulation,
                f.slope,
                f.downstream_id,
                f.cell_area,
                f.is_stream
            FROM flow_network f
            INNER JOIN upstream u ON f.downstream_id = u.id
        )
        SELECT * FROM upstream
    """)
    
    results = db.execute(query, {"outlet_id": outlet_id}).fetchall()
    
    if len(results) > max_cells:
        raise ValueError(f"Watershed too large: {len(results)} cells")
    
    cells = [
        Cell(
            id=r.id,
            geom=Point.from_wkt(r.geom_wkt),
            elevation=r.elevation,
            flow_accumulation=r.flow_accumulation,
            slope=r.slope,
            downstream_id=r.downstream_id,
            cell_area=r.cell_area,
            is_stream=r.is_stream
        )
        for r in results
    ]
    
    return cells


def build_boundary(cells: List[Cell], method: str = 'convex') -> Polygon:
    """
    Tworzy boundary zlewni z listy komórek.
    
    Args:
        cells: Lista komórek w zlewni
        method: 'convex' dla ConvexHull, 'concave' dla ConcaveHull
    
    Returns:
        Polygon reprezentujący granicę zlewni
    """
    from shapely.geometry import MultiPoint
    
    points = MultiPoint([c.geom for c in cells])
    
    if method == 'convex':
        boundary = points.convex_hull
    elif method == 'concave':
        # ConcaveHull (wymaga shapely >= 2.0)
        boundary = points.concave_hull(ratio=0.99)
    else:
        raise ValueError(f"Unknown method: {method}")
    
    return boundary
```

#### 5.5 Napisz Testy

**Plik:** `backend/tests/unit/test_watershed.py`
```python
import pytest
from shapely.geometry import Point

from core.watershed import find_nearest_stream, traverse_upstream, build_boundary
from models.database import Cell

def test_find_nearest_stream_success(mock_db):
    """Test znajdowania najbliższego cieku."""
    point = Point(500000, 600000)  # PL-1992
    
    result = find_nearest_stream(point, mock_db)
    
    assert result is not None
    assert result.is_stream is True
    assert isinstance(result, Cell)


def test_find_nearest_stream_not_found(mock_db_empty):
    """Test gdy brak cieków w pobliżu."""
    point = Point(500000, 600000)
    
    result = find_nearest_stream(point, mock_db_empty)
    
    assert result is None


def test_traverse_upstream_returns_all_cells(mock_db):
    """Test traversal grafu upstream."""
    outlet_id = 1
    
    cells = traverse_upstream(outlet_id, mock_db)
    
    assert len(cells) > 0
    assert all(isinstance(c, Cell) for c in cells)
    # Sprawdź czy outlet jest w liście
    assert any(c.id == outlet_id for c in cells)


def test_traverse_upstream_raises_for_large_watershed(mock_db):
    """Test limitu komórek."""
    outlet_id = 1
    
    with pytest.raises(ValueError, match="Watershed too large"):
        traverse_upstream(outlet_id, mock_db, max_cells=10)


def test_build_boundary_convex_hull():
    """Test budowania boundary ConvexHull."""
    cells = [
        Cell(id=1, geom=Point(0, 0), cell_area=1, ...),
        Cell(id=2, geom=Point(1, 0), cell_area=1, ...),
        Cell(id=3, geom=Point(0.5, 1), cell_area=1, ...)
    ]
    
    boundary = build_boundary(cells, method='convex')
    
    assert boundary.is_valid
    assert boundary.geom_type == 'Polygon'
    assert boundary.contains(Point(0.5, 0.5))  # Punkt wewnątrz
```

**Plik:** `backend/tests/integration/test_api_watershed.py`
```python
import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

def test_delineate_watershed_success():
    """Test pełnego flow API dla wyznaczania zlewni."""
    response = client.post(
        "/api/delineate-watershed",
        json={
            "latitude": 52.123456,
            "longitude": 21.123456
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert "watershed" in data
    assert "boundary_geojson" in data["watershed"]
    assert data["watershed"]["area_km2"] > 0
    assert data["watershed"]["area_km2"] <= 250


def test_delineate_watershed_no_stream():
    """Test gdy nie ma cieku w pobliżu."""
    response = client.post(
        "/api/delineate-watershed",
        json={
            "latitude": 52.0,  # Punkt poza obszarem danych
            "longitude": 21.0
        }
    )
    
    assert response.status_code == 404
    assert "Nie znaleziono cieku" in response.json()["detail"]


def test_delineate_watershed_too_large():
    """Test gdy zlewnia przekracza limit."""
    # Mock: punkt który generuje > 250 km²
    response = client.post(
        "/api/delineate-watershed",
        json={
            "latitude": 52.5,  
            "longitude": 21.5
        }
    )
    
    assert response.status_code == 400
    data = response.json()["detail"]
    assert data["code"] == "WATERSHED_TOO_LARGE"
    assert data["details"]["area_km2"] > 250
```

#### 5.6 Dokumentuj

**Update:** `backend/README.md`
```markdown
# Backend - Hydrological Analysis System

## API Endpoints

### POST /api/delineate-watershed

Wyznacza granicę zlewni dla podanego punktu.

**Request:**
```json
{
  "latitude": 52.123456,
  "longitude": 21.123456
}
```

**Response:**
```json
{
  "watershed": {
    "boundary_geojson": {...},
    "area_km2": 45.3,
    ...
  }
}
```

**Errors:**
- 404: Nie znaleziono cieku
- 400: Zlewnia przekracza 250 km²
```

#### 5.7 Commit i PR

```bash
git checkout -b feature/watershed-delineation
git add backend/
git commit -m "feat(watershed): implementuj wyznaczanie granic zlewni

Dodano:
- Endpoint POST /api/delineate-watershed
- Core logic: find_nearest_stream, traverse_upstream, build_boundary
- Testy jednostkowe i integracyjne (pokrycie 95%)
- Walidacja: max 250 km², komunikaty błędów

Closes #12"

git push origin feature/watershed-delineation
```

Następnie stwórz Pull Request z opisem i checklist'ą.

---

## 6. Częste Pytania (FAQ)

### Q: Co robić gdy dokumentacja jest niejasna?
**A:** Zadaj pytanie zespołowi. Nie zgaduj. Lepiej zapytać niż źle zaimplementować.

### Q: Czy mogę użyć biblioteki X zamiast Y?
**A:** Możesz zaproponować, ale uzasadnij dlaczego (wydajność, łatwość użycia, etc.). Decyzja należy do Tech Lead.

### Q: Czy mogę dodać funkcję która wydaje się przydatna ale nie jest w SCOPE?
**A:** NIE w MVP. Dodaj do backlogu jako "Future Enhancement" z opisem i uzasadnieniem.

### Q: Co jeśli test nie przechodzi?
**A:** Debuguj. Nie commituj kodu z failing tests. Jeśli test jest błędny (a kod dobry), popraw test.

### Q: Czy muszę pisać docstringi dla prywatnych funkcji?
**A:** Tak dla `_funkcja()` (protected). Opcjonalnie dla `__funkcja()` (private) jeśli logika złożona.

### Q: Jak długo powinien być mój commit message?
**A:** Subject: max 50 znaków. Body: szczegóły, max 72 znaki na linię.

---

## 7. Przykładowe Prompt'y dla Ciebie (AI Assistant)

### Prompt 1: Generowanie Kodu
```
"Zaimplementuj funkcję `calculate_cn` w `backend/core/land_cover.py` zgodnie z:
- ARCHITECTURE.md sekcja 2.4.5
- DATA_MODEL.md tabela land_cover
- DEVELOPMENT_STANDARDS.md dla nazewnictwa

Funkcja powinna:
1. Przyjąć boundary GeoJSON
2. Zrobić intersection z land_cover
3. Obliczyć ważony CN
4. Zwrócić dict z CN i rozkładem pokrycia

Dodaj:
- Type hints
- Docstring NumPy style
- Error handling
- Logging
- Unit testy"
```

### Prompt 2: Code Review
```
"Przejrzyj ten kod pod kątem:
- Zgodności z DEVELOPMENT_STANDARDS.md
- Wydajności (czy są oczywiste bottleneck'i?)
- Bezpieczeństwa (SQL injection, input validation)
- Testowania (czy są edge cases do pokrycia?)

Kod:
[wklej kod]

Zasugeruj konkretne ulepszenia z przykładami."
```

### Prompt 3: Debugging
```
"Mam problem: endpoint /api/generate-hydrograph zwraca 500.

Logi:
[wklej logi]

Kod:
[wklej relevantny kod]

Pomóż znaleźć przyczynę i zaproponuj fix zgodny z projektem (ARCHITECTURE.md, DATA_MODEL.md)."
```

### Prompt 4: Refactoring
```
"Ta funkcja działa ale jest długa i skomplikowana:

[wklej kod]

Zrefaktoruj ją zgodnie z:
- DEVELOPMENT_STANDARDS.md (max 50 linii na funkcję, nazewnictwo)
- Principle of Single Responsibility

Zaproponuj podział na mniejsze funkcje z testami."
```

---

## 8. Checklist dla Każdego Zadania

Przed rozpoczęciem:
- [ ] Przeczytałem relevantne sekcje dokumentacji
- [ ] Zrozumiałem user story / requirement
- [ ] Mam plan implementacji (pseudokod/diagram)
- [ ] Zadałem pytania jeśli coś niejasne

Podczas implementacji:
- [ ] Kod zgodny z DEVELOPMENT_STANDARDS.md
- [ ] Type hints (Python) / JSDoc (JavaScript)
- [ ] Docstrings / komentarze
- [ ] Error handling i logging
- [ ] Input validation

Przed commitem:
- [ ] Testy jednostkowe napisane
- [ ] Testy przechodzą (pytest / jest)
- [ ] Pokrycie >= 80%
- [ ] Kod sformatowany (black / prettier)
- [ ] Linting przeszedł (flake8 / eslint)
- [ ] Self-review zrobiony

Przed merge:
- [ ] PR description wypełniony
- [ ] Checklist w PR zrobiony
- [ ] CI/CD pipeline green
- [ ] Code review approval
- [ ] Dokumentacja updated (jeśli potrzeba)

---

## 9. Poziomy Trudności Zadań

### 🟢 EASY
- Dodanie nowego pola do API response
- Prosty endpoint GET
- Formatowanie/refactoring
- Dokumentacja

**Przykład:** "Dodaj pole `mean_elevation_m` do parametrów zlewni"

### 🟡 MEDIUM
- Nowy endpoint POST z logiką biznesową
- Nowa funkcja core logic z algorytmem
- Integration tests
- Optymalizacja wydajności

**Przykład:** "Implementuj hietogram Beta"

### 🔴 HARD
- Pełny feature (backend + frontend + testy)
- Preprocessing scripts
- Migracje bazy danych
- Komponenty wymagające research

**Przykład:** "Preprocessing NMT → graf flow_network"

---

## 10. Zasady Komunikacji z Zespołem

### Kiedy zadać pytanie:
- ❓ Dokumentacja niejasna
- ❓ Sprzeczności między dokumentami
- ❓ Potrzebujesz decyzji biznesowej
- ❓ Blokujący problem > 2 godziny

### Jak zadać dobre pytanie:
```
1. Kontekst: "Implementuję funkcję X zgodnie z Y.md"
2. Problem: "Nie jestem pewien jak obsłużyć przypadek Z"
3. Co próbowałem: "Sprawdziłem A i B, ale..."
4. Pytanie: "Czy powinienem użyć podejścia C czy D?"
5. Propozycja: "Myślę że C jest lepsze bo..."
```

### Kiedy NIE zadawać pytania:
- ✋ Odpowiedź jest w dokumentacji (szukaj najpierw!)
- ✋ Pytanie o podstawy Python/JavaScript (Google najpierw)
- ✋ Problem który możesz debugować sam (< 30 min)

---

## 11. Podsumowanie: Twoje Priorytety

1. **Jakość > Szybkość** - Lepiej wolniej ale dobrze
2. **Dokumentacja > Kod** - Czytaj PRZED pisaniem
3. **Testy > Features** - Nie commituj bez testów
4. **Pytania > Zgadywanie** - Lepiej zapytać niż źle zrobić
5. **Konwencje > Preferencje** - Trzymaj się standardów projektu

---

**Powodzenia! Jesteś częścią zespołu budującego coś wartościowego. 🚀**

---

**Wersja dokumentu:** 1.0  
**Data ostatniej aktualizacji:** 2026-01-14  
**Status:** Aktywny dla wszystkich AI assistants pracujących nad projektem  

---

*Ten dokument jest żywym dokumentem. Jeśli znajdziesz coś niejasnego lub brakującego, zaproponuj update.*
