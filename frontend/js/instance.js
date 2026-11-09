/**
 * Hydrograf Instance — what the data of this instance cover, from /data/instance.json
 * (schema hydrograf-instance/1, written by the bootstrap or scripts.write_instance_info).
 * Without the file every text stays neutral. An element marked data-instance-area gets
 * ": <area> (ok. <km²> km²)" appended to its sentence.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var INFO_URL = '/data/instance.json';
    var SCHEMA = 'hydrograf-instance/1';

    var pending = null;

    // The document, or null: missing (404), unreadable or of another schema
    function load() {
        if (!pending) {
            pending = fetch(INFO_URL, { cache: 'no-cache' })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (info) { return info && info.schema === SCHEMA ? info : null; })
                .catch(function () { return null; });
        }
        return pending;
    }

    function formatNumber(value, digits) {
        return value.toLocaleString('pl-PL', { maximumFractionDigits: digits });
    }

    // "zlewnia Kaczawy do Legnicy (ok. 790 km²)", or null without a name
    function areaLabel(info) {
        var area = info && info.area;
        if (!area || !area.name) return null;
        if (typeof area.area_km2 !== 'number') return area.name;
        var km2 = formatNumber(area.area_km2, area.area_km2 < 100 ? 1 : 0);
        return area.name + ' (ok.\u00a0' + km2 + '\u00a0km²)';
    }

    // "NMT 5 m, zestaw danych „2026-2” (zamknięty 8.11.2026)", or null when unknown
    function sourcesLabel(info) {
        if (!info) return null;
        var parts = [];
        if (info.nmt && typeof info.nmt.resolution_m === 'number') {
            parts.push('NMT ' + formatNumber(info.nmt.resolution_m, 1) + '\u00a0m');
        }
        if (info.set && info.set.name) {
            var set = 'zestaw danych „' + info.set.name + '”';
            var closed = info.set.closed_at ? new Date(info.set.closed_at) : null;
            if (closed && !isNaN(closed)) {
                set += ' (zamknięty ' + closed.toLocaleDateString('pl-PL') + ')';
            }
            parts.push(set);
        }
        return parts.length ? parts.join(', ') : null;
    }

    function fillAreas() {
        var targets = document.querySelectorAll('[data-instance-area]');
        if (!targets.length) return;
        load().then(function (info) {
            var label = areaLabel(info);
            if (!label) return;
            targets.forEach(function (el) { el.textContent = ': ' + label; });
        });
    }

    window.Hydrograf.instance = {
        load: load,
        areaLabel: areaLabel,
        sourcesLabel: sourcesLabel,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', fillAreas);
    } else {
        fillAreas();
    }
})();
