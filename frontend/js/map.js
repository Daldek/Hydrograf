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

    // BDOT10k vector layers (lakes + streams)
    var bdotLakesLayer = null;
    var bdotStreamsLayer = null;
    var bdotBounds = null;

    /**
     * Initialize the Leaflet map.
     * Base layer is NOT added here — layers.js handles it via setBaseLayer().
     */
    function init(onClickCallback) {
        map = L.map('map', {
            center: [51.9, 19.5],
            zoom: 7,
            zoomControl: false,
        });
        L.control.zoom({ position: 'topright' }).addTo(map);

        // Custom panes for layer ordering:
        // Base (tilePane z-200) → NMT → Zlewnie → Cieki → overlay (z-400)
        map.createPane('demPane');
        map.getPane('demPane').style.zIndex = 250;
        map.createPane('catchmentsPane');
        map.getPane('catchmentsPane').style.zIndex = 300;
        map.createPane('streamsPane');
        map.getPane('streamsPane').style.zIndex = 350;

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
        // Try tiled DEM first, fall back to single PNG overlay
        fetch('/data/dem_tiles.json')
            .then(function (res) {
                if (!res.ok) throw new Error('tiles not found');
                return res.json();
            })
            .then(function (meta) {
                demBounds = L.latLngBounds(meta.bounds);
                demLayer = L.tileLayer('/data/dem_tiles/{z}/{x}/{y}.png', {
                    minZoom: meta.min_zoom || 8,
                    maxZoom: 22,
                    maxNativeZoom: meta.max_zoom || 18,
                    bounds: demBounds,
                    opacity: 0.7,
                    pane: 'demPane',
                    attribution: 'NMT &copy; GUGiK',
                    errorTileUrl: '',
                });
                if (map) map.fitBounds(demBounds, { padding: [20, 20] });
            })
            .catch(function () {
                // Fallback: single PNG overlay
                fetch('/data/dem.json')
                    .then(function (res) {
                        if (!res.ok) throw new Error('DEM metadata not found');
                        return res.json();
                    })
                    .then(function (meta) {
                        demBounds = L.latLngBounds(meta.bounds);
                        demLayer = L.imageOverlay('/data/dem.png', demBounds, {
                            opacity: 0.7,
                            pane: 'demPane',
                            attribution: 'NMT &copy; GUGiK',
                        });
                        if (map) map.fitBounds(demBounds, { padding: [20, 20] });
                    })
                    .catch(function (err) {
                        console.warn('DEM overlay not available:', err.message);
                    });
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

    /**
     * Compute stream color from upstream_area_km2 using log10 scale.
     * Gradient: light cyan (#B3E5FC) → navy (#002F6C).
     */
    function flowAccColor(area_km2) {
        // Map log10(area) from [-4, 1.3] (0.0001–20 km²) to [0, 1]
        var logVal = Math.log10(Math.max(area_km2, 0.0001));
        var t = (logVal - (-4)) / (1.3 - (-4)); // range 5.3
        t = Math.max(0, Math.min(1, t));

        // Interpolate between light cyan and navy (RGB)
        var r = Math.round(179 * (1 - t) + 0 * t);
        var g = Math.round(229 * (1 - t) + 47 * t);
        var b = Math.round(252 * (1 - t) + 108 * t);
        return 'rgb(' + r + ',' + g + ',' + b + ')';
    }

    /**
     * Compute stream width from upstream_area_km2 using log10 scale.
     * Range: 0.5px (tiny streams) → 4px (large rivers).
     */
    function flowAccWidth(area_km2) {
        var logVal = Math.log10(Math.max(area_km2, 0.0001));
        var t = (logVal - (-4)) / (1.3 - (-4));
        t = Math.max(0, Math.min(1, t));
        return 0.5 + t * 3.5;
    }

    /**
     * Get tile URL for a given layer and threshold.
     * Uses pre-generated PMTiles if available, falls back to API.
     */
    function getTileUrl(layer, threshold) {
        // Check for pre-generated tiles metadata
        var meta = window.Hydrograf._tilesMeta;
        if (meta && meta.format === 'pmtiles' &&
            meta.thresholds && meta.thresholds.indexOf(threshold) !== -1) {
            return '/tiles/' + layer + '_' + threshold + '.pmtiles';
        }
        // Fallback: dynamic PostGIS MVT
        return '/api/tiles/' + layer + '/{z}/{x}/{y}.pbf?threshold=' + threshold;
    }

    function loadStreamsVector(threshold) {
        if (streamsLayer && map.hasLayer(streamsLayer)) {
            map.removeLayer(streamsLayer);
        }
        currentThreshold = threshold || currentThreshold;

        streamsLayer = L.vectorGrid.protobuf(
            getTileUrl('streams', currentThreshold),
            {
                pane: 'streamsPane',
                vectorTileLayerStyles: {
                    streams: function (properties) {
                        var area = properties.upstream_area_km2 || 0.0001;
                        return {
                            weight: flowAccWidth(area),
                            color: flowAccColor(area),
                            opacity: 0.9,
                        };
                    }
                },
                interactive: true,
                maxNativeZoom: 18,
                attribution: 'Cieki (flow acc)',
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
                '<b>Zlewnia:</b> ' + (props.upstream_area_km2 ? props.upstream_area_km2.toFixed(2) + ' km²' : '?') + '<br>' +
                '<b>Rząd Strahlera:</b> ' + (props.strahler_order || '?') + '<br>' +
                '<b>Długość:</b> ' + (props.length_m ? (props.length_m / 1000).toFixed(2) + ' km' : '?');
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
            // Use CSS container opacity to avoid flicker from redraw()
            var container = streamsLayer.getContainer();
            if (container) {
                container.style.opacity = opacity;
            }
        }
    }

    // ===== Catchments Vector (MVT) =====

    var catchmentsLayer = null;
    var currentCatchmentThreshold = null;
    var currentCatchmentOpacity = 1.0;
    var catchmentTooltip = null;
    var highlightedSegments = new Set();
    var selectionBoundaryLayer = null;

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
            getTileUrl('catchments', currentCatchmentThreshold),
            {
                pane: 'catchmentsPane',
                vectorTileLayerStyles: {
                    catchments: function (properties) {
                        var order = properties.strahler_order || 1;
                        return {
                            weight: 0.5,
                            color: '#666',
                            fillColor: catchmentColor(order),
                            fillOpacity: 1.0,
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
        currentCatchmentOpacity = opacity;
        if (catchmentsLayer) {
            // Use CSS container opacity to avoid flicker from redraw()
            var container = catchmentsLayer.getContainer();
            if (container) {
                container.style.opacity = opacity;
            }
        }
    }

    /**
     * Highlight upstream catchments by segment indices.
     */
    function highlightUpstreamCatchments(segmentIndices) {
        highlightedSegments = new Set(segmentIndices);
        if (catchmentsLayer) {
            catchmentsLayer.options.vectorTileLayerStyles.catchments = function (props) {
                if (highlightedSegments.has(props.segment_idx)) {
                    return {
                        weight: 2,
                        color: '#28A745',
                        fillColor: '#28A745',
                        fillOpacity: 0.5,
                        fill: true,
                    };
                }
                return {
                    weight: 0.3,
                    color: '#999',
                    fillColor: '#ddd',
                    fillOpacity: 0.15,
                    fill: true,
                };
            };
            if (map.hasLayer(catchmentsLayer)) {
                catchmentsLayer.redraw();
            }
        }
    }

    /**
     * Clear catchment highlights, restore default style.
     */
    function clearCatchmentHighlights() {
        highlightedSegments.clear();
        setCatchmentsOpacity(currentCatchmentOpacity);
    }

    /**
     * Show upstream catchment boundary polygon.
     */
    function showSelectionBoundary(geojsonFeature) {
        clearSelectionBoundary();
        selectionBoundaryLayer = L.geoJSON(geojsonFeature, {
            style: {
                color: '#FF6B00',
                weight: 2.5,
                fillColor: '#FF6B00',
                fillOpacity: 0.1,
                dashArray: '6, 4',
            },
        }).addTo(map);
        map.fitBounds(selectionBoundaryLayer.getBounds(), { padding: [20, 20] });
    }

    /**
     * Clear selection boundary layer.
     */
    function clearSelectionBoundary() {
        if (selectionBoundaryLayer) {
            map.removeLayer(selectionBoundaryLayer);
            selectionBoundaryLayer = null;
        }
    }

    // ===== Legends =====

    var streamsLegend = null;
    var catchmentsLegend = null;

    function createStreamsLegend() {
        if (streamsLegend) return;
        streamsLegend = L.control({ position: 'bottomleft' });
        streamsLegend.onAdd = function () {
            var div = L.DomUtil.create('div', 'layer-legend');
            div.innerHTML =
                '<div class="layer-legend-title">Cieki — zlewnia [km²]</div>' +
                '<div class="legend-gradient" style="background: linear-gradient(to right, rgb(179,229,252), rgb(90,138,180), rgb(0,47,108));"></div>' +
                '<div class="legend-labels"><span>0.001</span><span>0.1</span><span>20</span></div>';
            return div;
        };
        streamsLegend.addTo(map);
    }

    function removeStreamsLegend() {
        if (streamsLegend) {
            map.removeControl(streamsLegend);
            streamsLegend = null;
        }
    }

    function createCatchmentsLegend() {
        if (catchmentsLegend) return;
        catchmentsLegend = L.control({ position: 'bottomleft' });
        catchmentsLegend.onAdd = function () {
            var div = L.DomUtil.create('div', 'layer-legend');
            var html = '<div class="layer-legend-title">Zlewnie — rząd Strahlera</div>';
            var orders = [1, 2, 3, 4, 5, 6, 7, 8];
            var colors = CATCHMENT_COLORS;
            for (var i = 0; i < orders.length; i++) {
                html += '<div class="legend-item">' +
                    '<span class="legend-swatch" style="background:' + colors[i] + '"></span>' +
                    '<span>' + orders[i] + '</span></div>';
            }
            div.innerHTML = html;
            return div;
        };
        catchmentsLegend.addTo(map);
    }

    function removeCatchmentsLegend() {
        if (catchmentsLegend) {
            map.removeControl(catchmentsLegend);
            catchmentsLegend = null;
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

    // ===== BDOT10k vector layers (lakes + streams) =====

    function loadBdotLakes() {
        return fetch('/data/bdot_lakes.geojson')
            .then(function (res) {
                if (!res.ok) throw new Error('No BDOT lakes data');
                return res.json();
            })
            .then(function (geojson) {
                bdotLakesLayer = L.geoJSON(geojson, {
                    style: {
                        color: '#1565C0',
                        weight: 1,
                        fillColor: '#42A5F5',
                        fillOpacity: 0.4,
                    },
                });
                bdotBounds = bdotLakesLayer.getBounds();
                return bdotLakesLayer;
            })
            .catch(function () { return null; });
    }

    function getBdotLakesLayer() { return bdotLakesLayer; }

    function setBdotLakesOpacity(opacity) {
        if (bdotLakesLayer) {
            bdotLakesLayer.setStyle({
                fillOpacity: opacity * 0.4,
                opacity: opacity,
            });
        }
    }

    function loadBdotStreams() {
        return fetch('/data/bdot_streams.geojson')
            .then(function (res) {
                if (!res.ok) throw new Error('No BDOT streams data');
                return res.json();
            })
            .then(function (geojson) {
                bdotStreamsLayer = L.geoJSON(geojson, {
                    style: function (feature) {
                        var src = feature.properties.source_layer || '';
                        if (src === 'OT_SWRS_L') {
                            return { color: '#0D47A1', weight: 2, opacity: 0.8 };
                        } else if (src === 'OT_SWKN_L') {
                            return { color: '#1976D2', weight: 1.5, opacity: 0.7, dashArray: '6,3' };
                        }
                        return { color: '#64B5F6', weight: 1, opacity: 0.6, dashArray: '4,4' };
                    },
                });
                if (!bdotBounds) {
                    bdotBounds = bdotStreamsLayer.getBounds();
                } else {
                    bdotBounds.extend(bdotStreamsLayer.getBounds());
                }
                return bdotStreamsLayer;
            })
            .catch(function () { return null; });
    }

    function getBdotStreamsLayer() { return bdotStreamsLayer; }

    function setBdotStreamsOpacity(opacity) {
        if (bdotStreamsLayer) {
            bdotStreamsLayer.setStyle({ opacity: opacity });
        }
    }

    function fitBdotBounds() {
        if (bdotBounds && bdotBounds.isValid()) {
            map.fitBounds(bdotBounds, { padding: [20, 20] });
        }
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
        highlightUpstreamCatchments: highlightUpstreamCatchments,
        clearCatchmentHighlights: clearCatchmentHighlights,
        showSelectionBoundary: showSelectionBoundary,
        clearSelectionBoundary: clearSelectionBoundary,
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
        // BDOT10k vectors
        loadBdotLakes: loadBdotLakes,
        getBdotLakesLayer: getBdotLakesLayer,
        setBdotLakesOpacity: setBdotLakesOpacity,
        loadBdotStreams: loadBdotStreams,
        getBdotStreamsLayer: getBdotStreamsLayer,
        setBdotStreamsOpacity: setBdotStreamsOpacity,
        fitBdotBounds: fitBdotBounds,
        // Legends
        createStreamsLegend: createStreamsLegend,
        removeStreamsLegend: removeStreamsLegend,
        createCatchmentsLegend: createCatchmentsLegend,
        removeCatchmentsLegend: removeCatchmentsLegend,
    };
})();
