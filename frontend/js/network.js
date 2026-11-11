/**
 * Hydrograf mode „Sieć zlewni” (ADR-080, plan docs/plans/2026-11-10-network-delineation.md).
 *
 * The first click of the mode places the closing section A, the next ones the points
 * P1, P2, … above it (tributaries at their mouths, gauges): numbered markers that drag
 * (also by touch), listed in the panel with a name field and „Usuń”. „Wyznacz sieć”
 * sends them, with the threshold of the streams on the map, to POST
 * /api/delineate-network. The answer moves every marker to the stream cell it snapped
 * to („przy ujściu” on a point moved to the junction below it) and draws the network:
 * the elements filled by kind (zlewnia górna, dopływ, przyrzecze) with their ids, the
 * reaches as lines with theirs, the junctions as dots and A's boundary. The panel lists
 * the tree from A upward, the check of B5 and the notices; a row of the tree or the
 * label of an element or a reach on the map shows its parameters: an element's in the
 * sections of „Wybierz zlewnię” (js/app.js), a reach's in a table of its own. The
 * hand-off of the network goes through js/handoff.js. A change of the points marks the
 * result outdated, an error marks the points it names, leaving the mode takes the
 * network off the map and „Wyczyść” removes the points and the result.
 *
 * Clicks on the map always place points; elements and reaches are selected by their
 * labels or in the list, so a gauge can be placed on a drawn reach.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    // Limits of POST /api/delineate-network (models/schemas.py)
    var MAX_POINTS = 30;
    var MIN_THRESHOLD_M2 = 10000;
    var DEFAULT_THRESHOLD_M2 = 100000;
    var NAME_MAX = 100;

    var KIND_LABELS = { headwater: 'Zlewnia górna', tributary: 'Dopływ', intermediate: 'Przyrzecze' };
    var KIND_INFO = {
        headwater: 'network-headwater', tributary: 'network-tributary', intermediate: 'network-intermediate',
    };
    var KIND_TOKENS = { headwater: '--accent-green', tributary: '--warn', intermediate: '--tool-hydraulik' };
    var KINDS = ['headwater', 'tributary', 'intermediate'];
    var JUNCTION_LABELS = { confluence: 'Zbieg cieków', point: 'Punkt', outlet: 'Przekrój zamykający' };

    var state = {
        active: false,      // the mode is on
        outlet: null,       // A: { id, lat, lng, name, marker, snap }
        points: [],         // P1, P2, …: the same, in the order they were placed
        result: null,       // the answer the panel shows
        resultKey: '',      // the request it answers, with the snapped places
        request: 0,         // number of the latest request; answers to older ones are dropped
        loading: false,
        bad: {},            // ids of the points the last error names
        selected: null,     // id of the element or reach whose parameters are shown
    };

    var markers = null;     // L.LayerGroup of the point markers
    var drawn = null;       // the layers of the result: { group, labels, elements, reaches }
    var legend = null;      // L.Control of the map legend
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

    // ===== The request and whether the result still answers it =====

    function apiPoint(p) {
        var point = { id: p.id, latitude: p.lat, longitude: p.lng };
        var name = cleanName(p.name);
        if (name) point.name = name;
        return point;
    }

    function requestBody() {
        return {
            outlet: apiPoint(state.outlet),
            points: state.points.map(apiPoint),
            threshold_m2: threshold(),
        };
    }

    function requestKey() {
        return state.outlet ? JSON.stringify(requestBody()) : '';
    }

    function isOutdated() {
        return !!state.result && requestKey() !== state.resultKey;
    }

    function canRun() {
        return !state.loading && !!state.outlet && state.points.length > 0;
    }

    // ===== Point markers =====

    function markerTitle(p) {
        var role = p === state.outlet ? 'przekrój zamykający' : 'punkt sieci';
        var text = pointLabel(p.id) + ' – ' + role;
        if (p.snap && p.snap.at_mouth) text += ', przy ujściu dopływu';
        return text;
    }

    function markerIcon(p) {
        var classes = ['net-marker'];
        if (p === state.outlet) classes.push('is-outlet');
        if (state.bad[p.id]) classes.push('is-bad');
        if (p.snap && p.snap.at_mouth) classes.push('at-mouth');
        return L.divIcon({
            className: classes.join(' '),
            html: '<span>' + p.id + '</span>',
            iconSize: [28, 28],
            iconAnchor: [14, 14],
        });
    }

    function refreshMarker(p) {
        p.marker.setIcon(markerIcon(p));
        var icon = p.marker.getElement();
        if (icon) icon.title = markerTitle(p);
    }

    function addMarker(p) {
        p.marker = L.marker([p.lat, p.lng], {
            icon: markerIcon(p),
            draggable: !state.loading,
            autoPan: true,
            title: markerTitle(p),
            alt: p.id,
            riseOnHover: true,
        });
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

    // ===== Editing the points =====

    /**
     * A click of the mode: A first, then P1, P2, …; at most MAX_POINTS points
     * besides A. Nothing changes while a network is being delineated.
     */
    function addPoint(lat, lng) {
        if (state.loading) return;
        var p;
        if (!state.outlet) {
            p = state.outlet = { id: 'A', lat: lat, lng: lng, name: '', snap: null };
        } else if (state.points.length >= MAX_POINTS) {
            Hydrograf.app.setNetworkStatus({
                error: 'Sieć ma już ' + MAX_POINTS + ' punktów powyżej A, najwięcej, ile przyjmuje Hydrograf. ' +
                    'Usuń punkt, aby dodać nowy.',
            });
            return;
        } else {
            p = { id: nextPointId(), lat: lat, lng: lng, name: '', snap: null };
            state.points.push(p);
            state.points.sort(function (a, b) { return Number(a.id.slice(1)) - Number(b.id.slice(1)); });
        }
        addMarker(p);
        changed(p);
    }

    function removePoint(id) {
        if (state.loading) return;
        var p = findPoint(id);
        if (!p) return;
        markers.removeLayer(p.marker);
        if (p === state.outlet) state.outlet = null;
        else state.points = state.points.filter(function (q) { return q !== p; });
        changed(p);
    }

    /**
     * The points changed: the error that named the old ones goes, the moved point is
     * no longer where it snapped, the result is outdated until delineated again.
     */
    function changed(p) {
        if (p) {
            delete state.bad[p.id];
            p.snap = null;
            if (p.marker) refreshMarker(p);
        }
        Hydrograf.app.setNetworkStatus({ error: '' });
        renderPoints();
        renderState();
    }

    // ===== Requests =====

    function run() {
        if (!canRun()) return;
        var body = requestBody();
        var request = ++state.request;
        clearResult();
        state.bad = {};
        state.loading = true;
        allPoints().forEach(refreshMarker);
        setDraggable(false);
        Hydrograf.app.setNetworkStatus({ loading: true, error: '' });
        renderPoints();
        renderState();

        Hydrograf.api.delineateNetwork(body).then(function (data) {
            if (request !== state.request) return;
            showResult(data, body);
        }).catch(function (err) {
            if (request !== state.request) return;
            markBadPoints(err.problem);
            Hydrograf.app.setNetworkStatus({ error: err.message });
        }).then(function () {
            if (request !== state.request) return;
            state.loading = false;
            setDraggable(true);
            Hydrograf.app.setNetworkStatus({ loading: false });
            renderPoints();
            renderState();
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
        allPoints().forEach(refreshMarker);
    }

    /**
     * The answer: every point moves to the cell it snapped to, the network is drawn
     * and listed. The result answers its request with the snapped places, which snap
     * to themselves, so it is outdated only when the points or the threshold change.
     */
    function showResult(data, body) {
        var snapped = {};
        data.points.forEach(function (sp) { snapped[sp.id] = sp; });
        function snappedPoint(bp) {
            var sp = snapped[bp.id];
            return sp ? Object.assign({}, bp, { latitude: sp.latitude, longitude: sp.longitude }) : bp;
        }
        allPoints().forEach(function (p) {
            var sp = snapped[p.id];
            if (!sp) return;
            p.lat = sp.latitude;
            p.lng = sp.longitude;
            p.snap = sp;
            p.marker.setLatLng([p.lat, p.lng]);
            refreshMarker(p);
        });
        state.result = data;
        state.resultKey = JSON.stringify({
            outlet: snappedPoint(body.outlet),
            points: body.points.map(snappedPoint),
            threshold_m2: body.threshold_m2,
        });
        state.selected = null;
        drawResult(data);
        if (state.active && drawn) map().fitBounds(drawn.boundary.getBounds(), { padding: [20, 20] });
        renderResult();
    }

    /** Drop the result: its layers, its rows, the element whose parameters show, the hand-off. */
    function clearResult() {
        removeDrawn();
        state.result = null;
        state.resultKey = '';
        state.selected = null;
        Hydrograf.app.showElementParameters(null);
        renderResult();
    }

    /** „Wyczyść” and the bin of the panel: no points, no result, nothing pending. */
    function clear() {
        state.request += 1;
        state.loading = false;
        clearResult();
        allPoints().forEach(function (p) { markers.removeLayer(p.marker); });
        state.outlet = null;
        state.points = [];
        state.bad = {};
        Hydrograf.app.setNetworkStatus({ loading: false, error: '' });
        renderPoints();
        renderState();
    }

    // ===== Map layers of the result =====

    function kindColor(kind) { return token(KIND_TOKENS[kind]); }

    function boundaryStyle() {
        return { color: token('--tool-hydrograf'), weight: 2.5, opacity: 1, fill: false };
    }

    function elementStyle(kind, selected) {
        var color = kindColor(kind);
        return {
            color: color,
            weight: selected ? 3 : 1.2,
            opacity: 0.95,
            fillColor: color,
            fillOpacity: selected ? 0.38 : 0.2,
        };
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
     */
    function labelPoint(geometry) {
        var polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
        var best = null;
        polygons.forEach(function (polygon) {
            var ring = polygon[0];
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

    function drawResult(data) {
        removeDrawn();
        drawn = {
            group: L.featureGroup(),
            labels: L.layerGroup(),
            boundary: L.geoJSON(data.boundary_geojson, { style: boundaryStyle, interactive: false }),
            elements: {},
            reaches: {},
            junctions: [],
            labelOf: {},
        };
        data.subcatchments.forEach(function (s) {
            var layer = L.geoJSON(s.watershed.boundary_geojson, {
                style: function () { return elementStyle(s.kind, false); },
                interactive: false,
            });
            drawn.elements[s.id] = { layer: layer, kind: s.kind };
            drawn.group.addLayer(layer);
            addLabel(s.id, s.kind, labelPoint(s.watershed.boundary_geojson.geometry),
                s.id + ': ' + elementText(s));
        });
        drawn.group.addLayer(drawn.boundary);
        data.reaches.forEach(function (r) {
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

    function showDrawn() {
        if (!drawn || !state.active) return;
        drawn.group.addTo(map());
        drawn.labels.addTo(map());
        drawn.boundary.bringToFront();
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

    /** Styles from the tokens of the theme; the selection and an outdated result show. */
    function restyle() {
        if (!drawn) return;
        var faded = isOutdated();
        drawn.boundary.setStyle(boundaryStyle());
        Object.keys(drawn.elements).forEach(function (id) {
            var e = drawn.elements[id];
            var style = elementStyle(e.kind, state.selected === id);
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
        var data = state.result;
        var rows = [[Hydrograf.map.pathSwatch(Object.assign({ fillColor: 'none', fillOpacity: 0 },
            boundaryStyle()), 'area'), 'Granica zlewni A']];
        KINDS.forEach(function (kind) {
            if (data.subcatchments.some(function (s) { return s.kind === kind; })) {
                rows.push([Hydrograf.map.pathSwatch(elementStyle(kind, false), 'area'), KIND_LABELS[kind]]);
            }
        });
        if (data.reaches.length) rows.push([Hydrograf.map.pathSwatch(reachStyle(false)), 'Odcinek']);
        rows.push([Hydrograf.map.pathSwatch(junctionStyle(), 'point'), 'Węzeł']);
        return rows;
    }

    function updateLegend() {
        var shown = !!(state.active && drawn && state.result);
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
        legend.getContainer().innerHTML = '<div class="layer-legend-title">Sieć zlewni</div>' +
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

    function findElement(id) {
        if (!state.result) return null;
        return state.result.subcatchments.filter(function (s) { return s.id === id; })[0] || null;
    }

    function findReach(id) {
        if (!state.result) return null;
        return state.result.reaches.filter(function (r) { return r.id === id; })[0] || null;
    }

    /** A label on the map: select its element or reach, or drop it when selected; the panel follows. */
    function toggleSelect(id) {
        select(state.selected === id ? null : id, { reveal: 'start' });
    }

    /**
     * Show the parameters of an element (in the sections of the panel) or of a reach
     * (in the selection's table); null shows neither. `how.zoom` moves the map to it
     * (a row of the list), `how.reveal` scrolls the panel to its parameters.
     */
    function select(id, how) {
        var opts = how || {};
        var element = id ? findElement(id) : null;
        var reach = id && !element ? findReach(id) : null;
        state.selected = element || reach ? id : null;
        Hydrograf.app.showElementParameters(element && state.active ? element.watershed : null);
        if (drawn) {
            drawn.selectedLayer = element ? drawn.elements[id].layer : reach ? drawn.reaches[id] : null;
            restyle();
            if (opts.zoom && drawn.selectedLayer && state.active) {
                map().fitBounds(drawn.selectedLayer.getBounds(), { padding: [40, 40], maxZoom: 15 });
            }
        }
        renderSelection();
        renderTreeSelection();
        if (opts.reveal && state.selected && state.active) {
            els.selection.scrollIntoView({ block: opts.reveal, behavior: 'smooth' });
        }
    }

    // ===== Panel =====

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

    function renderPoints() {
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
            var li = el('li', 'net-point' + (p === state.outlet ? ' is-outlet' : '') +
                (state.bad[p.id] ? ' is-bad' : ''));
            li.appendChild(el('span', 'net-badge', p.id));
            var body = el('div', 'net-point-body');
            var input = el('input');
            input.type = 'text';
            input.maxLength = NAME_MAX;
            input.value = p.name;
            input.placeholder = p === state.outlet ? 'Przekrój zamykający: nazwa (opcjonalnie)' : 'Nazwa (opcjonalnie)';
            input.setAttribute('aria-label', 'Nazwa punktu ' + p.id);
            input.disabled = state.loading;
            input.addEventListener('input', function () {
                p.name = input.value;
                refreshMarker(p);
                renderState();
            });
            body.appendChild(input);
            var meta = pointMeta(p);
            if (meta) body.appendChild(el('span', 'net-point-meta', meta));
            li.appendChild(body);
            var remove = el('button', 'btn sm ghost', 'Usuń');
            remove.type = 'button';
            remove.disabled = state.loading;
            remove.setAttribute('aria-label', 'Usuń punkt ' + p.id);
            remove.addEventListener('click', function () { removePoint(p.id); });
            li.appendChild(remove);
            list.appendChild(li);
        });
    }

    /** The parts that follow the points and the result: buttons, outdated mark, hand-off, context. */
    function renderState() {
        var outdated = isOutdated();
        els.run.disabled = !canRun();
        els.clear.disabled = !allPoints().length && !state.result;
        els.outdated.classList.toggle('d-none', !outdated);
        els.result.classList.toggle('is-outdated', outdated);
        Hydrograf.app.setNetworkStatus({ clearable: !els.clear.disabled });
        if (Hydrograf.handoff) {
            Hydrograf.handoff.showNetwork(state.result ? state.result.handoff : null, outdated);
        }
        restyle();
        renderContext();
    }

    function renderContext() {
        if (!state.active) return;
        var data = state.result;
        if (data) {
            var a = data.points[0];
            Hydrograf.app.setContext('Sieć zlewni ' + fixed(data.area_km2, 2) + ' km²',
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

    function renderResult() {
        var data = state.result;
        els.result.classList.toggle('d-none', !data);
        renderSelection();
        if (!data) return;

        els.summary.textContent = '';
        els.summary.appendChild(kpi('Zlewnia A', fixed(data.area_km2, 2), 'km²'));
        els.summary.appendChild(kpi('Zlewnie', String(data.subcatchments.length)));
        els.summary.appendChild(kpi('Odcinki', String(data.reaches.length)));
        els.summary.appendChild(kpi('Węzły', String(data.junctions.length)));

        els.check.textContent = 'Suma elementów = zlewnia A: elementy ' +
            fixed(data.area_check.elements_km2, 6) + ' km², zlewnia A ' +
            fixed(data.area_check.watershed_km2, 6) + ' km².';

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

        renderTree(data);
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

    function renderTree(data) {
        var tbody = els.tree;
        tbody.textContent = '';
        treeRows(data).forEach(function (row) {
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
                    var m = row.item.watershed.morphometry || {};
                    valueCells(tr, fixed(m.area_km2, 2), 'km²');
                    valueCells(tr, fixed(m.cn, 1), 'CN');
                } else {
                    valueCells(tr, fixed(row.item.length_km, 2), 'km');
                    valueCells(tr, slopeText(row.item), row.item.slope_method === 'minimum' ? '‰ min.' : '‰');
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

    function renderSelection() {
        var element = state.selected ? findElement(state.selected) : null;
        var reach = state.selected && !element ? findReach(state.selected) : null;
        els.selection.hidden = !(element || reach);
        els.selectionKind.textContent = '';
        els.reach.textContent = '';
        if (element) {
            var m = element.watershed.morphometry || {};
            els.selectionTitle.textContent = element.id + ' · ' + elementText(element);
            var kind = el('span', 'net-kind ' + element.kind, KIND_LABELS[element.kind]);
            els.selectionKind.appendChild(kind);
            Hydrograf.info.attach(kind, KIND_INFO[element.kind]);
            els.selectionKind.appendChild(document.createTextNode(
                ' · ' + fixed(m.area_km2, 2) + ' km² · CN ' + fixed(m.cn, 1) + ' · do ' + element.to +
                '. Parametry w sekcjach poniżej, jak dla wyznaczonej zlewni.'));
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
        renderState();
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
            outdated: document.getElementById('network-outdated'),
            result: document.getElementById('network-result'),
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
            renderState();
        });
        Hydrograf.map.onThemeChange(function () {
            restyle();
            updateLegend();
        });
        renderSnap();
        renderPoints();
        renderResult();
        renderState();
    }

    window.Hydrograf.network = {
        init: init,
        addPoint: addPoint,
        clear: clear,
        enter: enter,
        leave: leave,
    };
})();
