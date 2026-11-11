/**
 * Hydrograf mode „Sieć zlewni” (ADR-080, ADR-081; plans docs/plans/2026-11-10-network-delineation.md
 * and docs/plans/2026-11-11-network-nodes.md).
 *
 * The first click of the mode places the closing section, the next ones the control
 * points above it (tributaries at their mouths, gauges): markers that drag (also by
 * touch), listed in the panel with a name field and „Usuń”. Every point is a node of
 * the network, named by where it lies (N1): `J` at a confluence, `P` elsewhere. A
 * marker shows its node's id from the latest answer; one not answered yet the first
 * free `P<n>` among the ids shown. That id is its handle in the next request, so a
 * problem names a point as the map does. The network comes in two stages:
 *
 * - The preview. A short pause after every change of the points or of the threshold of
 *   the streams on the map, POST /api/delineate-network/preview answers in a fraction
 *   of a second: every marker moves to the stream cell it snapped to („w węźle sieci”
 *   on a point drawn to a confluence within 50 m) and takes its node's id, and the
 *   network is drawn: the elements filled by kind (dopływ, przyrzecze) with their ids,
 *   dashed where the outline follows a whole unit that the characteristics split (the
 *   point inside it is marked), the reaches as lines with theirs and the nodes as dots.
 *   The closing section alone is a network. The panel lists the tree from the closing
 *   section upward with the area of every element, the whole area in the row of the
 *   closing section, and the length of every reach. An error (a point outside the
 *   catchment, off the streams, two points on one node) marks the points it names at
 *   once. Names do not change the preview.
 * - The characteristics. „Oblicz charakterystyki” sends the points to POST
 *   /api/delineate-network: the boundary of the whole catchment (outlined as „Zlewnia
 *   (całość)”), the parameters of every element, the slopes of the reaches, the check
 *   of B5 and the hand-off of the network (js/handoff.js).
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

    // Two kinds of elements (plan 2026-11-11-network-nodes, N7): the kind `headwater` of the
    // API, the river above a node it enters without a reach, shows as a dopływ.
    var KIND_LABELS = { headwater: 'Dopływ', intermediate: 'Przyrzecze' };
    var KIND_INFO = { headwater: 'network-headwater', intermediate: 'network-intermediate' };
    var KIND_TOKENS = { headwater: '--warn', intermediate: '--tool-hydraulik' };
    var KINDS = ['headwater', 'intermediate'];
    var WHOLE = 'Zlewnia (całość)';
    var EXACT_LATER = 'granica dokładna po obliczeniu charakterystyk';
    var OUTDATED_PLACES = 'Charakterystyki są nieaktualne: punkty zmieniły się po ich obliczeniu, poniżej ' +
        'podgląd sieci. Oblicz charakterystyki ponownie, aby przekazać sieć do Hydrologa.';
    var OUTDATED_NAMES = 'Nazwy punktów zmieniły się po obliczeniu charakterystyk. Oblicz je ponownie, ' +
        'aby przekazać sieć do Hydrologa z nowymi nazwami.';

    var state = {
        active: false,      // the mode is on
        outlet: null,       // the closing section: { id, lat, lng, name, marker, snap, row }
        points: [],         // the points above it: the same, in the order of their ids (byId)
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
        bad: {},            // ids (handles) of the points the last error names
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
        var name = p ? cleanName(p.name) : null;
        return name ? id + ' (' + name + ')' : id;
    }

    /**
     * The order of the ids of the points, the panel's and the requests': the `J`s, then
     * the `P`s, each by its number.
     */
    function byId(a, b) {
        var ka = a.id.charAt(0);
        var kb = b.id.charAt(0);
        if (ka !== kb) return ka < kb ? -1 : 1;
        return Number(a.id.slice(1)) - Number(b.id.slice(1));
    }

    /** The id of a point no answer has named yet: the lowest `P<n>` that no marker shows. */
    function nextPointId() {
        var used = {};
        allPoints().forEach(function (p) { used[p.id] = true; });
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

    /** The request of the preview; '' while there is nothing to preview (no closing section). */
    function previewKey() {
        return state.outlet ? JSON.stringify(previewBody()) : '';
    }

    /**
     * The key of the request an answer answers: its points at the places they snapped
     * to, each by the id of its node, in the order of those ids. The markers move there
     * and take those ids (moveToSnapped), and these places snap to themselves, so the
     * answer goes on answering the points until they or the threshold change.
     */
    function answerKey(body, data) {
        var snapped = {};
        data.points.forEach(function (sp) { snapped[sp.id] = sp; });
        function at(bp) {
            var sp = snapped[bp.id];
            return sp ? Object.assign({}, bp, { id: sp.node, latitude: sp.latitude, longitude: sp.longitude }) : bp;
        }
        return JSON.stringify({
            outlet: at(body.outlet),
            points: body.points.map(at).sort(byId),
            threshold_m2: body.threshold_m2,
        });
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
        return !state.loading && !!state.outlet && !compositionError();
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
        return d.data.points.filter(function (sp) { return sp.node === p.id; })[0] || null;
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
        if (p.snap && p.snap.at_node) text += ', w węźle sieci';
        if (insideUnit(p)) text += ', ' + EXACT_LATER;
        return text;
    }

    function markerIcon(p) {
        var classes = ['net-marker'];
        if (p === state.outlet) classes.push('is-outlet');
        if (state.bad[p.id]) classes.push('is-bad');
        if (p.snap && p.snap.at_node) classes.push('at-node');
        if (insideUnit(p)) classes.push('inside-unit');
        return L.divIcon({
            className: classes.join(' '),
            // The ids are the client's own `P<n>` or the network's `J<n>`/`P<n>`, never typed text
            html: '<span>' + p.id + '</span>',
            iconSize: [28, 28],
            iconAnchor: [14, 14],
        });
    }

    /** A new icon only when its marks or its id change: replacing it ends a drag under way. */
    function refreshMarker(p) {
        var icon = markerIcon(p);
        var key = icon.options.className + ' ' + p.id;
        if (key !== p.iconKey) {
            p.iconKey = key;
            p.marker.options.alt = p.id;
            p.marker.setIcon(icon);
        }
        var node = p.marker.getElement();
        if (node) node.title = markerTitle(p);
    }

    function addMarker(p) {
        var icon = markerIcon(p);
        p.iconKey = icon.options.className + ' ' + p.id;
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

    /** The points by the ids they carry now, the handles of a request built from them. */
    function handles() {
        var of = {};
        allPoints().forEach(function (p) { of[p.id] = p; });
        return of;
    }

    /**
     * Every point of an answer moves to the cell it snapped to and takes the id of its
     * node (N1, N8), its handle in the next request: the map, the panel and the hand-off
     * name it alike. The answer names the points by the handles `sent` with its request
     * (handles()), which an answer that came first may have renamed since. A point
     * that snapped to its own place (the request carried where it snapped before) keeps
     * the distance from where it was placed.
     */
    function moveToSnapped(data, sent) {
        data.points.forEach(function (sp) {
            var p = sent[sp.id];
            if (!p || allPoints().indexOf(p) < 0) return;
            var kept = p.snap && sp.latitude === p.lat && sp.longitude === p.lng;
            p.snap = kept ? Object.assign({}, sp, { snap_distance_m: p.snap.snap_distance_m }) : sp;
            p.id = sp.node;
            p.lat = sp.latitude;
            p.lng = sp.longitude;
            p.marker.setLatLng([p.lat, p.lng]);
        });
        state.points.sort(byId);
    }

    // ===== Editing the points =====

    /**
     * A click of the mode: the closing section first, then the points; at most
     * MAX_POINTS points besides the closing section. A new point shows the first free
     * `P<n>` until an answer names its node. Nothing changes while the characteristics
     * are computed.
     */
    function addPoint(lat, lng) {
        if (state.loading) return;
        var p;
        if (!state.outlet) {
            p = state.outlet = { id: nextPointId(), lat: lat, lng: lng, name: '', snap: null };
        } else if (state.points.length >= MAX_POINTS) {
            state.error = 'Sieć ma już ' + MAX_POINTS + ' punktów powyżej przekroju zamykającego, najwięcej, ' +
                'ile przyjmuje Hydrograf. Usuń punkt, aby dodać nowy.';
            renderState();
            Hydrograf.app.showPanel();
            return;
        } else {
            p = { id: nextPointId(), lat: lat, lng: lng, name: '', snap: null };
            state.points.push(p);
            state.points.sort(byId);
        }
        addMarker(p);
        buildPoints();
        changed(p);
    }

    function removePoint(p) {
        if (state.loading) return;
        markers.removeLayer(p.marker);
        if (p === state.outlet) state.outlet = null;
        else state.points = state.points.filter(function (q) { return q !== p; });
        buildPoints();
        changed(p);
    }

    /** „Przesuń do zbiegu”: the point goes to the cell above its confluence, which draws it into the confluence (N3). */
    function moveToConfluence(id, place) {
        var p = findPoint(id);
        if (!p || state.loading) return;
        p.lat = place.latitude;
        p.lng = place.longitude;
        p.marker.setLatLng([p.lat, p.lng]);
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
        var sent = handles();
        var key = JSON.stringify(body);
        var request = ++state.previewRequest;
        var abort = new AbortController();
        previewAbort = abort;
        Hydrograf.api.previewNetwork(body, abort.signal).then(function (data) {
            if (request !== state.previewRequest) return;
            moveToSnapped(data, sent);
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
            markBadPoints(err.problem, sent);
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
        var sent = handles();
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
            moveToSnapped(data, sent);
            state.result = data;
            state.resultKey = answerKey(body, data);
            state.resultPlaces = answerKey(places, data);
        }).catch(function (err) {
            if (request !== state.request) return;
            state.error = err.message;
            markBadPoints(err.problem, sent);
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

    /** Mark the points a problem document names by their handles (`details.point_id`, `details.point_ids`). */
    function markBadPoints(problem, sent) {
        var details = problem && problem.details;
        if (!details) return;
        var ids = [].concat(details.point_ids || [], details.point_id || []);
        ids.forEach(function (id) {
            var p = sent[id];
            if (p && allPoints().indexOf(p) >= 0) state.bad[p.id] = true;
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

    /** The whole catchment: a heavier outline than any element's, in Hydrograf's colour. */
    function boundaryStyle() {
        return { color: token('--tool-hydrograf'), weight: 4, opacity: 1, fill: false };
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
            var kind = s.kind;
            var layer = L.geoJSON(boundary, {
                style: function () { return elementStyle(kind, false, approximate); },
                interactive: false,
            });
            drawn.elements[s.id] = { layer: layer, kind: kind, approximate: approximate };
            drawn.group.addLayer(layer);
            var at = labelPoint(boundary.geometry);
            if (at) addLabel(s.id, kind, at, s.id + ': ' + elementText(s, data));
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
            dot.bindTooltip(el('span', null, j.id + ' · ' + junctionText(j)), { direction: 'top' });
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
                boundaryStyle()), 'area'), WHOLE]);
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

    /**
     * An element as the hand-off names it (backend/core/handoff.py, N7): a headwater by
     * the id of the node it enters, the main river of a confluence (its first inflow)
     * as such: „Dopływ do J4 (ciek główny)”; the name of the node's point is the node's.
     */
    function elementText(s, data) {
        if (s.kind === 'intermediate') return 'Przyrzecze odcinka ' + s.reach;
        var into = data.junctions.filter(function (j) { return j.id === s.to; })[0];
        var main = s.to.charAt(0) === 'J' && !!into && into.inflows[0] === s.id;
        return 'Dopływ do ' + s.to + (main ? ' (ciek główny)' : '');
    }

    function reachText(r) {
        return 'Odcinek ' + r.from + ' → ' + r.to;
    }

    /**
     * What a node is, by where it lies, and the name of its point (N7): „Zbieg: Paszówka”,
     * „Zbieg”, „Punkt: Nysa Mała”, „Przekrój zamykający: Kaczawa”. A point's name is the
     * one in the panel, as the elements' texts give it.
     */
    function junctionText(j) {
        var text = j.kind === 'outlet' ? 'Przekrój zamykający' : j.id.charAt(0) === 'J' ? 'Zbieg' : 'Punkt';
        var p = j.kind === 'confluence' ? null : findPoint(j.id);
        var name = p ? cleanName(p.name) : j.name;
        return name ? text + ': ' + name : text;
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
        if (p.snap.at_node) return 'w węźle sieci';
        return p.snap.snap_distance_m >= 1
            ? 'na cieku, ' + Math.round(p.snap.snap_distance_m) + ' m od kliknięcia'
            : 'na cieku';
    }

    /**
     * The rows of the points, built when points come or go: the closing section first,
     * then the points by their ids. updatePoints() fills what changes, the ids included.
     */
    function buildPoints() {
        var list = els.points;
        list.textContent = '';
        var points = allPoints();
        if (!points.length) {
            list.appendChild(el('li', 'network-empty', 'Brak punktów: kliknij na mapie przekrój zamykający.'));
            return;
        }
        if (!state.outlet) {
            list.appendChild(el('li', 'network-empty', 'Brak przekroju zamykającego: kliknij go na mapie.'));
        }
        points.forEach(function (p) {
            var li = el('li');
            var badge = el('span', 'net-badge');
            li.appendChild(badge);
            var body = el('div', 'net-point-body');
            var input = el('input');
            input.type = 'text';
            input.maxLength = NAME_MAX;
            input.value = p.name;
            input.placeholder = p === state.outlet ? 'Przekrój zamykający: nazwa (opcjonalnie)' : 'Nazwa (opcjonalnie)';
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
            remove.addEventListener('click', function () { removePoint(p); });
            li.appendChild(remove);
            p.row = { li: li, badge: badge, input: input, meta: meta, approx: approx, remove: remove };
            list.appendChild(li);
        });
        updatePoints();
    }

    /**
     * What the rows of the points show of the answers: the id, the error mark, where they
     * snapped, the busy state. An answer that renames the points reorders their rows,
     * keeping the focus of a name being typed.
     */
    function updatePoints() {
        var points = allPoints();
        points.forEach(function (p) {
            if (!p.row) return;
            p.row.badge.textContent = p.id;
            p.row.input.setAttribute('aria-label', 'Nazwa punktu ' + p.id);
            p.row.remove.setAttribute('aria-label', 'Usuń punkt ' + p.id);
            p.row.li.className = 'net-point' + (p === state.outlet ? ' is-outlet' : '') +
                (state.bad[p.id] ? ' is-bad' : '');
            p.row.meta.textContent = pointMeta(p);
            p.row.meta.hidden = !p.row.meta.textContent;
            p.row.approx.hidden = !insideUnit(p);
            p.row.input.disabled = state.loading;
            p.row.remove.disabled = state.loading;
        });
        var rows = Array.prototype.slice.call(els.points.querySelectorAll('li.net-point'));
        var ordered = points.every(function (p, i) { return p.row && rows[i] === p.row.li; });
        if (ordered) return;
        var focused = document.activeElement;
        points.forEach(function (p) { if (p.row) els.points.appendChild(p.row.li); });
        if (focused && focused !== document.activeElement && els.points.contains(focused)) focused.focus();
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
            var outlet = d.data.points[0];
            Hydrograf.app.setContext('Sieć zlewni ' + fixed(d.data.area_km2, 2) + ' km²',
                outlet.node + ' ' + fixed(outlet.latitude, 5) + ' °N, ' + fixed(outlet.longitude, 5) + ' °E');
        } else {
            var n = state.points.length;
            var text = n ? 'Przekrój zamykający i ' + n + ' ' + plural(n, 'punkt', 'punkty', 'punktów') : 'Przekrój zamykający';
            Hydrograf.app.setContext('Sieć zlewni', state.outlet ? text : '');
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

    /**
     * A reach shorter than 200 m or flat (D10a), which Muskingum-Cunge may not route at
     * any usable time step: where it lies and what to do. A point above a confluence the
     * network made gets the button that moves it into the confluence (N3), which then
     * splits there without the reach; a flat reach is a lag in the hand-off. The notice
     * names its upper point by the handle of the request, the point by its node now.
     */
    function reachNotice(data, id, r) {
        var reach = data.reaches.filter(function (x) { return x.id === id; })[0];
        var lower = data.junctions.filter(function (j) { return j.id === r.lower; })[0];
        var upperPoint = r.upper_point
            ? (data.points.filter(function (sp) { return sp.id === r.upper_point; })[0] || { node: r.upper_point }).node
            : null;
        var length = Math.round(r.length_m) + ' m';
        var upper = upperPoint ? 'punkt ' + upperPoint : 'zbieg ' + (reach ? reach.from : '');
        var below = (!lower || lower.kind === 'confluence' ? 'zbiegiem '
            : lower.kind === 'outlet' ? 'przekrojem zamykającym ' : 'punktem ') + r.lower;
        var text = 'Odcinek ' + id + ' ma ' + length + (r.slope_minimum ? ' (spadek minimalny)' : '') +
            ': ' + upper + ' leży ' + length + ' nad ' + below + '. ';
        if (r.lag_min) {
            var lag = 'opóźnienie ' + r.lag_min + ' min';
            text += r.move_to
                ? 'Przesuń go do zbiegu albo zostaw ' + lag + ', które Hydrograf zapisuje w przekazaniu zamiast ' +
                    'Muskingum-Cunge (ten nie trasuje odcinka bez spadku).'
                : 'Hydrograf zapisuje go w przekazaniu jako ' + lag + ' zamiast Muskingum-Cunge, który nie ' +
                    'trasuje odcinka bez spadku.';
        } else {
            text += r.move_to
                ? 'Przesuń go do zbiegu albo w Hydrologu użyj opóźnienia.'
                : 'Jeśli Hydrolog nie przeliczy go metodą Muskingum-Cunge, użyj tam opóźnienia.';
        }
        var box = notice('warn has-action', text);
        if (r.move_to && upperPoint) {
            var move = el('button', 'btn sm', 'Przesuń ' + upperPoint + ' do zbiegu');
            move.type = 'button';
            move.disabled = state.loading;
            move.addEventListener('click', function () { moveToConfluence(upperPoint, r.move_to); });
            box.appendChild(move);
        }
        return box;
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
        els.summary.appendChild(kpi('Cała zlewnia', fixed(data.area_km2, 2), 'km²'));
        els.summary.appendChild(kpi('Zlewnie', String(data.subcatchments.length)));
        els.summary.appendChild(kpi('Odcinki', String(data.reaches.length)));
        els.summary.appendChild(kpi('Węzły', String(data.junctions.length)));

        els.check.hidden = !d.full;
        if (d.full) {
            els.check.textContent = 'Suma elementów = zlewnia przekroju zamykającego: elementy ' +
                fixed(data.area_check.elements_km2, 6) + ' km², zlewnia ' +
                fixed(data.area_check.watershed_km2, 6) + ' km².';
        }

        els.notices.textContent = '';
        data.notices.forEach(function (n) {
            var ids = n.ids.join(', ');
            if (n.code === 'over_scs_cn_limit') {
                els.notices.appendChild(notice('warn', 'Zlewnie powyżej 250 km², granicy stosowalności ' +
                    'metody SCS-CN: ' + ids + '.'));
            } else if (n.code === 'reach_short_or_flat') {
                els.notices.appendChild(reachNotice(data, n.ids[0], n.reach));
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

    // ===== The tree, from the closing section upward =====

    /**
     * The rows of the tree, from the closing section upward. The inflows of a node form
     * its branches: a reach with its przyrzecze and the node above it, a dopływ, or a
     * node entered without a reach. Each branch reads the same way, przyrzecze, reach,
     * then the node above it with everything that node receives, so one branch is
     * listed whole before the next. At a node the branches joining from the side come
     * first, one step in, then the trunk (the branch of the node's first inflow, the
     * main river) goes on at the same depth. A node entered without a reach carries the
     * node it enters (`into`).
     */
    function treeRows(data) {
        var items = {};
        data.subcatchments.forEach(function (s) { items[s.id] = { type: 'element', item: s }; });
        data.reaches.forEach(function (r) { items[r.id] = { type: 'reach', item: r }; });
        data.junctions.forEach(function (j) { items[j.id] = { type: 'junction', item: j }; });
        // The przyrzecze of each reach, which enters the reach's lower node beside it
        var przyrzecze = {};
        data.subcatchments.forEach(function (s) {
            if (s.kind === 'intermediate' && s.reach) przyrzecze[s.reach] = s.id;
        });
        var rows = [];
        function row(id, depth, into) {
            rows.push({ id: id, type: items[id].type, item: items[id].item, depth: depth, into: into || null });
        }
        function branch(id, depth, node) {
            var it = items[id];
            if (!it) return;
            if (it.type === 'reach') {
                if (przyrzecze[id]) row(przyrzecze[id], depth);
                row(id, depth);
                walk(it.item.from, depth, null);
            } else if (it.type === 'junction') {
                walk(id, depth, node);
            } else {
                row(id, depth);
            }
        }
        function walk(id, depth, into) {
            var it = items[id];
            if (!it) return;
            if (it.type !== 'junction') {
                branch(id, depth, null);
                return;
            }
            row(id, depth, into);
            // A przyrzecze goes with its reach, not as a branch of its own
            var inflows = it.item.inflows.filter(function (inflow) {
                var s = items[inflow];
                return !(s && s.type === 'element' && s.item.kind === 'intermediate' && s.item.reach && items[s.item.reach]);
            });
            if (!inflows.length) return;
            var trunk = inflows.indexOf(it.item.inflows[0]) >= 0 ? it.item.inflows[0] : trunkOf(it.item.inflows[0], inflows);
            inflows.forEach(function (inflow) {
                if (inflow !== trunk) branch(inflow, depth + 1, id);
            });
            branch(trunk, depth, id);
        }
        // A node's first inflow is a przyrzecze only beside its reach: the reach is the trunk
        function trunkOf(first, inflows) {
            var s = items[first];
            return s && s.item.reach && inflows.indexOf(s.item.reach) >= 0 ? s.item.reach : inflows[0];
        }
        var outlet = data.junctions.filter(function (j) { return j.kind === 'outlet'; })[0];
        if (outlet) walk(outlet.id, 0, null);
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
                // A node entered without a reach: „J4 → J1”
                var into = row.into ? ' → ' + row.into + ' ·' : '';
                th.appendChild(document.createTextNode(into + ' ' + junctionText(row.item)));
                tr.appendChild(th);
                // The closing section's row carries the whole catchment
                if (row.item.kind === 'outlet') {
                    valueCells(tr, fixed(d.data.area_km2, 2), 'km²');
                    tr.title = WHOLE + ': ' + fixed(d.data.area_km2, 2) + ' km²';
                } else {
                    valueCells(tr, '', '');
                }
                valueCells(tr, '', '');
            } else {
                var btn = el('button', 'net-row-btn');
                btn.type = 'button';
                btn.appendChild(id);
                var text = row.type === 'element' ? elementText(row.item, d.data) : reachText(row.item);
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
            els.selectionTitle.textContent = element.id + ' · ' + elementText(element, d.data);
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
