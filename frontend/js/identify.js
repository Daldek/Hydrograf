/**
 * Hydrograf Identify module.
 *
 * Mode "Identyfikuj": a click on the map puts a marker there and asks the API
 * (GET /api/identify-point) what Hydrograf knows at the point: coordinates,
 * terrain elevation and slope, the water of the analysis results shown on the
 * map (as the terrain profile does), the nearest BDOT10k stream and the water
 * body, land cover with its CN, soil group, terrain depression and the
 * sub-catchment of the flow lines. The answer fills the card #identify-card
 * over the map (a sheet at the bottom of the map on phones). Turning a result
 * or the flow lines threshold on or off reads the open point again.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    // Land cover categories of the database (core/land_cover.py)
    var LAND_COVER = {
        'las': 'Las',
        'łąka': 'Łąka, pastwisko',
        'grunt_orny': 'Grunt orny',
        'zabudowa_mieszkaniowa': 'Zabudowa mieszkaniowa',
        'zabudowa_przemysłowa': 'Zabudowa przemysłowa',
        'droga': 'Droga, plac',
        'woda': 'Woda',
        'inny': 'Inne',
    };
    // BDOT10k stream layers
    var STREAM_KIND = { SWRS: 'rzeka', SWKN: 'kanał', SWRM: 'rów' };
    var SOIL_GROUP = {
        A: 'przepuszczalne',
        B: 'średnio przepuszczalne',
        C: 'słabo przepuszczalne',
        D: 'nieprzepuszczalne',
    };
    // Search radius of the nearest stream in the API (core/point_info.py)
    var STREAM_RADIUS_M = 25;
    // Threshold of "Wybierz zlewnię" while the flow lines were never shown
    var DEFAULT_THRESHOLD_M2 = 100000;
    var COPY_FEEDBACK_MS = 1500;

    var els = {};
    var _request = 0;      // number of the latest request; older answers are dropped
    var _point = null;     // { lat, lng } of the open card
    var _inputs = '';      // threshold and shown results the open card was read with
    var _marker = null;

    // ===== Formatting =====

    /** Number with a decimal comma and a fixed number of decimals. */
    function num(value, digits) {
        return value.toLocaleString('pl-PL', {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
        });
    }

    /** Area as [value, unit]: hectares below 1 km², km² above. */
    function area(m2) {
        var km2 = m2 >= 1e6;
        var value = km2 ? m2 / 1e6 : m2 / 1e4;
        if (!km2 && value < 0.01) return ['< 0,01', 'ha'];
        return [value.toLocaleString('pl-PL', { maximumFractionDigits: 2 }), km2 ? 'km²' : 'ha'];
    }

    /** "Name (kind)"; unnamed objects are common in BDOT10k. */
    function named(name, kind) {
        return (name || 'bez nazwy') + (kind ? ' (' + kind + ')' : '');
    }

    /** Distance in metres: decimetres below 10 m. */
    function metres(value) {
        return num(value, value < 10 ? 1 : 0);
    }

    // ===== Card content =====

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    /**
     * Table of rows: [label, value, unit] for a quantity, [label, text] for a
     * text over the value and unit columns, [title] for a subheading.
     */
    function table(rows) {
        var t = el('table', 'params');
        var body = el('tbody');
        rows.forEach(function (row) {
            var tr = el('tr');
            if (row.length === 1) {
                var cell = el('th', 'identify-subhead', row[0]);
                cell.colSpan = 3;
                cell.scope = 'rowgroup';
                tr.appendChild(cell);
            } else {
                var th = el('th', null, row[0]);
                th.scope = 'row';
                tr.appendChild(th);
                if (row.length === 2) {
                    var text = el('td', 'text', row[1]);
                    text.colSpan = 2;
                    tr.appendChild(text);
                } else {
                    tr.appendChild(el('td', null, row[1]));
                    tr.appendChild(el('td', 'u', row[2]));
                }
            }
            body.appendChild(tr);
        });
        t.appendChild(body);
        return t;
    }

    function section(title, content, source) {
        var wrap = el('section', 'identify-section');
        wrap.appendChild(el('h3', null, title));
        content.forEach(function (node) { wrap.appendChild(node); });
        if (source) wrap.appendChild(el('p', 'identify-source', 'Źródło: ' + source));
        return wrap;
    }

    /** Copy through a selected text field: the Clipboard API needs HTTPS. */
    function legacyCopy(text) {
        var field = el('textarea', 'identify-clip');
        field.value = text;
        field.setAttribute('readonly', '');
        document.body.appendChild(field);
        field.select();
        var ok = false;
        try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
        field.remove();
        return ok;
    }

    function copy(text, button) {
        function show(label) {
            button.textContent = label;
            setTimeout(function () { button.textContent = 'Kopiuj'; }, COPY_FEEDBACK_MS);
        }
        function fallback() { show(legacyCopy(text) ? 'Skopiowano' : 'Nie udało się'); }
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text).then(function () { show('Skopiowano'); }, fallback);
        } else {
            fallback();
        }
    }

    /** WGS84 and PL-1992 rows, each with its copy button. */
    function coordinates(c) {
        var wgs = c.latitude.toFixed(6) + ', ' + c.longitude.toFixed(6);
        var x = c.northing_m.toFixed(2);
        var y = c.easting_m.toFixed(2);
        var block = el('div', 'identify-coords');
        [
            ['WGS84', wgs, wgs, 'Kopiuj współrzędne WGS84 (szerokość, długość)'],
            ['PL-1992', 'X ' + x + ', Y ' + y, 'X=' + x + ' Y=' + y, 'Kopiuj współrzędne PL-1992 (X, Y)'],
        ].forEach(function (row) {
            block.appendChild(el('span', 'k', row[0]));
            block.appendChild(el('span', 'v num', row[1]));
            var button = el('button', 'btn ghost sm', 'Kopiuj');
            button.type = 'button';
            button.title = row[3];
            button.setAttribute('aria-label', row[3]);
            button.addEventListener('click', function () { copy(row[2], button); });
            block.appendChild(button);
        });
        return block;
    }

    function terrainRows(data) {
        var rows = [['Rzędna terenu', num(data.elevation_m, 2), 'm n.p.m.']];
        if (data.slope_percent !== null) rows.push(['Spadek terenu', num(data.slope_percent, 1), '%']);
        return rows;
    }

    /** Depth and level of every shown result, the stream and the water body. */
    function waterContent(data, shown) {
        var rows = [];
        shown.forEach(function (result) {
            var water = data.water.filter(function (w) { return w.result_id === result.id; })[0];
            rows.push([result.title]);
            if (!water) {
                rows.push(['Głębokość wody', 'poza zasięgiem wyniku']);
                return;
            }
            if (water.depth_m !== null) {
                rows.push(['Głębokość wody', num(water.depth_m, 2), 'm']);
            } else {
                rows.push(['Głębokość wody', 'brak wody w tym miejscu']);
            }
            if (water.water_level_m !== null) {
                rows.push(['Zwierciadło wody', num(water.water_level_m, 2), 'm n.p.m.']);
            }
        });
        if (shown.length) rows.push(['Cieki i wody powierzchniowe']);
        var s = data.stream;
        if (s) {
            rows.push(['Ciek', named(s.name, STREAM_KIND[s.layer_type])]);
            rows.push(['Odległość od cieku', metres(s.distance_m), 'm']);
        } else {
            rows.push(['Ciek', 'brak w promieniu ' + STREAM_RADIUS_M + ' m']);
        }
        var b = data.water_body;
        rows.push(['Wody powierzchniowe', b ? named(b.name, b.kind) : 'brak']);

        var content = [table(rows)];
        if (!shown.length && Hydrograf.results && Hydrograf.results.hasWaterLevels()) {
            content.push(el('p', 'identify-note',
                'Włącz wynik analizy w panelu „Warstwy”, aby odczytać głębokość wody.'));
        }
        return content;
    }

    function landRows(data) {
        var lc = data.land_cover;
        var rows = [];
        if (lc) {
            var label = LAND_COVER[lc.category] || lc.category;
            rows.push(['Pokrycie terenu', label + (lc.bdot_class ? ' (' + lc.bdot_class + ')' : '')]);
            rows.push(['CN (AMC II)', String(lc.cn), '']);
            if (lc.imperviousness !== null) {
                rows.push(['Nieprzepuszczalność', num(lc.imperviousness * 100, 0), '%']);
            }
        } else {
            rows.push(['Pokrycie terenu', 'brak danych']);
        }
        var g = data.soil_hsg;
        rows.push(['Grupa glebowa HSG', g ? g + ': ' + (SOIL_GROUP[g] || '') : 'brak danych']);
        var d = data.depression;
        if (d) {
            var surface = area(d.area_m2);
            rows.push(['Zagłębienie terenu']);
            rows.push(['Głębokość maks.', num(d.max_depth_m, 2), 'm']);
            rows.push(['Powierzchnia', surface[0], surface[1]]);
            rows.push(['Objętość', num(d.volume_m3, 0), 'm³']);
        } else {
            rows.push(['Zagłębienie terenu', 'brak']);
        }
        return rows;
    }

    function networkRows(sub) {
        if (!sub) return [['Zlewnia cząstkowa', 'punkt poza siecią spływu']];
        var rows = [];
        if (sub.strahler_order !== null) rows.push(['Rząd Strahlera', String(sub.strahler_order), '']);
        if (sub.upstream_area_km2 !== null) {
            var upstream = area(sub.upstream_area_km2 * 1e6);
            rows.push(['Zlewnia na końcu odcinka', upstream[0], upstream[1]]);
        }
        var own = area(sub.area_km2 * 1e6);
        rows.push(['Zlewnia cząstkowa', own[0], own[1]]);
        if (sub.segment_length_m !== null) rows.push(['Długość odcinka', num(sub.segment_length_m, 0), 'm']);
        if (sub.is_real_stream !== null) rows.push(['Ciek w BDOT10k', sub.is_real_stream ? 'tak' : 'nie']);
        var threshold = area(sub.threshold_m2);
        rows.push(['Próg akumulacji spływu', threshold[0], threshold[1]]);
        return rows;
    }

    function render(data, shown) {
        els.body.innerHTML = '';
        els.body.appendChild(section('Położenie', [coordinates(data.coordinates), table(terrainRows(data))],
            'NMT (GUGiK), spadek z NMT — Hydrograf'));
        els.body.appendChild(section('Woda', waterContent(data, shown),
            (shown.length ? 'wyniki analiz włączone w panelu „Warstwy”; ' : '') +
            'cieki i wody powierzchniowe — BDOT10k (GUGiK)'));
        els.body.appendChild(section('Teren i gleba', [table(landRows(data))],
            'pokrycie terenu — BDOT10k (GUGiK), CN — Hydrograf; grupy glebowe — SoilGrids (Kartograf); zagłębienia — analiza NMT'));
        els.body.appendChild(section('Sieć spływu', [table(networkRows(data.subcatchment))],
            'zlewnie cząstkowe i linie spływu z NMT — Hydrograf'));
    }

    function showLoading() {
        els.body.innerHTML = '';
        var box = el('div', 'loading');
        box.setAttribute('role', 'status');
        var spinner = el('span', 'spinner');
        spinner.setAttribute('aria-hidden', 'true');
        box.appendChild(spinner);
        box.appendChild(el('span', null, 'Odczytywanie danych o punkcie…'));
        els.body.appendChild(box);
    }

    function showError(message) {
        els.body.innerHTML = '';
        var notice = el('p', 'notice bad');
        notice.setAttribute('role', 'alert');
        notice.appendChild(el('span', null, message || 'Nie udało się odczytać informacji o punkcie.'));
        els.body.appendChild(notice);
    }

    // ===== Map marker =====

    function markerStyle() {
        return {
            radius: 7,
            color: Hydrograf.map.token('--surface'),
            weight: 3,
            opacity: 1,
            fillColor: Hydrograf.map.token('--accent'),
            fillOpacity: 1,
        };
    }

    function placeMarker(lat, lng) {
        var map = Hydrograf.map._getMap();
        if (_marker) {
            _marker.setLatLng([lat, lng]);
        } else {
            // Not interactive: a click on it identifies the point under it
            _marker = L.circleMarker([lat, lng], Object.assign({ interactive: false }, markerStyle())).addTo(map);
        }
    }

    /** Pan the map when the card covers the marker (the bottom sheet on phones). */
    function keepMarkerVisible() {
        var map = Hydrograf.map._getMap();
        if (!_marker || els.card.hidden) return;
        var point = map.latLngToContainerPoint(_marker.getLatLng());
        var mapBox = map.getContainer().getBoundingClientRect();
        var card = els.card.getBoundingClientRect();
        var x = mapBox.left + point.x;
        var y = mapBox.top + point.y;
        var margin = 24;
        if (x < card.left - margin || x > card.right + margin || y < card.top - margin || y > card.bottom + margin) return;
        if (card.top - mapBox.top > mapBox.height / 3) {
            map.panBy([0, y - card.top + margin]);
        } else {
            map.panBy([x - card.left + margin, 0]);
        }
    }

    // ===== Requests =====

    function threshold() {
        return Hydrograf.map.getStreamsThreshold() || DEFAULT_THRESHOLD_M2;
    }

    function shownResults() {
        return Hydrograf.results ? Hydrograf.results.shownWaterLevels() : [];
    }

    function inputsKey(t, shown) {
        return t + '|' + shown.map(function (r) { return r.id; }).join(',');
    }

    /**
     * Identify a point: marker, card with a spinner, then the answer or the error.
     * @param {number} lat - latitude (WGS84)
     * @param {number} lng - longitude (WGS84)
     */
    function identifyAt(lat, lng) {
        var request = ++_request;
        var t = threshold();
        var shown = shownResults();
        _point = { lat: lat, lng: lng };
        _inputs = inputsKey(t, shown);
        placeMarker(lat, lng);
        els.card.hidden = false;
        showLoading();
        keepMarkerVisible();
        var ids = shown.map(function (r) { return r.id; });
        Hydrograf.api.identifyPoint(lat, lng, t, ids).then(function (data) {
            if (request !== _request) return;
            render(data, shown);
            keepMarkerVisible();
        }).catch(function (err) {
            if (request !== _request) return;
            showError(err.message);
        });
    }

    /** Read the open point again when the threshold or the shown results changed. */
    function refreshIfInputsChanged() {
        if (!_point) return;
        if (inputsKey(threshold(), shownResults()) !== _inputs) identifyAt(_point.lat, _point.lng);
    }

    /** Close the card and remove the marker. */
    function close() {
        _request++;
        _point = null;
        _inputs = '';
        if (els.card) {
            els.card.hidden = true;
            els.body.innerHTML = '';
        }
        if (_marker) {
            Hydrograf.map._getMap().removeLayer(_marker);
            _marker = null;
        }
    }

    function isOpen() {
        return !!els.card && !els.card.hidden;
    }

    /** Bind the card; call after Hydrograf.map.init. */
    function init() {
        els = {
            card: document.getElementById('identify-card'),
            body: document.getElementById('identify-body'),
        };
        document.getElementById('identify-close').addEventListener('click', close);
        Hydrograf.map._getMap().on('layeradd layerremove', refreshIfInputsChanged);
        Hydrograf.map.onThemeChange(function () {
            if (_marker) _marker.setStyle(markerStyle());
        });
    }

    window.Hydrograf.identify = {
        init: init,
        identifyAt: identifyAt,
        close: close,
        isOpen: isOpen,
    };
})();
