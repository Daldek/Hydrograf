/**
 * Hydrograf analysis results.
 *
 * Results of external analyses (first: SFINCS maximum water depth from
 * Hydraulik) are listed in the manifest /data/results/index.json
 * (schema "hydrograf-results/1"). This module reads it once, keeps the
 * entries it can show (kind "raster_tiles": XYZ PNG tiles) and puts their
 * tiles on the map (Hydrograf.map, overlay `result:<id>`) with their legends
 * and (i) texts; layers.js turns each entry into a row of the "Warstwy"
 * panel. No manifest, or no usable entry, means no rows.
 * A result made with a provider's data (the SFINCS depths of a PMAXTP
 * rainfall) carries the lines its producer wrote in `attribution` and
 * `terms_notice`: they go to the view's strip while its layer is on
 * (attribution.js).
 * A result with a `water_level` raster (sampled by the API) adds its water
 * surface to the terrain profile and its water depth to the point card of
 * the mode "Identyfikuj" while its layer is on the map: a result turned on or
 * off fires `hydrograf:results` on window (js/identify.js asks again).
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var MANIFEST_URL = '/data/results/index.json';
    var SCHEMA = 'hydrograf-results/1';
    var DEFAULT_GROUP = 'Wyniki analiz';
    var DEFAULT_OPACITY = 0.8;
    // The map's first zoom of a result without a first tile level: today's 1:2 183 915
    var FIRST_ZOOM = 7;

    // Results read from the manifest (load)
    var _results = [];

    /** [west, south, east, north] (WGS84) of the manifest; null if invalid. */
    function parseBounds(b) {
        if (!Array.isArray(b) || b.length !== 4) return null;
        if (!b.every(function (v) { return typeof v === 'number' && isFinite(v); })) return null;
        if (b[0] >= b[2] || b[1] >= b[3]) return null;
        return b.slice();
    }

    function zoomLevel(v) {
        return typeof v === 'number' && v >= 0 && v <= 24 && Math.floor(v) === v ? v : undefined;
    }

    /** Legend classes with a label and a colour; null when there are none. */
    function parseLegend(legend) {
        if (!legend || !Array.isArray(legend.classes)) return null;
        var classes = legend.classes.filter(function (c) {
            return c && typeof c.label === 'string' && typeof c.color === 'string';
        });
        if (!classes.length) return null;
        return {
            title: typeof legend.title === 'string' ? legend.title : '',
            unit: typeof legend.unit === 'string' ? legend.unit : '',
            classes: classes,
        };
    }

    /** Register the result's description and source as an (i) text; returns its key or null. */
    function registerInfo(result, raw) {
        var texts = window.Hydrograf.infoTexts;
        var description = typeof raw.description === 'string' ? raw.description : '';
        var source = typeof raw.source === 'string' ? raw.source : '';
        if (!texts || (!description && !source)) return null;
        var key = 'result:' + result.id;
        texts[key] = {
            title: result.title,
            definition: description,
            sources: source,
        };
        return key;
    }

    /**
     * Normalised result (its tiles not yet on the map), or null when the entry
     * cannot be shown.
     */
    function parseResult(raw) {
        if (!raw || typeof raw !== 'object') return null;
        var id = typeof raw.id === 'string' ? raw.id : '';
        if (raw.kind !== 'raster_tiles') {
            console.warn('Analysis result "' + id + '" skipped: unsupported kind', raw.kind);
            return null;
        }
        var bounds = parseBounds(raw.bounds);
        var tiles = typeof raw.tiles === 'string' && /\{z\}.*\{x\}.*\{y\}/.test(raw.tiles) ? raw.tiles : null;
        if (!id || !tiles || !bounds) {
            console.warn('Analysis result "' + id + '" skipped: missing id, tiles or bounds');
            return null;
        }
        var opacity = typeof raw.opacity === 'number' && raw.opacity >= 0 && raw.opacity <= 1
            ? raw.opacity : DEFAULT_OPACITY;
        var result = {
            id: id,
            title: typeof raw.title === 'string' && raw.title ? raw.title : id,
            group: typeof raw.group === 'string' && raw.group ? raw.group : DEFAULT_GROUP,
            bounds: bounds,
            opacity: opacity,
            tiles: tiles,
            minZoom: zoomLevel(raw.min_zoom),
            maxZoom: zoomLevel(raw.max_zoom),
            added: false,
            legend: parseLegend(raw.legend),
            legendControl: null,
            // Arrays of non-empty strings; anything else is ignored, as the API does
            lines: Hydrograf.attribution.lines(raw),
            waterLevel: !!(raw.water_level && typeof raw.water_level.path === 'string'),
        };
        result.infoKey = registerInfo(result, raw);
        return result;
    }

    /**
     * Put the result's tiles on the map, hidden, unless they are there: a raster source
     * with the manifest's extent and tile levels, drawn from its first level (a tile
     * level is the map's zoom plus one: 256-px tiles in MapLibre's 512-px world).
     * @returns {Promise<boolean>} Whether they are on the map.
     */
    function addLayer(result) {
        return Hydrograf.map.ready.then(function (shown) {
            if (!shown) return false;
            if (!result.added) {
                Hydrograf.map.showRaster('result:' + result.id, {
                    tiles: [new URL(result.tiles, document.baseURI).href
                        .replace(/%7B/gi, '{').replace(/%7D/gi, '}')],
                    tileSize: 256,
                    bounds: result.bounds,
                    minzoom: result.minZoom,
                    maxzoom: result.maxZoom,
                    layerMinzoom: result.minZoom === undefined ? FIRST_ZOOM : Math.max(FIRST_ZOOM, result.minZoom - 1),
                    opacity: result.opacity,
                    shown: false,
                });
                result.added = true;
            }
            return true;
        });
    }

    /**
     * Read the manifest once. Resolves to the usable results (possibly none);
     * a missing or invalid manifest gives one console warning, never an error.
     * @returns {Promise<Array<Object>>}
     */
    function load() {
        return fetch(MANIFEST_URL, { cache: 'no-cache' })
            .then(function (res) {
                if (!res.ok) throw new Error('HTTP ' + res.status);
                return res.json();
            })
            .then(function (manifest) {
                if (!manifest || manifest.schema !== SCHEMA) {
                    throw new Error('unsupported schema ' + (manifest && manifest.schema));
                }
                _results = (Array.isArray(manifest.results) ? manifest.results : [])
                    .map(parseResult)
                    .filter(Boolean);
                return _results;
            })
            .catch(function (err) {
                console.warn('Analysis results not available (' + MANIFEST_URL + '):', err.message);
                return [];
            });
    }

    function node(tag, className, parent) {
        var created = document.createElement(tag);
        created.className = className;
        if (parent) parent.appendChild(created);
        return created;
    }

    /** Legend box: title with the unit in brackets and one swatch per class. */
    function legendElement(result) {
        var legend = result.legend;
        var div = node('div', 'layer-legend');
        var title = node('div', 'layer-legend-title', div);
        title.textContent = legend.title + (legend.unit ? ' [' + legend.unit + ']' : '');
        legend.classes.forEach(function (c) {
            var item = node('div', 'legend-item', div);
            node('span', 'legend-swatch', item).style.background = c.color;
            item.appendChild(document.createTextNode(' ' + c.label));
        });
        return div;
    }

    function isShown(result) {
        return Hydrograf.map.hasOverlay('result:' + result.id);
    }

    /** The provider lines of the results whose layer is on the map to the view's strip. */
    function showProviderLines() {
        Hydrograf.attribution.show('results', Hydrograf.attribution.merge(_results
            .filter(isShown)
            .map(function (r) { return r.lines; })));
    }

    /** The result's layer is on: its legend, and its lines in the view's strip. */
    function showLegend(result) {
        showProviderLines();
        window.dispatchEvent(new CustomEvent('hydrograf:results'));
        if (result.legendControl || !result.legend) return;
        result.legendControl = Hydrograf.map.addControl(legendElement(result), 'bottom-left');
    }

    /** The result's layer is off: no legend, and its lines leave the view's strip. */
    function hideLegend(result) {
        showProviderLines();
        window.dispatchEvent(new CustomEvent('hydrograf:results'));
        if (!result.legendControl) return;
        result.legendControl.remove();
        result.legendControl = null;
    }

    /** Results with a water level raster whose layer is on the map: [{ id, title }]. */
    function shownWaterLevels() {
        return _results
            .filter(function (r) { return r.waterLevel && isShown(r); })
            .map(function (r) { return { id: r.id, title: r.title }; });
    }

    /** Whether the manifest lists a result with a water level raster. */
    function hasWaterLevels() {
        return _results.some(function (r) { return r.waterLevel; });
    }

    window.Hydrograf.results = {
        load: load,
        addLayer: addLayer,
        showLegend: showLegend,
        hideLegend: hideLegend,
        shownWaterLevels: shownWaterLevels,
        hasWaterLevels: hasWaterLevels,
    };
})();
