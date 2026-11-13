/**
 * Hydrograf provider lines (Nogat DEV §20).
 *
 * A product made with a provider's data (the PMAXTP precipitation of IMGW-PIB,
 * and the analysis results made with it) carries the lines the provider's terms
 * require: `attribution`, then `terms_notice`, arrays of strings in the API
 * responses and the entries of the results manifest (backend/core/attribution.py
 * is their one place). This module shows them next to the data, byte for byte
 * (the addresses in them become links with the same text), and adds them to the
 * exports: the trailing CSV columns `attribution` and `terms_notice`, and the
 * JSON and GeoJSON fields of the same names. Without lines nothing is shown or
 * added.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var KEYS = ['attribution', 'terms_notice'];
    var ADDRESS_RE = /https?:\/\/[^\s<>"]+/g;
    // Punctuation after an address ends the sentence, not the address
    var TRAILING_PUNCTUATION_RE = /[.,;:!?)\]}\u201d\u2019'"]+$/;

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

    /** Whether `source` has a provider line. */
    function has(source) {
        return !isEmpty(lines(source));
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

    /** Append `text` to `parent` as it is; its web addresses become links with the same text. */
    function appendLine(parent, text) {
        var last = 0;
        var match;
        ADDRESS_RE.lastIndex = 0;
        while ((match = ADDRESS_RE.exec(text)) !== null) {
            var address = match[0].replace(TRAILING_PUNCTUATION_RE, '');
            if (match.index > last) parent.appendChild(document.createTextNode(text.slice(last, match.index)));
            var link = document.createElement('a');
            link.href = address;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = address;
            parent.appendChild(link);
            last = match.index + address.length;
        }
        if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
    }

    /**
     * Show the lines of `source` in `container`: a paragraph per line, the
     * attribution first, then the terms notice. Without lines the container is
     * emptied and hidden. Returns whether lines are shown.
     */
    function render(container, source) {
        if (!container) return false;
        var l = lines(source);
        container.textContent = '';
        KEYS.forEach(function (key) {
            l[key].forEach(function (text) {
                var p = document.createElement('p');
                p.className = key === 'attribution' ? 'provider-attribution' : 'provider-terms';
                appendLine(p, text);
                container.appendChild(p);
            });
        });
        container.hidden = isEmpty(l);
        return !container.hidden;
    }

    /** A new box (class "provider-lines" and `className`) with the lines of `source`; null without lines. */
    function element(source, className) {
        var box = document.createElement('div');
        box.className = 'provider-lines' + (className ? ' ' + className : '');
        return render(box, source) ? box : null;
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
        has: has,
        merge: merge,
        render: render,
        element: element,
        csvTable: csvTable,
        fields: fields,
    };
})();
