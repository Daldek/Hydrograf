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
    var currentThreshold = null;
    var streamTooltip = null;
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

    // ===== Streams Vector (MVT) =====

    var STRAHLER_COLORS = [
        '#B3E5FC', '#81D4FA', '#4FC3F7', '#29B6F6',
        '#039BE5', '#0277BD', '#01579B', '#002F6C'
    ];

    function strahlerColor(order) {
        return STRAHLER_COLORS[Math.min(order, 8) - 1] || '#039BE5';
    }

    function loadStreamsVector(threshold) {
        if (streamsLayer && map.hasLayer(streamsLayer)) {
            map.removeLayer(streamsLayer);
        }
        currentThreshold = threshold || currentThreshold;

        streamsLayer = L.vectorGrid.protobuf(
            '/api/tiles/streams/{z}/{x}/{y}.pbf?threshold=' + currentThreshold,
            {
                vectorTileLayerStyles: {
                    streams: function (properties) {
                        var order = properties.strahler_order || 1;
                        return {
                            weight: order * 0.8 + 0.5,
                            color: strahlerColor(order),
                            opacity: 0.9,
                        };
                    }
                },
                interactive: true,
                maxNativeZoom: 18,
                attribution: 'Cieki (Strahler)',
            }
        );

        // Re-fire click to map so watershed delineation works even on stream features
        streamsLayer.on('click', function (e) {
            map.fire('click', { latlng: e.latlng });
        });

        // Stream info via hover tooltip (not click popup)
        streamsLayer.on('mouseover', function (e) {
            var props = e.layer.properties;
            var content =
                '<b>Rząd Strahlera:</b> ' + (props.strahler_order || '?') + '<br>' +
                '<b>Długość:</b> ' + (props.length_m ? (props.length_m / 1000).toFixed(2) + ' km' : '?') + '<br>' +
                '<b>Zlewnia:</b> ' + (props.upstream_area_km2 ? props.upstream_area_km2.toFixed(2) + ' km²' : '?');
            streamTooltip = L.tooltip({ sticky: true, direction: 'top', offset: [0, -8] })
                .setLatLng(e.latlng)
                .setContent(content)
                .addTo(map);
        });
        streamsLayer.on('mouseout', function () {
            if (streamTooltip) {
                map.removeLayer(streamTooltip);
                streamTooltip = null;
            }
        });

        return streamsLayer;
    }

    function getStreamsLayer() { return streamsLayer; }

    function getStreamsThreshold() { return currentThreshold; }

    function fitStreamsBounds() {
        // MVT layers don't have predefined bounds; fit to DEM bounds if available
        if (demBounds && map) map.fitBounds(demBounds, { padding: [20, 20] });
    }

    function setStreamsOpacity(opacity) {
        if (streamsLayer) {
            // VectorGrid uses setFeatureStyle or direct opacity via options
            // Re-set styles with new opacity
            streamsLayer.options.vectorTileLayerStyles.streams = function (properties) {
                var order = properties.strahler_order || 1;
                return {
                    weight: order * 0.8 + 0.5,
                    color: strahlerColor(order),
                    opacity: opacity,
                };
            };
            // Force redraw
            if (map.hasLayer(streamsLayer)) {
                streamsLayer.redraw();
            }
        }
    }

    // ===== Catchments Vector (MVT) =====

    var catchmentsLayer = null;
    var currentCatchmentThreshold = null;
    var catchmentTooltip = null;

    var CATCHMENT_COLORS = [
        '#E1F5FE', '#B3E5FC', '#81D4FA', '#4FC3F7',
        '#29B6F6', '#03A9F4', '#039BE5', '#0288D1'
    ];

    function catchmentColor(order) {
        return CATCHMENT_COLORS[Math.min(order, 8) - 1] || '#03A9F4';
    }

    function loadCatchmentsVector(threshold) {
        if (catchmentsLayer && map.hasLayer(catchmentsLayer)) {
            map.removeLayer(catchmentsLayer);
        }
        currentCatchmentThreshold = threshold || currentCatchmentThreshold;

        catchmentsLayer = L.vectorGrid.protobuf(
            '/api/tiles/catchments/{z}/{x}/{y}.pbf?threshold=' + currentCatchmentThreshold,
            {
                vectorTileLayerStyles: {
                    catchments: function (properties) {
                        var order = properties.strahler_order || 1;
                        return {
                            weight: 0.5,
                            color: '#666',
                            fillColor: catchmentColor(order),
                            fillOpacity: 0.3,
                            fill: true,
                        };
                    }
                },
                interactive: true,
                maxNativeZoom: 18,
                attribution: 'Zlewnie cząstkowe',
            }
        );

        // Re-fire click to map so watershed delineation works
        catchmentsLayer.on('click', function (e) {
            map.fire('click', { latlng: e.latlng });
        });

        // Catchment info via hover tooltip
        catchmentsLayer.on('mouseover', function (e) {
            var props = e.layer.properties;
            var content =
                '<b>Rząd Strahlera:</b> ' + (props.strahler_order || '?') + '<br>' +
                '<b>Powierzchnia:</b> ' + (props.area_km2 ? props.area_km2.toFixed(4) + ' km²' : '?') + '<br>' +
                '<b>Śr. wysokość:</b> ' + (props.mean_elevation_m ? props.mean_elevation_m.toFixed(1) + ' m' : '?');
            catchmentTooltip = L.tooltip({ sticky: true, direction: 'top', offset: [0, -8] })
                .setLatLng(e.latlng)
                .setContent(content)
                .addTo(map);
        });
        catchmentsLayer.on('mouseout', function () {
            if (catchmentTooltip) {
                map.removeLayer(catchmentTooltip);
                catchmentTooltip = null;
            }
        });

        return catchmentsLayer;
    }

    function getCatchmentsLayer() { return catchmentsLayer; }

    function fitCatchmentsBounds() {
        if (demBounds && map) map.fitBounds(demBounds, { padding: [20, 20] });
    }

    function setCatchmentsOpacity(opacity) {
        if (catchmentsLayer) {
            catchmentsLayer.options.vectorTileLayerStyles.catchments = function (properties) {
                var order = properties.strahler_order || 1;
                return {
                    weight: 0.5,
                    color: '#666',
                    fillColor: catchmentColor(order),
                    fillOpacity: opacity * 0.5,
                    fill: true,
                };
            };
            if (map.hasLayer(catchmentsLayer)) {
                catchmentsLayer.redraw();
            }
        }
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
        getStreamsThreshold: getStreamsThreshold,
        loadStreamsVector: loadStreamsVector,
        fitStreamsBounds: fitStreamsBounds,
        setStreamsOpacity: setStreamsOpacity,
        getCatchmentsLayer: getCatchmentsLayer,
        loadCatchmentsVector: loadCatchmentsVector,
        fitCatchmentsBounds: fitCatchmentsBounds,
        setCatchmentsOpacity: setCatchmentsOpacity,
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
