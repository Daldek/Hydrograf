# SCOPE.md - Zakres Projektu
## System Analizy Hydrologicznej

**Wersja:** 1.2
**Data:** 2026-03-25
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
- Interaktywna mapa webowa z podkładami: OSM, ESRI Satellite, OpenTopoMap, GUGiK WMTS (ortofoto + topo)
- Wybór punktu przez kliknięcie na mapie (tryb rysowania poligonu + tryb wyboru obiektow)
- Automatyczne wykrywanie najbliższego cieku (snap-to-stream ST_Distance + fallback ST_Contains)
- Wyznaczanie granicy zlewni metodą BFS na grafie in-memory (CatchmentGraph)
- Wygladzanie granic zlewni: `ST_SimplifyPreserveTopology` + `ST_ChaikinSmoothing` (ADR-032)
- Podniesienie budynkow w NMT (+5m pod obrysami BUBD z BDOT10k, ADR-033)
- Wizualizacja granicy na mapie (GeoJSON polygon)
- Eksport granicy jako GeoJSON
- Eksport granicy jako Shapefile
- Czas wykonania: < 10 sekund
- Selekcja segmentu cieku z upstream traversal (POST `/api/select-stream`)

**Wymagania techniczne:**
- Dane wejściowe: NMT z GUGIK (rozdzielczość 5m, pobieranie przez Kartograf)
- Preprocessing: pyflwdir (D8 flow direction) → wektoryzacja → PostGIS + CatchmentGraph in-memory
- Algorytm: D8 flow direction + BFS upstream traversal na CatchmentGraph
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
- Długość hydrauliczna zlewni (hydraulic_length_km) [km]
- Rzeczywista długość cieku głównego (real_channel_length_km) [km]
- Sciezki splywu (flow paths): najdluzsza, od dzialu wodnego, od centroidu [km]
- Wazona nieprzepuszczalnosc (weighted_imperviousness) [-]

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
- Integracja z danymi BDOT10k z GUGIK (import do PostGIS, 8 kategorii)
- Rozkład kategorii pokrycia [%] wg Corine Land Cover
- Obliczenie ważonego Curve Number (CN) z uwzglednieniem HSG (Hydrologic Soil Group)
- Mapowanie CN dla każdej kategorii (zgodnie z USDA NRCS)
- Warstwa tematyczna MVT: `/api/tiles/landcover/{z}/{x}/{y}.pbf` z kolorowaniem wg kategorii

**Profil terenu:**
- Profile podłużne cieku (POST /api/terrain-profile)

**Zaglebienia terenu:**
- Endpoint GET `/api/depressions` z filtrami (area, depth)
- Wizualizacja depresji jako overlay na mapie

**Kafelki wektorowe (MVT):**
- Cieki: GET `/api/tiles/streams/{z}/{x}/{y}.pbf` (filtr wg progu FA, styl wg rzedu Strahlera)
- Zlewnie czastkowe: GET `/api/tiles/catchments/{z}/{x}/{y}.pbf`
- Pokrycie terenu: GET `/api/tiles/landcover/{z}/{x}/{y}.pbf`
- Dostepne progi: GET `/api/tiles/thresholds`

**Kafelki rastrowe DEM:**
- Piramida XYZ (zoom 8-16) z multi-directional hillshade (4 kierunki oswietlenia)

**Prezentacja wyników:**
- Glassmorphism panel boczny (draggable, floating)
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

**Czas koncentracji (tc):**
- Wzór Kirpicha
- Wzór NRCS (SCS lag)
- Wzór Giandottiego
- Wzór FAA (Federal Aviation Administration)
- Wzór Kerby'ego
- Wzór Kerby-Kirpicha (zlozony)

**Model opad-odpływ:**
- Hietogram: rozkład Beta (α=2, β=5)
- Krok czasowy: 5 minut
- Metoda SCS Curve Number:
  - Retencja maksymalna: S = 25400/CN - 254
  - Initial abstraction: Ia = 0.2 × S
  - Opad efektywny: Pe = (P - Ia)² / (P + 0.8S) gdy P > Ia

**Hydrogram jednostkowy:**
- Metoda SCS Dimensionless Unit Hydrograph:
  - Czas do szczytu: tp = 0.6 × tc
  - Przepływ szczytowy: qp = 0.208 × A / tp
  - Czas bazowy: tb = 2.67 × tp
- Metoda Nash IUH (Instantaneous Unit Hydrograph):
  - Estymacja parametrow: from_lutz, from_urban_regression
  - Estymacja from_tc (deprecated)
- Metoda Snyder UH:
  - Parametry: ct (wspolczynnik opoznienia), cp (wspolczynnik szczytowy)
- Typy hietogramu: Beta, Block, Euler II

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

#### 2.1.4 Panel Administracyjny (ADR-034)

**✅ W zakresie:**
- Strona `/admin` z uwierzytelnianiem API key (header X-Admin-Key)
- Dashboard: status systemu, liczby rekordow w 6 tabelach, zuzycie dysku
- Monitorowanie zasobow: CPU/RAM (psutil), pool DB, CatchmentGraph cache, rozmiar bazy
- Uruchamianie bootstrap pipeline z panelu + real-time logi (SSE)
- Czyszczenie danych: tiles, overlays, dem_mosaic, TRUNCATE tabel
- 8 endpointow API `/api/admin/*`

---

#### 2.1.5 Konfiguracja Pipeline (YAML)

**✅ W zakresie:**
- Plik `config.yaml` do konfiguracji pipeline (database, DEM, paths, steps, custom sources)
- Flaga `--config` w `bootstrap.py`
- Flaga `--waterbody-mode` (3 tryby: auto, none, custom) do sterowania obsluga zbiornikow wodnych (ADR-031)
- Selektor rozdzielczosci NMT w panelu admin (5m / 1m)
- Flaga `--waterbody-mode` rowniez dostepna z poziomu panelu admin

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
- ❌ Role i uprawnienia (admin, user, viewer) — uwaga: prosty admin API key auth jest zaimplementowany (ADR-034), ale nie jest to pelny system rol
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
- ~~🎨 Konfigurowalne mapy (wybór podkładu)~~ — **ZREALIZOWANE** (CP4: OSM, ESRI, OpenTopoMap, GUGiK WMTS)
- ~~🔗 API publiczne (REST, dokumentacja OpenAPI)~~ — **CZESCIOWO ZREALIZOWANE** (dokumentacja OpenAPI/Swagger dostepna pod `/docs`)
- ~~🔬 Nash IUH / Snyder UH~~ — **ZREALIZOWANE** (CP5: 3 modele UH z selektorem)
- ~~🗺️ BDOT stream matching~~ — **ZREALIZOWANE** (ADR-044: dopasowanie ciekow NMT do BDOT10k)
- ~~📐 Flow paths (longest/divide/centroid)~~ — **ZREALIZOWANE** (CP5: sciezki splywu w parametrach)
- ~~✨ Chaikin smoothing granic~~ — **ZREALIZOWANE** (ADR-032: ST_ChaikinSmoothing)
- ~~🏛️ WFS TERYT~~ — **ZREALIZOWANE** (CP5: integracja z rejestrem TERYT)
- ~~🔍 DEM auto-discovery~~ — **ZREALIZOWANE** (CP5: automatyczne wykrywanie arkuszy NMT)
- 🧪 Moduł kalibracji (porównanie z pomiarami)
- 🎯 Optymalizacja parametrów
- 🔄 Podwojna analiza NMT (z/bez obszarow bezodplywowych) — backlog

---

## 3. ZAKRES DANYCH

### 3.1 ✅ Dane Wejściowe - W Zakresie

#### 3.1.1 Numeryczny Model Terenu (NMT)

**Źródło:** GUGIK via Kartograf v0.6.1 (automatyczne pobieranie arkuszy NMT)
**Format:** ARC/INFO ASCII GRID → mozaika VRT
**Rozdzielczość:** 5m (konfigurowane w Kartograf `GugikProvider(resolution="5m")`)
**Układ współrzędnych:** EPSG:2180 (PL-1992)
**Zakres przestrzenny:** Bbox definiowany przy setupie (np. `16.9279,52.3729,17.3825,52.5870`)
**Aktualizacja:** Raz, przy setupie systemu (lub na zadanie po aktualizacji NMT)

**Preprocessing (pyflwdir):**
- Podniesienie budynkow w NMT (+5m pod BUBD z BDOT10k, ADR-033)
- Klasyfikacja zbiornikow wodnych (waterbody-mode: auto/none/custom, ADR-031)
- Wypełnienie depresji (sink filling)
- Obliczenie kierunków spływu (D8)
- Obliczenie akumulacji przepływu
- Obliczenie nachylenia
- Wektoryzacja ciekow (progi FA: 1000, 10000, 100000 m²) → PostGIS `stream_network`
- Wektoryzacja zlewni czastkowych → PostGIS `stream_catchments`
- Budowa grafu in-memory (CatchmentGraph, ~44k nodow, ~0.5 MB)
- Generowanie overlayow: DEM hillshade (PNG + piramida XYZ), streams overlay
- Generowanie kafelkow MVT (tippecanoe)

#### 3.1.2 Pokrycie Terenu

**Źródła:** GUGIK - BDOT10k (via Kartograf v0.6.1, automatyczne pobieranie wg powiatow)
**Format:** GeoPackage
**Układ współrzędnych:** EPSG:2180
**Zakres:** Powiaty pokrywajace bbox
**Aktualizacja:** Raz na kwartał (lub na zadanie)

**Kategorie (8):**
- Wody powierzchniowe
- Trawniki, parki
- Drogi i parkingi
- Zabudowa przemysłowa/usługowa
- Zabudowa mieszkaniowa
- Grunty orne
- Łąki i pastwiska
- Lasy

**Preprocessing:**
- Import do PostGIS (tabela `land_cover`, ~112k obiektow)
- Mapowanie klas BDOT10k na kategorie CN (`cn_tables.py`)
- Przypisanie wartości CN dla każdej kategorii z uwzglednieniem HSG
- Serwowanie jako MVT (`/api/tiles/landcover/`)

#### 3.1.3 Siec Ciekow

**Źródło:** Generowana automatycznie z NMT (progi flow accumulation: 1000, 10000, 100000 m²)
**Format:** PostGIS (tabela `stream_network`)
**Atrybuty:**
- Rząd Strahlera
- Długość [m]
- Upstream area [km²]
- Segment index (1-based per threshold)
- Threshold [m²]

**Dopasowanie do BDOT10k (ADR-044):**
- Matching ciekow NMT z ciekami referencyjnymi BDOT10k
- Tabela `bdot_streams` — cieki referencyjne z BDOT10k
- Nadawanie nazw cieków na podstawie dopasowania geometrycznego

**Preprocessing:**
- Wektoryzacja ciekow z rastra flow accumulation (pyflwdir)
- Rozbicie na segmenty w konfluencjach i zmianach rzedu Strahlera
- Uproszczenie geometrii (`simplify_tol = 2*cellsize`)
- Import do PostGIS z indeksami przestrzennymi
- Serwowanie jako MVT (`/api/tiles/streams/`)

#### 3.1.4 Dane Opadowe

**Źródło:** IMGW - Atlas Pmax_PT via IMGWTools v2.1.0
**Format:** Punkty stacji meteorologicznych
**Zakres przestrzenny:** Stacje w obrebie bbox (~192 stacji)
**Parametry:**
- Czas trwania: 15min, 30min, 1h, 2h, 6h, 12h, 24h
- Prawdopodobieństwo: 1%, 2%, 5%, 10%, 20%, 50%
- Wartość: opad [mm]

**Preprocessing:**
- Pobranie wszystkich kombinacji (42 zestawy danych × ~192 stacji = ~8064 rekordow)
- Import do PostGIS (tabela `precipitation_data`)
- Indeksowanie przestrzenne (GIST)
- Interpolacja dla centroidu zlewni w runtime

**Aktualizacja:** Raz na rok (lub gdy IMGW publikuje nowe dane)

#### 3.1.5 Dane Glebowe (HSG)

**Źródło:** PIG (Panstwowy Instytut Geologiczny) via Kartograf v0.6.1
**Format:** GeoPackage → raster → PostGIS (tabela `soil_hsg`)
**Atrybuty:** Hydrologic Soil Group (A/B/C/D)
**Preprocessing:**
- Rasteryzacja na siatke NMT
- Nearest-neighbor fill brakujacych pikseli (distance_transform_edt)
- Poligonizacja → import do PostGIS (~197 poligonow)

---

### 3.2 ❌ Dane Poza Zakresem MVP

**NIE w MVP:**
- ❌ Dane pomiarowe z posterunków wodowskazowych
- ❌ Prognozy pogodowe
- ❌ Dane o zbiornikach retencyjnych
- ❌ Dane o przepustowości mostów/przepustów
- ~~❌ Dane geologiczne (przepuszczalność gruntów)~~ — **ZREALIZOWANE** (HSG z PIG, sekcja 3.1.5)
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
**Baza danych:** PostgreSQL 16+ z PostGIS 3.4+
**Biblioteki:**
- GeoPandas, Shapely (operacje przestrzenne)
- Rasterio, GDAL (preprocessing rastrów)
- NumPy, SciPy (obliczenia numeryczne)
- pyflwdir (analiza hydrologiczna — D8, flow accumulation)
- Pydantic (walidacja danych)
- SQLAlchemy (ORM)
- structlog (structured logging)
- psutil (monitorowanie zasobow — admin panel)
- Alembic (migracje bazy danych)
**Biblioteki wlasne:**
- Hydrolog v0.6.3 (obliczenia hydrologiczne)
- Kartograf v0.6.1 (pobieranie NMT, Land Cover, HSG, BDOT10k)
- IMGWTools v2.1.0 (opady projektowe z IMGW)

#### Frontend
**Języki:** HTML5, CSS3, JavaScript (ES6+) — Vanilla JS, brak frameworka
**Mapa:** Leaflet.js 1.9.4
**Wykresy:** Chart.js 4.4.7
**UI Framework:** Bootstrap 5.3.3 (CDN)
**Styl:** Glassmorphism (zmienne CSS w `glass.css`), floating draggable panel
**Moduly:** 10 modulow JS (IIFE na `window.Hydrograf`): api, map, draggable, charts, layers, profile, hydrograph, depressions, app + 3 moduly admin
**Podkład mapy:** OpenStreetMap, ESRI Satellite, OpenTopoMap, GUGiK WMTS (ortofoto + topo)
**Strony:** `index.html` (glowna), `admin.html` (panel administracyjny)

#### Infrastruktura
**Konteneryzacja:** Docker + Docker Compose (3 kontenery: db, api, nginx)
**Reverse Proxy:** Nginx (alpine)
**Serwer:** Własny (domowy) - Debian 13
**CI/CD:** GitHub Actions (lub GitLab CI)
**Monitoring:** Panel administracyjny `/admin` (CPU/RAM, pool DB, uptime) + health check `/health`

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
- ❌ WebSockets (real-time updates) — uwaga: SSE (Server-Sent Events) uzyty w panelu admin do streamowania logow bootstrap
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
- ⚠️ **Jednorazowy preprocessing NMT:** ~45 minut (pipeline bootstrap, mierzone na bbox ~400 km²)
- ⚠️ **Wymaga serwera:** minimum 8 GB RAM, 100 GB dysku
- ⚠️ **Mozliwosc uruchomienia z panelu admin** (`/admin` → Bootstrap) lub CLI (`bootstrap.py`)

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
| **HSG** | Hydrologic Soil Group - grupa hydrologiczna gleby (A/B/C/D) |
| **MVT** | Mapbox Vector Tiles - format kafelkow wektorowych |
| **BFS** | Breadth-First Search - przeszukiwanie grafu wszerz |
| **SSE** | Server-Sent Events - protokol streamowania danych z serwera |
| **ADR** | Architecture Decision Record - rejestr decyzji architektonicznych |

---

**Wersja dokumentu:** 1.2
**Data ostatniej aktualizacji:** 2026-03-25
**Wersja biezaca:** v0.4.0 (CP4 zakonczone, 899 testow, 19 endpointow, 49 ADR)
**Planowana wersja MVP:** v1.0.0 (CP5)
**Status:** Zatwierdzony — projekt w aktywnym rozwoju

---

*Ten dokument definiuje zakres projektu MVP. Wszelkie zmiany wymagają formalnego procesu change management i aktualizacji tego dokumentu.*
