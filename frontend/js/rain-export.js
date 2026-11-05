/**
 * Hydrograf export of the rainfall of a hydrograph (Hietogram section).
 *
 * "Hietogram CSV" and "Hietogram JSON" download the steps of the hietogram the
 * hydrograph used (depth, effective rainfall, cumulative depth); the JSON adds the
 * scenario and the PMAXTP grid points of the depth. "Punkty PMAXTP (GeoJSON)"
 * downloads those points (WGS84, RFC 7946) with their depths and weights: the
 * Thiessen polygon areas of a watershed mean with its boundary, or the distances
 * of the interpolation at a point with that point. A custom series has no points.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var _current = null; // { result, context } of the hietogram shown
    var els = {};

    /** "1h, p = 10%" in a file name: "1h_p10"; a custom series: "wlasna_seria". */
    function fileStem(c) {
        var p = c.result.precipitation;
        if (p.source === 'custom') return 'wlasna_seria';
        return c.context.duration + '_p' + String(p.probability_percent).replace('.', ',');
    }

    function round(x, digits) {
        var f = Math.pow(10, digits);
        return Math.round(x * f) / f;
    }

    /** The steps of the hietogram: times_min are the ends of the steps. */
    function steps(p) {
        var cumulative = 0;
        return p.times_min.map(function (end, i) {
            var depth = p.intensities_mm[i];
            cumulative += depth;
            return {
                step: i + 1,
                start_min: round(end - p.timestep_min, 3),
                end_min: end,
                precipitation_mm: depth,
                effective_mm: p.effective_mm[i] != null ? p.effective_mm[i] : null,
                cumulative_mm: round(cumulative, 3),
            };
        });
    }

    function save(name, text, type) {
        var url = URL.createObjectURL(new Blob([text], { type: type }));
        var link = document.createElement('a');
        link.href = url;
        link.download = name;
        link.hidden = true;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    }

    function csv() {
        var rows = ['krok,czas_od_min,czas_do_min,opad_mm,opad_efektywny_mm,opad_narastajacy_mm'];
        steps(_current.result.precipitation).forEach(function (s) {
            rows.push([s.step, s.start_min, s.end_min, s.precipitation_mm,
                s.effective_mm == null ? '' : s.effective_mm, s.cumulative_mm].join(','));
        });
        save('hietogram_' + fileStem(_current) + '.csv', rows.join('\r\n') + '\r\n', 'text/csv');
    }

    function json() {
        var p = _current.result.precipitation;
        var c = _current.context;
        var doc = {
            created_at: new Date().toISOString(),
            producer: 'Hydrograf',
            point: c.point,
            rainfall: {
                source: p.source,
                duration: p.source === 'custom' ? null : c.duration,
                duration_min: p.duration_min,
                probability_percent: p.probability_percent,
                total_mm: p.total_mm,
                timestep_min: p.timestep_min,
                hietogram_type: c.hietogram,
                hietogram_alpha: c.hietogram === 'beta' ? c.alpha : null,
                hietogram_beta: c.hietogram === 'beta' ? c.beta : null,
                interpolation: p.interpolation || null,
            },
            steps: steps(p),
            pmaxtp_points: p.pmaxtp_points || [],
        };
        save('hietogram_' + fileStem(_current) + '.json', JSON.stringify(doc, null, 2) + '\n', 'application/json');
    }

    function geojson() {
        var p = _current.result.precipitation;
        var c = _current.context;
        var features = (p.pmaxtp_points || []).map(function (pt) {
            return {
                type: 'Feature',
                geometry: { type: 'Point', coordinates: [pt.longitude, pt.latitude] },
                properties: {
                    role: 'pmaxtp_grid_point',
                    precipitation_mm: pt.precipitation_mm,
                    weight: pt.weight,
                    area_km2: pt.area_km2,
                    distance_m: pt.distance_m,
                    easting_m_epsg2180: pt.easting_m,
                    northing_m_epsg2180: pt.northing_m,
                },
            };
        });
        if (p.interpolation === 'thiessen' && c.boundary && c.boundary.geometry) {
            features.push({ type: 'Feature', geometry: c.boundary.geometry, properties: { role: 'watershed' } });
        } else if (p.interpolation === 'idw') {
            features.push({
                type: 'Feature',
                geometry: { type: 'Point', coordinates: [c.point.longitude, c.point.latitude] },
                properties: { role: 'interpolation_point' },
            });
        }
        var doc = {
            type: 'FeatureCollection',
            // Foreign members (RFC 7946, 6.1): the scenario of the depths
            rainfall: {
                duration: c.duration,
                probability_percent: p.probability_percent,
                total_mm: p.total_mm,
                interpolation: p.interpolation,
            },
            features: features,
        };
        save('punkty_PMAXTP_' + fileStem(_current) + '.geojson', JSON.stringify(doc) + '\n', 'application/geo+json');
    }

    /** A new hietogram of a hydrograph response; context: duration, hietogram, alpha, beta, point, boundary. */
    function show(result, context) {
        _current = { result: result, context: context };
        els.box.classList.remove('d-none');
        var points = (result.precipitation.pmaxtp_points || []).length;
        els.geojson.classList.toggle('d-none', !points);
    }

    /** No hietogram: the export is hidden. */
    function clear() {
        _current = null;
        if (els.box) els.box.classList.add('d-none');
    }

    function init() {
        els = {
            box: document.getElementById('rain-export'),
            geojson: document.getElementById('rain-export-geojson'),
        };
        if (!els.box) return;
        document.getElementById('rain-export-csv').addEventListener('click', function () { if (_current) csv(); });
        document.getElementById('rain-export-json').addEventListener('click', function () { if (_current) json(); });
        els.geojson.addEventListener('click', function () { if (_current) geojson(); });
    }

    window.Hydrograf.rainExport = {
        init: init,
        show: show,
        clear: clear,
    };
})();
