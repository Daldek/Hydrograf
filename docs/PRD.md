# Product Requirements Document (PRD)
## System Analizy Hydrologicznej

**Wersja:** 1.1
**Data:** 2026-03-01
**Status:** Approved
**Autor:** Zespół projektowy

---

## 1. Podsumowanie Wykonawcze

### 1.1 Cel Produktu
Stworzenie wewnętrznego narzędzia webowego do szybkiego wyznaczania granic zlewni, parametrów fizjograficznych i hydrogramów odpływu. System ma być alternatywą dla komercyjnego oprogramowania, wykorzystującą otwarte dane GUGIK i IMGW. Uwaga: generowanie hydrogramów metodą SCS-CN ograniczone do zlewni ≤ 250 km² (ograniczenie metody).

### 1.2 Problem Biznesowy
Obecnie profesjonalne narzędzia do analiz hydrologicznych są:
- Kosztowne w licencjonowaniu
- Wymagają zaawansowanej wiedzy GIS
- Opierają się na danych nie zawsze dostępnych lokalnie
- Nie pozwalają na pełną kontrolę nad danymi i algorytmami

### 1.3 Grupa Docelowa
**Użytkownicy pierwotni:**
- Specjaliści ds. planowania przestrzennego
- Pracownicy urzędów gmin
- Konsultanci środowiskowi

**Charakterystyka użytkowników:**
- Niekoniecznie posiadają umiejętności GIS
- Potrzebują szybkich wyników dla decyzji planistycznych

### 1.4 Kluczowe Metryki Sukcesu
- Czas wyznaczenia zlewni i hydrogramu: **< 30 sekund**
- Dokładność granic zlewni: **95%+ zgodności z metodami referencyjnymi**
- Dostępność systemu: **99% uptime**
- Satysfakcja użytkowników: **> 4/5** w badaniach

---

## 2. Zakres Produktu

### 2.1 Co JEST w zakresie (MVP)

**FAZA 1: Wyznaczanie granic zlewni**
- Wybór punktu na mapie interaktywnej
- Automatyczne wyznaczenie granicy zlewni
- Wizualizacja wyniku jako GeoJSON

**FAZA 2: Parametry fizjograficzne**
- Powierzchnia i obwód zlewni
- Długość głównego cieku
- Średnie spadki (terenu i cieku)
- Współczynniki morfometryczne
- Rozkład pokrycia terenu
- Curve Number (CN)

**FAZA 3: Hydrogram odpływu**
- Wybór scenariusza opadowego (czas × prawdopodobieństwo)
- Dane z IMGW
- Hietogram z rozkładu Beta
- Model SCS Curve Number
- Hydrogram jednostkowy SCS
- Wizualizacja wykresu hydrogramu
- Parametry: Qmax, czas do szczytu, objętość

### 2.2 Co NIE JEST w zakresie (MVP)

**Poza MVP:**
- Routing (wyznaczanie tras przepływu)
- Symulacje różnych scenariuszy klimatycznych jednocześnie
- Analiza ryzyka powodziowego (mapy zalewowe)
- Wizualizacja 3D terenu
- Integracja z danymi pomiarowymi w czasie rzeczywistym
- Aplikacja mobilna
- Współpraca wieloużytkownikowa w czasie rzeczywistym
- Eksport raportów PDF (możliwe w przyszłości)

### 2.3 Źródła Danych

**Dane przestrzenne:**
- NMT (Numeryczny Model Terenu)
- Pokrycie terenu - BDOT10k z GUGIK lub CLC
- Osie cieków - MPHP lub własne dane wektorowe

**Dane opadowe:**
- IMGW pmaxpt lub dane historyczne
- Wszystkie kombinacje:
  - Czasy: 15min, 30min, 1h, 2h, 6h, 12h, 24h
  - Prawdopodobieństwa: 1%, 2%, 5%, 10%, 20%, 50%

**Założenia:**
- Opad równomierny na całą zlewnię
- Dane aktualizowane raz na rok

---

## 3. Wymagania Funkcjonalne - User Stories

### US-01: Wyznaczenie zlewni
**Jako** specjalista ds. planowania przestrzennego  
**Chcę** wybrać punkt na mapie i otrzymać granicę zlewni  
**Aby** szybko określić obszar oddziaływania dla planowanej inwestycji

**Kryteria akceptacji:**
- Użytkownik klika punkt na mapie
- System znajduje najbliższy ciek
- System wyznacza zlewnię w < 10 sekund
- Granica zlewni jest wyświetlana na mapie
- Możliwość eksportu granicy jako GeoJSON/Shapefile

**Priorytet:** MUST HAVE  
**Story Points:** 8

---

### US-02: Wyświetlenie parametrów zlewni
**Jako** użytkownik  
**Chcę** zobaczyć kluczowe parametry wyznaczonej zlewni  
**Aby** ocenić jej charakterystykę hydrologiczną

**Kryteria akceptacji:**
- Wyświetlenie powierzchni [km²]
- Wyświetlenie długości głównego cieku [km]
- Wyświetlenie średniego spadku [%]
- Wyświetlenie rozkładu pokrycia terenu [%]
- Wyświetlenie CN
- Wszystkie parametry w przejrzystej tabeli

**Priorytet:** MUST HAVE  
**Story Points:** 5

---

### US-03: Wybór scenariusza opadowego
**Jako** użytkownik  
**Chcę** wybrać czas trwania i prawdopodobieństwo opadu  
**Aby** wygenerować hydrogram dla konkretnego scenariusza

**Kryteria akceptacji:**
- Lista dostępnych czasów trwania (7 opcji)
- Lista dostępnych prawdopodobieństw (6 opcji)
- Wyświetlenie wartości opadu dla wybranego scenariusza
- Przycisk "Oblicz hydrogram"

**Priorytet:** MUST HAVE  
**Story Points:** 3

---

### US-04: Generowanie hydrogramu
**Jako** użytkownik  
**Chcę** wygenerować hydrogram odpływu  
**Aby** określić przepływy maksymalne dla wybranego scenariusza

**Kryteria akceptacji:**
- Wygenerowanie hydrogramu w < 5 sekund
- Wykres liniowy (czas vs przepływ)
- Wyświetlenie kluczowych parametrów:
  - Qmax [m³/s]
  - Czas do szczytu [min]
  - Objętość odpływu [m³]
- Możliwość eksportu danych jako CSV

**Priorytet:** MUST HAVE  
**Story Points:** 8

---

### US-05: Eksport wyników
**Jako** użytkownik  
**Chcę** wyeksportować wyniki analizy  
**Aby** użyć ich w innych narzędziach lub dokumentacji

**Kryteria akceptacji:**
- Eksport granicy zlewni (GeoJSON/Shapefile)
- Eksport hydrogramu (CSV: czas, przepływ)
- Eksport parametrów (JSON lub CSV)
- Przyciski eksportu w interfejsie

**Priorytet:** SHOULD HAVE  
**Story Points:** 3

---

### US-06: Komunikaty o błędach
**Jako** użytkownik  
**Chcę** otrzymać jasne komunikaty o błędach  
**Aby** zrozumieć, co poszło nie tak

**Kryteria akceptacji:**
- "Nie można znaleźć cieku w tym miejscu"
- "Błąd połączenia z serwerem - spróbuj ponownie"
- Komunikaty wyświetlane jako modal lub toast

**Priorytet:** MUST HAVE  
**Story Points:** 2

---

## 4. Wymagania Niefunkcjonalne

### NFR-01: Wydajność
- Wyznaczenie zlewni: **< 10 sekund**
- Generowanie hydrogramu: **< 5 sekund**
- Ładowanie mapy: **< 2 sekundy**
- Responsywność UI: **< 100ms** dla interakcji użytkownika

### NFR-02: Skalowalność
- Obsługa **10 równoczesnych użytkowników** (MVP)
- Możliwość skalowania do **50+ użytkowników** w przyszłości
- Architektura umożliwiająca dodawanie serwerów obliczeniowych

### NFR-03: Dostępność
- **99% uptime** (dopuszczalny downtime: ~7h/miesiąc)
- Automatyczne restarty w przypadku awarii
- Backupy bazy danych: codziennie

### NFR-04: Bezpieczeństwo
- Dostęp do systemu: **tylko z sieci wewnętrznej** (MVP)
- HTTPS dla wszystkich połączeń
- Walidacja wszystkich danych wejściowych
- Brak przechowywania danych osobowych użytkowników

### NFR-05: Użyteczność
- Intuicyjny interfejs, **bez wymaganego szkolenia** dla podstawowych funkcji
- Dostępność na desktop (Chrome, Firefox, Safari, Edge)
- Responsywność: ekrany ≥ 1280px szerokości
- Język: **polski**

### NFR-06: Utrzymanie
- Kod zgodny z PEP 8 (Python)
- Dokumentacja API (OpenAPI/Swagger)
- Dokumentacja użytkownika (Markdown)
- Testy jednostkowe: **> 80% pokrycia**

---

## 5. Interfejs Użytkownika (UI/UX)

### 5.1 Wireframe - Ekran Główny

```
┌─────────────────────────────────────────────────────────────┐
│  🏞️ SYSTEM ANALIZY HYDROLOGICZNEJ                [? Pomoc]  │
├─────────────────────────────────┬───────────────────────────┤
│                                 │  PARAMETRY ZLEWNI         │
│         MAPA                    │  ─────────────────────    │
│  ┌───────────────────────────┐  │  Powierzchnia: 45.3 km²   │
│  │                           │  │  Obwód: 38.5 km           │
│  │   🗺️                      │  │  Dł. cieku: 8.2 km        │
│  │                           │  │  Spadek: 2.3%             │
│  │   📍← kliknij tu          │  │  CN: 72                   │
│  │                           │  │                           │
│  │                           │  │  POKRYCIE TERENU          │
│  │   [Granica zlewni         │  │  ─────────────────────    │
│  │    wyświetlona]           │  │  🌲 Las: 35%              │
│  │                           │  │  🌾 Pola: 42%             │
│  │                           │  │  🏡 Zabudowa: 5%          │
│  └───────────────────────────┘  │  🌿 Łąki: 18%             │
│                                 │                           │
│  Legenda:                       │  SCENARIUSZ OPADOWY       │
│  🔵 Cieki  🟢 Zlewnia          │  ─────────────────────    │
│                                 │  Czas trwania:            │
│                                 │  ○ 15min  ○ 30min         │
│                                 │  ● 1h     ○ 2h            │
│                                 │  ○ 6h     ○ 24h           │
│                                 │                           │
│                                 │  Prawdopodobieństwo:      │
│                                 │  ○ 1%   ○ 2%   ● 10%      │
│                                 │  ○ 20%  ○ 50%             │
│                                 │                           │
│                                 │  Opad: 38.5 mm            │
│                                 │                           │
│                                 │  [ OBLICZ HYDROGRAM ]     │
├─────────────────────────────────┴───────────────────────────┤
│  HYDROGRAM ODPŁYWU                                          │
│  ──────────────────────────────────────────────────────────│
│                                                             │
│   Qmax = 42.3 m³/s  │  Czas do szczytu = 75 min            │
│                                                             │
│   Q [m³/s]                                                  │
│   50 │                                                      │
│      │           ╱╲                                         │
│   40 │          ╱  ╲                                        │
│      │         ╱    ╲                                       │
│   30 │        ╱      ╲                                      │
│      │       ╱        ╲                                     │
│   20 │      ╱          ╲                                    │
│      │     ╱            ╲___                                │
│   10 │    ╱                                                 │
│      │___╱                                                  │
│    0 └──────────────────────────────────> t [min]          │
│       0    60   120   180   240   300                      │
│                                                             │
│   [📥 Eksport CSV]  [📥 Eksport GeoJSON]                   │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 Paleta Kolorów

**Główne:**
- Tło: `#FFFFFF` (biały)
- Panel boczny: `#F8F9FA` (jasnoszary)
- Przycisk główny: `#007BFF` (niebieski)
- Przycisk hover: `#0056B3` (ciemnoniebieski)

**Mapa:**
- Cieki: `#0066CC` (niebieski)
- Granica zlewni: `#28A745` z opacity 0.3 (zielony)
- Główny ciek: `#DC3545` (czerwony)

**Wykres:**
- Linia hydrogramu: `#007BFF` (niebieski)
- Siatka: `#E0E0E0` (jasnoszary)
- Qmax marker: `#DC3545` (czerwony)

### 5.3 Typografia

- **Nagłówki:** Roboto Bold, 18-24px
- **Tekst:** Roboto Regular, 14-16px
- **Etykiety:** Roboto Medium, 12-14px
- **Dane liczbowe:** Roboto Mono, 14px

---

## 6. Przepływ Użytkownika (User Flow)

### 6.1 Główny Przepływ - Generowanie Hydrogramu

```
START
  │
  ├─> [1] Użytkownik otwiera aplikację
  │        ↓
  │   [2] Mapa ładuje się z podkładem OSM
  │        ↓
  │   [3] Użytkownik klika punkt na mapie
  │        ↓
  │   [4] System wyznacza granicę zlewni (loader: "Wyznaczam zlewnię...")
  │        ↓
  │   [5] Granica wyświetla się na mapie
  │        ↓
  │   [6] Parametry zlewni wyświetlają się w panelu bocznym
  │        │
  │        ├─> Powierzchnia: 45.3 km²
  │        ├─> CN: 72
  │        ├─> Długość cieku: 8.2 km
  │        └─> Rozkład pokrycia: las 35%, pola 42%, ...
  │        ↓
  │   [7] Użytkownik wybiera scenariusz opadowy
  │        │
  │        ├─> Czas trwania: [○15min ○30min ●1h ○2h ○6h ○24h]
  │        └─> Prawdopodobieństwo: [○1% ○2% ●10% ○20% ○50%]
  │        ↓
  │   [8] System wyświetla wartość opadu: "P = 38.5 mm"
  │        ↓
  │   [9] Użytkownik klika "OBLICZ HYDROGRAM"
  │        ↓
  │   [10] System generuje hydrogram (loader: "Obliczam...")
  │        ↓
  │   [11] Wykres hydrogramu wyświetla się
  │        │
  │        ├─> Qmax = 42.3 m³/s
  │        ├─> Czas do szczytu = 75 min
  │        └─> Objętość = 156,780 m³
  │        ↓
  │   [12] Użytkownik może:
  │        │
  │        ├─> Zmienić scenariusz i przeliczyć
  │        ├─> Eksportować wyniki (CSV/GeoJSON)
  │        └─> Wybrać nowy punkt na mapie
  │
END
```

### 6.2 Przepływ Alternatywny - Błędy

```
[3] Użytkownik klika punkt
     ↓
[4a] Punkt nie jest na cieku
     ↓
     Komunikat: "Nie znaleziono cieku w tym miejscu. 
                  Wybierz punkt na niebieskiej linii."
     ↓
     Powrót do [3]

---

[4b] Zlewnia > 250 km²
     ↓
     Zlewnia wyznaczona poprawnie, ale:
     - Komunikat ostrzegawczy: "Zlewnia przekracza 250 km².
       Obliczenie hydrogramu metodą SCS-CN niedostępne."
     - Przycisk "OBLICZ HYDROGRAM" nieaktywny
     - Wyznaczanie zlewni i parametry fizjograficzne działają normalnie
     ↓
     Użytkownik może eksportować granicę zlewni i parametry

---

[10a] Błąd serwera
      ↓
      Komunikat: "Nie udało się obliczyć hydrogramu. 
                   Spróbuj ponownie."
      ↓
      Powrót do [9]
```

---

## 7. Harmonogram i Kamienie Milowe

### 7.1 Timeline (Gantt Chart)

```
Koleność:  1    2    3    4    5    6    7    8    9    10
         ────────────────────────────────────────────────────
Faza 0:  ████████
Faza 1:          ████████████████████
Faza 2:                              ██████████████
Faza 3:                                            ██████████████
Faza 4:                                                          ██████
         ────────────────────────────────────────────────────
Launch:                                                            🚀
```

**Szacowany czas całkowity: 10 tygodni**

### 7.2 Fazy Projektu

#### **Faza 0: Preprocessing (2 tygodnie)**
**Kamienie milowe:**
- ☑ Pobrane dane z IMGW
- ☑ Wygenerowana tabela `flow_network` (WYELIMINOWANA w ADR-028, migracja 015 — zastapiona przez stream_network + CatchmentGraph in-memory)
- ☑ Zaimportowane pokrycie terenu i cieki
- ☑ Walidacja danych: pokrycie 100% obszaru gminy

#### **Faza 1: Backend MVP (3 tygodnie)**
**Kamienie milowe:**
- ☑ Setup FastAPI + PostgreSQL
- ☑ Endpoint: POST `/api/delineate-watershed`
- ☑ Endpoint: POST `/api/select-stream` — selekcja segmentu cieku + upstream traversal
- ☑ Endpoint: POST `/api/terrain-profile` — profil terenu wzdluz polilinii
- ☑ Endpoint: GET `/api/depressions` — zaglbienia terenu z filtrami
- ☑ Endpoint: GET `/api/tiles/streams/{z}/{x}/{y}.pbf` — kafelki MVT ciekow
- ☑ Endpoint: GET `/api/tiles/catchments/{z}/{x}/{y}.pbf` — kafelki MVT zlewni czastkowych
- ☑ Endpoint: GET `/api/tiles/landcover/{z}/{x}/{y}.pbf` — kafelki MVT pokrycia terenu BDOT10k
- ☑ Endpoint: GET `/api/tiles/thresholds` — dostepne progi FA
- ☑ Endpoint: GET `/api/scenarios` — lista dostepnych scenariuszy opadowych
- ☑ Endpoint: GET `/health` — health check
- ☑ Algorytm wyznaczania zlewni z grafu (CatchmentGraph in-memory + BFS)
- ☑ Obliczanie parametrów fizjograficznych
- ☑ Testy jednostkowe: > 80% pokrycia (720 testow, 43 pliki testowe)

#### **Faza 2: Model Hydrologiczny (2 tygodnie)**
**Kamienie milowe:**
- ☑ Implementacja hietogramu Beta
- ☑ Model SCS Curve Number
- ☑ Hydrogram jednostkowy SCS
- ☑ Splot numeryczny
- ☑ Endpoint: POST `/api/generate-hydrograph`
- ☑ Walidacja na 3 przykładowych zlewniach

#### **Faza 3: Frontend (2 tygodnie)**
**Kamienie milowe:**
- ☑ Mapa Leaflet z wyborem punktu (tryb rysowania poligonu, tryb wyboru obiektow)
- ☑ Formularz scenariusza opadowego
- ☑ Wywołania API z obsługą błędów
- ☑ Wykres Chart.js (hydrogram, histogram)
- ☑ Eksport CSV/GeoJSON
- ☑ Glassmorphism UI z draggable panelem bocznym
- ☑ Warstwy podkladowe: OSM, ESRI Satellite, OpenTopoMap, GUGiK WMTS (ortofoto + topo)
- ☑ Warstwy tematyczne: cieki MVT, zlewnie MVT, pokrycie terenu MVT, DEM hillshade, depresje
- ☑ Profil terenu — wizualizacja podluzna cieku
- ☑ 10 modulow JS (IIFE na `window.Hydrograf`): api, map, draggable, charts, layers, profile, hydrograph, depressions, app

#### **Faza 3b: Panel administracyjny (ADR-034)**
**Kamienie milowe:**
- ☑ Frontend `/admin` — glassmorphism, 4 sekcje (Dashboard, Bootstrap, Zasoby, Czyszczenie)
- ☑ 8 endpointow API `/api/admin/*` (dashboard, resources, cleanup estimate/execute, bootstrap start/cancel/status/stream)
- ☑ Uwierzytelnianie API key (header X-Admin-Key, env ADMIN_API_KEY)
- ☑ Uruchamianie bootstrap.py z panelu + real-time logi SSE
- ☑ Monitorowanie zasobow: CPU/RAM (psutil), pool DB, CatchmentGraph cache
- ☑ Czyszczenie danych: tiles, overlays, dem_mosaic, TRUNCATE tabel
- ☑ 3 moduly JS admin: admin-api.js, admin-app.js, admin-bootstrap.js

#### **Faza 4: Testy i Deploy (1 tydzień)**
**Kamienie milowe:**
- ☑ Optymalizacja wydajności (CatchmentGraph in-memory, O(n) downstream links, boundary smoothing)
- ☑ Docker Compose setup (db + api + nginx, 3 kontenery)
- ☑ Dokumentacja techniczna (34 ADR, architektura, integracje)
- ⏳ Testy akceptacyjne z użytkownikami (UAT) — planowane na CP5
- ⏳ Deploy produkcyjny — planowany na CP5

---

## 8. Kryteria Sukcesu i Metryki

### 8.1 Metryki Produktowe (MVP)

| Metryka | Target | Pomiar |
|---------|--------|--------|
| Czas wyznaczenia zlewni | < 10s | Backend logs |
| Czas generowania hydrogramu | < 5s | Backend logs |
| Dokładność granic zlewni | > 95% | Walidacja vs. metody referencyjne |
| Dostępność systemu | > 99% | Uptime monitoring |
| Liczba użytkowników/miesiąc | > 20 | Analytics |
| Średnia liczba analiz/użytkownik | > 5 | Analytics |

### 8.2 Metryki Jakościowe

| Metryka | Target | Pomiar |
|---------|--------|--------|
| Satysfakcja użytkowników (NPS) | > 8/10 | Ankiety |
| Łatwość użycia (SUS) | > 75/100 | SUS questionnaire |
| Liczba zgłoszeń błędów | < 5/miesiąc | Issue tracker |
| Czas rozwiązania błędu krytycznego | < 24h | Issue tracker |

### 8.3 Kryteria Akceptacji (Go/No-Go)

**MVP jest gotowy do wdrożenia, gdy:**
- ✅ Wszystkie user stories (MUST HAVE) są zaimplementowane
- ✅ Testy jednostkowe: > 80% pokrycia
- ✅ Testy akceptacyjne: 100% pass rate
- ✅ Wydajność: wszystkie operacje < targetów czasowych
- ✅ Dokumentacja użytkownika: gotowa
- ✅ 3 użytkowników testowych zaakceptowało system

---

## 9. Przykładowe Scenariusze Użycia

### Scenariusz 1: Ocena wpływu inwestycji
> Użytkownik planuje nową osiedlową inwestycję. Chce sprawdzić, czy zwiększenie powierzchni uszczelnionej wpłynie na przepływy maksymalne. Wyznacza zlewnię, zapisuje wyniki, następnie ręcznie zmienia CN (symulując zwiększenie zabudowy) i generuje nowy hydrogram.

### Scenariusz 2: Weryfikacja przekroju mostowego
> Inżynier sprawdza, czy istniejący most jest odpowiedni dla przepływu Q10%. Wyznacza zlewnię powyżej mostu, generuje hydrogram dla p=10%, porównuje Qmax z przepustowością mostu.

### Scenariusz 3: Raport dla urzędu
> Konsultant przygotowuje raport o oddziaływaniu na środowisko. Wyznacza 5 zlewni, dla każdej generuje hydrogram, eksportuje wyniki (CSV + GeoJSON), wkleja do raportu w Word.

---

**Wersja dokumentu:** 1.1
**Data ostatniej aktualizacji:** 2026-03-01
**Status:** Approved — projekt w aktywnym rozwoju (CP4 zakonczone, CP5 MVP w przygotowaniu)  

---

*Ten dokument stanowi podstawę do rozpoczęcia prac nad systemem analizy hydrologicznej. Wszelkie zmiany w wymaganiach muszą być zatwierdzone przez Product Ownera i udokumentowane jako addendum do tego PRD.*
