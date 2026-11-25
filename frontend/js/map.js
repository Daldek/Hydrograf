/**
 * Hydrograf Map module: the one owner of the map's library (Nogat's plan
 * 2026-11-24-hydrograf-maplibre, M12).
 *
 * MapLibre GL JS 6.14.0 (vendor/maplibre-gl-6.14.0/) draws the map. Its ES module is
 * loaded by import() from this classic script, so the map comes later than the page's
 * scripts: init() returns Hydrograf.map.ready, a promise that resolves to true once the
 * map is drawn and to false when it cannot be (no WebGL 2, M13); it never rejects. The
 * other modules ask Hydrograf.map for what they show (overlays by id, their opacity
 * and extent, points, legends, the view); none of them touches the library.
 *
 * The map's setup, its slots, its tooltip and its drawing (M3, M4, M9, M10) are
 * functions here free of Hydrograf's other modules, so that a map shell of Nogat's kit
 * can lift them (the plan's open question 7).
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    // MapLibre's module; it starts its worker from maplibre-gl-worker.mjs beside it
    var LIBRARY = 'vendor/maplibre-gl-6.14.0/maplibre-gl.mjs';
    // The names of the base map's grey style: Noto Sans 2.0 of openmaptiles/fonts, vendored
    var GLYPHS = 'vendor/openmaptiles-fonts-2.0/{fontstack}/{range}.pbf';
    var NO_WEBGL = 'Mapa wymaga przeglądarki z WebGL 2.';
    var NO_MAP = 'Nie udało się wczytać mapy. Odśwież stronę.';
    // Up to this width the map's credit folds at the first drag (Nogat DEV-15.15)
    var PHONE = '(max-width: 860px)';
    // The view before the data's extent is known; the map's closest zoom. MapLibre's
    // world is 512 px wide: every zoom is one less than Leaflet's for the same scale
    var START = { center: [19.5, 51.9], zoom: 6 };
    var MAX_ZOOM = 21;
    var FIT_PADDING_PX = 20;
    // A zoom farther than this from the view is jumped to, not animated
    var ANIMATED_ZOOMS = 4;
    var FIT_DURATION_MS = 250;

    var maplibregl = null;
    var map = null;
    var clickCallback = null;
    var resolveReady = null;
    var ready = new Promise(function (resolve) { resolveReady = resolve; });

    /** An address of the site as MapLibre asks for it: absolute, its {z} braces kept. */
    function absolute(path) {
        return new URL(path, document.baseURI).href.replace(/%7B/gi, '{').replace(/%7D/gi, '}');
    }

    // ===== Theme: overlay colours from tokens.css =====
    //
    // MapLibre paints with colours, not with var(), so the tokens are read with
    // getComputedStyle. A theme change (data-theme attribute or the OS scheme) drops
    // the cached colours and runs every restyler registered with onThemeChange().

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

    function rgbText(values) {
        return 'rgb(' + values.map(Math.round).join(', ') + ')';
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

    // ===== The order of the layers (M4) =====
    //
    // Empty layers name the slots of the map's groups, from the bottom up: the base map
    // (the kit's maplibreBasemap), the DEM, the flood hazard map, the land cover, the
    // results of analyses, the streams, the delineation preview, the overlays of the
    // layers panel, the watershed, the network and the drawing. A layer of a group goes
    // in under its group's slot, above the groups below; within a group the overlays
    // keep the order of OVERLAY_ORDER (results among themselves the order they came
    // in). The network's points and labels are DOM markers over the canvas.

    var GROUPS = ['basemap', 'dem', 'hazard', 'landcover', 'results', 'streams', 'preview',
        'overlays', 'watershed', 'network', 'drawing'];
    var OVERLAY_ORDER = [
        ['dem', 'dem'],
        ['hazard', 'hazard'],
        ['landcover', 'landcover'],
        ['result', 'results'],
        ['streams', 'streams'],
        ['preview', 'preview'],
        ['bdot-lakes', 'overlays'],
        ['hsg', 'overlays'],
        ['bdot-streams', 'overlays'],
        ['depressions', 'overlays'],
        ['sewer', 'overlays'],
        ['watershed', 'watershed'],
        ['main-channel', 'watershed'],
        ['longest-flow-path', 'watershed'],
        ['divide-flow-path', 'watershed'],
        ['outlet', 'watershed'],
        ['network', 'network'],
        ['draw', 'drawing'],
        ['profile-line', 'drawing'],
        ['profile-marker', 'drawing'],
        ['identify-marker', 'drawing'],
    ];

    function slot(group) { return 'slot:' + group; }

    /** The rank and group of an overlay id ('result:<id>' ranks as 'result'). */
    function placeOf(id) {
        var kind = id.split(':')[0];
        for (var i = 0; i < OVERLAY_ORDER.length; i++) {
            if (OVERLAY_ORDER[i][0] === kind) return { rank: i, group: OVERLAY_ORDER[i][1] };
        }
        throw new Error('Unknown overlay ' + id);
    }

    /** The map's style before any overlay: its background and the empty slots. */
    function emptyStyle() {
        return {
            version: 8,
            glyphs: absolute(GLYPHS),
            sources: {},
            layers: [{ id: 'background', type: 'background', paint: { 'background-color': token('--surface-2') } }]
                .concat(GROUPS.map(function (group) {
                    return { id: slot(group), type: 'background', layout: { visibility: 'none' } };
                })),
        };
    }

    // ===== Overlays =====
    //
    // An overlay is what the map shows under one id (describe()): its sources and style
    // layers, shown or hidden as one, with one opacity that multiplies the opacities of
    // its paint (the layers panel's slider). A layer's paint is a function, read again
    // after a change of theme.

    var OPACITY = {
        'fill-opacity': true,
        'line-opacity': true,
        'circle-opacity': true,
        'circle-stroke-opacity': true,
        'raster-opacity': true,
    };
    var overlays = {};      // id → { id, rank, group, sources, layers, opacity, shown, … }
    var layerOverlay = {};  // style layer id → overlay id

    function scaled(value, factor) {
        if (factor === 1) return value;
        return typeof value === 'number' ? value * factor : ['*', value, factor];
    }

    /** A layer's paint with the opacities multiplied by its overlay's; `only` the opacities. */
    function paintOf(o, layer, only) {
        var own = layer.paint();
        var paint = {};
        Object.keys(own).forEach(function (name) {
            if (OPACITY[name]) paint[name] = scaled(own[name], o.opacity);
            else if (!only) paint[name] = own[name];
        });
        return paint;
    }

    /** The style layer before which a layer of overlay `o` goes. */
    function beneath(o) {
        var order = map.getLayersOrder();
        for (var i = 0; i < order.length; i++) {
            var other = overlays[layerOverlay[order[i]]];
            if (other && other !== o && other.group === o.group && other.rank > o.rank) return order[i];
        }
        return slot(o.group);
    }

    /**
     * Put an overlay on the map in place of one of the same id.
     * @param {Object} spec - `id`; `sources` {id: MapLibre source}; `layers`, each a
     *     MapLibre layer whose `paint` is a function of no argument; `opacity` (1),
     *     `shown` (true), `bounds` [west, south, east, north], `point` [lng, lat] of an
     *     overlay of one point, `tooltip` (properties, feature) → {text|html, at} or null.
     * @returns {?Object} The overlay; null without a map.
     */
    function addOverlay(spec) {
        if (!map) return null;
        removeOverlay(spec.id);
        var place = placeOf(spec.id);
        var o = {
            id: spec.id,
            rank: place.rank,
            group: place.group,
            sources: Object.keys(spec.sources || {}),
            layers: [],
            opacity: spec.opacity === undefined ? 1 : spec.opacity,
            shown: spec.shown !== false,
            bounds: spec.bounds || null,
            point: spec.point || null,
            tooltip: spec.tooltip || null,
        };
        o.sources.forEach(function (id) { map.addSource(id, spec.sources[id]); });
        overlays[o.id] = o;
        var before = beneath(o);
        spec.layers.forEach(function (layer) {
            var entry = { id: layer.id, paint: layer.paint, filter: layer.filter || null,
                minzoom: layer.minzoom, maxzoom: layer.maxzoom };
            var style = { id: layer.id, type: layer.type, paint: paintOf(o, entry, false),
                layout: Object.assign({}, layer.layout, { visibility: o.shown ? 'visible' : 'none' }) };
            ['source', 'source-layer', 'filter', 'minzoom', 'maxzoom'].forEach(function (key) {
                if (layer[key] !== undefined && layer[key] !== null) style[key] = layer[key];
            });
            map.addLayer(style, before);
            layerOverlay[layer.id] = o.id;
            o.layers.push(entry);
        });
        return o;
    }

    function removeOverlay(id) {
        var o = overlays[id];
        if (!o || !map) return;
        o.layers.forEach(function (layer) {
            if (map.getLayer(layer.id)) map.removeLayer(layer.id);
            delete layerOverlay[layer.id];
        });
        o.sources.forEach(function (source) {
            if (map.getSource(source)) map.removeSource(source);
        });
        delete overlays[id];
        if (tip.overlay === id) hideTooltip();
    }

    /** Whether the overlay is on the map and shown (at any zoom). */
    function hasOverlay(id) {
        var o = overlays[id];
        return !!(o && o.shown);
    }

    function setOverlayShown(id, shown) {
        var o = overlays[id];
        if (!o || !map || o.shown === shown) return;
        o.shown = shown;
        o.layers.forEach(function (layer) {
            map.setLayoutProperty(layer.id, 'visibility', shown ? 'visible' : 'none');
        });
        if (!shown && tip.overlay === id) hideTooltip();
    }

    /** The opacity of an overlay as a whole, 0..1: its paint's opacities times it. */
    function setOverlayOpacity(id, opacity) {
        var o = overlays[id];
        if (!o || !map) return;
        o.opacity = opacity;
        applyPaint(o, true);
    }

    /** Set an overlay's paint again: its opacities (`only`) or all of it (theme). */
    function applyPaint(o, only) {
        o.layers.forEach(function (layer) {
            var paint = paintOf(o, layer, only);
            Object.keys(paint).forEach(function (name) {
                map.setPaintProperty(layer.id, name, paint[name]);
            });
        });
    }

    /** Show only the features of an overlay that pass `filter` (null: all of them). */
    function setOverlayFilter(id, filter) {
        var o = overlays[id];
        if (!o || !map) return;
        o.layers.forEach(function (layer) {
            var own = layer.filter;
            map.setFilter(layer.id, filter && own ? ['all', own, filter] : filter || own);
        });
    }

    function overlayBounds(id) {
        var o = overlays[id];
        return o ? o.bounds : null;
    }

    function drawnAt(layer, zoom) {
        return (layer.minzoom === undefined || zoom >= layer.minzoom) &&
            (layer.maxzoom === undefined || zoom < layer.maxzoom);
    }

    /**
     * Whether the view's zoom lies within the zoom range of the overlay's layers, shown
     * or not; false before the overlay exists.
     */
    function withinZoom(id) {
        var o = overlays[id];
        if (!o || !map) return false;
        var zoom = map.getZoom();
        return o.layers.some(function (layer) { return drawnAt(layer, zoom); });
    }

    /** The scale (its denominator) from which the overlay is drawn; null when at every scale. */
    function firstScale(id) {
        var o = overlays[id];
        if (!o) return null;
        var first = Math.min.apply(null, o.layers.map(function (layer) {
            return layer.minzoom === undefined ? 0 : layer.minzoom;
        }));
        return first > 0 ? scaleAt(first) : null;
    }

    // ===== GeoJSON overlays (M8) =====
    //
    // Hydrograf's style of a path (Leaflet's options: color, weight, opacity, fillColor,
    // fillOpacity, dashArray in pixels, lineCap, radius of a point) stays its description
    // of a path, which the legends' swatches read; pathPaint() turns it into the paint of
    // a fill, line or circle layer. A value may be a MapLibre expression of the feature's
    // properties.

    var GEOMETRY = {
        fill: ['match', ['geometry-type'], ['Polygon', 'MultiPolygon'], true, false],
        line: ['match', ['geometry-type'], ['LineString', 'MultiLineString', 'Polygon', 'MultiPolygon'], true, false],
        circle: ['match', ['geometry-type'], ['Point', 'MultiPoint'], true, false],
    };

    function resolved(style) {
        return typeof style === 'function' ? style() : style;
    }

    /** Whether a style fills its polygons (Leaflet's `fill`, a fill colour and opacity). */
    function fills(style) {
        return style.fill !== false && style.fillOpacity !== 0 && style.fillColor !== 'none';
    }

    /** A dash pattern in pixels („12,8”) as MapLibre's, in line widths. */
    function dashes(style) {
        var weight = style.weight === undefined ? 3 : style.weight;
        return String(style.dashArray).split(/[\s,]+/).filter(Boolean).map(function (value) {
            return parseFloat(value) / weight;
        });
    }

    /** The paint of one shape of a path style. */
    function pathPaint(shape, style) {
        var color = style.color;
        var fillColor = style.fillColor || color;
        var weight = style.weight === undefined ? 3 : style.weight;
        var opacity = style.opacity === undefined ? 1 : style.opacity;
        var fillOpacity = style.fillOpacity === undefined ? 0.2 : style.fillOpacity;
        if (shape === 'fill') return { 'fill-color': fillColor, 'fill-opacity': fillOpacity };
        if (shape === 'circle') {
            // Leaflet strokes a circle across its radius, MapLibre outside it
            return {
                'circle-radius': Math.max(style.radius - weight / 2, 0),
                'circle-color': fillColor,
                'circle-opacity': fillOpacity,
                'circle-stroke-color': color,
                'circle-stroke-width': weight,
                'circle-stroke-opacity': opacity,
            };
        }
        var paint = { 'line-color': color, 'line-width': weight, 'line-opacity': opacity };
        if (style.dashArray) paint['line-dasharray'] = dashes(style);
        return paint;
    }

    /** Which geometries the GeoJSON holds: {polygon, line, point}. */
    function geometryKinds(data) {
        var kinds = { polygon: false, line: false, point: false };
        eachGeometry(data, function (geometry) {
            if (/Polygon$/.test(geometry.type)) kinds.polygon = true;
            else if (/LineString$/.test(geometry.type)) kinds.line = true;
            else if (/Point$/.test(geometry.type)) kinds.point = true;
        });
        return kinds;
    }

    function eachGeometry(data, fn) {
        if (!data) return;
        if (data.type === 'FeatureCollection') {
            data.features.forEach(function (feature) { eachGeometry(feature, fn); });
        } else if (data.type === 'Feature') {
            eachGeometry(data.geometry, fn);
        } else if (data.type === 'GeometryCollection') {
            data.geometries.forEach(function (geometry) { eachGeometry(geometry, fn); });
        } else if (data.coordinates) {
            fn(data);
        }
    }

    /** [west, south, east, north] of a GeoJSON's positions (Archiwista's geometryBounds); null when empty. */
    function geojsonBounds(data) {
        var box = null;
        function walk(coordinates) {
            if (typeof coordinates[0] === 'number') {
                var lng = coordinates[0];
                var lat = coordinates[1];
                if (!box) box = [lng, lat, lng, lat];
                box = [Math.min(box[0], lng), Math.min(box[1], lat), Math.max(box[2], lng), Math.max(box[3], lat)];
                return;
            }
            coordinates.forEach(walk);
        }
        eachGeometry(data, function (geometry) { walk(geometry.coordinates); });
        return box;
    }

    /** The place of a GeoJSON of one point, else null. */
    function onlyPoint(data) {
        var points = [];
        var other = false;
        eachGeometry(data, function (geometry) {
            if (geometry.type === 'Point') points.push(geometry.coordinates);
            else other = true;
        });
        return !other && points.length === 1 ? [points[0][0], points[0][1]] : null;
    }

    /**
     * Show a GeoJSON overlay: one source, and for each part of its style the fill, line
     * or circle layers of the geometries the data holds.
     * @param {string} id - The overlay.
     * @param {Object} data - GeoJSON.
     * @param {Object} options - `style` (a path style or a function returning one) or
     *     `parts` [{style, filter, shapes}], `tooltip`, `opacity`, `shown`.
     */
    function showGeojson(id, data, options) {
        if (!map) return null;
        var kinds = geometryKinds(data);
        var source = 'source:' + id;
        var parts = options.parts || [{ style: options.style }];
        var layers = [];
        parts.forEach(function (part, i) {
            var style = resolved(part.style);
            var shapes = part.shapes || (style.radius !== undefined ? ['circle'] : ['fill', 'line']);
            shapes.forEach(function (shape) {
                if (shape === 'fill' && (!kinds.polygon || !fills(style))) return;
                if (shape === 'line' && (!(kinds.line || kinds.polygon) || style.stroke === false)) return;
                if (shape === 'circle' && !kinds.point && !part.shapes) return;
                layers.push({
                    id: id + ':' + i + ':' + shape,
                    type: shape,
                    source: source,
                    filter: part.filter ? ['all', GEOMETRY[shape], part.filter] : GEOMETRY[shape],
                    layout: shape === 'line'
                        ? { 'line-cap': style.lineCap || 'round', 'line-join': style.lineJoin || 'round' }
                        : {},
                    paint: function () { return pathPaint(shape, resolved(part.style)); },
                });
            });
        });
        var sources = {};
        sources[source] = { type: 'geojson', data: data };
        return addOverlay({
            id: id,
            sources: sources,
            layers: layers,
            opacity: options.opacity,
            shown: options.shown,
            bounds: geojsonBounds(data),
            point: onlyPoint(data),
            tooltip: options.tooltip,
        });
    }

    /** New data of a GeoJSON overlay, its layers kept. */
    function setGeojson(id, data) {
        var o = overlays[id];
        if (!o || !map) return;
        map.getSource('source:' + id).setData(data);
        o.bounds = geojsonBounds(data);
        o.point = onlyPoint(data);
    }

    function pointFeature(lngLat, properties) {
        return { type: 'Feature', properties: properties || {}, geometry: { type: 'Point', coordinates: lngLat } };
    }

    /**
     * Show a point (identify's marker, the profile's readout) or move the one shown.
     * @param {string} id - The overlay.
     * @param {number[]} lngLat - [longitude, latitude].
     * @param {Object|function} style - A path style with a `radius`.
     */
    function showPoint(id, lngLat, style) {
        if (overlays[id]) {
            setGeojson(id, pointFeature(lngLat));
            return;
        }
        showGeojson(id, pointFeature(lngLat), { style: style });
    }

    // ===== Raster and image overlays (M6) =====

    /**
     * Show tiles of images: the DEM's, a result's, the flood hazard map's WMS.
     * @param {string} id - The overlay.
     * @param {Object} options - `tiles` [template], `tileSize`, `bounds` [w, s, e, n],
     *     `minzoom` and `maxzoom` of the tiles, `layerMinzoom` (the map's first zoom),
     *     `opacity`, `attribution`, `shown`; `floorLevel`: the tiles of the whole level
     *     at or below the zoom, as a vector source's, not of the nearest, so that a zoom
     *     in asks the new level only for the view it ends at.
     */
    function showRaster(id, options) {
        var source = { type: 'raster', tiles: options.tiles, tileSize: options.tileSize || 256 };
        if (options.bounds) source.bounds = options.bounds;
        if (options.minzoom !== undefined) source.minzoom = options.minzoom;
        if (options.maxzoom !== undefined) source.maxzoom = options.maxzoom;
        if (options.attribution) source.attribution = options.attribution;
        var o = rasterOverlay(id, source, options);
        if (o && options.floorLevel) map.getSource('source:' + id).roundZoom = false;
        return o;
    }

    /**
     * Show one image over the box [west, south, east, north] (the DEM's PNG, the
     * depressions'). The style's image source has no `attribution`; the map's credit reads
     * the source's all the same, so it is set once the source is there.
     */
    function showImage(id, options) {
        var b = options.bounds;
        var o = rasterOverlay(id, {
            type: 'image',
            url: absolute(options.url),
            coordinates: [[b[0], b[3]], [b[2], b[3]], [b[2], b[1]], [b[0], b[1]]],
        }, options);
        if (o && options.attribution) map.getSource('source:' + id).attribution = options.attribution;
        return o;
    }

    function rasterOverlay(id, source, options) {
        var sources = {};
        sources['source:' + id] = source;
        return addOverlay({
            id: id,
            sources: sources,
            layers: [{
                id: id + ':raster',
                type: 'raster',
                source: 'source:' + id,
                minzoom: options.layerMinzoom,
                paint: function () { return { 'raster-opacity': 1 }; },
            }],
            opacity: options.opacity,
            shown: options.shown,
            bounds: options.bounds || null,
        });
    }

    /** New tile templates of a raster overlay (the flood hazard map's probability switch). */
    function setTiles(id, tiles) {
        if (!overlays[id] || !map) return;
        map.getSource('source:' + id).setTiles(tiles);
    }

    // ===== DEM Overlay =====

    var demBounds = null;
    // Metadata of the rendered DEM (dem_tiles.json or dem.json): elevation and colour range
    var demMeta = null;
    var demLoad = null;

    /** [west, south, east, north] of the metadata's [[south, west], [north, east]]. */
    function metaBox(bounds) {
        return [bounds[0][1], bounds[0][0], bounds[1][1], bounds[1][0]];
    }

    function readJson(url) {
        return fetch(url, { cache: 'no-cache' }).then(function (res) {
            if (!res.ok) throw new Error(url + ': ' + res.status);
            return res.json();
        });
    }

    /** The DEM's tiles, else its one image: added hidden, the view fitted to its extent. */
    function loadDemOverlay() {
        demLoad = readJson('/data/dem_tiles.json')
            .then(function (meta) {
                demMeta = meta;
                demBounds = metaBox(meta.bounds);
                var tiles = '/data/dem_tiles/{z}/{x}/{y}.png';
                if (meta.generated_at) tiles += '?v=' + meta.generated_at;
                var first = meta.min_zoom || 8;
                showRaster('dem', {
                    tiles: [absolute(tiles)],
                    tileSize: 256,
                    bounds: demBounds,
                    minzoom: first,
                    maxzoom: meta.max_zoom || 18,
                    // A tile level is the map's zoom plus one: 256-px tiles in a 512-px world
                    layerMinzoom: first - 1,
                    opacity: 0.7,
                    attribution: 'NMT &copy; GUGiK',
                    shown: false,
                });
                fitToBounds(demBounds);
                return true;
            })
            .catch(function () {
                return readJson('/data/dem.json').then(function (meta) {
                    demMeta = meta;
                    demBounds = metaBox(meta.bounds);
                    var url = '/data/dem.png';
                    if (meta.generated_at) url += '?v=' + meta.generated_at;
                    showImage('dem', {
                        url: url,
                        bounds: demBounds,
                        opacity: 0.7,
                        attribution: 'NMT &copy; GUGiK',
                        shown: false,
                    });
                    fitToBounds(demBounds);
                    return true;
                });
            })
            .catch(function (err) {
                console.warn('DEM overlay not available:', err.message);
                return false;
            });
        return demLoad;
    }

    /** Whether the DEM is on the map, once its metadata answered (the layers panel's row). */
    function loadDem() {
        return demLoad || ready.then(function () { return demLoad || false; });
    }

    function getDemBounds() { return demBounds; }

    // ===== Streams Vector (MVT) =====

    // The log10 of a stream's upstream area, 0.0001 km² and less as 0.0001 km²
    var LOG_AREA = ['log10', ['max', ['to-number', ['get', 'upstream_area_km2']], 0.0001]];

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
        return rgbText([0, 1, 2].map(function (i) { return ramp[0][i] * (1 - t) + ramp[1][i] * t; }));
    }

    var currentThreshold = null;

    /** The streams' tiles of a threshold: pre-generated where generate_tiles.py wrote them, else the API's. */
    function streamsTiles(threshold) {
        var meta = window.Hydrograf._tilesMeta;
        if (meta && meta.format === 'pbf' && meta.thresholds && meta.thresholds.indexOf(threshold) !== -1) {
            return absolute('/tiles/streams_' + threshold + '/{z}/{x}/{y}.pbf');
        }
        return absolute('/api/tiles/streams/{z}/{x}/{y}.pbf?threshold=' + threshold);
    }

    /** The first zoom of a threshold's streams (tiles_metadata.json), 0 without the metadata. */
    function streamsMinZoom(threshold) {
        var meta = window.Hydrograf._tilesMeta || {};
        if (!meta.min_zoom) return 0;
        var zooms = meta.threshold_min_zoom || {};
        return zooms[String(threshold)] || meta.min_zoom;
    }

    /** The streams' extent from the tiles' metadata, else none. */
    function tilesBounds() {
        var meta = window.Hydrograf._tilesMeta || {};
        return meta.bounds && meta.bounds.length === 4 ? meta.bounds.slice() : null;
    }

    function streamsTooltip(props) {
        return {
            html: '<b>Zlewnia:</b> ' + (props.upstream_area_km2 ? props.upstream_area_km2.toFixed(2) + ' km²' : '?') + '<br>' +
                '<b>Rząd Strahlera:</b> ' + (props.strahler_order || '?') + '<br>' +
                '<b>Długość:</b> ' + (props.length_m ? (props.length_m / 1000).toFixed(2) + ' km' : '?'),
        };
    }

    /**
     * The streams of a threshold (m²) on the map: an overlay of the threshold's tiles and
     * first zoom, made anew for each threshold with the shown state and opacity it had.
     * A new source, not `setTiles`: MapLibre drops a vector source's new tiles when a layer
     * of it changes before they load, and keeps drawing the old ones. A change of threshold
     * fires `hydrograf:streams` on window (js/network.js and js/identify.js ask again).
     */
    function setStreamsThreshold(threshold) {
        var changed = threshold !== currentThreshold;
        currentThreshold = threshold;
        var drawn = overlays.streams;
        if (map && (!drawn || changed)) {
            var meta = window.Hydrograf._tilesMeta || {};
            var source = {
                type: 'vector',
                tiles: [streamsTiles(threshold)],
                minzoom: meta.min_zoom || 0,
                maxzoom: 18,
                attribution: 'Linie spływu (flow acc)',
            };
            var bounds = tilesBounds();
            if (bounds) source.bounds = bounds;
            addOverlay({
                id: 'streams',
                sources: { 'source:streams': source },
                layers: [{
                    id: 'streams:line',
                    type: 'line',
                    source: 'source:streams',
                    'source-layer': 'streams',
                    minzoom: streamsMinZoom(threshold),
                    layout: { 'line-cap': 'round', 'line-join': 'round' },
                    paint: function () {
                        var ramp = colors().streamRamp;
                        return {
                            'line-color': ['interpolate', ['linear'], LOG_AREA,
                                -4, rgbText(ramp[0]), 1.3, rgbText(ramp[1])],
                            // 0.5 px for tiny streams, 4 px for large rivers
                            'line-width': ['interpolate', ['linear'], LOG_AREA, -4, 0.5, 1.3, 4],
                            'line-opacity': 0.9,
                        };
                    },
                }],
                shown: drawn ? drawn.shown : false,
                opacity: drawn ? drawn.opacity : 1,
                tooltip: streamsTooltip,
            });
        }
        if (changed) window.dispatchEvent(new CustomEvent('hydrograf:streams', { detail: { threshold: threshold } }));
    }

    function getStreamsThreshold() { return currentThreshold; }

    /**
     * Data extent from the vector tiles metadata (bounds as [W, S, E, N]),
     * falling back to the DEM extent.
     */
    function getDataBounds() {
        return tilesBounds() || demBounds;
    }

    // ===== Land cover and sewer (MVT) =====

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

    /** Land cover from the API's tiles (BDOT10k), from today's 1:2 183 915 on. */
    function loadLandCover() {
        return ready.then(function (shown) {
            if (shown && !overlays.landcover) addLandCover();
            return shown;
        });
    }

    function addLandCover() {
        addOverlay({
            id: 'landcover',
            sources: {
                'source:landcover': {
                    type: 'vector',
                    tiles: [absolute('/api/tiles/landcover/{z}/{x}/{y}.pbf')],
                    minzoom: 7,
                    maxzoom: 18,
                    attribution: 'Pokrycie terenu (BDOT10k)',
                },
            },
            layers: [{
                id: 'landcover:fill',
                type: 'fill',
                source: 'source:landcover',
                'source-layer': 'landcover',
                minzoom: 7,
                paint: function () {
                    var match = ['match', ['get', 'category']];
                    LANDCOVER_LEGEND.forEach(function (entry) {
                        if (entry[0] !== 'inny') match.push(entry[0], landCoverColor(entry[0]));
                    });
                    match.push(landCoverColor('inny'));
                    return { 'fill-color': match, 'fill-opacity': 0.6 };
                },
            }],
            shown: false,
        });
    }

    /** The storm sewer from the API's tiles (lines and nodes by kind), from today's 1:545 979 on. */
    function loadSewer() {
        return ready.then(function (shown) {
            if (shown && !overlays.sewer) addSewer();
            return shown;
        });
    }

    function addSewer() {
        addOverlay({
            id: 'sewer',
            sources: {
                'source:sewer': {
                    type: 'vector',
                    tiles: [absolute('/api/tiles/sewer/{z}/{x}/{y}.pbf')],
                    minzoom: 9,
                    maxzoom: 20,
                },
            },
            layers: [{
                id: 'sewer:lines',
                type: 'line',
                source: 'source:sewer',
                'source-layer': 'sewer_lines',
                minzoom: 9,
                layout: { 'line-cap': 'round', 'line-join': 'round' },
                paint: function () {
                    return { 'line-color': token('--text-2'), 'line-width': 2, 'line-opacity': 0.8 };
                },
            }, {
                id: 'sewer:nodes',
                type: 'circle',
                source: 'source:sewer',
                'source-layer': 'sewer_nodes',
                minzoom: 9,
                paint: function () {
                    return pathPaint('circle', {
                        radius: 4,
                        weight: 1,
                        color: token('--surface'),
                        opacity: 1,
                        fillColor: ['match', ['get', 'node_type'],
                            'inlet', token('--info'), 'outlet', token('--bad'), token('--text-3')],
                        fillOpacity: 0.9,
                    });
                },
            }],
            shown: false,
        });
    }

    // ===== Selection boundary =====

    /** Delineated catchment: tool colour outline with a light fill of the same colour. */
    function watershedStyle() {
        var c = colors();
        return { color: c.tool, weight: 2.5, opacity: 1, fillColor: c.tool, fillOpacity: 0.12 };
    }

    /**
     * Show upstream catchment boundary polygon.
     */
    function showSelectionBoundary(geojsonFeature) {
        if (!map) return;
        showGeojson('watershed', geojsonFeature, { style: watershedStyle });
        fitToBounds(overlayBounds('watershed'));
        updateWatershedLegend();
    }

    /**
     * Clear selection boundary layer.
     */
    function clearSelectionBoundary() {
        if (!overlays.watershed) return;
        removeOverlay('watershed');
        updateWatershedLegend();
    }

    // ===== Delineation preview =====
    //
    // While the server merges the boundary, the sub-catchments it merges fill the network
    // up from the outlet (`watershed preview`, GET /api/v1/watershed/preview, one feature
    // per BFS depth). The map first moves to the watershed; then depth d appears at
    // d / maxDepth of PREVIEW_DURATION_MS, as many levels per frame as are due (a filter
    // of the source by depth), and the preview's opacity pulses until
    // clearDelineatePreview(). Reduced motion: all levels at once, no pulse.

    var PREVIEW_DURATION_MS = 500;
    var PULSE_MS = 1600;
    var PULSE_LOW = 0.6;
    var preview = null; // { frame, onMoveEnd }

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
        var features = (collection && collection.features) || [];
        if (!map || !features.length) return;

        var maxDepth = features[features.length - 1].properties.depth;
        var instant = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        var start = null;
        var current = { frame: null, onMoveEnd: null };
        preview = current;
        showGeojson('preview', collection, { style: previewStyle });
        setOverlayFilter('preview', ['<', ['get', 'depth'], 0]);

        function step(now) {
            if (start === null) start = now;
            var reached = instant ? maxDepth : Math.min(maxDepth, (now - start) / PREVIEW_DURATION_MS * maxDepth);
            setOverlayFilter('preview', ['<=', ['get', 'depth'], reached]);
            if (reached < maxDepth) {
                current.frame = requestAnimationFrame(step);
            } else if (!instant) {
                start = null;
                current.frame = requestAnimationFrame(pulse);
            } else {
                current.frame = null;
            }
        }

        // The opacity eases from 1 to PULSE_LOW and back, as the CSS pulse of a pane did
        function pulse(now) {
            if (start === null) start = now;
            var phase = ((now - start) % PULSE_MS) / PULSE_MS;
            setOverlayOpacity('preview', 1 - (1 - PULSE_LOW) * (1 - Math.cos(2 * Math.PI * phase)) / 2);
            current.frame = requestAnimationFrame(pulse);
        }

        current.onMoveEnd = function () {
            current.onMoveEnd = null;
            current.frame = requestAnimationFrame(step);
        };
        fitView(overlayBounds('preview'), {}, function () {
            if (current.onMoveEnd) current.onMoveEnd();
        });
    }

    /** Remove the preview and stop its animation. */
    function clearDelineatePreview() {
        if (!preview) return;
        preview.onMoveEnd = null;
        if (preview.frame !== null) cancelAnimationFrame(preview.frame);
        removeOverlay('preview');
        preview = null;
    }

    // ===== Legends (M11: controls of the map's bottom left) =====

    /**
     * Put an element in a corner of the map as a control (a legend, the coordinates).
     * MapLibre, like Leaflet, puts a later bottom control above the earlier ones.
     * @returns {?Object} {element, remove()}; null without a map.
     */
    function addControl(element, corner) {
        if (!map) return null;
        element.classList.add('maplibregl-ctrl');
        var control = {
            onAdd: function () { return element; },
            onRemove: function () { element.remove(); },
        };
        map.addControl(control, corner || 'bottom-left');
        return {
            element: element,
            remove: function () { if (map) map.removeControl(control); },
        };
    }

    /** A legend box of HTML in the bottom left; null without a map. */
    function legendControl(className, html) {
        var div = document.createElement('div');
        div.className = className;
        div.innerHTML = html;
        return addControl(div, 'bottom-left');
    }

    var streamsLegend = null;

    function streamsLegendHtml() {
        return '<div class="layer-legend-title">Linie spływu — zlewnia [km²]</div>' +
            '<div class="legend-gradient" style="background: linear-gradient(to right, ' +
            flowAccColor(0.001) + ', ' + flowAccColor(0.1) + ', ' + flowAccColor(20) + ');"></div>' +
            '<div class="legend-labels"><span>0.001</span><span>0.1</span><span>20</span></div>';
    }

    function createStreamsLegend() {
        if (!streamsLegend) streamsLegend = legendControl('layer-legend', streamsLegendHtml());
    }

    function removeStreamsLegend() {
        if (streamsLegend) {
            streamsLegend.remove();
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
        demLegend = legendControl('layer-legend', demLegendHtml(demMeta));
    }

    function removeDemLegend() {
        if (demLegend) {
            demLegend.remove();
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
        if (!hsgLegend) hsgLegend = legendControl('layer-legend', hsgLegendHtml());
    }

    function removeHsgLegend() {
        if (hsgLegend) {
            hsgLegend.remove();
            hsgLegend = null;
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
        if (!landCoverLegend) landCoverLegend = legendControl('layer-legend', landCoverLegendHtml());
    }

    function removeLandCoverLegend() {
        if (landCoverLegend) {
            landCoverLegend.remove();
            landCoverLegend = null;
        }
    }

    // ===== Watershed display =====

    /** Outlet: tool colour ring on the surface colour. */
    function outletStyle() {
        var c = colors();
        return { radius: 6, color: c.tool, weight: 3, opacity: 1, fillColor: c.surface, fillOpacity: 1 };
    }

    function showOutlet(lat, lng, elevation) {
        if (!map) return;
        var text = 'Ujście: ' + elevation.toFixed(1) + ' m n.p.m.';
        showGeojson('outlet', pointFeature([lng, lat]), {
            style: outletStyle,
            shown: !watershedHidden,
            tooltip: function () { return { text: text, at: [lng, lat] }; },
        });
        updateWatershedLegend();
    }

    function clearWatershed() {
        removeOverlay('outlet');
        removeOverlay('main-channel');
        removeOverlay('longest-flow-path');
        removeOverlay('divide-flow-path');
        mainChannelKinds = { real: false, dem: false };
        updateWatershedLegend();
    }

    // ===== Main channel display =====

    // The kinds of segment of the main channel shown: BDOT10k-matched (`real`) and the rest (`dem`)
    var mainChannelKinds = { real: false, dem: false };
    var IS_REAL_STREAM = ['to-boolean', ['get', 'is_real_stream']];

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
        if (!geojson || !map) return;
        var features = geojson.type === 'FeatureCollection' ? geojson.features
            : [geojson.type === 'Feature' ? geojson : { type: 'Feature', properties: {}, geometry: geojson }];
        mainChannelKinds = { real: false, dem: false };
        features.forEach(function (feature) {
            mainChannelKinds[feature.properties && feature.properties.is_real_stream ? 'real' : 'dem'] = true;
        });
        showGeojson('main-channel', { type: 'FeatureCollection', features: features }, {
            shown: !watershedHidden,
            parts: [{
                filter: ['!', IS_REAL_STREAM],
                style: function () { return mainChannelStyle({ properties: { is_real_stream: false } }); },
            }, {
                filter: IS_REAL_STREAM,
                style: function () { return mainChannelStyle({ properties: { is_real_stream: true } }); },
            }],
        });
        updateWatershedLegend();
    }

    function clearMainChannel() {
        if (!overlays['main-channel']) return;
        removeOverlay('main-channel');
        mainChannelKinds = { real: false, dem: false };
        updateWatershedLegend();
    }

    // ===== Flow paths: the longest one and the one from the watershed boundary =====
    //
    // Both in the warning colour; long dashes and round dots tell them apart,
    // also where they run along the same cells (the dots are drawn on top).

    function longestFlowPathStyle() {
        return { color: colors().warn, weight: 2.5, opacity: 0.9, dashArray: '12,8' };
    }

    function divideFlowPathStyle() {
        return { color: colors().warn, weight: 4, opacity: 0.9, dashArray: '0.1,8', lineCap: 'round' };
    }

    function showFlowPath(id, geojson, style) {
        removeOverlay(id);
        if (geojson && map) showGeojson(id, geojson, { style: style, shown: !watershedHidden });
        updateWatershedLegend();
    }

    function showLongestFlowPath(geojson) {
        showFlowPath('longest-flow-path', geojson, longestFlowPathStyle);
    }

    function showDivideFlowPath(geojson) {
        showFlowPath('divide-flow-path', geojson, divideFlowPathStyle);
    }

    // ===== Watershed legend =====
    //
    // While a watershed is shown, a legend lists the parts of it on the map,
    // each with a swatch in the style of its layer.

    var WATERSHED_PARTS = ['watershed', 'outlet', 'main-channel', 'longest-flow-path', 'divide-flow-path'];
    var watershedLegend = null;
    // The option „Sieć zlewni” takes the watershed off the map (setWatershedShown)
    var watershedHidden = false;

    function escapeAttr(value) {
        return String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
    }

    /** SVG swatch of a path style: a line, an area (`area`) or a circle marker (`point`). */
    function pathSwatch(style, shape) {
        var attrs = ' stroke="' + escapeAttr(style.color) + '" stroke-width="' + style.weight + '"' +
            ' stroke-opacity="' + style.opacity + '"' +
            // Leaflet's default caps and joins are round, as the map's lines
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

    function watershedLegendRows() {
        var rows = [];
        if (overlays.watershed) rows.push([pathSwatch(watershedStyle(), 'area'), 'Granica zlewni']);
        if (overlays.outlet) rows.push([pathSwatch(outletStyle(), 'point'), 'Ujście']);
        if (overlays['main-channel'] && mainChannelKinds.real) {
            rows.push([pathSwatch(mainChannelStyle({ properties: { is_real_stream: true } })),
                'Ciek główny (BDOT10k)']);
        }
        if (overlays['main-channel'] && mainChannelKinds.dem) {
            rows.push([pathSwatch(mainChannelStyle({ properties: { is_real_stream: false } })),
                'Ciek główny (z NMT)']);
        }
        if (overlays['longest-flow-path']) {
            rows.push([pathSwatch(longestFlowPathStyle()), 'Najdłuższa droga spływu']);
        }
        if (overlays['divide-flow-path']) {
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
                watershedLegend.remove();
                watershedLegend = null;
            }
            return;
        }
        if (!watershedLegend) watershedLegend = legendControl('layer-legend watershed-legend', '');
        watershedLegend.element.innerHTML = '<div class="layer-legend-title">Zlewnia</div>' +
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
        WATERSHED_PARTS.forEach(function (id) { setOverlayShown(id, shown); });
        updateWatershedLegend();
    }

    // ===== Profile line styles =====

    function drawLineStyle() {
        return { color: colors().accent, weight: 2, opacity: 1, dashArray: '6, 4' };
    }

    function profileLineStyle() {
        return { color: colors().accent, weight: 3, opacity: 0.9 };
    }

    /** Vertex and chart-hover markers: accent dot with a surface ring. */
    function pointStyle(radius) {
        var c = colors();
        return { radius: radius, color: c.surface, weight: 2, opacity: 1, fillColor: c.accent, fillOpacity: 1 };
    }

    // ===== Drawing mode (polyline for terrain profile, M10) =====
    //
    // A click or tap adds a vertex, a double click or a tap within FINISH_TAP_PX of the
    // last vertex ends the line, Esc cancels and Backspace takes the last vertex back
    // (the three buttons of #draw-tools do the same on phones); double-click zoom is off
    // meanwhile. The vertices and the line so far are the overlay `draw`, the line drawn
    // the overlay `profile-line`.

    // A tap or click this close to the last vertex ends the line instead of adding a
    // vertex: the second tap of a double tap never lands on the exact same spot.
    var FINISH_TAP_PX = 20;

    var drawMode = false;
    var drawVertices = [];  // [lng, lat]
    var drawCallback = null;

    function setDrawUi(active) {
        var banner = document.getElementById('draw-instructions');
        if (banner) banner.classList.toggle('d-none', !active);
        var tools = document.getElementById('draw-tools');
        if (tools) tools.hidden = !active;
        if (active) updateDrawCount();
    }

    function pointsLabel(n) {
        return n + ' ' + Hydrograf.app.plural(n, 'punkt', 'punkty', 'punktów');
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

    function lineFeature(vertices) {
        return { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: vertices } };
    }

    /** The vertices placed and the line through them, as the overlay `draw`. */
    function showDrawn() {
        if (!drawVertices.length) {
            removeOverlay('draw');
            return;
        }
        var features = drawVertices.map(function (v) { return pointFeature(v); });
        if (drawVertices.length > 1) features.unshift(lineFeature(drawVertices));
        var data = { type: 'FeatureCollection', features: features };
        if (overlays.draw) {
            setGeojson('draw', data);
            return;
        }
        showGeojson('draw', data, {
            parts: [{ style: drawLineStyle, shapes: ['line'] }, { style: function () { return pointStyle(5); }, shapes: ['circle'] }],
        });
    }

    function setDrawing(active) {
        drawMode = active;
        if (!map) return;
        map.getContainer().classList.toggle('is-drawing', active);
        if (active) map.doubleClickZoom.disable();
        else map.doubleClickZoom.enable();
    }

    function startDrawing(onComplete) {
        drawVertices = [];
        drawCallback = onComplete;
        setDrawing(true);
        setDrawUi(true);
    }

    function addDrawVertex(lngLat) {
        if (drawVertices.length > 0) {
            var last = map.project(drawVertices[drawVertices.length - 1]);
            var at = map.project(lngLat);
            if (Math.hypot(at.x - last.x, at.y - last.y) <= FINISH_TAP_PX) {
                if (drawVertices.length >= 2) finishDrawing();
                return;
            }
        }
        drawVertices.push([lngLat.lng, lngLat.lat]);
        showDrawn();
        updateDrawCount();
    }

    function undoLastVertex() {
        if (!drawMode || drawVertices.length === 0) return;
        drawVertices.pop();
        showDrawn();
        updateDrawCount();
    }

    function finishDrawing() {
        if (drawVertices.length < 2) {
            cancelDrawing();
            return;
        }

        var coords = drawVertices.map(function (v) { return [v[1], v[0]]; });
        var line = lineFeature(drawVertices);
        setDrawing(false);
        setDrawUi(false);
        drawVertices = [];
        removeOverlay('draw');
        // The line drawn stays as the profile line
        showGeojson('profile-line', line, { style: profileLineStyle });

        if (drawCallback) drawCallback(coords);
    }

    function cancelDrawing() {
        setDrawing(false);
        setDrawUi(false);
        drawVertices = [];
        drawCallback = null;
        removeOverlay('draw');
        // Clear profile line from previous completed drawing
        removeOverlay('profile-line');
    }

    function isDrawing() { return drawMode; }

    // ===== Profile line display =====

    function clearProfileLine() {
        removeOverlay('profile-line');
    }

    // Profile hover marker (shows position on line when hovering over chart)
    function showProfileHoverMarker(lat, lng) {
        if (!map) return;
        showPoint('profile-marker', [lng, lat], function () { return pointStyle(6); });
    }

    function clearProfileHoverMarker() {
        removeOverlay('profile-marker');
    }

    // ===== BDOT10k vector layers (lakes + streams) =====

    var geojsonLoads = {};

    /**
     * A GeoJSON overlay of the data directory, fetched once and added hidden.
     * @returns {Promise<boolean>} Whether it is on the map.
     */
    function loadGeojsonOverlay(id, url, options) {
        if (!geojsonLoads[id]) {
            geojsonLoads[id] = ready.then(function (shown) {
                if (!shown) return false;
                return fetch(url).then(function (res) {
                    if (!res.ok) throw new Error(url + ': ' + res.status);
                    return res.json();
                }).then(function (geojson) {
                    showGeojson(id, geojson, Object.assign({ shown: false }, options));
                    return true;
                });
            }).catch(function (err) {
                console.warn(id + ' not available:', err.message);
                geojsonLoads[id] = null;
                return false;
            });
        }
        return geojsonLoads[id];
    }

    function loadBdotLakes() {
        return loadGeojsonOverlay('bdot-lakes', '/data/bdot_lakes.geojson', {
            style: function () {
                var info = colors().info;
                return { color: info, weight: 1, opacity: 1, fillColor: info, fillOpacity: 0.4 };
            },
        });
    }

    var SOURCE_LAYER = ['get', 'source_layer'];

    /** BDOT10k streams: rivers (SWRS) and canals (SWKN) in --info, ditches softer and dashed. */
    function loadBdotStreams() {
        return loadGeojsonOverlay('bdot-streams', '/data/bdot_streams.geojson', {
            parts: [{
                filter: ['!', ['match', SOURCE_LAYER, ['OT_SWRS_L', 'OT_SWKN_L'], true, false]],
                style: function () { return { color: colors().infoSoft, weight: 1, opacity: 0.6, dashArray: '4,4' }; },
            }, {
                filter: ['==', SOURCE_LAYER, 'OT_SWKN_L'],
                style: function () { return { color: colors().info, weight: 1.5, opacity: 0.7, dashArray: '6,3' }; },
            }, {
                filter: ['==', SOURCE_LAYER, 'OT_SWRS_L'],
                style: function () { return { color: colors().info, weight: 2, opacity: 0.8 }; },
            }],
        });
    }

    // ===== HSG soil layer =====

    /** HSG group colour, shared with the HSG chart (charts.js palette). */
    function hsgColor(group) {
        var memo = colors().hsg;
        if (!(group in memo)) memo[group] = Hydrograf.charts.hsgColor(group);
        return memo[group];
    }

    /** The colour of a feature's group: B where it names none, as the chart counts it. */
    function hsgFeatureColor() {
        var group = ['get', 'hsg_group'];
        return ['case', ['!', ['to-boolean', group]], hsgColor('B'),
            ['match', group, 'A', hsgColor('A'), 'B', hsgColor('B'), 'C', hsgColor('C'), 'D', hsgColor('D'),
                hsgColor('')]];
    }

    function loadHsgLayer() {
        return loadGeojsonOverlay('hsg', '/data/soil_hsg.geojson', {
            style: function () {
                var color = hsgFeatureColor();
                return { color: color, weight: 0.5, opacity: 1, fillColor: color, fillOpacity: 0.35 };
            },
        });
    }

    // ===== Pointer (M9) =====
    //
    // A click goes to the mode of js/app.js, or adds a vertex while drawing; a click on a
    // marker (a network point or label) is the marker's alone. A pointer over a feature of
    // an overlay with a tooltip (a stream, the outlet, a junction of the network) shows
    // one tooltip, a popup without a close button.

    var tip = { popup: null, overlay: null };

    function hideTooltip() {
        if (tip.popup) tip.popup.remove();
        tip.overlay = null;
    }

    function tooltipLayers() {
        var ids = [];
        Object.keys(overlays).forEach(function (id) {
            var o = overlays[id];
            if (!o.tooltip || !o.shown) return;
            o.layers.forEach(function (layer) { ids.push(layer.id); });
        });
        return ids;
    }

    function onHover(e) {
        var layers = tooltipLayers();
        var feature = layers.length ? map.queryRenderedFeatures(e.point, { layers: layers })[0] : null;
        var id = feature && layerOverlay[feature.layer.id];
        var shown = id ? overlays[id].tooltip(feature.properties || {}, feature) : null;
        if (!shown) {
            hideTooltip();
            return;
        }
        if (!tip.popup) {
            tip.popup = new maplibregl.Popup({
                closeButton: false,
                closeOnClick: false,
                focusAfterOpen: false,
                anchor: 'bottom',
                offset: 10,
                maxWidth: 'none',
                className: 'map-tooltip',
            });
        }
        if (shown.html !== undefined) tip.popup.setHTML(shown.html);
        else tip.popup.setText(shown.text);
        tip.popup.setLngLat(shown.at || e.lngLat);
        if (!tip.popup.isOpen()) tip.popup.addTo(map);
        tip.overlay = id;
    }

    /** Whether a map event began on a marker's element. */
    function onMarker(e) {
        var target = e.originalEvent && e.originalEvent.target;
        return !!(target && target.closest && target.closest('.maplibregl-marker'));
    }

    // ===== Markers: the network's points and labels =====

    // A dragged point this close to the map's edge pans the map (open question 5)
    var EDGE_PX = 20;
    var EDGE_STEP_PX = 10;
    var markers = [];   // every marker made, shown or not

    /**
     * A DOM marker over the map whose element the caller owns.
     * @param {number[]} lngLat - [longitude, latitude].
     * @param {Object} options - `element`, `draggable`, `point` (a point of the network,
     *     listed by describe() as `id` with the element's title), `id`, `onClick`,
     *     `onDragStart`, `onDragEnd(lngLat)`.
     * @returns {?Object} The handle: show(), hide(), remove(), setLngLat(lngLat),
     *     getLngLat(), setDraggable(on), `id`, `element`; null without a map.
     */
    function addMarker(lngLat, options) {
        if (!map) return null;
        var element = options.element;
        var marker = new maplibregl.Marker({ element: element, anchor: 'center', draggable: !!options.draggable })
            .setLngLat(lngLat);
        var handle = {
            id: options.id,
            element: element,
            point: !!options.point,
            shown: false,
            show: function () {
                if (!handle.shown && map) marker.addTo(map);
                handle.shown = true;
            },
            hide: function () {
                marker.remove();
                handle.shown = false;
            },
            remove: function () {
                handle.hide();
                markers = markers.filter(function (m) { return m !== handle; });
            },
            setLngLat: function (to) { marker.setLngLat(to); },
            getLngLat: function () {
                var at = marker.getLngLat();
                return [at.lng, at.lat];
            },
            setDraggable: function (on) { marker.setDraggable(on); },
        };
        if (options.onClick) {
            element.addEventListener('click', function (event) {
                event.stopPropagation();
                options.onClick();
            });
        }
        var panning = null;
        function edgePan() {
            var container = map.getContainer();
            var at = map.project(marker.getLngLat());
            var dx = at.x < EDGE_PX ? -EDGE_STEP_PX : at.x > container.clientWidth - EDGE_PX ? EDGE_STEP_PX : 0;
            var dy = at.y < EDGE_PX ? -EDGE_STEP_PX : at.y > container.clientHeight - EDGE_PX ? EDGE_STEP_PX : 0;
            if (!dx && !dy) {
                panning = null;
                return;
            }
            // The point stays under the pointer while the map moves under it
            map.panBy([dx, dy], { animate: false });
            marker.setLngLat(map.unproject(at));
            panning = requestAnimationFrame(edgePan);
        }
        marker.on('dragstart', function () {
            if (options.onDragStart) options.onDragStart();
        });
        marker.on('drag', function () {
            if (panning === null) edgePan();
        });
        marker.on('dragend', function () {
            if (panning !== null) cancelAnimationFrame(panning);
            panning = null;
            if (options.onDragEnd) options.onDragEnd(handle.getLngLat());
        });
        markers.push(handle);
        return handle;
    }

    /** A point of the network: a draggable marker, described by describe() (M9). */
    function addPoint(lngLat, options) {
        return addMarker(lngLat, Object.assign({}, options, { point: true }));
    }

    /** A label of the network that selects on a click or a key and keeps keyboard focus. */
    function addLabel(lngLat, options) {
        var element = options.element;
        element.tabIndex = 0;
        element.setAttribute('role', 'button');
        element.addEventListener('keydown', function (event) {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            options.onClick();
        });
        return addMarker(lngLat, options);
    }

    // ===== Utilities =====

    function setLoadingCursor(loading) {
        if (map) map.getContainer().classList.toggle('is-loading', loading);
    }

    /**
     * Fit the view to [west, south, east, north] at a whole zoom level, as the map's fits
     * have always been: raster tiles show at the scale they were drawn for and the flood
     * hazard map's boxes at the view's. `done` runs once the view stays.
     */
    function fitView(box, options, done) {
        if (!map || !box) return false;
        var camera = map.cameraForBounds([[box[0], box[1]], [box[2], box[3]]], {
            padding: options.padding === undefined ? FIT_PADDING_PX : options.padding,
            maxZoom: options.maxZoom === undefined ? MAX_ZOOM : options.maxZoom,
        });
        if (!camera) return false;
        var zoom = Math.floor(Math.round(camera.zoom * 100) / 100);
        zoom = Math.max(map.getMinZoom(), Math.min(zoom, map.getMaxZoom()));
        var center = map.getCenter();
        var target = { center: camera.center, zoom: zoom };
        var still = zoom === map.getZoom() && map.project(camera.center).dist(map.project(center)) < 0.5;
        if (done) {
            if (still) done();
            else map.once('moveend', function () { done(); });
        }
        if (still) return true;
        if (Math.abs(zoom - map.getZoom()) > ANIMATED_ZOOMS) map.jumpTo(target);
        else map.easeTo(Object.assign(target, { duration: FIT_DURATION_MS }));
        return true;
    }

    /**
     * Fit the map to [west, south, east, north]; ignores missing or invalid bounds.
     * `options`: `padding` in pixels (20), `maxZoom`.
     */
    function fitToBounds(box, options) {
        if (!box || !(box[0] <= box[2] && box[1] <= box[3])) return;
        fitView(box, options || {});
    }

    /** The view for a report (js/feedback.js): centre and MapLibre's zoom; null without a map. */
    function view() {
        if (!map) return null;
        var center = map.getCenter();
        return { center: { lat: center.lat, lng: center.lng }, zoom: map.getZoom() };
    }

    /** The container's pixel of a place, from the map's top left; null without a map. */
    function containerPoint(lngLat) {
        if (!map) return null;
        var at = map.project(lngLat);
        return { x: at.x, y: at.y };
    }

    function containerRect() {
        return map ? map.getContainer().getBoundingClientRect() : null;
    }

    /** Move the view by pixels (x right, y down). */
    function panBy(dx, dy) {
        if (map) map.panBy([dx, dy]);
    }

    /** Call `fn` after every change of the view's zoom. */
    function onZoomEnd(fn) {
        ready.then(function (shown) { if (shown) map.on('zoomend', fn); });
    }

    /** Call `fn(lat, lng)` as the pointer moves over the map. */
    function onPointerMove(fn) {
        ready.then(function (shown) {
            if (!shown) return;
            map.on('mousemove', function (e) { fn(e.lngLat.lat, e.lngLat.lng); });
        });
    }

    // ===== Base maps of Nogat's kit (DEV-15.15, ADR-089) =====
    //
    // The kit draws the chosen entry under the slot of the base map, `removeMaplibreBasemap`
    // takes it off and `repaintMaplibreBasemap` repaints its grey style after a change of
    // theme (js/nogat.js hands them on). Each waits for the map, in the order called.

    function basemapKit() {
        return (window.Hydrograf.nogat && window.Hydrograf.nogat.basemaps) || null;
    }

    /**
     * Draw a base map entry; `options.onFailure(id)` when its provider fails.
     * @returns {Promise} Settled once drawn; rejected when it fails or another replaces it.
     */
    function showBasemap(entry, options) {
        return ready.then(function (shown) {
            var kit = basemapKit();
            if (!shown || !kit) return null;
            return kit.maplibre(entry, {
                map: map,
                locale: 'pl',
                before: slot('basemap'),
                onFailure: options.onFailure,
            });
        });
    }

    function removeBasemap() {
        return ready.then(function (shown) {
            var kit = basemapKit();
            if (shown && kit) kit.remove(map);
        });
    }

    function repaintBasemap() {
        var kit = basemapKit();
        if (map && kit) kit.repaint(map);
    }

    // ===== What the map draws (the browser tests of tests/e2e) =====
    //
    // describe() reads what the map draws the same way whatever library draws it
    // (Nogat's plan 2026-11-24-hydrograf-maplibre, step 1): the overlays from the
    // bottom up with their opacity, the network's point markers and the view in
    // degrees and as a scale. An overlay is listed while it is shown and the view's zoom
    // lies within its layers' zoom range.

    // The scale as a WMS server computes it: metres of EPSG:3857 per CSS pixel over
    // OGC's standard rendering pixel of 0.28 mm; MapLibre's world is 512 px wide
    var EQUATOR_M = 40075016.68557849;
    var WORLD_PX = 512;
    var STANDARD_PIXEL_M = 0.00028;

    /** The scale's denominator of a zoom. */
    function scaleAt(zoom) {
        return EQUATOR_M / (WORLD_PX * Math.pow(2, zoom)) / STANDARD_PIXEL_M;
    }

    /**
     * What the map draws.
     * @returns {?Object} null before the map exists; else `center` [lng, lat] and
     *     `bounds` [west, south, east, north] in degrees, `scale` (the denominator),
     *     `overlays` from the bottom up, each {id, opacity} and the `lngLat` of an
     *     overlay of one point, and `points`, the network's markers {id, title, lngLat}.
     */
    function describe() {
        if (!map) return null;
        var zoom = map.getZoom();
        var listed = {};
        var shown = [];
        map.getLayersOrder().forEach(function (layerId) {
            var id = layerOverlay[layerId];
            var o = id && overlays[id];
            if (!o || listed[id] || !o.shown) return;
            var layer = o.layers.filter(function (l) { return l.id === layerId; })[0];
            if (!drawnAt(layer, zoom)) return;
            listed[id] = true;
            shown.push(o);
        });
        var center = map.getCenter();
        var bounds = map.getBounds();
        return {
            center: [center.lng, center.lat],
            bounds: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()],
            scale: scaleAt(zoom),
            overlays: shown.map(function (o) {
                var overlay = { id: o.id, opacity: o.opacity };
                if (o.point) overlay.lngLat = o.point.slice();
                return overlay;
            }),
            points: markers.filter(function (m) { return m.point && m.shown; }).map(function (m) {
                return { id: m.id, title: m.element.title, lngLat: m.getLngLat() };
            }),
        };
    }

    // ===== Theme change: restyle every overlay =====

    onThemeChange(function () {
        if (!map) return;
        map.setPaintProperty('background', 'background-color', token('--surface-2'));
        Object.keys(overlays).forEach(function (id) { applyPaint(overlays[id], false); });
        if (streamsLegend) streamsLegend.element.innerHTML = streamsLegendHtml();
        if (hsgLegend) hsgLegend.element.innerHTML = hsgLegendHtml();
        if (landCoverLegend) landCoverLegend.element.innerHTML = landCoverLegendHtml();
        updateWatershedLegend();
    });

    // ===== The map (M3) and its absence (M13) =====

    /** The map's area says why there is no map; the panels go on without it. */
    function unavailable(container, message, error) {
        console.warn('The map is not drawn:', error && error.message ? error.message : error);
        var note = document.createElement('p');
        note.className = 'map-unavailable';
        note.setAttribute('role', 'status');
        note.textContent = message;
        container.replaceChildren(note);
        resolveReady(false);
    }

    /** MapLibre's words of its controls, in Polish. */
    function locale() {
        var kit = basemapKit();
        return {
            'Map.Title': 'Mapa',
            'NavigationControl.ZoomIn': 'Przybliż',
            'NavigationControl.ZoomOut': 'Oddal',
            'AttributionControl.ToggleAttribution': kit && kit.texts ? kit.texts.credit : 'Pokaż lub ukryj źródła',
        };
    }

    /**
     * Keep MapLibre's credit to what the map draws: once no source has a credit left, its
     * control only hides (`maplibregl-attrib-empty`) and keeps the words it showed last,
     * those of a base map that failed or was taken off. The control's own listeners come
     * first, added with it by the map.
     */
    function clearHiddenCredit(created) {
        var credit = created.getContainer().querySelector('.maplibregl-ctrl-attrib');
        var words = credit && credit.querySelector('.maplibregl-ctrl-attrib-inner');
        if (!words) return;
        function clear() {
            if (credit.classList.contains('maplibregl-attrib-empty')) words.replaceChildren();
        }
        created.on('sourcedata', clear);
        created.on('styledata', clear);
    }

    /** A map without rotation or pitch on #map; throws without WebGL 2. */
    function create(container) {
        var created = new maplibregl.Map({
            container: container,
            style: emptyStyle(),
            center: START.center,
            zoom: START.zoom,
            maxZoom: MAX_ZOOM,
            dragRotate: false,
            pitchWithRotate: false,
            touchPitch: false,
            maxPitch: 0,
            // The catalogue's credit in the map's corner; on a phone folded at the first drag
            attributionControl: { compact: window.matchMedia(PHONE).matches },
            locale: locale(),
        });
        created.touchZoomRotate.disableRotation();
        created.keyboard.disableRotation();
        clearHiddenCredit(created);
        // With a listener MapLibre logs nothing itself: a tile that does not load (a
        // missing DEM tile at the data's edge, a provider's failure the kit reports)
        // leaves the map as it is; anything else is a fault of this page
        created.on('error', function (event) {
            if (!event.sourceId && !event.tile) console.warn(event.error);
        });
        return created;
    }

    /** The map's controls and events, once its style has loaded. */
    function configure() {
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
        // Cursor coordinates, bottom left: added first, so the legends stack above it
        if (Hydrograf.coords) Hydrograf.coords.addReadout();

        map.on('click', function (e) {
            if (onMarker(e)) return;
            // Drawing mode: add vertex
            if (drawMode) {
                addDrawVertex(e.lngLat);
                return;
            }
            if (clickCallback) clickCallback(e.lngLat.lat, e.lngLat.lng);
        });

        map.on('dblclick', function (e) {
            if (drawMode) {
                e.preventDefault();
                finishDrawing();
            }
        });

        map.on('mousemove', onHover);
        map.on('mouseout', hideTooltip);

        loadDemOverlay();
    }

    /**
     * Draw the map on #map. A click on the map calls `onClickCallback(lat, lng)`.
     * The base map is not added here: layers.js draws the one its switcher shows.
     * @returns {Promise<boolean>} Hydrograf.map.ready.
     */
    function init(onClickCallback) {
        clickCallback = onClickCallback;
        var container = document.getElementById('map');

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

        // The shell resizes panels around the map; the map must re-measure.
        window.addEventListener('hydrograf:layout', function () {
            if (map) map.resize();
        });

        import(absolute(LIBRARY)).then(function (library) {
            maplibregl = library;
            var created;
            try {
                created = create(container);
            } catch (error) {
                unavailable(container, error instanceof library.GPUInitializationError ? NO_WEBGL : NO_MAP, error);
                return;
            }
            created.once('load', function () {
                map = created;
                configure();
                resolveReady(true);
            });
        }).catch(function (error) {
            unavailable(container, NO_MAP, error);
        });
        return ready;
    }

    window.Hydrograf.map = {
        init: init,
        // Resolves to true once the map is drawn, to false without one (M13); never rejects
        ready: ready,
        // What the map draws, for the browser tests
        describe: describe,
        // Theme: token colours for overlays and charts drawn by other modules
        token: token,
        rgb: rgb,
        mix: mix,
        onThemeChange: onThemeChange,
        // Legend swatch in the style of a path (the network's legend, js/network.js)
        pathSwatch: pathSwatch,
        // Overlays by id (describe()): shown, opacity, extent, filter
        hasOverlay: hasOverlay,
        withinZoom: withinZoom,
        firstScale: firstScale,
        setOverlayShown: setOverlayShown,
        setOverlayOpacity: setOverlayOpacity,
        setOverlayFilter: setOverlayFilter,
        overlayBounds: overlayBounds,
        removeOverlay: removeOverlay,
        showGeojson: showGeojson,
        setGeojson: setGeojson,
        showPoint: showPoint,
        showRaster: showRaster,
        showImage: showImage,
        setTiles: setTiles,
        geojsonBounds: geojsonBounds,
        // Markers and controls
        addPoint: addPoint,
        addLabel: addLabel,
        addControl: addControl,
        // The view
        fitToBounds: fitToBounds,
        getDataBounds: getDataBounds,
        getDemBounds: getDemBounds,
        view: view,
        containerPoint: containerPoint,
        containerRect: containerRect,
        panBy: panBy,
        onZoomEnd: onZoomEnd,
        onPointerMove: onPointerMove,
        setLoadingCursor: setLoadingCursor,
        // Base maps of Nogat's kit
        showBasemap: showBasemap,
        removeBasemap: removeBasemap,
        repaintBasemap: repaintBasemap,
        // DEM, streams and the overlays of the layers panel
        loadDem: loadDem,
        setStreamsThreshold: setStreamsThreshold,
        getStreamsThreshold: getStreamsThreshold,
        loadLandCover: loadLandCover,
        loadSewer: loadSewer,
        loadBdotLakes: loadBdotLakes,
        loadBdotStreams: loadBdotStreams,
        loadHsgLayer: loadHsgLayer,
        // Watershed
        showSelectionBoundary: showSelectionBoundary,
        clearSelectionBoundary: clearSelectionBoundary,
        showDelineatePreview: showDelineatePreview,
        clearDelineatePreview: clearDelineatePreview,
        showOutlet: showOutlet,
        clearWatershed: clearWatershed,
        showMainChannel: showMainChannel,
        showLongestFlowPath: showLongestFlowPath,
        showDivideFlowPath: showDivideFlowPath,
        setWatershedShown: setWatershedShown,
        // Drawing
        startDrawing: startDrawing,
        cancelDrawing: cancelDrawing,
        isDrawing: isDrawing,
        // Profile
        clearProfileLine: clearProfileLine,
        showProfileHoverMarker: showProfileHoverMarker,
        clearProfileHoverMarker: clearProfileHoverMarker,
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
