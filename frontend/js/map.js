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
    // Metadata of the rendered DEM (dem_tiles.json or dem.json): elevation and colour range
    var demMeta = null;
    var streamsLayer = null;
    var currentThreshold = null;
    var streamTooltip = null;
    var watershedLayer = null;
    var outletMarker = null;

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
    var hsgLayer = null;
    var landCoverLayer = null;

    // ===== Theme: overlay colours from tokens.css =====
    //
    // Leaflet writes colours into SVG attributes, where var() does not work,
    // so the tokens are read with getComputedStyle. A theme change (data-theme
    // attribute or the OS scheme) drops the cached colours and runs every
    // restyler registered with onThemeChange().

    var palette = null;
    var restylers = [];
    var _colorCtx = null;

    function token(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

    /** Any CSS colour as [r, g, b]. */
    function rgb(color) {
        if (!_colorCtx) _colorCtx = document.createElement('canvas').getContext('2d');
        _colorCtx.fillStyle = '#000000';
        _colorCtx.fillStyle = color;
        var s = _colorCtx.fillStyle;
        if (s.charAt(0) === '#') {
            return [1, 3, 5].map(function (i) { return parseInt(s.slice(i, i + 2), 16); });
        }
        return s.replace(/^rgba?\(|\)$/g, '').split(',').slice(0, 3).map(parseFloat);
    }

    /** `weight` of colour a mixed with colour b (like color-mix in srgb). */
    function mix(a, b, weight) {
        var ca = rgb(a);
        var cb = rgb(b);
        return 'rgb(' + [0, 1, 2].map(function (i) {
            return Math.round(ca[i] * weight + cb[i] * (1 - weight));
        }).join(', ') + ')';
    }

    /** Token colours of the current theme, cached until the theme changes. */
    function colors() {
        if (palette) return palette;
        var surface = token('--surface');
        var info = token('--info');
        var infoSoft = mix(info, surface, 0.35);
        palette = {
            tool: token('--tool-hydrograf'),
            surface: surface,
            accent: token('--accent'),
            info: info,
            infoSoft: infoSoft,
            warn: token('--warn'),
            streamRamp: [rgb(infoSoft), rgb(info)],
            landCover: {},
            hsg: {},
        };
        return palette;
    }

    /** Run `fn` after every theme change, when the new tokens are readable. */
    function onThemeChange(fn) { restylers.push(fn); }

    function refreshTheme() {
        palette = null;
        restylers.forEach(function (fn) { fn(); });
    }

    new MutationObserver(refreshTheme).observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme'],
    });
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', refreshTheme);

    // ===== Mouse-wheel zoom =====
    //
    // Leaflet's scroll-wheel zoom turns every 40 ms batch of wheel events into
    // at least one whole zoom level (zoomSnap 1), however small the batch.
    // Touchpads, the Magic Mouse and smooth-scrolling mouse drivers go on
    // sending a fading tail of small events after the fingers or the wheel
    // stop, so each batch of the tail zoomed one more level; and while the
    // vector base map draws the new zoom, wheel input and the zoom timer wait
    // and run after the wheel has stopped. This handler starts a zoom step
    // only on fresh input: events weaker than WHEEL_TAIL_RATIO of the
    // gesture's strongest are its tail, and input older than WHEEL_STALE_MS
    // (an event or a whole batch) is dropped.

    var WHEEL_STALE_MS = 150;        // older wheel input does not start a zoom step
    var WHEEL_GESTURE_GAP_MS = 80;   // a longer pause between events starts a new gesture
    var WHEEL_TAIL_RATIO = 0.5;      // share of the gesture's strongest event below which events are its tail

    /** Time of a wheel event on the performance.now() clock; a foreign clock counts as now. */
    function wheelEventTime(e) {
        var age = performance.now() - e.timeStamp;
        return performance.now() - (age >= 0 && age < 10000 ? age : 0);
    }

    /** Leaflet's scroll-wheel zoom without the tail of a gesture and without late input. */
    function wheelZoomHandler() {
        var Base = L.Map.ScrollWheelZoom;
        return Base.extend({
            _onWheelScroll: function (e) {
                var delta = L.DomEvent.getWheelDelta(e);
                if (delta) {
                    var t = wheelEventTime(e);
                    var size = Math.abs(delta);
                    var g = this._gesture;
                    if (performance.now() - t > WHEEL_STALE_MS) {
                        L.DomEvent.stop(e);
                        return;
                    }
                    if (!g || t - g.last > WHEEL_GESTURE_GAP_MS || (delta > 0) !== g.zoomIn) {
                        g = this._gesture = { zoomIn: delta > 0, peak: size, last: t };
                    }
                    g.last = t;
                    if (size < g.peak * WHEEL_TAIL_RATIO) {
                        L.DomEvent.stop(e);
                        return;
                    }
                    g.peak = Math.max(g.peak, size);
                    this._lastInput = t;
                }
                Base.prototype._onWheelScroll.call(this, e);
            },

            _performZoom: function () {
                // The timer ran late (the page was busy): the wheel has stopped meanwhile
                if (performance.now() - this._lastInput > WHEEL_STALE_MS) {
                    this._delta = 0;
                    this._startTime = null;
                    return;
                }
                Base.prototype._performZoom.call(this);
            },
        });
    }

    /**
     * Initialize the Leaflet map.
     * Base layer is NOT added here — layers.js handles it via setBaseLayer().
     */
    function init(onClickCallback) {
        map = L.map('map', {
            center: [51.9, 19.5],
            zoom: 7,
            zoomControl: false,
            scrollWheelZoom: false,     // replaced by wheelZoomHandler()
        });
        map.addHandler('wheelZoom', wheelZoomHandler());
        map.wheelZoom.enable();
        L.control.zoom({ position: 'bottomright' }).addTo(map);
        // Cursor coordinates, bottom left: added first, so the legends stack above it
        Hydrograf.coords.addReadout(map);

        // Custom panes for layer ordering:
        // Base (tilePane z-200) → NMT → Mapa zagrożenia powodziowego → Pokrycie terenu → Wyniki analiz → Linie spływu → delineation preview → overlay (z-400)
        map.createPane('demPane');
        map.getPane('demPane').style.zIndex = 250;
        map.createPane('hazardPane');
        map.getPane('hazardPane').style.zIndex = 255;
        map.createPane('landcoverPane');
        map.getPane('landcoverPane').style.zIndex = 260;
        map.createPane('resultsPane');
        map.getPane('resultsPane').style.zIndex = 300;
        map.createPane('streamsPane');
        map.getPane('streamsPane').style.zIndex = 350;
        map.createPane('previewPane');
        map.getPane('previewPane').style.zIndex = 390;

        // Load overlays
        loadDemOverlay();

        map.on('click', function (e) {
            // Drawing mode: add vertex
            if (drawMode) {
                addDrawVertex(e.latlng);
                return;
            }

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

        // On-screen drawing controls: phones have no Esc/Backspace and no reliable dblclick.
        // Absent in an index.html cached from before they existed; drawing still works then.
        var drawTools = document.getElementById('draw-tools');
        if (drawTools) {
            document.getElementById('draw-undo').addEventListener('click', undoLastVertex);
            document.getElementById('draw-finish').addEventListener('click', finishDrawing);
            document.getElementById('draw-cancel').addEventListener('click', cancelDrawing);
        }

        // The shell resizes panels around the map; Leaflet must re-measure.
        window.addEventListener('hydrograf:layout', function () {
            map.invalidateSize();
        });
    }

    // ===== DEM Overlay =====

    function loadDemOverlay() {
        // Try tiled DEM first, fall back to single PNG overlay
        fetch('/data/dem_tiles.json', { cache: 'no-cache' })
            .then(function (res) {
                if (!res.ok) throw new Error('tiles not found');
                return res.json();
            })
            .then(function (meta) {
                demBounds = L.latLngBounds(meta.bounds);
                demMeta = meta;
                var tileUrl = '/data/dem_tiles/{z}/{x}/{y}.png';
                if (meta.generated_at) tileUrl += '?v=' + meta.generated_at;
                demLayer = L.tileLayer(tileUrl, {
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
                fetch('/data/dem.json', { cache: 'no-cache' })
                    .then(function (res) {
                        if (!res.ok) throw new Error('DEM metadata not found');
                        return res.json();
                    })
                    .then(function (meta) {
                        demBounds = L.latLngBounds(meta.bounds);
                        demMeta = meta;
                        var demUrl = '/data/dem.png';
                        if (meta.generated_at) demUrl += '?v=' + meta.generated_at;
                        demLayer = L.imageOverlay(demUrl, demBounds, {
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
    function getDemBounds() { return demBounds; }
    function setDemOpacity(opacity) {
        if (demLayer) demLayer.setOpacity(opacity);
    }

    // ===== Streams Vector (MVT) =====

    /**
     * Position of a stream on the log10 upstream-area scale:
     * 0 at 0.0001 km² (and below), 1 at 20 km² (and above).
     */
    function flowAccT(area_km2) {
        var logVal = Math.log10(Math.max(area_km2, 0.0001));
        var t = (logVal - (-4)) / (1.3 - (-4)); // range 5.3
        return Math.max(0, Math.min(1, t));
    }

    /** Stream colour: a soft --info for tiny streams, full --info for large rivers. */
    function flowAccColor(area_km2) {
        var ramp = colors().streamRamp;
        var t = flowAccT(area_km2);
        return 'rgb(' + [0, 1, 2].map(function (i) {
            return Math.round(ramp[0][i] * (1 - t) + ramp[1][i] * t);
        }).join(', ') + ')';
    }

    /** Stream width: 0.5px (tiny streams) → 4px (large rivers). */
    function flowAccWidth(area_km2) {
        return 0.5 + flowAccT(area_km2) * 3.5;
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

        // Limit requests to the data: outside its bounds and below its first
        // zoom no tile exists and each request would answer 404.
        var meta = window.Hydrograf._tilesMeta || {};
        var extent = {};
        if (meta.bounds && meta.bounds.length === 4) {
            extent.bounds = L.latLngBounds(
                [meta.bounds[1], meta.bounds[0]],
                [meta.bounds[3], meta.bounds[2]]
            );
        }
        if (meta.min_zoom) {
            var zooms = meta.threshold_min_zoom || {};
            extent.minZoom = zooms[String(currentThreshold)] || meta.min_zoom;
        }

        streamsLayer = L.vectorGrid.protobuf(
            getTileUrl('streams', currentThreshold),
            L.extend({
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
                attribution: 'Linie spływu (flow acc)',
            }, extent)
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

    /**
     * Data extent from the vector tiles metadata (bounds as [W, S, E, N]),
     * falling back to the DEM extent.
     * @returns {L.LatLngBounds|null}
     */
    function getDataBounds() {
        var meta = window.Hydrograf._tilesMeta || {};
        if (meta.bounds && meta.bounds.length === 4) {
            return L.latLngBounds(
                [meta.bounds[1], meta.bounds[0]],
                [meta.bounds[3], meta.bounds[2]]
            );
        }
        return demBounds;
    }

    /**
     * Fit the map to the given bounds; ignores missing or invalid bounds.
     * @param {L.LatLngBounds|null} bounds
     */
    function fitToBounds(bounds) {
        if (map && bounds && bounds.isValid()) {
            map.fitBounds(bounds, { padding: [20, 20] });
        }
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
            style: watershedStyle(),
        }).addTo(map);
        map.fitBounds(selectionBoundaryLayer.getBounds(), { padding: [20, 20] });
        updateWatershedLegend();
    }

    /**
     * Clear selection boundary layer.
     */
    function clearSelectionBoundary() {
        if (selectionBoundaryLayer) {
            map.removeLayer(selectionBoundaryLayer);
            selectionBoundaryLayer = null;
            updateWatershedLegend();
        }
    }

    // ===== Delineation preview =====
    //
    // While the server merges the boundary, the sub-catchments it merges fill
    // the network up from the outlet (POST /api/delineate-watershed/preview,
    // one feature per BFS depth). The map first moves to the watershed, as
    // paths added during a zoom animation are drawn out of place; then depth
    // d appears at d / maxDepth of PREVIEW_DURATION_MS, as many levels per
    // frame as are due, and the preview pane pulses (app.css) until
    // clearDelineatePreview(). Reduced motion: all levels at once, no pulse.

    var PREVIEW_DURATION_MS = 500;
    var preview = null; // { levels: L.GeoJSON, shown: L.LayerGroup, onMoveEnd, frame }

    /** Preview: the watershed's tool colour, thinner and fainter than the result. */
    function previewStyle() {
        var c = colors();
        return { color: c.tool, weight: 1, opacity: 0.5, fillColor: c.tool, fillOpacity: 0.08 };
    }

    /**
     * Animate the preview of a pending delineation, replacing any previous one.
     * @param {Object} collection - FeatureCollection, one feature per depth
     *     (property `depth`), by increasing depth
     */
    function showDelineatePreview(collection) {
        clearDelineatePreview();
        var levels = L.geoJSON(collection, { pane: 'previewPane', style: previewStyle, interactive: false });
        var layers = levels.getLayers();
        if (!layers.length) return;

        var maxDepth = layers[layers.length - 1].feature.properties.depth;
        var instant = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        var next = 0;
        var start = null;
        var current = { levels: levels, shown: L.layerGroup().addTo(map), onMoveEnd: null, frame: null };
        preview = current;

        function step(now) {
            if (start === null) start = now;
            var reached = instant ? Infinity : (now - start) / PREVIEW_DURATION_MS * maxDepth;
            while (next < layers.length && layers[next].feature.properties.depth <= reached) {
                current.shown.addLayer(layers[next]);
                next += 1;
            }
            if (next < layers.length) {
                current.frame = requestAnimationFrame(step);
            } else {
                current.frame = null;
                map.getPane('previewPane').classList.add('waiting');
            }
        }

        // fitBounds always ends in moveend: at once when the view stays
        // or jumps, after the animation when it pans or zooms.
        current.onMoveEnd = function () {
            map.off('moveend', current.onMoveEnd);
            current.onMoveEnd = null;
            current.frame = requestAnimationFrame(step);
        };
        map.on('moveend', current.onMoveEnd);
        map.fitBounds(levels.getBounds(), { padding: [20, 20] });
    }

    /** Remove the preview and stop its animation. */
    function clearDelineatePreview() {
        if (!preview) return;
        if (preview.onMoveEnd) map.off('moveend', preview.onMoveEnd);
        if (preview.frame !== null) cancelAnimationFrame(preview.frame);
        map.removeLayer(preview.shown);
        map.getPane('previewPane').classList.remove('waiting');
        preview = null;
    }

    // ===== Legends =====

    var streamsLegend = null;

    function streamsLegendHtml() {
        return '<div class="layer-legend-title">Linie spływu — zlewnia [km²]</div>' +
            '<div class="legend-gradient" style="background: linear-gradient(to right, ' +
            flowAccColor(0.001) + ', ' + flowAccColor(0.1) + ', ' + flowAccColor(20) + ');"></div>' +
            '<div class="legend-labels"><span>0.001</span><span>0.1</span><span>20</span></div>';
    }

    function createStreamsLegend() {
        if (streamsLegend) return;
        streamsLegend = L.control({ position: 'bottomleft' });
        streamsLegend.onAdd = function () {
            var div = L.DomUtil.create('div', 'layer-legend');
            div.innerHTML = streamsLegendHtml();
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

    /**
     * Hypsometric ramp of the DEM tiles and image: COLOR_STOPS of
     * backend/utils/dem_color.py, linear in RGB between the stops. The ramp
     * spans color_min_m..color_max_m of the metadata (5th to 95th percentile of
     * the elevations); lower and higher terrain keeps the end colours.
     */
    var DEM_COLOR_STOPS = [
        [0.0, 'rgb(56, 128, 60)'],
        [0.15, 'rgb(76, 175, 80)'],
        [0.30, 'rgb(139, 195, 74)'],
        [0.45, 'rgb(205, 220, 57)'],
        [0.60, 'rgb(255, 193, 7)'],
        [0.75, 'rgb(161, 110, 60)'],
        [0.90, 'rgb(120, 100, 90)'],
        [1.0, 'rgb(245, 245, 240)'],
    ];

    var demLegend = null;

    function formatElevation(elevation_m) {
        return Math.round(elevation_m).toLocaleString('pl-PL');
    }

    function demLegendHtml(meta) {
        var lo = meta.color_min_m;
        var hi = meta.color_max_m;
        var ramp = DEM_COLOR_STOPS.map(function (s) {
            return s[1] + ' ' + Math.round(s[0] * 100) + '%';
        }).join(', ');
        return '<div class="layer-legend-title">Wysokość terenu [m n.p.m.]</div>' +
            '<div class="legend-gradient" style="background: linear-gradient(to right, ' + ramp + ');"></div>' +
            '<div class="legend-labels"><span>≤\u00A0' + formatElevation(lo) + '</span>' +
            '<span>' + formatElevation((lo + hi) / 2) + '</span>' +
            '<span>≥\u00A0' + formatElevation(hi) + '</span></div>' +
            '<div class="layer-legend-note">Skala barw: 5.–95. percentyl wysokości, poza nim barwy skrajne' +
            ' (cały NMT: ' + formatElevation(meta.elevation_min_m) + '–' + formatElevation(meta.elevation_max_m) +
            '\u00A0m n.p.m.). Cieniowanie rzeźby przyciemnia stoki.</div>';
    }

    /** Legend of the DEM layer; none for metadata without the colour and elevation range. */
    function createDemLegend() {
        if (demLegend || !demMeta) return;
        var keys = ['color_min_m', 'color_max_m', 'elevation_min_m', 'elevation_max_m'];
        if (!keys.every(function (k) { return typeof demMeta[k] === 'number'; })) return;
        demLegend = L.control({ position: 'bottomleft' });
        demLegend.onAdd = function () {
            var div = L.DomUtil.create('div', 'layer-legend');
            div.innerHTML = demLegendHtml(demMeta);
            return div;
        };
        demLegend.addTo(map);
    }

    function removeDemLegend() {
        if (demLegend) {
            map.removeControl(demLegend);
            demLegend = null;
        }
    }

    var hsgLegend = null;

    function hsgLegendHtml() {
        return '<div class="layer-legend-title">Grupy glebowe HSG</div>' +
            ['A', 'B', 'C', 'D'].map(function (g) {
                return '<div class="legend-item"><span class="legend-swatch" style="background:' +
                    hsgColor(g) + ';"></span> ' + g + '</div>';
            }).join('');
    }

    function createHsgLegend() {
        if (hsgLegend) return;
        hsgLegend = L.control({ position: 'bottomleft' });
        hsgLegend.onAdd = function () {
            var div = L.DomUtil.create('div', 'layer-legend');
            div.innerHTML = hsgLegendHtml();
            return div;
        };
        hsgLegend.addTo(map);
    }

    function removeHsgLegend() {
        if (hsgLegend) {
            map.removeControl(hsgLegend);
            hsgLegend = null;
        }
    }

    // ===== Watershed display =====

    /** Delineated catchment: tool colour outline with a light fill of the same colour. */
    function watershedStyle() {
        var c = colors();
        return { color: c.tool, weight: 2.5, opacity: 1, fillColor: c.tool, fillOpacity: 0.12 };
    }

    /** Outlet: tool colour ring on the surface colour. */
    function outletStyle() {
        var c = colors();
        return { radius: 6, color: c.tool, weight: 3, opacity: 1, fillColor: c.surface, fillOpacity: 1 };
    }

    function showWatershed(geojsonFeature) {
        clearWatershed();
        watershedLayer = L.geoJSON(geojsonFeature, {
            style: watershedStyle(),
        }).addTo(map);
        updateWatershedLegend();
        map.fitBounds(watershedLayer.getBounds(), { padding: [20, 20] });
    }

    function getWatershedLayer() { return watershedLayer; }

    function showOutlet(lat, lng, elevation) {
        if (outletMarker) map.removeLayer(outletMarker);
        outletMarker = L.circleMarker([lat, lng], outletStyle()).addTo(map);
        updateWatershedLegend();
        outletMarker.bindTooltip(
            'Ujście: ' + elevation.toFixed(1) + ' m n.p.m.',
            { permanent: false, direction: 'top' }
        );
    }

    function clearWatershed() {
        if (watershedLayer) { map.removeLayer(watershedLayer); watershedLayer = null; }
        if (outletMarker) { map.removeLayer(outletMarker); outletMarker = null; }
        clearLongestFlowPath();
        clearDivideFlowPath();
        clearMainChannel();
        updateWatershedLegend();
    }

    // ===== Main channel display =====

    var mainChannelLayer = null;

    /**
     * Main channel style: BDOT-matched segments (is_real_stream) in full
     * --info, the rest of the channel thinner and translucent.
     */
    function mainChannelStyle(feature) {
        var info = colors().info;
        var isReal = feature && feature.properties && feature.properties.is_real_stream;
        return isReal
            ? { color: info, weight: 3, opacity: 0.9 }
            : { color: info, weight: 2, opacity: 0.45 };
    }

    /**
     * Show main channel on map with BDOT stream highlighting.
     *
     * Accepts either a FeatureCollection (per-segment features with
     * is_real_stream property) or a plain LineString geometry, drawn as
     * the full channel.
     */
    function showMainChannel(geojson) {
        clearMainChannel();
        if (!geojson) return;
        mainChannelLayer = L.geoJSON(geojson, {
            style: mainChannelStyle,
            interactive: false,
        }).addTo(map);
        updateWatershedLegend();
    }

    function clearMainChannel() {
        if (mainChannelLayer) {
            map.removeLayer(mainChannelLayer);
            mainChannelLayer = null;
            updateWatershedLegend();
        }
    }

    // ===== Flow paths: the longest one and the one from the watershed boundary =====
    //
    // Both in the warning colour; long dashes and round dots tell them apart,
    // also where they run along the same cells (the dots are drawn on top).

    var longestFlowPathLayer = null;
    var divideFlowPathLayer = null;

    function longestFlowPathStyle() {
        return { color: colors().warn, weight: 2.5, opacity: 0.9, dashArray: '12,8' };
    }

    function divideFlowPathStyle() {
        return { color: colors().warn, weight: 4, opacity: 0.9, dashArray: '0.1,8', lineCap: 'round' };
    }

    function showLongestFlowPath(geojson) {
        clearLongestFlowPath();
        if (!geojson) return;
        longestFlowPathLayer = L.geoJSON(geojson, {
            style: longestFlowPathStyle(),
            interactive: false,
        }).addTo(map);
        if (divideFlowPathLayer) divideFlowPathLayer.bringToFront();
        updateWatershedLegend();
    }

    function clearLongestFlowPath() {
        if (longestFlowPathLayer) {
            map.removeLayer(longestFlowPathLayer);
            longestFlowPathLayer = null;
            updateWatershedLegend();
        }
    }

    function showDivideFlowPath(geojson) {
        clearDivideFlowPath();
        if (!geojson) return;
        divideFlowPathLayer = L.geoJSON(geojson, {
            style: divideFlowPathStyle(),
            interactive: false,
        }).addTo(map);
        updateWatershedLegend();
    }

    function clearDivideFlowPath() {
        if (divideFlowPathLayer) {
            map.removeLayer(divideFlowPathLayer);
            divideFlowPathLayer = null;
            updateWatershedLegend();
        }
    }

    // ===== Watershed legend =====
    //
    // While a watershed is shown, a legend lists the parts of it on the map,
    // each with a swatch in the style of its layer.

    var watershedLegend = null;
    // The option „Sieć zlewni” takes the watershed off the map (setWatershedShown)
    var watershedHidden = false;

    function escapeAttr(value) {
        return String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
    }

    /** SVG swatch of a Leaflet path style: a line, an area (`area`) or a circle marker (`point`). */
    function pathSwatch(style, shape) {
        var attrs = ' stroke="' + escapeAttr(style.color) + '" stroke-width="' + style.weight + '"' +
            ' stroke-opacity="' + style.opacity + '"' +
            // Leaflet's default caps and joins are round
            ' stroke-linecap="' + (style.lineCap || 'round') + '" stroke-linejoin="round"' +
            (style.dashArray ? ' stroke-dasharray="' + style.dashArray + '"' : '');
        var fill = ' fill="' + escapeAttr(style.fillColor) + '" fill-opacity="' + style.fillOpacity + '"';
        var body;
        if (shape === 'area') {
            body = '<rect x="2" y="3" width="28" height="10" rx="2"' + fill + attrs + '/>';
        } else if (shape === 'point') {
            body = '<circle cx="16" cy="8" r="' + style.radius + '"' + fill + attrs + '/>';
        } else {
            body = '<line x1="2" y1="8" x2="30" y2="8" fill="none"' + attrs + '/>';
        }
        return '<svg class="legend-line" width="32" height="16" viewBox="0 0 32 16" aria-hidden="true">' +
            body + '</svg>';
    }

    /** Main channel segments on the map: BDOT10k-matched (`real`) and the rest (`dem`). */
    function mainChannelKinds() {
        var kinds = { real: false, dem: false };
        if (mainChannelLayer) {
            mainChannelLayer.eachLayer(function (layer) {
                var props = layer.feature && layer.feature.properties;
                kinds[props && props.is_real_stream ? 'real' : 'dem'] = true;
            });
        }
        return kinds;
    }

    function watershedLegendRows() {
        var rows = [];
        if (selectionBoundaryLayer || watershedLayer) {
            rows.push([pathSwatch(watershedStyle(), 'area'), 'Granica zlewni']);
        }
        if (outletMarker) rows.push([pathSwatch(outletStyle(), 'point'), 'Ujście']);
        var channel = mainChannelKinds();
        if (channel.real) {
            rows.push([pathSwatch(mainChannelStyle({ properties: { is_real_stream: true } })),
                'Ciek główny (BDOT10k)']);
        }
        if (channel.dem) {
            rows.push([pathSwatch(mainChannelStyle({ properties: { is_real_stream: false } })),
                'Ciek główny (z NMT)']);
        }
        if (longestFlowPathLayer) {
            rows.push([pathSwatch(longestFlowPathStyle()), 'Najdłuższa droga spływu']);
        }
        if (divideFlowPathLayer) {
            rows.push([pathSwatch(divideFlowPathStyle()), 'Najdłuższa droga spływu od granicy zlewni']);
        }
        return rows;
    }

    /** Show, update or remove the watershed legend after a change of its layers or the theme. */
    function updateWatershedLegend() {
        if (!map) return;
        var rows = watershedHidden ? [] : watershedLegendRows();
        if (!rows.length) {
            if (watershedLegend) {
                map.removeControl(watershedLegend);
                watershedLegend = null;
            }
            return;
        }
        if (!watershedLegend) {
            watershedLegend = L.control({ position: 'bottomleft' });
            watershedLegend.onAdd = function () {
                return L.DomUtil.create('div', 'layer-legend watershed-legend');
            };
            watershedLegend.addTo(map);
        }
        watershedLegend.getContainer().innerHTML = '<div class="layer-legend-title">Zlewnia</div>' +
            rows.map(function (row) {
                return '<div class="legend-item">' + row[0] + '<span>' + row[1] + '</span></div>';
            }).join('');
    }

    /**
     * Take the watershed of „Jedna zlewnia” off the map, or put it back, without
     * clearing it: the option „Sieć zlewni” shows its network alone (js/network.js).
     * @param {boolean} shown
     */
    function setWatershedShown(shown) {
        if (!map) return;
        watershedHidden = !shown;
        [selectionBoundaryLayer, watershedLayer, outletMarker, mainChannelLayer,
         longestFlowPathLayer, divideFlowPathLayer].forEach(function (layer) {
            if (!layer) return;
            if (shown && !map.hasLayer(layer)) layer.addTo(map);
            if (!shown && map.hasLayer(layer)) map.removeLayer(layer);
        });
        if (shown && divideFlowPathLayer) divideFlowPathLayer.bringToFront();
        updateWatershedLegend();
    }

    // ===== Profile line styles =====

    function drawLineStyle() {
        return { color: colors().accent, weight: 2, opacity: 1, dashArray: '6, 4' };
    }

    function profileLineStyle() {
        return { color: colors().accent, weight: 3, opacity: 0.9, dashArray: null };
    }

    /** Vertex and chart-hover markers: accent dot with a surface ring. */
    function pointStyle(radius) {
        var c = colors();
        return { radius: radius, color: c.surface, weight: 2, opacity: 1, fillColor: c.accent, fillOpacity: 1 };
    }

    // ===== Drawing mode (polyline for terrain profile) =====

    // A tap or click this close to the last vertex ends the line instead of adding a
    // vertex: the second tap of a double tap never lands on the exact same spot.
    var FINISH_TAP_PX = 20;

    function setDrawUi(active) {
        var banner = document.getElementById('draw-instructions');
        if (banner) banner.classList.toggle('d-none', !active);
        var tools = document.getElementById('draw-tools');
        if (tools) tools.hidden = !active;
        if (active) updateDrawCount();
    }

    function pointsLabel(n) {
        var lastDigit = n % 10, lastTwo = n % 100;
        var few = lastDigit >= 2 && lastDigit <= 4 && (lastTwo < 12 || lastTwo > 14);
        return n + (few ? ' punkty' : ' punktów');
    }

    function updateDrawCount() {
        var n = drawVertices.length;
        if (!document.getElementById('draw-tools')) return;
        document.getElementById('draw-count').textContent =
            n === 0 ? 'Wskaż początek profilu' :
            n === 1 ? '1 punkt — wskaż kolejny' :
            pointsLabel(n) + ' — dotknij ostatniego, aby narysować profil';
        document.getElementById('draw-undo').disabled = n === 0;
        document.getElementById('draw-finish').disabled = n < 2;
    }

    function startDrawing(onComplete) {
        drawMode = true;
        drawVertices = [];
        drawMarkers = [];
        drawPolyline = null;
        drawCallback = onComplete;
        map.getContainer().style.cursor = 'crosshair';
        // Disable double-click zoom during drawing
        map.doubleClickZoom.disable();
        setDrawUi(true);
    }

    function addDrawVertex(latlng) {
        if (drawVertices.length > 0) {
            var last = drawVertices[drawVertices.length - 1];
            var gap = map.latLngToContainerPoint(latlng).distanceTo(map.latLngToContainerPoint(last));
            if (gap <= FINISH_TAP_PX) {
                if (drawVertices.length >= 2) finishDrawing();
                return;
            }
        }
        drawVertices.push(latlng);

        var marker = L.circleMarker(latlng, pointStyle(5)).addTo(map);
        drawMarkers.push(marker);

        // Update polyline
        if (drawPolyline) map.removeLayer(drawPolyline);
        if (drawVertices.length > 1) {
            drawPolyline = L.polyline(drawVertices, drawLineStyle()).addTo(map);
        }
        updateDrawCount();
    }

    function undoLastVertex() {
        if (!drawMode || drawVertices.length === 0) return;
        drawVertices.pop();
        var lastMarker = drawMarkers.pop();
        if (lastMarker) map.removeLayer(lastMarker);
        if (drawPolyline) { map.removeLayer(drawPolyline); drawPolyline = null; }
        if (drawVertices.length > 1) {
            drawPolyline = L.polyline(drawVertices, drawLineStyle()).addTo(map);
        }
        updateDrawCount();
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
        setDrawUi(false);

        // Clean up markers
        drawMarkers.forEach(function (m) { map.removeLayer(m); });
        drawMarkers = [];

        // Keep the polyline as profile line
        if (drawPolyline) {
            if (profileLine) map.removeLayer(profileLine);
            profileLine = drawPolyline;
            profileLine.setStyle(profileLineStyle());
            drawPolyline = null;
        }

        if (drawCallback) drawCallback(coords);
    }

    function cancelDrawing() {
        drawMode = false;
        map.getContainer().style.cursor = '';
        map.doubleClickZoom.enable();
        setDrawUi(false);
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
        profileLine = L.polyline(latlngs, profileLineStyle()).addTo(map);
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
            profileHoverMarker = L.circleMarker([lat, lng], pointStyle(6)).addTo(map);
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
                var info = colors().info;
                bdotLakesLayer = L.geoJSON(geojson, {
                    style: {
                        color: info,
                        weight: 1,
                        fillColor: info,
                        fillOpacity: 0.4,
                    },
                });
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

    /** BDOT10k streams: rivers (SWRS) and canals (SWKN) in --info, ditches softer. */
    function bdotStreamColor(feature) {
        var src = feature.properties.source_layer || '';
        var c = colors();
        return (src === 'OT_SWRS_L' || src === 'OT_SWKN_L') ? c.info : c.infoSoft;
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
                        var color = bdotStreamColor(feature);
                        if (src === 'OT_SWRS_L') {
                            return { color: color, weight: 2, opacity: 0.8 };
                        } else if (src === 'OT_SWKN_L') {
                            return { color: color, weight: 1.5, opacity: 0.7, dashArray: '6,3' };
                        }
                        return { color: color, weight: 1, opacity: 0.6, dashArray: '4,4' };
                    },
                });
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

    // ===== HSG soil layer =====

    /** HSG group colour, shared with the HSG chart (charts.js palette). */
    function hsgColor(group) {
        var memo = colors().hsg;
        if (!(group in memo)) memo[group] = Hydrograf.charts.hsgColor(group);
        return memo[group];
    }

    function hsgFeatureColor(feature) {
        return hsgColor(feature.properties.hsg_group || 'B');
    }

    function loadHsgLayer() {
        return fetch('/data/soil_hsg.geojson')
            .then(function (res) {
                if (!res.ok) throw new Error('No HSG data');
                return res.json();
            })
            .then(function (geojson) {
                hsgLayer = L.geoJSON(geojson, {
                    style: function (feature) {
                        var color = hsgFeatureColor(feature);
                        return {
                            color: color,
                            weight: 0.5,
                            fillColor: color,
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
                hsgLayer.setStyle({ weight: 0.5, fillOpacity: opacity * 0.35, opacity: opacity });
            }
        }
    }

    // ===== Land Cover (MVT) =====

    // Land cover classes in legend order, labels for the map legend
    var LANDCOVER_LEGEND = [
        ['las', 'Las'],
        ['łąka', 'Łąka'],
        ['grunt_orny', 'Grunt orny'],
        ['zabudowa_mieszkaniowa', 'Zabudowa mieszk.'],
        ['zabudowa_przemysłowa', 'Zabudowa przem.'],
        ['droga', 'Droga'],
        ['woda', 'Woda'],
        ['inny', 'Inny'],
    ];

    /** Land cover class colour, shared with the land cover chart (charts.js palette). */
    function landCoverColor(category) {
        var memo = colors().landCover;
        if (!(category in memo)) memo[category] = Hydrograf.charts.landCoverColor(category);
        return memo[category];
    }

    function loadLandCoverVector() {
        if (!L.vectorGrid) { console.warn('VectorGrid plugin not loaded'); return null; }
        if (landCoverLayer && map.hasLayer(landCoverLayer)) {
            map.removeLayer(landCoverLayer);
        }

        landCoverLayer = L.vectorGrid.protobuf(
            '/api/tiles/landcover/{z}/{x}/{y}.pbf',
            {
                pane: 'landcoverPane',
                vectorTileLayerStyles: {
                    landcover: function (properties) {
                        var color = landCoverColor(properties.category || 'inny');
                        return {
                            fill: true,
                            fillColor: color,
                            fillOpacity: 0.6,
                            stroke: false,
                            weight: 0,
                        };
                    }
                },
                interactive: false,
                minZoom: 8,
                maxZoom: 18,
                maxNativeZoom: 18,
                attribution: 'Pokrycie terenu (BDOT10k)',
            }
        );

        return landCoverLayer;
    }

    function getLandCoverLayer() { return landCoverLayer; }

    function setLandCoverOpacity(opacity) {
        if (landCoverLayer) {
            var container = landCoverLayer.getContainer();
            if (container) {
                container.style.opacity = opacity;
            }
        }
    }

    var landCoverLegend = null;

    function landCoverLegendHtml() {
        return '<div class="layer-legend-title">Pokrycie terenu</div>' +
            LANDCOVER_LEGEND.map(function (entry) {
                return '<div class="legend-item"><span class="legend-swatch" style="background:' +
                    landCoverColor(entry[0]) + ';"></span> ' + entry[1] + '</div>';
            }).join('');
    }

    function createLandCoverLegend() {
        if (landCoverLegend) return;
        landCoverLegend = L.control({ position: 'bottomleft' });
        landCoverLegend.onAdd = function () {
            var div = L.DomUtil.create('div', 'layer-legend');
            div.innerHTML = landCoverLegendHtml();
            return div;
        };
        landCoverLegend.addTo(map);
    }

    function removeLandCoverLegend() {
        if (landCoverLegend) {
            map.removeControl(landCoverLegend);
            landCoverLegend = null;
        }
    }

    // ===== Utilities =====

    function setLoadingCursor(loading) {
        if (map) map.getContainer().style.cursor = loading ? 'wait' : '';
    }

    function invalidateSize() {
        if (map) setTimeout(function () { map.invalidateSize(); }, 50);
    }

    // ===== Theme change: restyle every live overlay =====

    onThemeChange(function () {
        if (!map) return;
        var c = colors();
        if (selectionBoundaryLayer) selectionBoundaryLayer.setStyle(watershedStyle());
        if (preview) preview.levels.setStyle(previewStyle);
        if (watershedLayer) watershedLayer.setStyle(watershedStyle());
        if (outletMarker) outletMarker.setStyle(outletStyle());
        if (mainChannelLayer) mainChannelLayer.setStyle(mainChannelStyle);
        if (longestFlowPathLayer) longestFlowPathLayer.setStyle(longestFlowPathStyle());
        if (divideFlowPathLayer) divideFlowPathLayer.setStyle(divideFlowPathStyle());
        drawMarkers.forEach(function (m) { m.setStyle(pointStyle(5)); });
        if (drawPolyline) drawPolyline.setStyle(drawLineStyle());
        if (profileLine) profileLine.setStyle(profileLineStyle());
        if (profileHoverMarker) profileHoverMarker.setStyle(pointStyle(6));
        // Colours only: the opacity set from the layers panel stays
        if (bdotLakesLayer) bdotLakesLayer.setStyle({ color: c.info, fillColor: c.info });
        if (bdotStreamsLayer) {
            bdotStreamsLayer.setStyle(function (f) { return { color: bdotStreamColor(f) }; });
        }
        if (hsgLayer) {
            hsgLayer.setStyle(function (f) {
                var color = hsgFeatureColor(f);
                return { color: color, fillColor: color };
            });
        }
        // Vector tiles take their style when drawn: redraw the visible ones
        if (streamsLayer && map.hasLayer(streamsLayer)) streamsLayer.redraw();
        if (landCoverLayer && map.hasLayer(landCoverLayer)) landCoverLayer.redraw();
        if (streamsLegend) streamsLegend.getContainer().innerHTML = streamsLegendHtml();
        if (hsgLegend) hsgLegend.getContainer().innerHTML = hsgLegendHtml();
        if (landCoverLegend) landCoverLegend.getContainer().innerHTML = landCoverLegendHtml();
        updateWatershedLegend();
    });

    window.Hydrograf.map = {
        init: init,
        _getMap: function () { return map; },
        // Theme: token colours for overlays drawn by other modules
        token: token,
        mix: mix,
        onThemeChange: onThemeChange,
        // Legend swatch in the style of a Leaflet path (the network's legend, js/network.js)
        pathSwatch: pathSwatch,
        getDemLayer: getDemLayer,
        getDemBounds: getDemBounds,
        getDataBounds: getDataBounds,
        fitToBounds: fitToBounds,
        setDemOpacity: setDemOpacity,
        getStreamsLayer: getStreamsLayer,
        getStreamsThreshold: getStreamsThreshold,
        loadStreamsVector: loadStreamsVector,
        setStreamsOpacity: setStreamsOpacity,
        showSelectionBoundary: showSelectionBoundary,
        clearSelectionBoundary: clearSelectionBoundary,
        showDelineatePreview: showDelineatePreview,
        clearDelineatePreview: clearDelineatePreview,
        showWatershed: showWatershed,
        getWatershedLayer: getWatershedLayer,
        showOutlet: showOutlet,
        clearWatershed: clearWatershed,
        showMainChannel: showMainChannel,
        clearMainChannel: clearMainChannel,
        setWatershedShown: setWatershedShown,
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
        // HSG soil
        loadHsgLayer: loadHsgLayer,
        getHsgLayer: getHsgLayer,
        setHsgOpacity: setHsgOpacity,
        // Land Cover (MVT)
        loadLandCoverVector: loadLandCoverVector,
        getLandCoverLayer: getLandCoverLayer,
        setLandCoverOpacity: setLandCoverOpacity,
        // Longest flow path (from divide)
        showLongestFlowPath: showLongestFlowPath,
        clearLongestFlowPath: clearLongestFlowPath,
        // Divide flow path (from watershed boundary)
        showDivideFlowPath: showDivideFlowPath,
        clearDivideFlowPath: clearDivideFlowPath,
        // Legends
        createStreamsLegend: createStreamsLegend,
        removeStreamsLegend: removeStreamsLegend,
        createDemLegend: createDemLegend,
        removeDemLegend: removeDemLegend,
        createHsgLegend: createHsgLegend,
        removeHsgLegend: removeHsgLegend,
        createLandCoverLegend: createLandCoverLegend,
        removeLandCoverLegend: removeLandCoverLegend,
    };
})();
