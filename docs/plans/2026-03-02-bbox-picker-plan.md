# Bbox Picker UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace single-text bbox input in admin panel with 4 compass-layout fields + Leaflet map modal for visual bbox selection.

**Architecture:** New IIFE module `adminBboxPicker` handles map modal (Leaflet in Bootstrap modal, draw rectangle by click+drag). Existing `admin-bootstrap.js` modified to read 4 fields instead of 1 text input. Leaflet 1.9.4 CDN added to `admin.html`. Backend unchanged — 4 fields joined into comma string before API call.

**Tech Stack:** Leaflet 1.9.4 (already in project CDN), Bootstrap 5.3.3 modal, Vanilla JS IIFE

---

### Task 1: Add Leaflet CDN + compass bbox HTML + modal markup to admin.html

**Files:**
- Modify: `frontend/admin.html`

**Step 1: Add Leaflet CSS to `<head>` (after glass.css, before admin.css)**

In `frontend/admin.html`, after line 15 (`<link rel="stylesheet" href="css/glass.css">`), add:

```html
    <!-- Leaflet 1.9.4 (for bbox map picker) -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
          integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
          crossorigin="anonymous">
```

**Step 2: Replace bbox text input with 4 compass fields + map button**

Replace lines 90-95 (the `<form>` bbox `<div class="mb-2">` block):

```html
<!-- OLD: single text input -->
<div class="mb-2">
    <label for="bootstrap-bbox" class="form-label small">Bounding box (min_lon, min_lat, max_lon, max_lat)</label>
    <input type="text" id="bootstrap-bbox" class="form-control form-control-sm"
           value="16.9279,52.3729,17.3825,52.5870">
</div>
```

with:

```html
<fieldset class="mb-2">
    <legend class="form-label small mb-1">Bounding box</legend>
    <div class="bbox-compass">
        <div class="bbox-compass-row bbox-compass-center">
            <div class="bbox-field">
                <label for="bbox-north" class="bbox-label">N</label>
                <input type="number" id="bbox-north" class="form-control form-control-sm"
                       step="0.0001" min="-90" max="90" value="52.5870">
            </div>
        </div>
        <div class="bbox-compass-row bbox-compass-middle">
            <div class="bbox-field">
                <label for="bbox-west" class="bbox-label">W</label>
                <input type="number" id="bbox-west" class="form-control form-control-sm"
                       step="0.0001" min="-180" max="180" value="16.9279">
            </div>
            <div class="bbox-field">
                <label for="bbox-east" class="bbox-label">E</label>
                <input type="number" id="bbox-east" class="form-control form-control-sm"
                       step="0.0001" min="-180" max="180" value="17.3825">
            </div>
        </div>
        <div class="bbox-compass-row bbox-compass-center">
            <div class="bbox-field">
                <label for="bbox-south" class="bbox-label">S</label>
                <input type="number" id="bbox-south" class="form-control form-control-sm"
                       step="0.0001" min="-90" max="90" value="52.3729">
            </div>
        </div>
    </div>
    <button type="button" id="bbox-map-btn" class="btn btn-outline-secondary btn-sm mt-1">
        Wybierz na mapie
    </button>
    <div id="bbox-validation-error" class="text-danger small mt-1 d-none"></div>
</fieldset>
```

**Step 3: Add modal HTML before closing `</body>`**

Before line 141 (`<!-- Bootstrap 5.3.3 JS -->`), add:

```html
    <!-- Bbox map picker modal -->
    <div class="modal fade" id="bbox-map-modal" tabindex="-1" aria-labelledby="bbox-map-modal-label" aria-hidden="true">
        <div class="modal-dialog modal-lg modal-dialog-centered">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="bbox-map-modal-label">Wybierz obszar na mapie</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Zamknij"></button>
                </div>
                <div class="modal-body p-0">
                    <div id="bbox-picker-map" style="height: 500px;"></div>
                    <p class="text-secondary small px-3 py-2 mb-0">
                        Kliknij i przeciągnij, aby narysować prostokąt. Kliknij ponownie, aby narysować nowy.
                    </p>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Anuluj</button>
                    <button type="button" id="bbox-map-confirm-btn" class="btn btn-primary btn-sm" disabled>Zatwierdź</button>
                </div>
            </div>
        </div>
    </div>
```

**Step 4: Add Leaflet JS + new module script tag**

After line 144 (Bootstrap JS `<script>` tag), add Leaflet JS:

```html
    <!-- Leaflet 1.9.4 JS (for bbox map picker) -->
    <script defer src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
            integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
            crossorigin="anonymous"></script>
```

After admin-bootstrap.js script tag (line 148), before admin-app.js, add:

```html
    <script defer src="js/admin/admin-bbox-picker.js"></script>
```

**Step 5: Verify in browser**

Open `admin.html` — should see 4 fields in compass layout, "Wybierz na mapie" button, modal opens (empty map for now).

**Step 6: Commit**

```bash
git add frontend/admin.html
git commit -m "feat(frontend): replace bbox text input with 4 compass fields + map modal markup"
```

---

### Task 2: Add CSS for compass layout and map modal

**Files:**
- Modify: `frontend/css/admin.css`

**Step 1: Add compass layout styles**

Append to `frontend/css/admin.css` (after line 215, the closing `}` of media query):

```css
/* ----------------------------------------------------------------
   Bbox compass layout
   ---------------------------------------------------------------- */
.bbox-compass {
    max-width: 320px;
}

.bbox-compass-row {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 0.25rem;
}

.bbox-compass-center {
    justify-content: center;
}

.bbox-compass-middle {
    justify-content: space-between;
}

.bbox-field {
    display: flex;
    align-items: center;
    gap: 0.25rem;
}

.bbox-label {
    font-size: 0.7rem;
    font-weight: 700;
    color: var(--color-text-secondary);
    min-width: 1rem;
    text-align: center;
}

.bbox-field .form-control {
    width: 120px;
}

/* ----------------------------------------------------------------
   Bbox map picker modal
   ---------------------------------------------------------------- */
#bbox-picker-map {
    width: 100%;
    cursor: crosshair;
}

#bbox-picker-map .leaflet-interactive {
    cursor: crosshair;
}
```

**Step 2: Verify layout in browser**

4 fields should form a compass shape: N centered top, W-E in middle row spaced apart, S centered bottom.

**Step 3: Commit**

```bash
git add frontend/css/admin.css
git commit -m "feat(frontend): add CSS for bbox compass layout and map picker"
```

---

### Task 3: Create admin-bbox-picker.js module

**Files:**
- Create: `frontend/js/admin/admin-bbox-picker.js`

**Step 1: Write the full module**

```javascript
/**
 * Hydrograf Admin — Bbox map picker module.
 *
 * Opens a Leaflet map in a Bootstrap modal for drawing a bbox rectangle.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var _map = null;
    var _drawRect = null;
    var _drawing = false;
    var _startLatLng = null;
    var _modal = null;

    /**
     * Initialize bbox picker — bind map button, set up modal events.
     */
    function init() {
        var mapBtn = document.getElementById('bbox-map-btn');
        if (mapBtn) {
            mapBtn.addEventListener('click', openModal);
        }

        var confirmBtn = document.getElementById('bbox-map-confirm-btn');
        if (confirmBtn) {
            confirmBtn.addEventListener('click', confirmSelection);
        }

        var modalEl = document.getElementById('bbox-map-modal');
        if (modalEl) {
            modalEl.addEventListener('shown.bs.modal', onModalShown);
            modalEl.addEventListener('hidden.bs.modal', onModalHidden);
        }
    }

    /**
     * Open the map modal.
     */
    function openModal() {
        var modalEl = document.getElementById('bbox-map-modal');
        if (!modalEl) return;

        _modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        _modal.show();
    }

    /**
     * Called after modal is fully visible — init or refresh the map.
     */
    function onModalShown() {
        if (!_map) {
            initMap();
        } else {
            _map.invalidateSize();
        }
        showExistingBbox();
    }

    /**
     * Called when modal is hidden — clean up drawing state.
     */
    function onModalHidden() {
        _drawing = false;
        _startLatLng = null;
    }

    /**
     * Initialize the Leaflet map inside the modal.
     */
    function initMap() {
        _map = L.map('bbox-picker-map', {
            center: [52.0, 19.0],
            zoom: 6,
        });

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors',
            maxZoom: 18,
        }).addTo(_map);

        _map.on('mousedown', onMouseDown);
        _map.on('mousemove', onMouseMove);
        _map.on('mouseup', onMouseUp);
    }

    /**
     * If bbox fields already have values, show the rectangle on the map.
     */
    function showExistingBbox() {
        var vals = readFields();
        if (!vals) return;

        var bounds = L.latLngBounds(
            [vals.south, vals.west],
            [vals.north, vals.east]
        );

        setRectangle(bounds);
        _map.fitBounds(bounds, { padding: [50, 50] });
        document.getElementById('bbox-map-confirm-btn').disabled = false;
    }

    /**
     * Read current values from the 4 bbox fields.
     * Returns {north, south, east, west} or null if any field is empty/invalid.
     */
    function readFields() {
        var n = parseFloat(document.getElementById('bbox-north').value);
        var s = parseFloat(document.getElementById('bbox-south').value);
        var e = parseFloat(document.getElementById('bbox-east').value);
        var w = parseFloat(document.getElementById('bbox-west').value);

        if (isNaN(n) || isNaN(s) || isNaN(e) || isNaN(w)) return null;

        return { north: n, south: s, east: e, west: w };
    }

    /**
     * Write values to the 4 bbox fields.
     */
    function writeFields(north, south, east, west) {
        document.getElementById('bbox-north').value = round6(north);
        document.getElementById('bbox-south').value = round6(south);
        document.getElementById('bbox-east').value = round6(east);
        document.getElementById('bbox-west').value = round6(west);
    }

    function round6(v) {
        return Math.round(v * 1000000) / 1000000;
    }

    /**
     * Set (or replace) the rectangle on the map.
     */
    function setRectangle(bounds) {
        if (_drawRect) {
            _map.removeLayer(_drawRect);
        }
        _drawRect = L.rectangle(bounds, {
            color: '#f97316',
            weight: 2,
            fillOpacity: 0.15,
        }).addTo(_map);
    }

    // --- Drawing handlers ---

    function onMouseDown(e) {
        if (e.originalEvent.button !== 0) return; // left click only
        _drawing = true;
        _startLatLng = e.latlng;
        _map.dragging.disable();

        document.getElementById('bbox-map-confirm-btn').disabled = true;
    }

    function onMouseMove(e) {
        if (!_drawing || !_startLatLng) return;

        var bounds = L.latLngBounds(_startLatLng, e.latlng);
        setRectangle(bounds);
    }

    function onMouseUp(e) {
        if (!_drawing || !_startLatLng) return;
        _drawing = false;
        _map.dragging.enable();

        var bounds = L.latLngBounds(_startLatLng, e.latlng);

        // Ignore tiny accidental clicks (less than ~100m)
        if (bounds.getNorthEast().equals(bounds.getSouthWest())) {
            return;
        }

        setRectangle(bounds);
        _startLatLng = null;

        document.getElementById('bbox-map-confirm-btn').disabled = false;
    }

    /**
     * Confirm selection — write bounds to fields and close modal.
     */
    function confirmSelection() {
        if (!_drawRect) return;

        var bounds = _drawRect.getBounds();
        writeFields(
            bounds.getNorth(),
            bounds.getSouth(),
            bounds.getEast(),
            bounds.getWest()
        );

        if (_modal) {
            _modal.hide();
        }
    }

    window.Hydrograf.adminBboxPicker = {
        init: init,
    };
})();
```

**Step 2: Verify in browser**

Open admin panel → "Wybierz na mapie" → modal opens with OSM map → draw rectangle → "Zatwierdź" → values appear in 4 fields.

**Step 3: Commit**

```bash
git add frontend/js/admin/admin-bbox-picker.js
git commit -m "feat(frontend): add bbox map picker module with Leaflet draw"
```

---

### Task 4: Update admin-bootstrap.js to read 4 fields + add validation

**Files:**
- Modify: `frontend/js/admin/admin-bootstrap.js:99-106`

**Step 1: Replace bbox reading logic in handleStart()**

Replace the current bbox reading block (lines 100-106):

```javascript
        var bboxInput = document.getElementById('bootstrap-bbox');
        var bbox = bboxInput ? bboxInput.value.trim() : '';

        if (!bbox) {
            alert('Podaj bounding box.');
            return;
        }
```

with:

```javascript
        var bbox = readAndValidateBbox();
        if (!bbox) return;
```

**Step 2: Add readAndValidateBbox() function**

Add before `handleStart()` (before line 99):

```javascript
    /**
     * Read bbox from 4 compass fields, validate, return as comma string or null.
     */
    function readAndValidateBbox() {
        var n = document.getElementById('bbox-north');
        var s = document.getElementById('bbox-south');
        var e = document.getElementById('bbox-east');
        var w = document.getElementById('bbox-west');
        var errEl = document.getElementById('bbox-validation-error');

        var north = parseFloat(n.value);
        var south = parseFloat(s.value);
        var east = parseFloat(e.value);
        var west = parseFloat(w.value);

        // Clear previous error
        if (errEl) {
            errEl.classList.add('d-none');
            errEl.textContent = '';
        }
        [n, s, e, w].forEach(function (el) {
            el.classList.remove('is-invalid');
        });

        // Check empty / NaN
        if (isNaN(west) || isNaN(south) || isNaN(east) || isNaN(north)) {
            showBboxError('Wypełnij wszystkie pola bounding box.', [n, s, e, w]);
            return null;
        }

        // Check ordering
        if (west >= east) {
            showBboxError('W (min lon) musi być mniejsze niż E (max lon).', [w, e]);
            return null;
        }
        if (south >= north) {
            showBboxError('S (min lat) musi być mniejsze niż N (max lat).', [s, n]);
            return null;
        }

        return west + ',' + south + ',' + east + ',' + north;
    }

    /**
     * Show validation error under bbox fields.
     */
    function showBboxError(message, fields) {
        var errEl = document.getElementById('bbox-validation-error');
        if (errEl) {
            errEl.textContent = message;
            errEl.classList.remove('d-none');
        }
        fields.forEach(function (el) {
            if (el) el.classList.add('is-invalid');
        });
    }
```

**Step 3: Verify validation in browser**

Set W > E → click Start → red fields + error message. Fix values → Start → validation passes, error clears.

**Step 4: Commit**

```bash
git add frontend/js/admin/admin-bootstrap.js
git commit -m "feat(frontend): read bbox from 4 compass fields with validation"
```

---

### Task 5: Wire up bbox picker init in admin-app.js

**Files:**
- Modify: `frontend/js/admin/admin-app.js`

**Step 1: Add adminBboxPicker.init() call**

Find the `init()` or `DOMContentLoaded` handler in `admin-app.js` that calls `adminBootstrap.init()`. Add after it:

```javascript
window.Hydrograf.adminBboxPicker.init();
```

**Step 2: Verify full flow in browser**

1. Open admin panel, authenticate
2. See 4 compass fields with default values
3. Click "Wybierz na mapie" → modal opens, map shows existing bbox rectangle
4. Draw new rectangle → "Zatwierdź" → fields update
5. Click "Start" → bootstrap starts with correct bbox string

**Step 3: Commit**

```bash
git add frontend/js/admin/admin-app.js
git commit -m "feat(frontend): wire up bbox picker init in admin app"
```

---

### Task 6: Final review and docs update

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `docs/CHANGELOG.md`

**Step 1: Update PROGRESS.md**

Update "Ostatnia sesja" with bbox picker work done.

**Step 2: Update CHANGELOG.md**

Add entry for bbox picker UI redesign.

**Step 3: Commit**

```bash
git add docs/PROGRESS.md docs/CHANGELOG.md
git commit -m "docs: update PROGRESS.md and CHANGELOG.md for bbox picker UI"
```
