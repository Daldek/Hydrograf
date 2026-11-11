/**
 * Hydrograf mode „Sieć zlewni” (ADR-080, ADR-081; plan docs/plans/2026-11-10-network-delineation.md).
 *
 * The first click of the mode places the closing section A, the next ones the points
 * P1, P2, … above it (tributaries at their mouths, gauges): numbered markers that drag
 * (also by touch), listed in the panel with a name field and „Usuń”. The network comes
 * in two stages:
 *
 * - The preview. A short pause after every change of the points or of the threshold of
 *   the streams on the map, POST /api/delineate-network/preview answers in a fraction
 *   of a second: every marker moves to the stream cell it snapped to („przy ujściu” on
 *   a point moved to the junction below it) and the network is drawn: the elements
 *   filled by kind (zlewnia górna, dopływ, przyrzecze) with their ids, dashed where the
 *   outline follows a whole unit that the characteristics split (the point inside it is
 *   marked), the reaches as lines with theirs and the junctions as dots. The panel lists
 *   the tree from A upward with the area of every element and the length of every
 *   reach. An error (a point outside A, off the streams, two points on one cell) marks
 *   the points it names at once. Names do not change the preview.
 * - The characteristics. „Oblicz charakterystyki” sends the points to POST
 *   /api/delineate-network: A's boundary, the parameters of every element, the slopes
 *   of the reaches, the check of B5 and the hand-off of the network (js/handoff.js).
 *   They show while they answer the places of the points; after a point is added,
 *   removed or moved, or the threshold changes, the map and the panel go back to the
 *   preview of the new points. A notice says the characteristics are outdated and the
 *   hand-off is disabled, also after a point is renamed (its name names the hand-off),
 *   until they are computed again or the points come back to where they were.
 *
 * A row of the tree or the label of an element or a reach on the map selects it: with
 * the characteristics its parameters show (an element's in the sections of „Wybierz
 * zlewnię”, js/app.js, a reach's in a table of its own), in the preview a short summary.
 * Clicks on the map always place points, so a gauge can be placed on a drawn reach.
 * Leaving the mode takes the network off the map and „Wyczyść” removes the points, the
 * preview and the characteristics.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    // Limits of POST /api/delineate-network (models/schemas.py)
    var MAX_POINTS = 30;
    var MIN_THRESHOLD_M2 = 10000;
    var DEFAULT_THRESHOLD_M2 = 100000;
    var NAME_MAX = 100;
    // The pause after a change of the points before their preview is asked for [ms]
    var PREVIEW_DELAY_MS = 300;

    var KIND_LABELS = { headwater: 'Zlewnia górna', tributary: 'Dopływ', intermediate: 'Przyrzecze' };
    var KIND_INFO = {
        headwater: 'network-headwater', tributary: 'network-tributary', intermediate: 'network-intermediate',
    };
    var KIND_TOKENS = { headwater: '--accent-green', tributary: '--warn', intermediate: '--tool-hydraulik' };
    var KINDS = ['headwater', 'tributary', 'intermediate'];
    var JUNCTION_LABELS = { confluence: 'Zbieg cieków', point: 'Punkt', outlet: 'Przekrój zamykający' };
    var EXACT_LATER = 'granica dokładna po obliczeniu charakterystyk';
    var OUTDATED_PLACES = 'Charakterystyki są nieaktualne: punkty zmieniły się po ich obliczeniu, poniżej ' +
        'podgląd sieci. Oblicz charakterystyki ponownie, aby przekazać sieć do Hydrologa.';
    var OUTDATED_NAMES = 'Nazwy punktów zmieniły się po obliczeniu charakterystyk. Oblicz je ponownie, ' +
        'aby przekazać sieć do Hydrologa z nowymi nazwami.';

    var state = {
        active: false,      // the mode is on
        outlet: null,       // A: { id, lat, lng, name, marker, snap, row }
        points: [],         // P1, P2, …: the same, in the order of their numbers
        result: null,       // the characteristics (POST /api/delineate-network)
        resultKey: '',      // the request they answer, with the snapped places and the names
        resultPlaces: '',   // the places they answer, snapped, without the names
        request: 0,         // number of the latest run; answers to older ones are dropped
        loading: false,     // the characteristics are being computed
        preview: null,      // the latest preview (POST /api/delineate-network/preview)
        previewKey: '',     // the places it answers, snapped, without the names
        previewRequest: 0,  // number of the latest preview request; answers to older ones are dropped
        previewPending: false,  // the preview of the current points is due or on its way
        previewError: null, // { key, status } of the preview that failed, for the places it was asked for
        error: '',          // the text of the error under the buttons
        bad: {},            // ids of the points the last error names
        selected: null,     // id of the selected element or reach
    };

    var previewTimer = null;    // the pause before the next preview request
    var previewAbort = null;    // AbortController of the preview request on its way
    var markers = null;         // L.LayerGroup of the point markers
    var drawn = null;           // the layers of the network shown: { data, full, group, labels, … }
    var legend = null;          // L.Control of the map legend
    var els = {};

    // ===== Small helpers =====

    function map() { return Hydrograf.map._getMap(); }

    function token(name) { return Hydrograf.map.token(name); }

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function fixed(value, decimals) {
        return value === null || value === undefined ? '—' : value.toFixed(decimals);
    }

    /** Polish plural: 1 zlewnia, 2–4 zlewnie, 5+ zlewni. */
    function plural(n, one, few, many) {
        if (n === 1) return one;
        var mod10 = n % 10;
        var mod100 = n % 100;
        return (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) ? few : many;
    }

    /** The threshold of the streams on the map, the network the points snap to (D1). */
    function threshold() {
        return Math.max(MIN_THRESHOLD_M2, Hydrograf.map.getStreamsThreshold() || DEFAULT_THRESHOLD_M2);
    }

    function allPoints() {
        return (state.outlet ? [state.outlet] : []).concat(state.points);
    }

    function findPoint(id) {
        return allPoints().filter(function (p) { return p.id === id; })[0] || null;
    }

    /** A point's id with its name: „P1 (Kamiennik)”. */
    function pointLabel(id) {
        var p = findPoint(id);
        return p && p.name ? id + ' (' + p.name + ')' : id;
    }

    /** The lowest free P-number, so the ids stay P1…Pn after removals. */
    function nextPointId() {
        var used = {};
        state.points.forEach(function (p) { used[p.id] = true; });
        for (var n = 1; ; n++) {
            if (!used['P' + n]) return 'P' + n;
        }
    }

    /** The name sent to the API: no control characters, no spaces at the ends, null when empty. */
    function cleanName(name) {
        var text = String(name || '').replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ').trim();
        return text ? text.slice(0, NAME_MAX) : null;
    }

    // ===== The requests and what their answers still answer =====

    function apiPoint(p) {
        var point = { id: p.id, latitude: p.lat, longitude: p.lng };
        var name = cleanName(p.name);
        if (name) point.name = name;
        return point;
    }

    /** A point of the preview: its names do not change it, so they are not sent. */
    function placeOf(p) {
        return { id: p.id, latitude: p.lat, longitude: p.lng };
    }

    function requestBody() {
        return {
            outlet: apiPoint(state.outlet),
            points: state.points.map(apiPoint),
            threshold_m2: threshold(),
        };
    }

    function previewBody() {
        return {
            outlet: placeOf(state.outlet),
            points: state.points.map(placeOf),
            threshold_m2: threshold(),
        };
    }

    /** The request of the characteristics: the places, the names (they name the hand-off), the threshold. */
    function requestKey() {
        return state.outlet ? JSON.stringify(requestBody()) : '';
    }

    /** The request of the preview; '' while there is nothing to preview (A and a point at least). */
    function previewKey() {
        return state.outlet && state.points.length ? JSON.stringify(previewBody()) : '';
    }

    /**
     * The key of the request an answer answers: its points at the places they snapped
     * to. The markers move there, and these places snap to themselves, so the answer
     * goes on answering the points until they or the threshold change.
     */
    function answerKey(body, data) {
        var snapped = {};
        data.points.forEach(function (sp) { snapped[sp.id] = sp; });
        function at(bp) {
            var sp = snapped[bp.id];
            return sp ? Object.assign({}, bp, { latitude: sp.latitude, longitude: sp.longitude }) : bp;
        }
        return JSON.stringify({ outlet: at(body.outlet), points: body.points.map(at), threshold_m2: body.threshold_m2 });
    }

    /** The characteristics no longer answer the points: their places, their names or the threshold changed. */
    function isOutdated() {
        return !!state.result && requestKey() !== state.resultKey;
    }

    /** The characteristics no longer answer the places of the points or the threshold; a renamed point keeps them. */
    function placesChanged() {
        return !!state.result && previewKey() !== state.resultPlaces;
    }

    /** The preview of the current points failed on their composition (4xx; 429 is the rate limit). */
    function compositionError() {
        var e = state.previewError;
        return !!e && e.key === previewKey() && e.status >= 400 && e.status < 500 && e.status !== 429;
    }

    function canRun() {
        return !state.loading && !!state.outlet && state.points.length > 0 && !compositionError();
    }

    /**
     * What the map and the panel show: the characteristics while they answer the points,
     * else the preview of the points. While the preview of changed points is on its way,
     * or when it failed, the network shown before stays, faded. Null when there is
     * nothing to show.
     */
    function display() {
        if (state.result && !placesChanged()) return { data: state.result, full: true, faded: false };
        var key = previewKey();
        if (state.preview && key && key === state.previewKey) return { data: state.preview, full: false, faded: false };
        var failed = !!state.previewError && state.previewError.key === key;
        if (drawn && (state.previewPending || failed)) return { data: drawn.data, full: drawn.full, faded: true };
        return null;
    }

    /** The answer of the preview shown about a point, null outside the preview. */
    function previewPoint(p) {
        var d = display();
        if (!d || d.full) return null;
        return d.data.points.filter(function (sp) { return sp.id === p.id; })[0] || null;
    }

    /**
     * In the preview the point lies inside its unit: the outlines of its elements follow
     * the whole unit. A point moved since that preview has no mark.
     */
    function insideUnit(p) {
        var sp = p.snap ? previewPoint(p) : null;
        return !!(sp && sp.inside_unit);
    }

    // ===== Point markers =====

    function markerTitle(p) {
        var role = p === state.outlet ? 'przekrój zamykający' : 'punkt sieci';
        var text = pointLabel(p.id) + ' – ' + role;
        if (p.snap && p.snap.at_mouth) text += ', przy ujściu dopływu';
        if (insideUnit(p)) text += ', ' + EXACT_LATER;
        return text;
    }

    function markerIcon(p) {
        var classes = ['net-marker'];
        if (p === state.outlet) classes.push('is-outlet');
        if (state.bad[p.id]) classes.push('is-bad');
        if (p.snap && p.snap.at_mouth) classes.push('at-mouth');
        if (insideUnit(p)) classes.push('inside-unit');
        return L.divIcon({
            className: classes.join(' '),
            html: '<span>' + p.id + '</span>',
            iconSize: [28, 28],
            iconAnchor: [14, 14],
        });
    }

    /** A new icon only when its marks change: replacing it ends a drag under way. */
    function refreshMarker(p) {
        var icon = markerIcon(p);
        if (icon.options.className !== p.iconClass) {
            p.iconClass = icon.options.className;
            p.marker.setIcon(icon);
        }
        var node = p.marker.getElement();
        if (node) node.title = markerTitle(p);
    }

    function addMarker(p) {
        var icon = markerIcon(p);
        p.iconClass = icon.options.className;
        p.marker = L.marker([p.lat, p.lng], {
            icon: icon,
            draggable: !state.loading,
            autoPan: true,
            title: markerTitle(p),
            alt: p.id,
            riseOnHover: true,
        });
        // An answer to the places before the drag would move the marker under the pointer
        p.marker.on('dragstart', cancelPreview);
        p.marker.on('dragend', function () {
            var at = p.marker.getLatLng();
            p.lat = at.lat;
            p.lng = at.lng;
            changed(p);
        });
        markers.addLayer(p.marker);
    }

    function setDraggable(on) {
        allPoints().forEach(function (p) {
            if (!p.marker.dragging) return;
            if (on) p.marker.dragging.enable();
            else p.marker.dragging.disable();
        });
    }

    /**
     * Every point of an answer moves to the cell it snapped to. A point that snapped to
     * its own place (the request carried where it snapped before) keeps the distance
     * from where it was placed.
     */
    function moveToSnapped(data) {
        data.points.forEach(function (sp) {
            var p = findPoint(sp.id);
            if (!p) return;
            var kept = p.snap && sp.latitude === p.lat && sp.longitude === p.lng;
            p.snap = kept ? Object.assign({}, sp, { snap_distance_m: p.snap.snap_distance_m }) : sp;
            p.lat = sp.latitude;
            p.lng = sp.longitude;
            p.marker.setLatLng([p.lat, p.lng]);
        });
    }

    // ===== Editing the points =====

    /**
     * A click of the mode: A first, then P1, P2, …; at most MAX_POINTS points
     * besides A. Nothing changes while the characteristics are computed.
     */
    function addPoint(lat, lng) {
        if (state.loading) return;
        var p;
        if (!state.outlet) {
            p = state.outlet = { id: 'A', lat: lat, lng: lng, name: '', snap: null };
        } else if (state.points.length >= MAX_POINTS) {
            state.error = 'Sieć ma już ' + MAX_POINTS + ' punktów powyżej A, najwięcej, ile przyjmuje Hydrograf. ' +
                'Usuń punkt, aby dodać nowy.';
            renderState();
            Hydrograf.app.showPanel();
            return;
        } else {
            p = { id: nextPointId(), lat: lat, lng: lng, name: '', snap: null };
            state.points.push(p);
            state.points.sort(function (a, b) { return Number(a.id.slice(1)) - Number(b.id.slice(1)); });
        }
        addMarker(p);
        buildPoints();
        changed(p);
    }

    function removePoint(id) {
        if (state.loading) return;
        var p = findPoint(id);
        if (!p) return;
        markers.removeLayer(p.marker);
        if (p === state.outlet) state.outlet = null;
        else state.points = state.points.filter(function (q) { return q !== p; });
        buildPoints();
        changed(p);
    }

    /**
     * The points or the threshold changed: the error that named the old ones goes, the
     * moved point is no longer where it snapped, the preview of the new points is asked
     * for and the characteristics are outdated until computed again.
     */
    function changed(p) {
        if (p) {
            delete state.bad[p.id];
            p.snap = null;
        }
        state.error = '';
        state.previewError = null;
        Hydrograf.app.setNetworkStatus({ error: '' });
        schedulePreview();
        render();
    }

    // ===== The preview =====

    /**
     * Drop the preview due or on its way: its answer would no longer answer the points.
     * The callers render what follows; a drag that starts leaves the map as it is.
     */
    function cancelPreview() {
        if (previewTimer) {
            clearTimeout(previewTimer);
            previewTimer = null;
        }
        state.previewRequest += 1;
        if (previewAbort) {
            previewAbort.abort();
            previewAbort = null;
        }
        state.previewPending = false;
        els.pending.hidden = true;
    }

    /** Ask for the preview of the points after a pause, unless it is known already. */
    function schedulePreview() {
        cancelPreview();
        var key = previewKey();
        if (!key || key === state.previewKey) return;
        state.previewPending = true;
        previewTimer = setTimeout(requestPreview, PREVIEW_DELAY_MS);
    }

    function requestPreview() {
        previewTimer = null;
        var body = previewBody();
        var key = JSON.stringify(body);
        var request = ++state.previewRequest;
        var abort = new AbortController();
        previewAbort = abort;
        Hydrograf.api.previewNetwork(body, abort.signal).then(function (data) {
            if (request !== state.previewRequest) return;
            moveToSnapped(data);
            state.preview = data;
            state.previewKey = answerKey(body, data);
            state.bad = {};
            if (state.previewError) {
                state.previewError = null;
                state.error = '';
            }
        }).catch(function (err) {
            if (request !== state.previewRequest) return;
            state.previewError = { key: key, status: err.status || 0 };
            state.error = err.message;
            state.bad = {};
            markBadPoints(err.problem);
        }).then(function () {
            if (request !== state.previewRequest) return;
            previewAbort = null;
            state.previewPending = false;
            render();
        });
    }

    // ===== The characteristics =====

    function run() {
        if (!canRun()) return;
        var body = requestBody();
        var places = previewBody();
        var request = ++state.request;
        state.result = null;
        state.resultKey = '';
        state.resultPlaces = '';
        state.error = '';
        state.bad = {};
        state.loading = true;
        setDraggable(false);
        Hydrograf.app.setNetworkStatus({ loading: true, error: '' });
        render();

        Hydrograf.api.delineateNetwork(body).then(function (data) {
            if (request !== state.request) return;
            moveToSnapped(data);
            state.result = data;
            state.resultKey = answerKey(body, data);
            state.resultPlaces = answerKey(places, data);
        }).catch(function (err) {
            if (request !== state.request) return;
            state.error = err.message;
            markBadPoints(err.problem);
            Hydrograf.app.showPanel();
        }).then(function () {
            if (request !== state.request) return;
            state.loading = false;
            setDraggable(true);
            Hydrograf.app.setNetworkStatus({ loading: false });
            // The fallback of the characteristics: the preview of the places they snapped to
            if (!state.previewPending) schedulePreview();
            render();
            if (state.result && state.active && drawn && drawn.boundary) {
                map().fitBounds(drawn.boundary.getBounds(), { padding: [20, 20] });
            }
        });
    }

    /** Mark the points a problem document names (`details.point_id`, `details.point_ids`). */
    function markBadPoints(problem) {
        var details = problem && problem.details;
        if (!details) return;
        var ids = [].concat(details.point_ids || [], details.point_id || []);
        ids.forEach(function (id) {
            if (findPoint(id)) state.bad[id] = true;
        });
    }

    /** „Wyczyść” and the bin of the panel: no points, no preview, no characteristics, nothing pending. */
    function clear() {
        cancelPreview();
        state.request += 1;
        state.loading = false;
        allPoints().forEach(function (p) { markers.removeLayer(p.marker); });
        state.outlet = null;
        state.points = [];
        state.result = null;
        state.resultKey = '';
        state.resultPlaces = '';
        state.preview = null;
        state.previewKey = '';
        state.previewError = null;
        state.error = '';
        state.bad = {};
        Hydrograf.app.setNetworkStatus({ loading: false, error: '' });
        buildPoints();
        render();
    }

    // ===== Map layers of the network =====

    function kindColor(kind) { return token(KIND_TOKENS[kind]); }

    function boundaryStyle() {
        return { color: token('--tool-hydrograf'), weight: 2.5, opacity: 1, fill: false };
    }

    /** An element filled by its kind; dashed where its outline is approximate (preview). */
    function elementStyle(kind, selected, approximate) {
        var color = kindColor(kind);
        return {
            color: color,
            weight: selected ? 3 : approximate ? 2 : 1.2,
            opacity: 0.95,
            dashArray: approximate ? '6,4' : null,
            fillColor: color,
            fillOpacity: selected ? 0.38 : 0.2,
        };
    }

    function approximateStyle() {
        return { color: token('--text-2'), weight: 2, opacity: 1, dashArray: '6,4', fillColor: 'none', fillOpacity: 0 };
    }

    function reachStyle(selected) {
        return { color: token('--info'), weight: selected ? 5.5 : 3.5, opacity: 0.95, lineCap: 'round' };
    }

    function junctionStyle() {
        return { radius: 5, color: token('--text'), weight: 2, opacity: 1, fillColor: token('--surface'), fillOpacity: 1 };
    }

    /**
     * A point inside a polygon for its label: the area centroid of its largest ring,
     * or, when that falls outside (a bent przyrzecze), the middle of the widest run of
     * the ring along the parallel through it. Planar in degrees: elements are small.
     * Null for a geometry without rings.
     */
    function labelPoint(geometry) {
        var polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
        var best = null;
        polygons.forEach(function (polygon) {
            var ring = polygon[0];
            if (!ring || ring.length < 3) return;
            var a = 0;
            var cx = 0;
            var cy = 0;
            for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
                var f = ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1];
                a += f;
                cx += (ring[j][0] + ring[i][0]) * f;
                cy += (ring[j][1] + ring[i][1]) * f;
            }
            if (!best || Math.abs(a) > Math.abs(best.area)) {
                best = { area: a, ring: ring, x: cx / (3 * a), y: cy / (3 * a) };
            }
        });
        if (!best || !best.area) return null;
        var ring = best.ring;
        var y = best.y;
        var xs = [];
        for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
            var y1 = ring[j][1];
            var y2 = ring[i][1];
            if ((y1 > y) !== (y2 > y)) {
                xs.push(ring[j][0] + (y - y1) / (y2 - y1) * (ring[i][0] - ring[j][0]));
            }
        }
        xs.sort(function (p, q) { return p - q; });
        var inside = false;
        var widest = null;
        for (var k = 0; k + 1 < xs.length; k += 2) {
            if (best.x >= xs[k] && best.x <= xs[k + 1]) inside = true;
            if (!widest || xs[k + 1] - xs[k] > widest[1] - widest[0]) widest = [xs[k], xs[k + 1]];
        }
        var x = inside || !widest ? best.x : (widest[0] + widest[1]) / 2;
        return [y, x];
    }

    function labelIcon(id, kind) {
        var classes = 'net-label ' + kind + (state.selected === id ? ' is-selected' : '');
        return L.divIcon({ className: classes, html: '<span>' + id + '</span>', iconSize: null });
    }

    /** A label that selects its element or reach: a click on it places no point. */
    function addLabel(id, kind, latlng, title) {
        var label = L.marker(latlng, {
            icon: labelIcon(id, kind),
            pane: 'networkLabelPane',
            title: title,
            alt: id,
            keyboard: true,
        });
        label.on('click', function () { toggleSelect(id); });
        drawn.labels.addLayer(label);
        drawn.labelOf[id] = { marker: label, kind: kind };
    }

    function midpoint(coords) {
        var c = coords[Math.floor(coords.length / 2)];
        return [c[1], c[0]];
    }

    /** An element's outline: the characteristics carry it in its watershed, the preview may have none. */
    function elementBoundary(s) {
        return s.watershed ? s.watershed.boundary_geojson : s.boundary_geojson;
    }

    function elementArea(s) {
        return s.watershed ? (s.watershed.morphometry || {}).area_km2 : s.area_km2;
    }

    /** Draw a network: the characteristics (`full`) or the preview. */
    function draw(data, full) {
        removeDrawn();
        drawn = {
            data: data,
            full: full,
            group: L.featureGroup(),
            labels: L.layerGroup(),
            boundary: full ? L.geoJSON(data.boundary_geojson, { style: boundaryStyle, interactive: false }) : null,
            elements: {},
            reaches: {},
            junctions: [],
            labelOf: {},
            selectedLayer: null,
        };
        data.subcatchments.forEach(function (s) {
            var boundary = elementBoundary(s);
            // An element of a part of a split unit whose polygon went to its neighbour: no outline, no label
            if (!boundary || !boundary.geometry) return;
            var approximate = !full && !!s.outline_approximate;
            var layer = L.geoJSON(boundary, {
                style: function () { return elementStyle(s.kind, false, approximate); },
                interactive: false,
            });
            drawn.elements[s.id] = { layer: layer, kind: s.kind, approximate: approximate };
            drawn.group.addLayer(layer);
            var at = labelPoint(boundary.geometry);
            if (at) addLabel(s.id, s.kind, at, s.id + ': ' + elementText(s));
        });
        if (drawn.boundary) drawn.group.addLayer(drawn.boundary);
        data.reaches.forEach(function (r) {
            if (!r.geojson || !r.geojson.geometry) return;
            var layer = L.geoJSON(r.geojson, { style: function () { return reachStyle(false); }, interactive: false });
            drawn.reaches[r.id] = layer;
            drawn.group.addLayer(layer);
            addLabel(r.id, 'reach', midpoint(r.geojson.geometry.coordinates), r.id + ': ' + reachText(r));
        });
        data.junctions.forEach(function (j) {
            var dot = L.circleMarker([j.latitude, j.longitude], junctionStyle());
            // A DOM node: the names the person typed never become HTML
            dot.bindTooltip(el('span', null, j.id + ': ' + junctionText(j)), { direction: 'top' });
            drawn.junctions.push(dot);
            drawn.group.addLayer(dot);
        });
        showDrawn();
    }

    /** The layers on the map in their order: approximate outlines over the others, then the lines and dots. */
    function showDrawn() {
        if (!drawn || !state.active) return;
        drawn.group.addTo(map());
        drawn.labels.addTo(map());
        Object.keys(drawn.elements).forEach(function (id) {
            if (drawn.elements[id].approximate) drawn.elements[id].layer.bringToFront();
        });
        if (drawn.boundary) drawn.boundary.bringToFront();
        Object.keys(drawn.reaches).forEach(function (id) { drawn.reaches[id].bringToFront(); });
        drawn.junctions.forEach(function (dot) { dot.bringToFront(); });
        updateLegend();
        restyle();
    }

    function hideDrawn() {
        if (drawn) {
            map().removeLayer(drawn.group);
            map().removeLayer(drawn.labels);
        }
        updateLegend();
    }

    function removeDrawn() {
        hideDrawn();
        drawn = null;
        updateLegend();
    }

    /** Styles from the tokens of the theme; the selection and a network on its way out show. */
    function restyle() {
        if (!drawn) return;
        var d = display();
        var faded = !!(d && d.faded);
        if (drawn.boundary) drawn.boundary.setStyle(boundaryStyle());
        Object.keys(drawn.elements).forEach(function (id) {
            var e = drawn.elements[id];
            var style = elementStyle(e.kind, state.selected === id, e.approximate);
            if (faded) { style.opacity *= 0.5; style.fillOpacity *= 0.5; }
            e.layer.setStyle(style);
        });
        Object.keys(drawn.reaches).forEach(function (id) {
            var style = reachStyle(state.selected === id);
            if (faded) style.opacity *= 0.5;
            drawn.reaches[id].setStyle(style);
        });
        drawn.junctions.forEach(function (dot) { dot.setStyle(junctionStyle()); });
        Object.keys(drawn.labelOf).forEach(function (id) {
            var label = drawn.labelOf[id];
            label.marker.setIcon(labelIcon(id, label.kind));
        });
        if (drawn.selectedLayer) drawn.selectedLayer.bringToFront();
    }

    // ===== Map legend =====

    function legendRows() {
        var data = drawn.data;
        var rows = [];
        if (drawn.boundary) {
            rows.push([Hydrograf.map.pathSwatch(Object.assign({ fillColor: 'none', fillOpacity: 0 },
                boundaryStyle()), 'area'), 'Granica zlewni A']);
        }
        KINDS.forEach(function (kind) {
            if (data.subcatchments.some(function (s) { return s.kind === kind; })) {
                rows.push([Hydrograf.map.pathSwatch(elementStyle(kind, false, false), 'area'), KIND_LABELS[kind]]);
            }
        });
        var approximate = Object.keys(drawn.elements).some(function (id) { return drawn.elements[id].approximate; });
        if (approximate) rows.push([Hydrograf.map.pathSwatch(approximateStyle(), 'area'), 'Granica przybliżona']);
        if (Object.keys(drawn.reaches).length) rows.push([Hydrograf.map.pathSwatch(reachStyle(false)), 'Odcinek']);
        rows.push([Hydrograf.map.pathSwatch(junctionStyle(), 'point'), 'Węzeł']);
        return rows;
    }

    function updateLegend() {
        var shown = !!(state.active && drawn && map().hasLayer(drawn.group));
        if (!shown) {
            if (legend) {
                map().removeControl(legend);
                legend = null;
            }
            return;
        }
        if (!legend) {
            legend = L.control({ position: 'bottomleft' });
            legend.onAdd = function () { return L.DomUtil.create('div', 'layer-legend network-legend'); };
            legend.addTo(map());
        }
        legend.getContainer().innerHTML = '<div class="layer-legend-title">' +
            (drawn.full ? 'Sieć zlewni' : 'Podgląd sieci') + '</div>' +
            legendRows().map(function (row) {
                return '<div class="legend-item">' + row[0] + '<span>' + row[1] + '</span></div>';
            }).join('');
    }

    // ===== Texts of the elements =====

    function atMouth(pointId) {
        var p = findPoint(pointId);
        return !!(p && p.snap && p.snap.at_mouth);
    }

    function elementText(s) {
        if (s.kind === 'headwater') {
            return s.point ? 'Zlewnia górna do punktu ' + pointLabel(s.point) : 'Zlewnia górna powyżej ' + s.to;
        }
        if (s.kind === 'tributary') {
            return (atMouth(s.point) ? 'Dopływ do ujścia przy ' : 'Dopływ do punktu ') + pointLabel(s.point);
        }
        return 'Przyrzecze odcinka ' + s.reach;
    }

    function reachText(r) {
        return 'Odcinek ' + r.from + ' → ' + r.to;
    }

    function junctionText(j) {
        var text = JUNCTION_LABELS[j.kind];
        return j.point ? text + ' ' + pointLabel(j.point) : text;
    }

    function slopeText(r) {
        return fixed(r.slope_m_per_m * 1000, 2);
    }

    // ===== Selection =====

    function findElement(d, id) {
        if (!d || !id) return null;
        return d.data.subcatchments.filter(function (s) { return s.id === id; })[0] || null;
    }

    function findReach(d, id) {
        if (!d || !id) return null;
        return d.data.reaches.filter(function (r) { return r.id === id; })[0] || null;
    }

    /** A label on the map: select its element or reach, or drop it when selected; the panel follows. */
    function toggleSelect(id) {
        select(state.selected === id ? null : id, { reveal: 'start' });
    }

    /**
     * Select an element or a reach of the network shown; null selects nothing. With the
     * characteristics an element's parameters fill the sections of the panel; the
     * preview has none. `how.zoom` moves the map to it (a row of the list),
     * `how.reveal` scrolls the panel to the selection.
     */
    function select(id, how) {
        var opts = how || {};
        var d = display();
        var element = findElement(d, id);
        var reach = element ? null : findReach(d, id);
        state.selected = element || reach ? id : null;
        Hydrograf.app.showElementParameters(element && d.full && state.active ? element.watershed : null);
        if (drawn) {
            var layer = element ? drawn.elements[id] && drawn.elements[id].layer : reach ? drawn.reaches[id] : null;
            drawn.selectedLayer = layer || null;
            restyle();
            if (opts.zoom && drawn.selectedLayer && state.active) {
                map().fitBounds(drawn.selectedLayer.getBounds(), { padding: [40, 40], maxZoom: 15 });
            }
        }
        renderSelection(d);
        renderTreeSelection();
        if (opts.reveal && state.selected && state.active) {
            els.selection.scrollIntoView({ block: opts.reveal, behavior: 'smooth' });
        }
    }

    // ===== Rendering =====

    /**
     * Show what follows the points, the preview and the characteristics: the network on
     * the map (drawn anew when another answer shows, which drops the selection), the
     * rows of the points, the buttons and notices, the result in the panel.
     */
    function render() {
        var d = display();
        if (!d) {
            if (drawn) {
                dropSelection();
                removeDrawn();
            }
        } else if (!drawn || drawn.data !== d.data) {
            dropSelection();
            draw(d.data, d.full);
        }
        restyle();
        allPoints().forEach(refreshMarker);
        updatePoints();
        renderState();
        renderResult(d);
    }

    function dropSelection() {
        state.selected = null;
        Hydrograf.app.showElementParameters(null);
    }

    function renderSnap() {
        els.snap.textContent = 'Punkty dociągane do cieków progu ' +
            Hydrograf.layers.formatThreshold(threshold()) +
            ' (warstwa „Linie spływu”), każdy do najbliższego cieku w promieniu 100 m.';
    }

    function pointMeta(p) {
        if (!p.snap) return '';
        if (p.snap.at_mouth) return 'przy ujściu dopływu';
        return p.snap.snap_distance_m >= 1
            ? 'na cieku, ' + Math.round(p.snap.snap_distance_m) + ' m od kliknięcia'
            : 'na cieku';
    }

    /** The rows of the points, built when points come or go; updatePoints() fills what changes. */
    function buildPoints() {
        var list = els.points;
        list.textContent = '';
        var points = allPoints();
        if (!points.length) {
            list.appendChild(el('li', 'network-empty', 'Brak punktów: kliknij na mapie przekrój zamykający A.'));
            return;
        }
        if (!state.outlet) {
            list.appendChild(el('li', 'network-empty', 'Brak przekroju zamykającego A: kliknij go na mapie.'));
        }
        points.forEach(function (p) {
            var li = el('li');
            li.appendChild(el('span', 'net-badge', p.id));
            var body = el('div', 'net-point-body');
            var input = el('input');
            input.type = 'text';
            input.maxLength = NAME_MAX;
            input.value = p.name;
            input.placeholder = p === state.outlet ? 'Przekrój zamykający: nazwa (opcjonalnie)' : 'Nazwa (opcjonalnie)';
            input.setAttribute('aria-label', 'Nazwa punktu ' + p.id);
            // A name changes no preview, only the characteristics, whose hand-off it names
            input.addEventListener('input', function () {
                p.name = input.value;
                render();
            });
            body.appendChild(input);
            var meta = el('span', 'net-point-meta');
            body.appendChild(meta);
            var approx = el('span', 'net-point-meta is-approx', '≈ ' + EXACT_LATER);
            body.appendChild(approx);
            li.appendChild(body);
            var remove = el('button', 'btn sm ghost', 'Usuń');
            remove.type = 'button';
            remove.setAttribute('aria-label', 'Usuń punkt ' + p.id);
            remove.addEventListener('click', function () { removePoint(p.id); });
            li.appendChild(remove);
            p.row = { li: li, input: input, meta: meta, approx: approx, remove: remove };
            list.appendChild(li);
        });
        updatePoints();
    }

    /** What the rows of the points show of the answers: the error mark, where they snapped, the busy state. */
    function updatePoints() {
        allPoints().forEach(function (p) {
            if (!p.row) return;
            p.row.li.className = 'net-point' + (p === state.outlet ? ' is-outlet' : '') +
                (state.bad[p.id] ? ' is-bad' : '');
            p.row.meta.textContent = pointMeta(p);
            p.row.meta.hidden = !p.row.meta.textContent;
            p.row.approx.hidden = !insideUnit(p);
            p.row.input.disabled = state.loading;
            p.row.remove.disabled = state.loading;
        });
    }

    /** The parts that follow the points: buttons, error, preview status, outdated notice, hand-off, context. */
    function renderState() {
        var outdated = isOutdated();
        els.run.disabled = !canRun();
        els.clear.disabled = !allPoints().length && !state.result;
        els.pending.hidden = !state.previewPending;
        els.error.classList.toggle('d-none', !state.error);
        els.errorText.textContent = state.error;
        els.outdated.classList.toggle('d-none', !outdated);
        els.outdatedText.textContent = placesChanged() ? OUTDATED_PLACES : OUTDATED_NAMES;
        Hydrograf.app.setNetworkStatus({ clearable: !els.clear.disabled });
        if (Hydrograf.handoff) {
            Hydrograf.handoff.showNetwork(state.result ? state.result.handoff : null, outdated);
        }
        renderContext();
    }

    function renderContext() {
        if (!state.active) return;
        var d = display();
        if (d) {
            var a = d.data.points[0];
            Hydrograf.app.setContext('Sieć zlewni ' + fixed(d.data.area_km2, 2) + ' km²',
                'A ' + fixed(a.latitude, 5) + ' °N, ' + fixed(a.longitude, 5) + ' °E');
        } else {
            var n = state.points.length;
            Hydrograf.app.setContext('Sieć zlewni', state.outlet
                ? 'A i ' + n + ' ' + plural(n, 'punkt', 'punkty', 'punktów')
                : '');
        }
    }

    function kpi(label, value, unit) {
        var box = el('div', 'kpi');
        box.appendChild(el('div', 'k', label));
        var v = el('div', 'v', value);
        if (unit) {
            v.appendChild(document.createTextNode(' '));
            v.appendChild(el('span', 'u', unit));
        }
        box.appendChild(v);
        return box;
    }

    function notice(className, text) {
        var p = el('p', 'notice' + (className ? ' ' + className : ''));
        p.appendChild(el('span', null, text));
        return p;
    }

    /** The network shown in the panel; hidden while the characteristics are computed (their spinner shows). */
    function renderResult(d) {
        els.result.classList.toggle('d-none', !d || state.loading);
        els.result.classList.toggle('is-outdated', !!(d && d.faded));
        renderSelection(d);
        if (!d) return;
        var data = d.data;

        els.stage.hidden = d.full;
        els.summary.textContent = '';
        els.summary.appendChild(kpi('Zlewnia A', fixed(data.area_km2, 2), 'km²'));
        els.summary.appendChild(kpi('Zlewnie', String(data.subcatchments.length)));
        els.summary.appendChild(kpi('Odcinki', String(data.reaches.length)));
        els.summary.appendChild(kpi('Węzły', String(data.junctions.length)));

        els.check.hidden = !d.full;
        if (d.full) {
            els.check.textContent = 'Suma elementów = zlewnia A: elementy ' +
                fixed(data.area_check.elements_km2, 6) + ' km², zlewnia A ' +
                fixed(data.area_check.watershed_km2, 6) + ' km².';
        }

        els.notices.textContent = '';
        data.notices.forEach(function (n) {
            var ids = n.ids.join(', ');
            if (n.code === 'over_scs_cn_limit') {
                els.notices.appendChild(notice('warn', 'Zlewnie powyżej 250 km², granicy stosowalności ' +
                    'metody SCS-CN: ' + ids + '.'));
            } else if (n.code === 'reach_slope_minimum') {
                els.notices.appendChild(notice('warn', 'Spadek minimalny 0,1 ‰, bo NMT nie opada między ' +
                    'końcami odcinka: ' + ids + '.'));
            }
        });

        els.kinds.textContent = '';
        KINDS.forEach(function (kind) {
            if (!data.subcatchments.some(function (s) { return s.kind === kind; })) return;
            var item = el('li', 'net-kind-item');
            item.appendChild(el('span', 'net-swatch ' + kind));
            var label = el('span', null, KIND_LABELS[kind]);
            item.appendChild(label);
            Hydrograf.info.attach(label, KIND_INFO[kind]);
            els.kinds.appendChild(item);
        });

        renderTree(d);
    }

    // ===== The tree, from A upward =====

    /**
     * The rows of the tree: at a junction the branches joining from the side come
     * first, one step in, then the trunk goes on at the same depth, so the main river
     * reads down the list from A to its headwater.
     */
    function treeRows(data) {
        var byId = {};
        data.subcatchments.forEach(function (s) { byId[s.id] = { type: 'element', item: s }; });
        data.reaches.forEach(function (r) { byId[r.id] = { type: 'reach', item: r }; });
        data.junctions.forEach(function (j) { byId[j.id] = { type: 'junction', item: j }; });
        var rows = [];
        function walk(id, depth) {
            var node = byId[id];
            if (!node) return;
            rows.push({ id: id, type: node.type, item: node.item, depth: depth });
            if (node.type === 'junction') {
                node.item.inflows.slice(1).forEach(function (branch) { walk(branch, depth + 1); });
                if (node.item.inflows.length) walk(node.item.inflows[0], depth);
            } else if (node.type === 'reach') {
                walk(node.item.from, depth);
            }
        }
        var outlet = data.junctions.filter(function (j) { return j.kind === 'outlet'; })[0];
        if (outlet) walk(outlet.id, 0);
        return rows;
    }

    function valueCells(tr, value, unit) {
        tr.appendChild(el('td', null, value));
        tr.appendChild(el('td', 'u', unit));
    }

    /** The tree with the area and the CN of each element, the length and the slope of each reach (preview: „—”). */
    function renderTree(d) {
        var tbody = els.tree;
        tbody.textContent = '';
        treeRows(d.data).forEach(function (row) {
            var tr = el('tr', 'net-row is-' + row.type);
            tr.dataset.id = row.id;
            var th = el('th');
            th.scope = 'row';
            th.style.setProperty('--depth', String(row.depth));
            var kind = row.type === 'element' ? row.item.kind : row.type;
            var id = el('span', 'net-id ' + kind, row.id);
            if (row.type === 'junction') {
                th.appendChild(id);
                th.appendChild(document.createTextNode(' ' + junctionText(row.item)));
                tr.appendChild(th);
                tr.appendChild(el('td', null, ''));
                tr.appendChild(el('td', 'u', ''));
                tr.appendChild(el('td', null, ''));
                tr.appendChild(el('td', 'u', ''));
            } else {
                var btn = el('button', 'net-row-btn');
                btn.type = 'button';
                btn.appendChild(id);
                var text = row.type === 'element' ? elementText(row.item) : reachText(row.item);
                btn.appendChild(document.createTextNode(' ' + text));
                btn.setAttribute('aria-pressed', 'false');
                btn.addEventListener('click', function () {
                    select(state.selected === row.id ? null : row.id, { zoom: true, reveal: 'nearest' });
                });
                th.appendChild(btn);
                tr.appendChild(th);
                if (row.type === 'element') {
                    valueCells(tr, fixed(elementArea(row.item), 2), 'km²');
                    valueCells(tr, d.full ? fixed((row.item.watershed.morphometry || {}).cn, 1) : '—', 'CN');
                } else {
                    valueCells(tr, fixed(row.item.length_km, 2), 'km');
                    if (d.full) {
                        valueCells(tr, slopeText(row.item), row.item.slope_method === 'minimum' ? '‰ min.' : '‰');
                    } else {
                        valueCells(tr, '—', '‰');
                    }
                }
            }
            tbody.appendChild(tr);
        });
        renderTreeSelection();
    }

    function renderTreeSelection() {
        Array.prototype.forEach.call(els.tree.querySelectorAll('tr'), function (tr) {
            var on = tr.dataset.id === state.selected;
            tr.classList.toggle('is-selected', on);
            var btn = tr.querySelector('.net-row-btn');
            if (btn) btn.setAttribute('aria-pressed', String(on));
        });
    }

    // ===== The selected element or reach =====

    function paramRow(label, value, unit, infoKey) {
        var tr = el('tr');
        var th = el('th', null, label);
        th.scope = 'row';
        if (infoKey) Hydrograf.info.attach(th, infoKey);
        tr.appendChild(th);
        tr.appendChild(el('td', null, value));
        tr.appendChild(el('td', 'u', unit || ''));
        return tr;
    }

    function renderSelection(d) {
        var element = findElement(d, state.selected);
        var reach = element ? null : findReach(d, state.selected);
        els.selection.hidden = !(element || reach);
        els.selectionKind.textContent = '';
        els.reach.textContent = '';
        if (element) {
            els.selectionTitle.textContent = element.id + ' · ' + elementText(element);
            var kind = el('span', 'net-kind ' + element.kind, KIND_LABELS[element.kind]);
            els.selectionKind.appendChild(kind);
            Hydrograf.info.attach(kind, KIND_INFO[element.kind]);
            var text = ' · ' + fixed(elementArea(element), 2) + ' km²';
            if (d.full) {
                text += ' · CN ' + fixed((element.watershed.morphometry || {}).cn, 1) + ' · do ' + element.to +
                    '. Parametry w sekcjach poniżej, jak dla wyznaczonej zlewni.';
            } else {
                text += ' · do ' + element.to + '.';
                if (!elementBoundary(element)) text += ' Granica po obliczeniu charakterystyk.';
                else if (element.outline_approximate) text += ' Granica przybliżona, dokładna po obliczeniu charakterystyk.';
                text += ' Parametry po obliczeniu charakterystyk.';
            }
            els.selectionKind.appendChild(document.createTextNode(text));
        } else if (reach && !d.full) {
            els.selectionTitle.textContent = reach.id + ' · ' + reachText(reach);
            els.selectionKind.textContent = 'Odcinek · ' + fixed(reach.length_km, 2) + ' km · do ' + reach.to +
                '. Spadek i parametry po obliczeniu charakterystyk.';
        } else if (reach) {
            els.selectionTitle.textContent = reach.id + ' · ' + reachText(reach);
            els.selectionKind.textContent = 'Muskingum–Cunge w Hydrologu: przekrój (n Manninga, szerokość) ' +
                'podasz tam przed trasowaniem.';
            els.reach.appendChild(paramRow('Długość odcinka', fixed(reach.length_km, 2), 'km', 'reach_length_km'));
            els.reach.appendChild(paramRow('Spadek odcinka', slopeText(reach), '‰', 'reach_slope_m_per_m'));
            els.reach.appendChild(paramRow('Źródło spadku', reach.slope_method === 'minimum'
                ? 'minimalny (NMT nie opada)' : 'NMT na końcach'));
            els.reach.appendChild(paramRow('NMT u góry odcinka', fixed(reach.upstream_elevation_m, 2), 'm n.p.m.'));
            els.reach.appendChild(paramRow('NMT u dołu odcinka', fixed(reach.downstream_elevation_m, 2), 'm n.p.m.'));
            els.reach.appendChild(reach.vector_length_km !== null && reach.vector_length_km !== undefined
                ? paramRow('Długość wzdłuż BDOT10k', fixed(reach.vector_length_km, 2), 'km', 'reach_vector_length_km')
                : paramRow('Długość wzdłuż BDOT10k', 'brak', '', 'reach_vector_length_km'));
        }
    }

    // ===== The mode =====

    /** Entering „Sieć zlewni”: its points, its network, its section and its context. */
    function enter() {
        state.active = true;
        els.section.hidden = false;
        markers.addTo(map());
        showDrawn();
        renderSnap();
        render();
        if (state.selected) select(state.selected);
    }

    /** Leaving the mode: its layers leave the map and its section the panel; nothing is lost. */
    function leave() {
        state.active = false;
        els.section.hidden = true;
        map().removeLayer(markers);
        hideDrawn();
    }

    function init() {
        els = {
            section: document.getElementById('network'),
            snap: document.getElementById('network-snap'),
            points: document.getElementById('network-points'),
            run: document.getElementById('network-run'),
            clear: document.getElementById('network-clear'),
            pending: document.getElementById('network-pending'),
            error: document.getElementById('network-error'),
            errorText: document.getElementById('network-error-text'),
            outdated: document.getElementById('network-outdated'),
            outdatedText: document.getElementById('network-outdated-text'),
            result: document.getElementById('network-result'),
            stage: document.getElementById('network-stage'),
            summary: document.getElementById('network-summary'),
            check: document.getElementById('network-check'),
            notices: document.getElementById('network-notices'),
            kinds: document.getElementById('network-kinds'),
            tree: document.getElementById('network-tree'),
            selection: document.getElementById('network-selection'),
            selectionTitle: document.getElementById('network-selection-title'),
            selectionKind: document.getElementById('network-selection-kind'),
            reach: document.getElementById('network-reach'),
        };
        var m = map();
        m.createPane('networkLabelPane');
        m.getPane('networkLabelPane').style.zIndex = 450;
        markers = L.layerGroup();

        els.run.addEventListener('click', run);
        els.clear.addEventListener('click', clear);
        document.getElementById('network-deselect').addEventListener('click', function () { select(null); });

        // The threshold of the streams on the map changes when their layer is replaced
        var shownThreshold = threshold();
        m.on('layeradd layerremove', function () {
            if (threshold() === shownThreshold) return;
            shownThreshold = threshold();
            renderSnap();
            changed(null);
        });
        Hydrograf.map.onThemeChange(function () {
            restyle();
            updateLegend();
        });
        renderSnap();
        buildPoints();
        render();
    }

    window.Hydrograf.network = {
        init: init,
        addPoint: addPoint,
        clear: clear,
        enter: enter,
        leave: leave,
    };
})();
