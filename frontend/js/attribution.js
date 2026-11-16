/**
 * Hydrograf provider lines (Nogat DEV §20).
 *
 * A product made with a provider's data (the PMAXTP precipitation of IMGW-PIB and
 * the analysis results made with it, the NMT and BDOT10k of GUGiK and the SoilGrids
 * of ISRIC behind every layer and result of Hydrograf) carries the lines the
 * provider's terms require: `attribution`, then `terms_notice`, arrays of strings in
 * the API responses and the entries of the results manifest
 * (backend/core/attribution.py is their one place). On screen the view has one strip
 * of them, the kit's <nogat-sources id="view-sources"> under the map (DEV-20.5,
 * ECO-064, ECO-068): every surface of the view (the hydrograph panel, the own
 * rainfall series, the delineated watershed, the network, the layers of Hydrograf's
 * data and the result layers on the map, the point card, the terrain profile) hands
 * it the lines of the data it shows with show(), and the strip holds their union,
 * each line once, grouped by provider in the order of DEV-20.4; the kit draws GK and
 * SK from G and SG. The exports carry them in full, byte for byte: the trailing CSV
 * columns `attribution` and `terms_notice`, and the JSON and GeoJSON fields of the
 * same names. Without lines nothing is shown or added.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var KEYS = ['attribution', 'terms_notice'];
    // The lines each surface of the view shows, by surface (show)
    var _shown = {};
    // DEV-20.4 orders the lines by provider: IMGW-PIB (S, P, PS, PP, M), ČHMÚ (C, CP),
    // GUGiK (G), ISRIC (SG), ČÚZK (Z); a line of another provider follows them. The
    // lines themselves come from the responses, in their order within a provider.
    var PROVIDERS = [/Meteorologii i Gospodarki Wodnej/, /ČHMÚ/, /GUGiK/, /ISRIC/, /ČÚZK/];

    /** The place of a line's provider in the order of DEV-20.4. */
    function providerRank(text) {
        for (var i = 0; i < PROVIDERS.length; i++) {
            if (PROVIDERS[i].test(text)) return i;
        }
        return PROVIDERS.length;
    }

    /** The lines grouped by provider in the order of DEV-20.4, each group in its order. */
    function byProvider(texts) {
        return texts
            .map(function (text, i) { return { text: text, rank: providerRank(text), i: i }; })
            .sort(function (a, b) { return a.rank - b.rank || a.i - b.i; })
            .map(function (item) { return item.text; });
    }

    /** The lines under `key`: an array of non-empty strings, or none. */
    function list(source, key) {
        var value = source ? source[key] : null;
        if (value == null) return [];
        var valid = Array.isArray(value) && value.every(function (line) {
            return typeof line === 'string' && line !== '';
        });
        if (!valid) {
            console.warn('Provider lines ignored: ' + key + ' is not a list of texts');
            return [];
        }
        return value.slice();
    }

    /**
     * The provider lines of `source` (an API response, a manifest entry):
     * { attribution, terms_notice }, each an array of non-empty strings. A key
     * that is not such an array gives no lines, as the API reads the manifest.
     */
    function lines(source) {
        return { attribution: list(source, 'attribution'), terms_notice: list(source, 'terms_notice') };
    }

    function isEmpty(l) {
        return !l.attribution.length && !l.terms_notice.length;
    }

    /**
     * The lines of a product with the data of several `sources` (DEV-20.4):
     * every line once, in the order it first comes; a null source has none.
     */
    function merge(sources) {
        var out = { attribution: [], terms_notice: [] };
        sources.forEach(function (source) {
            var l = lines(source);
            KEYS.forEach(function (key) {
                l[key].forEach(function (text) {
                    if (out[key].indexOf(text) < 0) out[key].push(text);
                });
            });
        });
        return out;
    }

    /** Whether `element` is laid out: neither it nor an ancestor has display none. */
    function rendered(element) {
        for (var e = element; e; e = e.parentElement) {
            if (getComputedStyle(e).display === 'none') return false;
        }
        return true;
    }

    /** Put the union of the lines the surfaces show now into the view's strip. */
    function update() {
        var strip = document.getElementById('view-sources');
        if (!strip) return;
        var l = merge(Object.keys(_shown).filter(function (surface) {
            var places = _shown[surface].places;
            return !places || places.some(rendered);
        }).map(function (surface) { return _shown[surface].source; }));
        // Attributes, not properties: they hold before the kit's module defines the element.
        // Unchanged lines are not set again, so an open dialog of the strip stays open.
        var attribution = JSON.stringify(byProvider(l.attribution));
        var terms = JSON.stringify(l.terms_notice);
        if (strip.getAttribute('attribution') !== attribution) strip.setAttribute('attribution', attribution);
        if (strip.getAttribute('terms-notice') !== terms) strip.setAttribute('terms-notice', terms);
    }

    /**
     * The lines `source` (an API response, a manifest entry, lines; null for none)
     * that the surface `surface` of the view shows; the view's strip #view-sources
     * holds the union of every surface's lines. With `places` (elements of the
     * results panel) a surface's lines count only while one of them is laid out,
     * as the panel hides and shows its sections (a cleared watershed, a new one
     * loading, the network, a collapsed panel).
     */
    function show(surface, source, places) {
        _shown[surface] = { source: source, places: places || null };
        update();
    }

    // The panel hides its sections by classes and attributes: the strip follows them
    var _frame = 0;
    var panel = document.getElementById('results-panel');
    if (panel) {
        new MutationObserver(function () {
            if (_frame) return;
            _frame = requestAnimationFrame(function () {
                _frame = 0;
                update();
            });
        }).observe(panel, {
            attributes: true,
            subtree: true,
            attributeFilter: ['class', 'hidden', 'data-view', 'data-element'],
        });
    }

    /** A CSV cell of a line (RFC 4180): quoted, its quotes doubled; empty stays empty. */
    function csvCell(text) {
        return text === '' ? '' : '"' + text.replace(/"/g, '""') + '"';
    }

    /** One cell per row from the first; the last row of `n` holds the lines left, joined by "\n". */
    function column(texts, n) {
        var cells = [];
        for (var i = 0; i < n - 1; i++) cells.push(i < texts.length ? texts[i] : '');
        cells.push(texts.slice(n - 1).join('\n'));
        return cells;
    }

    /**
     * A CSV table with the lines of `source` as its trailing columns
     * `attribution` and `terms_notice` (DEV-20.5): `header` is the array of the
     * column names, `rows` the arrays of the data cells. The lines go one per
     * cell from the first data row down, empty cells below; with fewer rows than
     * lines the last row holds the rest. Returns the rows with the header first
     * (arrays of cells, to be joined with ","); without lines the columns are
     * left out.
     */
    function csvTable(header, rows, source) {
        var l = lines(source);
        var table = [header.slice()].concat(rows.map(function (row) { return row.slice(); }));
        if (isEmpty(l)) return table;
        // A table without data rows gets one with empty cells to hold the lines
        if (!rows.length) table.push(header.map(function () { return ''; }));
        var n = table.length - 1;
        var attribution = column(l.attribution, n);
        var terms = column(l.terms_notice, n);
        table[0].push('attribution', 'terms_notice');
        for (var i = 0; i < n; i++) table[i + 1].push(csvCell(attribution[i]), csvCell(terms[i]));
        return table;
    }

    /**
     * The fields `attribution` and `terms_notice` of a JSON document, or the
     * foreign members of a GeoJSON FeatureCollection, with the lines of
     * `source` (DEV-20.5), to be merged into the document where it puts them;
     * a field without lines is left out.
     */
    function fields(source) {
        var l = lines(source);
        var out = {};
        KEYS.forEach(function (key) {
            if (l[key].length) out[key] = l[key];
        });
        return out;
    }

    window.Hydrograf.attribution = {
        lines: lines,
        merge: merge,
        show: show,
        csvTable: csvTable,
        fields: fields,
    };
})();
