/**
 * Hydrograf Coordinates module.
 *
 * The position of the cursor, live, in the bottom left corner of the map: in
 * geographic coordinates WGS84, in PL-1992 (EPSG:2180) or in PL-2000
 * (EPSG:2176–2179, the zone by the longitude). The chosen system is kept in
 * localStorage. Screens without a hovering pointer (touch) do not show the
 * readout (app.css): "Identyfikuj" gives the three of a tapped point. Only
 * the Polish systems are supported.
 *
 * Both grids are Gauss–Krüger (transverse Mercator) projections of the GRS80
 * ellipsoid, computed with Krüger's series to the sixth order of the third
 * flattening (Karney 2011), which agree with PROJ to far below a millimetre
 * within a zone. WGS84 stands for ETRF2000-PL, the datum of the grids, as in
 * PROJ (a null transformation, accurate to 1 m).
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var STORAGE_KEY = 'hydrograf-coord-system';
    var DEG = Math.PI / 180;

    // GRS80 semi-major axis [m] and flattening
    var A = 6378137;
    var F = 1 / 298.257222101;
    var N = F / (2 - F);
    var E = 2 * Math.sqrt(N) / (1 + N);
    var N2 = N * N;
    var N3 = N2 * N;
    var N4 = N3 * N;
    var N5 = N4 * N;
    var N6 = N5 * N;
    // Rectifying radius and Krüger's coefficients α1…α6 (Karney 2011, eq. 14 and 35)
    var RECTIFYING_RADIUS = A / (1 + N) * (1 + N2 / 4 + N4 / 64 + N6 / 256);
    var ALPHA = [
        N / 2 - 2 * N2 / 3 + 5 * N3 / 16 + 41 * N4 / 180 - 127 * N5 / 288 + 7891 * N6 / 37800,
        13 * N2 / 48 - 3 * N3 / 5 + 557 * N4 / 1440 + 281 * N5 / 630 - 1983433 * N6 / 1935360,
        61 * N3 / 240 - 103 * N4 / 140 + 15061 * N5 / 26880 + 167603 * N6 / 181440,
        49561 * N4 / 161280 - 179 * N5 / 168 + 6601661 * N6 / 7257600,
        34729 * N5 / 80640 - 3418889 * N6 / 1995840,
        212378941 * N6 / 319334400,
    ];

    /**
     * Gauss–Krüger projection of a WGS84 point.
     * @returns {{x: number, y: number}} x northing, y easting [m], as in Polish surveying
     */
    function gaussKruger(lat, lng, centralMeridian, scale, falseEasting, falseNorthing) {
        var sinLat = Math.sin(lat * DEG);
        var dLng = (lng - centralMeridian) * DEG;
        // Tangent of the conformal latitude
        var t = Math.sinh(Math.atanh(sinLat) - E * Math.atanh(E * sinLat));
        var xi0 = Math.atan2(t, Math.cos(dLng));
        var eta0 = Math.atanh(Math.sin(dLng) / Math.sqrt(1 + t * t));
        var xi = xi0;
        var eta = eta0;
        for (var j = 1; j <= ALPHA.length; j++) {
            xi += ALPHA[j - 1] * Math.sin(2 * j * xi0) * Math.cosh(2 * j * eta0);
            eta += ALPHA[j - 1] * Math.cos(2 * j * xi0) * Math.sinh(2 * j * eta0);
        }
        return {
            x: falseNorthing + scale * RECTIFYING_RADIUS * xi,
            y: falseEasting + scale * RECTIFYING_RADIUS * eta,
        };
    }

    /** PL-1992 (EPSG:2180): meridian 19°E, scale 0.9993. */
    function pl1992(lat, lng) {
        return gaussKruger(lat, lng, 19, 0.9993, 500000, -5300000);
    }

    /** PL-2000 zone of a longitude: 5 west of 16.5°E, 6 to 19.5°E, 7 to 22.5°E, 8 east of it. */
    function pl2000Zone(lng) {
        return Math.min(8, Math.max(5, Math.floor((lng + 1.5) / 3)));
    }

    /** PL-2000 in the zone of the longitude: meridian 3·zone °E, scale 0.999923. */
    function pl2000(lat, lng) {
        var zone = pl2000Zone(lng);
        var point = gaussKruger(lat, lng, 3 * zone, 0.999923, zone * 1000000 + 500000, 0);
        point.zone = zone;
        return point;
    }

    // ===== Readout =====

    var SYSTEMS = [
        { id: 'wgs84', label: 'WGS84', title: 'Współrzędne geograficzne WGS84 (EPSG:4326)' },
        { id: 'pl1992', label: 'PL-1992', title: 'Układ PL-1992 (EPSG:2180): X na północ, Y na wschód' },
        {
            id: 'pl2000',
            label: 'PL-2000',
            title: 'Układ PL-2000 (EPSG:2176–2179), strefa według długości geograficznej: X na północ, Y na wschód',
        },
    ];
    var GAP = '\u2002';    // en space between the two coordinates

    function system(id) {
        return SYSTEMS.filter(function (s) { return s.id === id; })[0] || null;
    }

    function stored() {
        try { return localStorage.getItem(STORAGE_KEY); } catch (e) { return null; }
    }

    function store(id) {
        try {
            localStorage.setItem(STORAGE_KEY, id);
        } catch (e) {
            // Storage unavailable: the choice lasts for this page only.
        }
    }

    function degrees(value, positive, negative) {
        var text = Math.abs(value).toLocaleString('pl-PL', {
            minimumFractionDigits: 5,
            maximumFractionDigits: 5,
        });
        return text + '° ' + (value < 0 ? negative : positive);
    }

    function metres(value) {
        return Math.round(value).toLocaleString('pl-PL');
    }

    /** The point in a system: [coordinates, zone]. */
    function format(id, latlng) {
        if (id === 'wgs84') {
            return [degrees(latlng.lat, 'N', 'S') + GAP + degrees(latlng.lng, 'E', 'W'), ''];
        }
        var p = id === 'pl2000' ? pl2000(latlng.lat, latlng.lng) : pl1992(latlng.lat, latlng.lng);
        return ['X ' + metres(p.x) + GAP + 'Y ' + metres(p.y) + ' m', p.zone ? 'strefa ' + p.zone : ''];
    }

    /**
     * Add the readout of the cursor position to the map (bottom left, under the legends).
     * @param {L.Map} map
     */
    function addReadout(map) {
        var current = system(stored()) ? stored() : 'wgs84';
        var last = null;
        var frame = 0;
        var els = {};

        function render() {
            frame = 0;
            els.select.title = system(current).title;
            els.box.classList.toggle('empty', !last);
            if (!last) {
                els.value.textContent = 'Najedź kursorem na mapę';
                els.zone.textContent = '';
                return;
            }
            var text = format(current, last);
            els.value.textContent = text[0];
            els.zone.textContent = text[1];
        }

        var control = L.control({ position: 'bottomleft' });
        control.onAdd = function () {
            els.box = L.DomUtil.create('div', 'coord-readout');
            els.box.title = 'Współrzędne kursora';
            els.select = L.DomUtil.create('select', '', els.box);
            els.select.setAttribute('aria-label', 'Układ współrzędnych kursora');
            SYSTEMS.forEach(function (s) {
                var option = L.DomUtil.create('option', '', els.select);
                option.value = s.id;
                option.textContent = s.label;
            });
            els.select.value = current;
            els.value = L.DomUtil.create('span', 'coord-value num', els.box);
            els.zone = L.DomUtil.create('span', 'coord-zone', els.box);
            els.select.addEventListener('change', function () {
                current = els.select.value;
                store(current);
                render();
            });
            // A click or wheel on the readout is not a click or zoom of the map, and
            // the cursor over it keeps the last position on the map
            L.DomEvent.disableClickPropagation(els.box);
            L.DomEvent.disableScrollPropagation(els.box);
            L.DomEvent.on(els.box, 'mousemove', L.DomEvent.stopPropagation);
            render();
            return els.box;
        };
        control.addTo(map);

        map.on('mousemove', function (e) {
            last = e.latlng;
            if (!frame) frame = requestAnimationFrame(render);
        });
    }

    window.Hydrograf.coords = {
        pl1992: pl1992,
        pl2000: pl2000,
        pl2000Zone: pl2000Zone,
        addReadout: addReadout,
    };
})();
