/**
 * Hydrograf analysis results.
 *
 * Results of external analyses (first: SFINCS maximum water depth from
 * Hydraulik) are listed in the manifest /data/results/index.json
 * (schema "hydrograf-results/1"). This module reads it once, keeps the
 * entries it can show (kind "raster_tiles": XYZ PNG tiles) and builds their
 * tile layers, legends and (i) texts; layers.js turns each entry into a row
 * of the "Warstwy" panel. No manifest, or no usable entry, means no rows.
 * A result made with a provider's data (the SFINCS depths of a PMAXTP
 * rainfall) carries the lines its producer wrote in `attribution` and
 * `terms_notice`: its legend box shows them while its layer is on, and its
 * (i) text ends with them (attribution.js).
 * A result with a `water_level` raster (sampled by the API) adds its water
 * surface to the terrain profile and its water depth to the point card of
 * the mode "Identyfikuj" while its layer is on the map.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var MANIFEST_URL = '/data/results/index.json';
    var SCHEMA = 'hydrograf-results/1';
    var DEFAULT_GROUP = 'Wyniki analiz';
    var DEFAULT_OPACITY = 0.8;

    // Results read from the manifest (load)
    var _results = [];

    /** Leaflet bounds from [west, south, east, north] (WGS84); null if invalid. */
    function parseBounds(b) {
        if (!Array.isArray(b) || b.length !== 4) return null;
        if (!b.every(function (v) { return typeof v === 'number' && isFinite(v); })) return null;
        if (b[0] >= b[2] || b[1] >= b[3]) return null;
        return L.latLngBounds([b[1], b[0]], [b[3], b[2]]);
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

    /**
     * Register the result's description, source and provider lines as an (i)
     * text; returns its key or null.
     */
    function registerInfo(result, raw) {
        var texts = window.Hydrograf.infoTexts;
        var description = typeof raw.description === 'string' ? raw.description : '';
        var source = typeof raw.source === 'string' ? raw.source : '';
        if (!texts || (!description && !source && !Hydrograf.attribution.has(result.lines))) return null;
        var key = 'result:' + result.id;
        texts[key] = {
            title: result.title,
            definition: description,
            sources: source,
            attribution: result.lines.attribution,
            terms_notice: result.lines.terms_notice,
        };
        return key;
    }

    /**
     * Normalised result with its (not yet added) tile layer, or null when the
     * entry cannot be shown.
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
            legend: parseLegend(raw.legend),
            legendControl: null,
            // Arrays of non-empty strings; anything else is ignored, as the API does
            lines: Hydrograf.attribution.lines(raw),
            waterLevel: !!(raw.water_level && typeof raw.water_level.path === 'string'),
            layer: L.tileLayer(tiles, {
                bounds: bounds,
                minZoom: 8,
                maxZoom: 22,
                minNativeZoom: zoomLevel(raw.min_zoom),
                maxNativeZoom: zoomLevel(raw.max_zoom),
                opacity: opacity,
                pane: 'resultsPane',
                errorTileUrl: '',
            }),
        };
        result.infoKey = registerInfo(result, raw);
        return result;
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

    /**
     * Legend box: title with the unit in brackets and one swatch per class (or
     * the result's title without classes), then the provider lines.
     */
    function legendElement(result) {
        var legend = result.legend;
        var div = L.DomUtil.create('div', 'layer-legend');
        var title = L.DomUtil.create('div', 'layer-legend-title', div);
        if (legend) {
            title.textContent = legend.title + (legend.unit ? ' [' + legend.unit + ']' : '');
            legend.classes.forEach(function (c) {
                var item = L.DomUtil.create('div', 'legend-item', div);
                var swatch = L.DomUtil.create('span', 'legend-swatch', item);
                swatch.style.background = c.color;
                item.appendChild(document.createTextNode(' ' + c.label));
            });
        } else {
            title.textContent = result.title;
        }
        var lines = Hydrograf.attribution.element(result.lines, 'layer-legend-lines');
        if (lines) {
            div.classList.add('has-provider-lines');
            div.appendChild(lines);
            // A click on a link of the lines, or scrolling them (phones), does not reach the map below
            L.DomEvent.disableClickPropagation(div);
            L.DomEvent.disableScrollPropagation(div);
        }
        return div;
    }

    function showLegend(result) {
        if (result.legendControl || !(result.legend || Hydrograf.attribution.has(result.lines))) return;
        result.legendControl = L.control({ position: 'bottomleft' });
        result.legendControl.onAdd = function () { return legendElement(result); };
        result.legendControl.addTo(Hydrograf.map._getMap());
    }

    function hideLegend(result) {
        if (!result.legendControl) return;
        Hydrograf.map._getMap().removeControl(result.legendControl);
        result.legendControl = null;
    }

    /** Results with a water level raster whose layer is on the map: [{ id, title }]. */
    function shownWaterLevels() {
        var map = Hydrograf.map._getMap();
        return _results
            .filter(function (r) { return r.waterLevel && map.hasLayer(r.layer); })
            .map(function (r) { return { id: r.id, title: r.title }; });
    }

    /** Whether the manifest lists a result with a water level raster. */
    function hasWaterLevels() {
        return _results.some(function (r) { return r.waterLevel; });
    }

    /** The provider lines of the results whose layer is on the map, each once (attribution.js). */
    function shownLines() {
        var map = Hydrograf.map._getMap();
        return Hydrograf.attribution.merge(_results
            .filter(function (r) { return map.hasLayer(r.layer); })
            .map(function (r) { return r.lines; }));
    }

    window.Hydrograf.results = {
        load: load,
        showLegend: showLegend,
        hideLegend: hideLegend,
        shownWaterLevels: shownWaterLevels,
        hasWaterLevels: hasWaterLevels,
        shownLines: shownLines,
    };
})();
