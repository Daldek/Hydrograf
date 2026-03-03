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
        if (_map) {
            _map.dragging.enable();
        }
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

        _map.getContainer().addEventListener('mouseleave', function () {
            if (_drawing) {
                _drawing = false;
                _startLatLng = null;
                _map.dragging.enable();
            }
        });
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

        // Ignore tiny accidental clicks (less than 5px)
        var nePoint = _map.latLngToContainerPoint(bounds.getNorthEast());
        var swPoint = _map.latLngToContainerPoint(bounds.getSouthWest());
        if (Math.abs(nePoint.x - swPoint.x) < 5 && Math.abs(nePoint.y - swPoint.y) < 5) {
            _startLatLng = null;
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
