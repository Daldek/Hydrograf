# Design: Bbox UI Redesign — 4 pola + Map Picker

**Data:** 2026-03-02
**Status:** Zatwierdzony

## Problem

Panel administracyjny używa jednego pola tekstowego do wpisywania bbox (`min_lon,min_lat,max_lon,max_lat`). Brak walidacji frontend, nieintuicyjny format, brak wizualnej orientacji geograficznej.

## Rozwiązanie

### 1. Layout pól bbox — układ kompasu

4 pola `type="number"` ułożone w kształt kompasu (N/W/E/S):

```
         ┌─────────────────┐
         │   max_lat (N)    │
         │   [  52.5870  ]  │
         └─────────────────┘
┌──────────────┐     ┌──────────────┐
│ min_lon (W)  │     │ max_lon (E)  │
│ [ 16.9279 ]  │     │ [ 17.3825 ]  │
└──────────────┘     └──────────────┘
         ┌─────────────────┐
         │   min_lat (S)    │
         │   [  52.3729  ]  │
         └─────────────────┘

      [ Wybierz na mapie ]
```

- `step="0.0001"`, lon: -180..180, lat: -90..90
- Etykiety: N, S, W, E
- Walidacja: min_lon < max_lon, min_lat < max_lat

### 2. Modal z mapą OSM (Leaflet)

- Modal Bootstrap `modal-lg` (~800px)
- Mapa Leaflet z OSM tiles, centrowana na Polskę (52°N, 19°E, zoom 6)
- Jeśli pola bbox mają wartości — mapa centruje się na istniejącym bbox i wyświetla prostokąt
- Rysowanie: mousedown → drag pomarańczowy prostokąt → mouseup
- Ponowny mousedown kasuje stary prostokąt
- "Zatwierdź" → wpisuje współrzędne do 4 pól, zamyka modal
- "Anuluj" → zamyka bez zmian
- Bez L.Draw — własna logika (3 event listenery)
- `invalidateSize()` na `shown.bs.modal`

### 3. Szczegóły techniczne

**Pliki do zmiany:**
- `frontend/admin.html` — 4 pola bbox + przycisk + modal HTML
- `frontend/js/admin/admin-bootstrap.js` — składanie bbox z 4 pól, walidacja
- `frontend/css/admin.css` — style kompasu i modala mapy

**Nowy plik:**
- `frontend/js/admin/admin-bbox-picker.js` — moduł IIFE `window.Hydrograf.adminBboxPicker`

**Backend:** bez zmian — 4 pola składane w string przed wysłaniem.

**Podejście:** Leaflet w modalu Bootstrap (Leaflet już w CDN projektu, zero nowych zależności).
