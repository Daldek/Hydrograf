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
    var hsgLayer = null;

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
        L.control.zoom({ position: 'bottomright' }).addTo(map);

        // Custom panes for layer ordering:
        // Base (tilePane z-200) → NMT → Cieki → overlay (z-400)
        map.createPane('demPane');
        map.getPane('demPane').style.zIndex = 250;
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

        // Keyboard shortcuts for drawing mode
        document.addEventListener('keydown', function (e) {
            if (!drawMode) return;
            if (e.key === 'Escape') {
                cancelDrawing();
            } else if (e.key === 'Backspace') {
                e.preventDefault();
                undoLastVertex();
            }
        });
    }

    // ===== DEM Overlay =====

    function loadDemOverlay() {
        // Try tiled DEM first, fall back to single PNG overlay
        fetch('/data/dem_tiles.json', { cache: 'force-cache' })
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
                fetch('/data/dem.json', { cache: 'force-cache' })
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
        if (meta && meta.thresholds && meta.thresholds.indexOf(threshold) !== -1) {
            if (meta.format === 'pbf') {
                return '/tiles/' + layer + '_' + threshold + '/{z}/{x}/{y}.pbf';
            }
            if (meta.format === 'pmtiles') {
                return '/tiles/' + layer + '_' + threshold + '.pmtiles';
            }
        }
        // Fallback: dynamic PostGIS MVT
        return '/api/tiles/' + layer + '/{z}/{x}/{y}.pbf?threshold=' + threshold;
    }

    function loadStreamsVector(threshold) {
        if (!L.vectorGrid) { console.warn('VectorGrid plugin not loaded'); return null; }
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

        // Re-fire click to map so click mode routing works on stream features
        streamsLayer.on('click', function (e) {
            L.DomEvent.stopPropagation(e);
            map.fire('click', { latlng: e.latlng });
        });

        // Stream info via hover tooltip (not click popup)
        streamsLayer.on('mouseover', function (e) {
            if (streamTooltip) { map.removeLayer(streamTooltip); streamTooltip = null; }
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

    // ===== Selection boundary =====

    var selectionBoundaryLayer = null;

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
        var banner = document.getElementById('draw-instructions');
        if (banner) banner.classList.remove('d-none');
    }

    function addDrawVertex(latlng) {
        // Ignore duplicate vertex from dblclick (browser fires click+click+dblclick)
        if (drawVertices.length > 0) {
            var last = drawVertices[drawVertices.length - 1];
            if (Math.abs(last.lat - latlng.lat) < 0.00001 &&
                Math.abs(last.lng - latlng.lng) < 0.00001) {
                return;
            }
        }
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

    function undoLastVertex() {
        if (!drawMode || drawVertices.length === 0) return;
        drawVertices.pop();
        var lastMarker = drawMarkers.pop();
        if (lastMarker) map.removeLayer(lastMarker);
        if (drawPolyline) { map.removeLayer(drawPolyline); drawPolyline = null; }
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
        var banner = document.getElementById('draw-instructions');
        if (banner) banner.classList.add('d-none');

        // Clean up markers
        drawMarkers.forEach(function (m) { map.removeLayer(m); });
        drawMarkers = [];

        // Keep the polyline as profile line
        if (drawPolyline) {
            if (profileLine) map.removeLayer(profileLine);
            profileLine = drawPolyline;
            profileLine.setStyle({ color: '#DC3545', weight: 3, opacity: 0.8, dashArray: null });
            drawPolyline = null;
        }

        if (drawCallback) drawCallback(coords);
    }

    function cancelDrawing() {
        drawMode = false;
        map.getContainer().style.cursor = '';
        map.doubleClickZoom.enable();
        var banner = document.getElementById('draw-instructions');
        if (banner) banner.classList.add('d-none');
        drawMarkers.forEach(function (m) { map.removeLayer(m); });
        drawMarkers = [];
        if (drawPolyline) { map.removeLayer(drawPolyline); drawPolyline = null; }
        drawVertices = [];
        drawCallback = null;
        // Clear profile line from previous completed drawing
        if (profileLine) { map.removeLayer(profileLine); profileLine = null; }
    }

    function isDrawing() { return drawMode; }

    // ===== Profile line display =====

    function showProfileLine(coords) {
        clearProfileLine();
        // coords: [[lng, lat], ...] (GeoJSON order)
        var latlngs = coords.map(function (c) { return [c[1], c[0]]; });
        profileLine = L.polyline(latlngs, {
            color: '#DC3545',
            weight: 3,
            opacity: 0.8,
        }).addTo(map);
    }

    function clearProfileLine() {
        if (profileLine) { map.removeLayer(profileLine); profileLine = null; }
    }

    // Profile hover marker (shows position on line when hovering over chart)
    var profileHoverMarker = null;

    function showProfileHoverMarker(lat, lng) {
        if (profileHoverMarker) {
            profileHoverMarker.setLatLng([lat, lng]);
        } else {
            profileHoverMarker = L.circleMarker([lat, lng], {
                radius: 6,
                color: '#fff',
                fillColor: '#DC3545',
                fillOpacity: 1,
                weight: 2,
            }).addTo(map);
        }
    }

    function clearProfileHoverMarker() {
        if (profileHoverMarker) {
            map.removeLayer(profileHoverMarker);
            profileHoverMarker = null;
        }
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
            .catch(function (err) { console.warn('BDOT lakes not available:', err.message); return null; });
    }

    function getBdotLakesLayer() { return bdotLakesLayer; }

    function setBdotLakesOpacity(opacity) {
        if (bdotLakesLayer) {
            if (opacity === 0) {
                bdotLakesLayer.setStyle({
                    weight: 0,
                    fillOpacity: 0,
                    opacity: 0,
                });
            } else {
                bdotLakesLayer.setStyle({
                    weight: 1,
                    fillOpacity: opacity * 0.4,
                    opacity: opacity,
                });
            }
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
            .catch(function (err) { console.warn('BDOT streams not available:', err.message); return null; });
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

    // ===== HSG soil layer =====

    var HSG_FILL = { 'A': '#4CAF50', 'B': '#8BC34A', 'C': '#FF9800', 'D': '#F44336' };

    function loadHsgLayer() {
        return fetch('/data/soil_hsg.geojson')
            .then(function (res) {
                if (!res.ok) throw new Error('No HSG data');
                return res.json();
            })
            .then(function (geojson) {
                hsgLayer = L.geoJSON(geojson, {
                    style: function (feature) {
                        var g = feature.properties.hsg_group || 'B';
                        return {
                            color: HSG_FILL[g],
                            weight: 0.5,
                            fillColor: HSG_FILL[g],
                            fillOpacity: 0.35,
                        };
                    },
                });
                return hsgLayer;
            })
            .catch(function (err) { console.warn('HSG layer not available:', err.message); return null; });
    }

    function getHsgLayer() { return hsgLayer; }

    function setHsgOpacity(opacity) {
        if (hsgLayer) {
            if (opacity === 0) {
                hsgLayer.setStyle({ weight: 0, fillOpacity: 0, opacity: 0 });
            } else {
                hsgLayer.setStyle(function (feature) {
                    var g = feature.properties.hsg_group || 'B';
                    return {
                        color: HSG_FILL[g],
                        weight: 0.5,
                        fillColor: HSG_FILL[g],
                        fillOpacity: opacity * 0.35,
                        opacity: opacity,
                    };
                });
            }
        }
    }

    function fitHsgBounds() {
        if (hsgLayer) {
            var bounds = hsgLayer.getBounds();
            if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20] });
        }
    }

    // ===== Utilities =====

    function disableClick() { clickEnabled = false; }
    function enableClick() { clickEnabled = true; }

    function setLoadingCursor(loading) {
        if (map) map.getContainer().style.cursor = loading ? 'wait' : '';
    }

    function invalidateSize() {
        if (map) setTimeout(function () { map.invalidateSize(); }, 50);
    }

    function shiftZoomControls(show) {
        var wrapper = document.getElementById('map-wrapper');
        if (wrapper) {
            wrapper.classList.toggle('results-visible', show);
        }
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
        showSelectionBoundary: showSelectionBoundary,
        clearSelectionBoundary: clearSelectionBoundary,
        showWatershed: showWatershed,
        getWatershedLayer: getWatershedLayer,
        showOutlet: showOutlet,
        clearWatershed: clearWatershed,
        disableClick: disableClick,
        enableClick: enableClick,
        setLoadingCursor: setLoadingCursor,
        invalidateSize: invalidateSize,
        // Drawing
        startDrawing: startDrawing,
        cancelDrawing: cancelDrawing,
        undoLastVertex: undoLastVertex,
        isDrawing: isDrawing,
        // Profile
        showProfileLine: showProfileLine,
        clearProfileLine: clearProfileLine,
        showProfileHoverMarker: showProfileHoverMarker,
        clearProfileHoverMarker: clearProfileHoverMarker,
        // BDOT10k vectors
        loadBdotLakes: loadBdotLakes,
        getBdotLakesLayer: getBdotLakesLayer,
        setBdotLakesOpacity: setBdotLakesOpacity,
        loadBdotStreams: loadBdotStreams,
        getBdotStreamsLayer: getBdotStreamsLayer,
        setBdotStreamsOpacity: setBdotStreamsOpacity,
        fitBdotBounds: fitBdotBounds,
        // HSG soil
        loadHsgLayer: loadHsgLayer,
        getHsgLayer: getHsgLayer,
        setHsgOpacity: setHsgOpacity,
        fitHsgBounds: fitHsgBounds,
        // Panel/zoom interaction
        shiftZoomControls: shiftZoomControls,
        // Legends
        createStreamsLegend: createStreamsLegend,
        removeStreamsLegend: removeStreamsLegend,
    };
})();
