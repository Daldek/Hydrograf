# SCOPE.md - Zakres Projektu
## System Analizy Hydrologicznej

**Wersja:** 1.0  
**Data:** 2026-01-14  
**Status:** Zatwierdzony

---

## 1. Wprowadzenie

### 1.1 Cel Dokumentu
Ten dokument precyzyjnie definiuje:
- ✅ Co **JEST** w zakresie projektu (In Scope)
- ❌ Co **NIE JEST** w zakresie projektu (Out of Scope)
- ⏳ Co **MOŻE BYĆ** w przyszłości (Future Scope)
- 🔒 Ograniczenia i założenia

### 1.2 Kontekst Biznesowy
**Problem:** Brak dostępnego wewnętrznego narzędzia do szybkich analiz hydrologicznych dla małych zlewni.

**Rozwiązanie:** System webowy wykorzystujący otwarte dane (GIOŚ, GUGIK, PIG, IMGW, RZGW) do wyznaczania zlewni, parametrów i hydrogramów.

**Użytkownicy:** Specjaliści ds. planowania przestrzennego w gminach (bez zaawansowanej wiedzy GIS).

---

## 2. ZAKRES FUNKCJONALNY

### 2.1 ✅ IN SCOPE - Funkcjonalności MVP

#### 2.1.1 FAZA 1: Wyznaczanie Granic Zlewni

**✅ W zakresie:**
- Interaktywna mapa webowa z podkładem OSM
- Wybór punktu przez kliknięcie na mapie
- Automatyczne wykrywanie najbliższego cieku
- Wyznaczanie granicy zlewni metodą traversal grafu
- Wizualizacja granicy na mapie (GeoJSON polygon)
- Eksport granicy jako GeoJSON
- Eksport granicy jako Shapefile
- Czas wykonania: < 10 sekund

**Wymagania techniczne:**
- Dane wejściowe: NMT z GUGIK
- Preprocessing: konwersja NMT → graf w PostGIS
- Algorytm: D8 flow direction + upstream traversal
- Output: GeoJSON FeatureCollection

**Komunikaty błędów:**
- "Nie znaleziono cieku w tym miejscu"
- "Punkt poza obszarem danych"

---

#### 2.1.2 FAZA 2: Parametry Fizjograficzne Zlewni

**✅ W zakresie:**

**Parametry geometryczne:**
- Powierzchnia zlewni [km²]
- Obwód zlewni [km]
- Długość zlewni [km]
- Szerokość zlewni [km]
- Długość głównego cieku [km]

**Charakterystyki geometryczne:**
- Wskaźnik formy C<sub>f</sub>
- Wskaźnik zwartości C<sub>z</sub>
- Wskaźnik kolistości C<sub>k</sub>
- Wskaźnik wydłuenia C<sub>w</sub>
- Wskaźnik lemniskaty C<sub>l</sub>

**Parametry morfometryczne:**
- Wysokość maksymalna zlewni [m n.p.m.]
- Średnia wysokość zlewni [m]
- Wysokość minimalna zlewni [m n.p.m]
- Wielkość deniwelacji [m]
- Spadek zlewni [%]
- Spadek działu wodnego [%]
- Spadek głównego cieku [%]
- Wskaźnik formy zlewni (Strahlera)
- Gęstość sieci rzecznej
- Wskaźnik jeziorności
- Wskaźnik zalesienia
- Wskaźnik rozwinięcia lesistości
- Wskaźnik bagnistości
- Wskaźnik rozwinięcia bagnistości

**Sieć rzeczna (dla danych z MPHP):**
- Klasyfikacja sieci rzecznej wg Hortona
- Klasyfikacja sieci rzecznej wg Strahlera
- Prawo liczby cieków
- Prawo długości cieków
- Prawo powierzchni zlewni
- Liczba węzłów źródłowych
- Całkowita liczba cieków róznego rzędu
- Wskaźnik bifurkacji
- Całkowita długość cieków róznego rzędu
- Wskaźnik średniej długości cieków
- Wskaźnik średniej powierzchni zlewni
- Wskaźnik częstości cieków
- Wskaźnik struktury sieci rzecznej
- Współczynnik rozwinięcia cieku
- Współczynnk krętości rzeki
- Współczynnik rozwinięcia biegu rzeki

**Analiza pokrycia terenu:**
- Integracja z danymi BDOT10k z GUGIK
- Rozkład kategorii pokrycia [%] wg Corine Land Cover.
- Obliczenie ważonego Curve Number (CN)
- Mapowanie CN dla każdej kategorii (zgodnie z USDA NRCS)

**Profil terenu:**
- Profile podłużne cieku (POST /api/terrain-profile) — zaimplementowane w sesji 11

**Prezentacja wyników:**
- Tabela z parametrami w panelu bocznym
- Tooltips wyjaśniające terminy techniczne
- Możliwość kopiowania wartości
- Eksport parametrów jako JSON/CSV

---

#### 2.1.3 FAZA 3: Generowanie Hydrogramów Odpływu

**✅ W zakresie:**

**Scenariusze opadowe:**
- Źródło: Atlas Pmax_PT z IMGW (via API) lub dane pomiarowe
- Czasy trwania: 15min, 30min, 1h, 2h, 6h, 12h, 24h
- Prawdopodobieństwa: 1%, 2%, 5%, 10%, 20%, 50%
- Łącznie: 42 kombinacje (7 × 6)
- Wybór scenariusza przez użytkownika (radio buttons)
- Wyświetlenie wartości opadu dla centroidu zlewni

**Model opad-odpływ:**
- Hietogram: rozkład Beta (α=2, β=5)
- Krok czasowy: 5 minut
- Metoda SCS Curve Number:
  - Retencja maksymalna: S = 25400/CN - 254
  - Initial abstraction: Ia = 0.2 × S
  - Opad efektywny: Pe = (P - Ia)² / (P + 0.8S) gdy P > Ia

**Hydrogram jednostkowy:**
- Metoda: SCS Dimensionless Unit Hydrograph
- Parametry:
  - Czas koncentracji (tc): wzór Kirpicha lub SCS lag
  - Czas do szczytu: tp = 0.6 × tc
  - Przepływ szczytowy: qp = 0.208 × A / tp
  - Czas bazowy: tb = 2.67 × tp

**Transformacja opad → odpływ:**
- Splot dyskretny: Q(t) = Pe(t) ⊗ UH(t)
- Numeryczna implementacja convolution

**Wyniki:**
- Wykres hydrogramu (Chart.js line chart)
- Kluczowe parametry:
  - Qmax [m³/s] - przepływ maksymalny
  - Czas do szczytu [min]
  - Objętość odpływu całkowitego [m³]
  - Współczynnik odpływu [-]
- Eksport szeregu czasowego (CSV):
  - Kolumny: czas [min], przepływ [m³/s]
- Eksport wykresu (PNG - opcjonalnie)

**Założenia modelu:**
- Opad równomierny na całą zlewnię
- Warunki wilgotnościowe: AMC-II (przeciętne)
- Brak routingu w kanale (natychmiastowa agregacja)
- Model SCS-CN dla zlewni niekontrolowanych o powierzchni do 250 km² (ograniczenie metody)

---

### 2.2 ❌ OUT OF SCOPE - Poza Zakresem MVP

#### 2.2.1 Funkcjonalności Zaawansowane

**NIE w MVP:**
- ❌ Routing przepływu w sieci rzecznej
- ❌ Modelowanie retencji zbiorników/stawów
- ❌ Symulacja powodziowa (mapy zalewowe)
- ❌ Modelowanie transportu rumowiska
- ❌ Modelowanie jakości wody
- ❌ Analiza erozji i sedymentacji
- ❌ Symulacje długoterminowe (seria czasowa)
- ❌ Modelowanie topnienia śniegu
- ❌ Infiltracja szczegółowa (Green-Ampt)
- ❌ Modelowanie wód podziemnych

#### 2.2.2 Analiza Wieloscenariuszowa

**NIE w MVP:**
- ❌ Porównanie wielu scenariuszy opadowych jednocześnie
- ❌ Analiza wrażliwości parametrów (Monte Carlo)
- ❌ Przedziały ufności wyników
- ❌ Scenariusze "what-if" (zmiana użytkowania terenu)
- ❌ Optymalizacja parametrów modelu (kalibracja)
- ❌ Walidacja względem pomiarów terenowych

#### 2.2.3 Wizualizacje 3D i Zaawansowane

**NIE w MVP:**
- ❌ Wizualizacja 3D terenu
- ❌ Animacja przepływu wody
- ❌ Heatmapy intensywności opadu
- ❌ Mapy głębokości zalewu
- ❌ Przekroje poprzeczne

> **Uwaga:** Profile podłużne cieku (`POST /api/terrain-profile`) — pierwotnie w tej sekcji. Zaimplementowane w sesji 11 — przeniesione do zakresu MVP (sekcja 2.1.2).

#### 2.2.4 Integracje i Dane Real-Time

**NIE w MVP:**
- ❌ Integracja z danymi IMGW real-time (opady, stany wód)
- ❌ Prognoza pogodowa jako input
- ❌ Integracja z systemami GIS (QGIS, ArcGIS)
- ❌ Import własnych danych użytkownika (shapefiles, rasters)
- ❌ Połączenie z bazami danych zewnętrznymi
- ❌ API publiczne dla innych systemów

#### 2.2.5 Funkcjonalności Użytkownika

**NIE w MVP:**
- ❌ System kont użytkowników (rejestracja, login)
- ❌ Zapisywanie analiz do profilu użytkownika
- ❌ Historia analiz
- ❌ Współpraca wieloużytkownikowa (sharing, comments)
- ❌ Role i uprawnienia (admin, user, viewer)
- ❌ Powiadomienia email/SMS o zakończeniu analizy

#### 2.2.6 Raporty i Eksporty

**NIE w MVP:**
- ❌ Generowanie jakichkolwiek raportów

#### 2.2.7 Interfejsy Alternatywne

**NIE w MVP:**
- ❌ Aplikacja mobilna
- ❌ Aplikacja desktopowa
- ❌ CLI (command-line interface)

---

### 2.3 ⏳ FUTURE SCOPE - Planowane na Przyszłość

#### Roadmap Post-MVP

- 📊 Eksport raportów PDF (z mapą, wykresami, parametrami)
- 📈 Analiza wieloscenariuszowa (porównanie Q1%, Q10%, Q50%)
- 🎨 Konfigurowalne mapy (wybór podkładu)
- 🔗 API publiczne (REST, dokumentacja OpenAPI)
- 🧪 Moduł kalibracji (porównanie z pomiarami)
- 🎯 Optymalizacja parametrów

---

## 3. ZAKRES DANYCH

### 3.1 ✅ Dane Wejściowe - W Zakresie

#### 3.1.1 Numeryczny Model Terenu (NMT)

**Źródło:** GUGIK - Geoportal  
**Format:** ARC/INFO ASCII GRID 
**Rozdzielczość:** >=1m
**Układ współrzędnych:** EPSG:2180 (PL-1992)  
**Zakres przestrzenny:** Obszar gminy powiększony o granice zlewni wybranego rzędu (z MPHP) i bufor
**Aktualizacja:** Raz, przy setupie systemu (lub na zadanie po aktualizacji NMT)

**Preprocessing:**
- Wypełnienie depresji (sink filling)
- Obliczenie kierunków spływu (D8)
- Obliczenie akumulacji przepływu
- Obliczenie długiści spływu
- Obliczenie nachylenia
- Wektoryzacja → graf w PostGIS
- Identyfikacja cieków (próg akumulacji od 2 komórek)

#### 3.1.2 Pokrycie Terenu

**Źródła:** GIOŚ - Corine Land Cover, GUGIK - BDOT10k
**Format:** Shapefile / GeoPackage
**Układ współrzędnych:** EPSG:2180  
**Zakres:** Obszar gminy  
**Aktualizacja:** Raz na kwartał (lub na zadanie)

**Kategorie (minimum):**
- Wody powierzchniowe
- Trawniki, parki
- Drogi i parkingi
- Zabudowa przemysłowa/usługowa
- Zabudowa mieszkaniowa
- Grunty orne
- Łąki i pastwiska
- Lasy 

**Preprocessing:**
- Import do PostGIS (tabela `land_cover`)
- Przypisanie wartości CN dla każdej kategorii
- Generalizacja (opcjonalnie dla wydajności)

#### 3.1.3 Osie Cieków

**Źródło:** MPHP (Mapa Podziału Hydrograficznego Polski) 
**Format:** Shapefile, Geopackage lub Geobaza 
**Atrybuty:**
- Nazwa cieku
- Rząd Strahlera (opcjonalnie)
- Długość [m]

**Preprocessing:**
- Import do PostGIS (tabela `stream_network`)
- Walidacja topologii
- Obliczenie długości

#### 3.1.4 Dane Opadowe

**Źródło:** IMGW - Atlas Pmax_PT lub dane historyczne dla stacji meteorologicznych
**Dostęp:** IMGWTools
**Format:** Do ustalenia (prawdopodobnie punkty lub siatka)  
**Zakres przestrzenny:** Polska  
**Parametry:**
- Czas trwania: 15min, 30min, 1h, 2h, 6h, 12h, 24h
- Prawdopodobieństwo: 1%, 2%, 5%, 10%, 20%, 50%
- Wartość: opad [mm]

**Preprocessing:**
- Pobranie wszystkich kombinacji (42 zestawy danych)
- Import do PostGIS (tabela `pmax_pt_data`)
- Indeksowanie przestrzenne (GIST)

**Aktualizacja:** Raz na rok (lub gdy IMGW publikuje nowe dane)

---

### 3.2 ❌ Dane Poza Zakresem MVP

**NIE w MVP:**
- ❌ Dane pomiarowe z posterunków wodowskazowych
- ❌ Prognozy pogodowe
- ❌ Dane o zbiornikach retencyjnych
- ❌ Dane o przepustowości mostów/przepustów
- ❌ Dane geologiczne (przepuszczalność gruntów)
- ❌ Dane o użytkowaniu historycznym (zmiany w czasie)
- ❌ Dane satelitarne (Sentinel, Landsat)
- ❌ LiDAR (chmury punktów)
- ❌ Dane katasterowe
- ❌ Ortofotomapy wysokiej rozdzielczości

---

### 3.3 Format Danych Wyjściowych

**✅ W zakresie:**
- GeoJSON (granica zlewni, główny ciek)
- Shapefile (granica zlewni)
- CSV (parametry zlewni, hydrogram)
- JSON (pełne dane API response)

**❌ Poza zakresem:**
- GeoPackage
- KML/KMZ
- DWG/DXF
- GeoTIFF (rastry wynikowe)
- NetCDF
- HDF5

---

## 4. ZAKRES GEOGRAFICZNY

### 4.1 ✅ Obszar Objęty Systemem

**Zasięg przestrzenny:**
- **Obszar bazowy:** Do wyboru przez użytkownika podczas setupu
- **Powierzchnia:** typowo 50-200 km²
- **Bufor:** +1 km poza granice gminy

**Limity:**
- **Minimalna powierzchnia:** 2 koórki rastra NMT

**Układ współrzędnych:**
- **Wewnętrzny:** EPSG:2180 (PL-1992)
- **Frontend (mapa):** EPSG:4326 (WGS84) - automatyczna transformacja
- **API input/output:** WGS84 (lat/lon)

---

### 4.2 ❌ Obszary Poza Zakresem

**NIE w MVP:**
- ❌ Obszary poza Polską
- ❌ Dynamiczne dodawanie nowych obszarów przez użytkownika
- ~~❌ Obszary górskie > 1500 m n.p.m. (ograniczenia modelu SCS)~~

---

## 5. ZAKRES TECHNICZNY

### 5.1 ✅ Technologie i Narzędzia

#### Backend
**Język:** Python 3.12+  
**Framework:** FastAPI  
**Baza danych:** PostgreSQL 15+ z PostGIS 3.3+  
**Biblioteki:**
- GeoPandas, Shapely (operacje przestrzenne)
- Rasterio, GDAL (preprocessing rastrów)
- NumPy, SciPy (obliczenia numeryczne)
- WhiteboxTools (analiza hydrologiczna)
- Pydantic (walidacja danych)
- SQLAlchemy (ORM)

#### Frontend
**Języki:** HTML5, CSS3, JavaScript (ES6+)  
**Mapa:** Leaflet.js 1.9+  
**Wykresy:** Chart.js 4.0+  
**UI Framework:** Bootstrap 5  
**Podkład mapy:** OpenStreetMap, ESRI Satellite, OpenTopoMap, GUGiK WMTS (ortofoto + topo)

#### Infrastruktura
**Konteneryzacja:** Docker + Docker Compose  
**Reverse Proxy:** Nginx  
**Serwer:** Własny (domowy) - Debian 13
**CI/CD:** GitHub Actions (lub GitLab CI)  
**Monitoring:** Prometheus + Grafana (opcjonalnie)

---

### 5.2 ❌ Technologie Poza Zakresem

**NIE w MVP:**
- ❌ Kubernetes / orchestration
- ❌ Cloud hosting (AWS, Azure, GCP)
- ❌ Message queue (RabbitMQ, Kafka)
- ❌ Caching layer (Redis, Memcached)
- ❌ Load balancer
- ❌ CDN
- ❌ Elasticsearch (wyszukiwanie)
- ❌ Microservices architecture
- ❌ GraphQL
- ❌ WebSockets (real-time updates)
- ❌ Server-Side Rendering (SSR)
- ❌ Progressive Web App (PWA)

---

## 6. ZAKRES WYDAJNOŚCIOWY

### 6.1 ✅ Gwarantowane SLA (Service Level Agreement)

**Czas odpowiedzi API:**
- Wyznaczenie zlewni: **< 10 sekund** (95th percentile)
- Parametry fizjograficzne: **< 2 sekundy**
- Generowanie hydrogramu: **< 5 sekund**
- Ładowanie mapy: **< 2 sekundy**

**Throughput:**
- Równoczesnych użytkowników: **10** (MVP)
- Requestów na minutę: **50**

**Dostępność:**
- Uptime: **99%** (dopuszczalny downtime: ~7h/miesiąc)
- Planned maintenance: max 2h/tydzień (w godzinach nocnych)

**Limity danych:**
- Timeout API: **30 sekund**

---

### 6.2 ❌ Poza Gwarancją

**NIE gwarantowane w MVP:**
- ❌ Obsługa > 10 równoczesnych użytkowników
- ❌ Czas odpowiedzi < 1s dla wszystkich operacji
- ❌ 99.9% uptime (three nines)
- ❌ Horizontal scaling
- ❌ Disaster recovery < 1h
- ❌ Backups real-time (tylko daily)

---

## 7. OGRANICZENIA I ZAŁOŻENIA

### 7.1 Ograniczenia Techniczne

**Preprocessing:**
- ⚠️ **Jednorazowy preprocessing NMT:** 1-2 dni pracy
- ⚠️ **Wymaga serwera:** minimum 8 GB RAM, 100 GB dysku

**Model hydrologiczny:**
- ⚠️ **Model SCS CN:** Dla zlewni < 250 km²
- ⚠️ **Opad równomierny:** Uproszczenie dla małych zlewni
- ⚠️ **Brak routingu:** Hydrogram dla przekroju zamykającego
- ⚠️ **Warunki AMC-II:** Przeciętne warunki wilgotnościowe

**Dane:**
- ⚠️ **Jakość NMT:** Zależna od GUGIK (artefakty możliwe)
- ⚠️ **Aktualność danych:** Pokrycie terenu może być nieaktualne

---

### 7.2 Założenia Biznesowe

**Użytkownicy:**
- ✓ Mają dostęp do komputera z przeglądarką (Chrome, Firefox, Edge)
- ✓ Rozdzielczość ekranu: minimum 1280 × 720 px
- ✓ Podstawowa znajomość map i GIS
- ✓ Rozumienie pojęć hydrologicznych (lub chęć nauczenia się)

**Środowisko:**
- ✓ Sieć wewnętrzna (LAN) - brak dostępu z internetu (MVP)
- ✓ Stabilne połączenie sieciowe (10 Mbps)
- ✓ Serwer działa 24/7 (z wyjątkiem maintenance)

**Wsparcie:**
- ✓ Dokumentacja użytkownika w języku polskim

---

### 7.3 Założenia Prawne i Licencyjne

**Dane:**
- ✓ Dane GUGIK: Licencja otwarta (użytek niekomercyjny OK)
- ✓ Dane IMGW: Do weryfikacji (API terms of service)
- ✓ OpenStreetMap: ODbL license (attribution required)

**Kod:**
- ✓ Kod źródłowy: Proprietary (własność organizacji)
- ✓ Biblioteki open-source: Zgodność z licencjami (MIT, BSD, Apache)

**Odpowiedzialność:**
- ⚠️ System jest narzędziem wspomagającym decyzje
- ⚠️ Użytkownik odpowiada za interpretację wyników
- ⚠️ Brak gwarancji 100% dokładności (zależność od danych wejściowych)

---

## 8. KRYTERIA SUKCESU

### 8.1 Definicja "Done" dla MVP

**Funkcjonalnie:**
- ✅ Wszystkie user stories (MUST HAVE) z PRD.md zaimplementowane
- ✅ System wyznacza zlewnie dla 95%+ kliknięć na cieki
- ✅ Generuje hydrogram dla wszystkich 42 scenariuszy

**Jakościowo:**
- ✅ Testy jednostkowe: > 80% pokrycia
- ✅ Testy E2E: 100% critical paths pass
- ✅ Code review: wszystkie PR zaapprowane
- ✅ Dokumentacja: kompletna (user + tech docs)

**Wydajnościowo:**
- ✅ 95% requestów < targetów czasowych (10s, 5s, 2s)
- ✅ System stabilny dla 10 równoczesnych użytkowników
- ✅ Brak critical bugs w production przez 1 tydzień

**Akceptacja:**
- ✅ 3 użytkowników testowych zaakceptowało system (UAT)
- ✅ Product Owner zaakceptował MVP

---

### 8.2 Metryki Sukcesu Post-Launch

**Satysfakcja:**
- 🎯 < 5 zgłoszeń błędów krytycznych/miesiąc

**Wydajność:**
- 🎯 Średni czas odpowiedzi < 5s
- 🎯 Brak timeoutów > 1% requestów

---

## 9. DEPENDENCIES - Zależności

### 9.1 Zależności Zewnętrzne

**Dane:**
- 🔗 **GUGIK Geoportal:** Dostępność danych NMT i BDOT10k
- 🔗 **IMGW:** Działające API lub dostępność danych historycznych
- 🔗 **OpenStreetMap:** Podkład mapy

**Infrastruktura:**
- 🔗 **Serwer fizyczny:** Dostępność i działanie
- 🔗 **Połączenie internetowe:** Dla dostępu do API i map

**Zespół:**
- 🔗 **Backend Developer:** Dostępność full-time
- 🔗 **Frontend Developer:** Dostępność full-time
- 🔗 **GIS Specialist:** Dostępność part-time dla preprocessingu

---

### 9.2 Zależności Wewnętrzne (Między Fazami)

```
FAZA 0: Preprocessing
   ↓ (dane w PostGIS)
FAZA 1: Wyznaczanie zlewni
   ↓ (boundary GeoJSON)
FAZA 2: Parametry fizjograficzne
   ↓ (CN, tc)
FAZA 3: Generowanie hydrogramów
```

**Blokery:**
- ⚠️ Faza 1 wymaga zakończenia Fazy 0 (preprocessing)
- ⚠️ Faza 2 wymaga działającej Fazy 1 (granica zlewni)
- ⚠️ Faza 3 wymaga Fazy 2 (CN, parametry morfometryczne)

---

## 10. RISKS & MITIGATION - Ryzyka

### 10.1 Wysokie Ryzyko

**Ryzyko 1: Niedostępność IMGW**
- **Prawdopodobieństwo:** Niskie
- **Wpływ:** Wysoki (brak danych = brak hydrogramów)
- **Mitigacja:**
  - Plan A: Jednorazowe pobranie i lokalne przechowywanie
  - Plan B: Wartości z literatury (wartości typowe dla regionu)

**Ryzyko 2: Jakość danych NMT**
- **Prawdopodobieństwo:** Średnie
- **Wpływ:** Wysoki (błędne granice zlewni)
- **Mitigacja:**
  - Walidacja wizualna po preprocessingu
  - Porównanie z danymi referencyjnymi (topomapa, ortofoto)
  - Dokumentacja ograniczeń dla użytkownika
  - Możliwość ręcznej korekty (future scope)

---

### 10.2 Średnie Ryzyko

**Ryzyko 3: Wydajność dla dużych zlewni**
- **Prawdopodobieństwo:** Wysokie
- **Wpływ:** Średni (czas > 10s dla zlewni > 200 km²)
- **Mitigacja:**
  - Optymalizacja algorytmów (early termination)
  - Indeksy w bazie danych
- **Uwaga:** Dla zlewni > 250 km² hydrogram SCS-CN niedostępny (ograniczenie metody)

**Ryzyko 4: Brak doświadczenia użytkowników**
- **Prawdopodobieństwo:** Średnie
- **Wpływ:** Średni (nieprawidłowe użycie systemu)
- **Mitigacja:**
  - Intuicyjny interfejs (user testing)
  - Tooltips i help text
  - Dokumentacja użytkownika z przykładami
  - Webinary/szkolenia po wdrożeniu

---

### 10.3 Niskie Ryzyko

**Ryzyko 5: Awaria serwera**
- **Prawdopodobieństwo:** Niskie
- **Wpływ:** Wysoki (downtime)
- **Mitigacja:**
  - Daily backups
  - Monitoring (Prometheus + alerting)
  - Procedura recovery (< 4h)
  - Plan migracji na VPS (jeśli serwer domowy zawodzi)

---

## 11. ACCEPTANCE CRITERIA - Kryteria Akceptacji MVP

### 11.1 Funkcjonalne (Must Pass)

- ✅ **F1:** Użytkownik może kliknąć punkt na mapie i zobaczyć granicę zlewni w < 10s
- ✅ **F2:** System wyświetla parametry fizjograficznych zlewni
- ✅ **F3:** Użytkownik może wybrać jeden z 42 scenariuszy opadowych
- ✅ **F4:** System generuje hydrogram w < 5s i wyświetla wykres
- ✅ **F5:** Użytkownik może eksportować granicę jako GeoJSON/Shapefile
- ✅ **F6:** Użytkownik może eksportować hydrogram jako CSV
- ✅ **F7:** System wyświetla komunikaty błędów dla przypadków edge (brak cieku lub poza obszarem)

### 11.2 Niefunkcjonalne (Must Pass)

- ✅ **NF1:** System działa w Chrome, Firefox, Edge (latest versions)
- ✅ **NF2:** Responsywność UI < 100ms dla interakcji
- ✅ **NF3:** Pokrycie testami > 80%
- ✅ **NF4:** Dokumentacja użytkownika kompletna (setup, usage, troubleshooting)
- ✅ **NF5:** Dokumentacja techniczna kompletna (architecture, API, deployment)
- ✅ **NF6:** Brak SQL injection vulnerabilities (security audit)
- ✅ **NF7:** Uptime > 99% w pierwszym tygodniu produkcyjnym

### 11.3 User Acceptance Testing (UAT)

**Scenariusze testowe:**
1. Nowy użytkownik może wykonać pełną analizę (zlewnia → hydrogram) bez pomocy w < 5 minut
2. Użytkownik może wyeksportować wyniki i użyć ich w innym narzędziu (QGIS)
3. Komunikaty błędów są zrozumiałe i pomocne

**Akceptacja:**
- Minimum 3 użytkowników testowych musi zaakceptować system (ocena ≥ 4/5)
- Product Owner musi zaakceptować wszystkie funkcjonalności
- Zero critical bugs w UAT

---

## 12. HANDOFF CRITERIA - Kryteria Przekazania

### 12.1 Do Produkcji

**Code:**
- ✅ Wszystkie PR zmergowane do `main`
- ✅ Tagi wersji (semantic versioning): `v1.0.0`
- ✅ CHANGELOG.md zaktualizowany

**Deployment:**
- ✅ Docker images zbudowane i przetestowane
- ✅ docker-compose.yml gotowy na produkcję
- ✅ Zmienne środowiskowe (.env) skonfigurowane
- ✅ Nginx jako reverse proxy
- ✅ HTTPS skonfigurowane (Certbot)

**Database:**
- ✅ Preprocessing zakończony
- ✅ Backup strategy skonfigurowany (cron job)
- ✅ Database migrations applied

**Monitoring:**
- ✅ Logi aplikacji działają
- ✅ Health check endpoint: `/health`
- ✅ Prometheus metrics exposed (opcjonalnie)

**Documentation:**
- ✅ README.md z instrukcjami deploymentu
- ✅ User manual (PL) dostępny
- ✅ API documentation (Swagger/OpenAPI)
- ✅ Runbook dla operacji (restart, backup, restore)

---

### 12.2 Do Utrzymania (Maintenance)

**Przekazanie zespołowi utrzymaniowemu:**
- 📋 Lista znanych limitacji i workarounds
- 📋 Kontakty do deweloperów (email, Slack)

**Monitoring i Alerty:**
- 🔔 Alert: Downtime > 5 minut
- 🔔 Alert: Czas odpowiedzi > 30s
- 🔔 Alert: Disk usage > 80%
- 🔔 Alert: Database connection failures

---

## 13. OUT OF SCOPE - Podsumowanie

### Co Definitywnie NIE JEST w MVP:

**Funkcjonalności:**
- ❌ Routing, modelowanie retencji, mapy zalewowe
- ❌ Analiza wieloscenariuszowa, kalibracja
- ❌ Wizualizacje 3D, animacje
- ❌ Integracje real-time, API publiczne

**Użytkownicy:**
- ❌ System kont, historia, współpraca
- ❌ Role i uprawnienia
- ❌ Powiadomienia, newslettery

**Dane:**
- ❌ Pomiary terenowe, prognozy, dane satelitarne
- ❌ Multiple regiony, import własnych danych

**Technologia:**
- ❌ Cloud hosting, Kubernetes, microservices
- ❌ Aplikacje mobilne, CLI, GraphQL

**Raporty:**
- ❌ PDF generation, szablony, batch export

---

## 14. CHANGE MANAGEMENT

### 14.1 Jak Zmienić Zakres?

**Proces:**
1. **Propozycja:** Issue na GitHubie/GitLabie z tagiem `scope-change`
2. **Analiza:** Ocena wpływu (czas, zasoby, ryzyko)
3. **Dyskusja:** Zespół + Product Owner
4. **Decyzja:** Go/No-Go
5. **Dokumentacja:** Update SCOPE.md + PRD.md + CHANGELOG.md

**Kryteria akceptacji zmiany:**
- ✅ Uzasadnienie biznesowe
- ✅ Oszacowanie nakładu pracy (story points)
- ✅ Brak konfliktu z istniejącym zakresem
- ✅ Akceptacja Product Ownera
- ✅ Dostępne zasoby (czas, ludzie)

---

### 14.2 Scope Creep Prevention

**Zasady:**
- 🛑 **Żadnych nowych funkcji bez dokumentacji w SCOPE.md**
- 🛑 **Nie "tylko szybkie dodanie X"** - zawsze przez proces change management
- 🛑 **MVP = Minimum Viable Product** - oprzeć się pokusie "nice to have"
- ✅ **Feature requests → backlog** (nie do MVP)
- ✅ **Re-priorytetyzacja co 2 tygodnie** (sprint planning)

---

## 15. GLOSSARY

| Termin | Definicja |
|--------|-----------|
| **MVP** | Minimum Viable Product - podstawowa wersja z kluczowymi funkcjami |
| **In Scope** | Funkcjonalność/element objęty zakresem projektu |
| **Out of Scope** | Funkcjonalność/element poza zakresem projektu |
| **Future Scope** | Funkcjonalność planowana na przyszłość (post-MVP) |
| **SLA** | Service Level Agreement - gwarantowany poziom usług |
| **UAT** | User Acceptance Testing - testy akceptacyjne użytkownika |
| **NMT** | Numeryczny Model Terenu |
| **CN** | Curve Number - parametr spływu powierzchniowego |
| **SCS** | Soil Conservation Service - metoda hydrologiczna |
| **Pmax_PT** | Maksymalne opady o określonym prawdopodobieństwie i czasie trwania |

---

**Wersja dokumentu:** 1.0  
**Data ostatniej aktualizacji:** 2026-02-22
**Wersja biezaca:** v0.4.0 (CP4)
**Planowana wersja MVP:** v1.0.0 (CP5)
**Status:** Zatwierdzony — projekt w aktywnym rozwoju

---

*Ten dokument definiuje zakres projektu MVP. Wszelkie zmiany wymagają formalnego procesu change management i aktualizacji tego dokumentu.*
