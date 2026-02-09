/**
 * Hydrograf Map module.
 *
 * Manages Leaflet map, watershed polygon, outlet marker,
 * drawing mode, and profile line.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var map = null;
    var demLayer = null;
    var demBounds = null;
    var streamsLayer = null;
    var streamsBounds = null;
    var watershedLayer = null;
    var outletMarker = null;
    var clickEnabled = true;

    // Drawing state
    var drawMode = false;
    var drawVertices = [];
    var drawMarkers = [];
    var drawPolyline = null;
    var drawCallback = null;

    // Profile line
    var profileLine = null;

    /**
     * Initialize the Leaflet map.
     * Base layer is NOT added here — layers.js handles it via setBaseLayer().
     */
    function init(onClickCallback) {
        map = L.map('map', {
            center: [51.9, 19.5],
            zoom: 7,
            zoomControl: true,
        });

        // Load overlays
        loadDemOverlay();
        loadStreamsOverlay();

        map.on('click', function (e) {
            // Drawing mode: add vertex
            if (drawMode) {
                addDrawVertex(e.latlng);
                return;
            }

            if (!clickEnabled) return;
            if (onClickCallback) {
                onClickCallback(e.latlng.lat, e.latlng.lng);
            }
        });

        map.on('dblclick', function (e) {
            if (drawMode) {
                L.DomEvent.stopPropagation(e);
                L.DomEvent.preventDefault(e);
                finishDrawing();
            }
        });

        // Escape cancels drawing
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && drawMode) {
                cancelDrawing();
            }
        });
    }

    // ===== DEM Overlay =====

    function loadDemOverlay() {
        fetch('/data/dem.json')
            .then(function (res) {
                if (!res.ok) throw new Error('DEM metadata not found');
                return res.json();
            })
            .then(function (meta) {
                demBounds = L.latLngBounds(meta.bounds);
                demLayer = L.imageOverlay('/data/dem.png', demBounds, {
                    opacity: 0.7,
                    attribution: 'NMT &copy; GUGiK',
                });
            })
            .catch(function (err) {
                console.warn('DEM overlay not available:', err.message);
            });
    }

    function getDemLayer() { return demLayer; }
    function fitDemBounds() {
        if (demBounds && map) map.fitBounds(demBounds, { padding: [20, 20] });
    }
    function setDemOpacity(opacity) {
        if (demLayer) demLayer.setOpacity(opacity);
    }

    // ===== Streams Overlay =====

    function loadStreamsOverlay() {
        fetch('/data/streams.json')
            .then(function (res) {
                if (!res.ok) throw new Error('Streams metadata not found');
                return res.json();
            })
            .then(function (meta) {
                streamsBounds = L.latLngBounds(meta.bounds);
                streamsLayer = L.imageOverlay('/data/streams.png', streamsBounds, {
                    opacity: 1.0,
                    attribution: 'Cieki (Strahler)',
                });
            })
            .catch(function (err) {
                console.warn('Streams overlay not available:', err.message);
            });
    }

    function getStreamsLayer() { return streamsLayer; }
    function fitStreamsBounds() {
        if (streamsBounds && map) map.fitBounds(streamsBounds, { padding: [20, 20] });
    }
    function setStreamsOpacity(opacity) {
        if (streamsLayer) streamsLayer.setOpacity(opacity);
    }

    // ===== Watershed display =====

    function showWatershed(geojsonFeature) {
        clearWatershed();
        watershedLayer = L.geoJSON(geojsonFeature, {
            style: {
                color: '#28A745',
                weight: 2,
                fillColor: '#28A745',
                fillOpacity: 0.3,
            },
        }).addTo(map);
        map.fitBounds(watershedLayer.getBounds(), { padding: [20, 20] });
    }

    function getWatershedLayer() { return watershedLayer; }

    function showOutlet(lat, lng, elevation) {
        if (outletMarker) map.removeLayer(outletMarker);
        outletMarker = L.circleMarker([lat, lng], {
            radius: 7,
            color: '#DC3545',
            fillColor: '#DC3545',
            fillOpacity: 0.8,
            weight: 2,
        }).addTo(map);
        outletMarker.bindTooltip(
            'Ujście: ' + elevation.toFixed(1) + ' m n.p.m.',
            { permanent: false, direction: 'top' }
        );
    }

    function clearWatershed() {
        if (watershedLayer) { map.removeLayer(watershedLayer); watershedLayer = null; }
        if (outletMarker) { map.removeLayer(outletMarker); outletMarker = null; }
    }

    // ===== Drawing mode (polyline for terrain profile) =====

    function startDrawing(onComplete) {
        drawMode = true;
        drawVertices = [];
        drawMarkers = [];
        drawPolyline = null;
        drawCallback = onComplete;
        map.getContainer().style.cursor = 'crosshair';
        // Disable double-click zoom during drawing
        map.doubleClickZoom.disable();
    }

    function addDrawVertex(latlng) {
        drawVertices.push(latlng);

        var marker = L.circleMarker(latlng, {
            radius: 5,
            color: '#0A84FF',
            fillColor: '#0A84FF',
            fillOpacity: 1,
            weight: 1,
        }).addTo(map);
        drawMarkers.push(marker);

        // Update polyline
        if (drawPolyline) map.removeLayer(drawPolyline);
        if (drawVertices.length > 1) {
            drawPolyline = L.polyline(drawVertices, {
                color: '#0A84FF',
                weight: 2,
                dashArray: '6, 4',
            }).addTo(map);
        }
    }

    function finishDrawing() {
        if (drawVertices.length < 2) {
            cancelDrawing();
            return;
        }

        var coords = drawVertices.map(function (ll) { return [ll.lat, ll.lng]; });
        drawMode = false;
        map.getContainer().style.cursor = '';
        map.doubleClickZoom.enable();

        // Clean up markers
        drawMarkers.forEach(function (m) { map.removeLayer(m); });
        drawMarkers = [];

        // Keep the polyline as profile line
        if (drawPolyline) {
            if (profileLine) map.removeLayer(profileLine);
            profileLine = drawPolyline;
            drawPolyline = null;
        }

        if (drawCallback) drawCallback(coords);
    }

    function cancelDrawing() {
        drawMode = false;
        map.getContainer().style.cursor = '';
        map.doubleClickZoom.enable();
        drawMarkers.forEach(function (m) { map.removeLayer(m); });
        drawMarkers = [];
        if (drawPolyline) { map.removeLayer(drawPolyline); drawPolyline = null; }
        drawVertices = [];
        drawCallback = null;
    }

    function isDrawing() { return drawMode; }

    // ===== Profile line display =====

    function showProfileLine(coords) {
        clearProfileLine();
        // coords: [[lng, lat], ...] (GeoJSON order)
        var latlngs = coords.map(function (c) { return [c[1], c[0]]; });
        profileLine = L.polyline(latlngs, {
            color: '#8B4513',
            weight: 3,
            opacity: 0.8,
        }).addTo(map);
    }

    function clearProfileLine() {
        if (profileLine) { map.removeLayer(profileLine); profileLine = null; }
    }

    // ===== Utilities =====

    function disableClick() { clickEnabled = false; }
    function enableClick() { clickEnabled = true; }

    function invalidateSize() {
        if (map) setTimeout(function () { map.invalidateSize(); }, 50);
    }

    window.Hydrograf.map = {
        init: init,
        _getMap: function () { return map; },
        getDemLayer: getDemLayer,
        fitDemBounds: fitDemBounds,
        setDemOpacity: setDemOpacity,
        getStreamsLayer: getStreamsLayer,
        fitStreamsBounds: fitStreamsBounds,
        setStreamsOpacity: setStreamsOpacity,
        showWatershed: showWatershed,
        getWatershedLayer: getWatershedLayer,
        showOutlet: showOutlet,
        clearWatershed: clearWatershed,
        disableClick: disableClick,
        enableClick: enableClick,
        invalidateSize: invalidateSize,
        // Drawing
        startDrawing: startDrawing,
        cancelDrawing: cancelDrawing,
        isDrawing: isDrawing,
        // Profile
        showProfileLine: showProfileLine,
        clearProfileLine: clearProfileLine,
    };
})();
