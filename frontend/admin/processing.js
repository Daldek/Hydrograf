/**
 * Hydrograf admin panel: the section „Przetwarzanie NMT”, the bootstrap of the data of
 * an area (`scripts.bootstrap` as a process of the API).
 *
 * The area is a rectangle in WGS84 degrees, typed or drawn on a map, or the boundary
 * uploaded in „Granice i kanalizacja”; the storm sewer is included as that section sets
 * it. Routes: GET bootstrap/status, POST bootstrap/start and bootstrap/cancel, GET
 * bootstrap/stream (the log as server-sent events) and GET sewer/status.
 */
(function () {
    'use strict';

    var admin = window.Hydrograf.admin;
    var status = admin.lines('processing-error', 'processing-note');
    var form = document.getElementById('processing-form');
    var state = document.getElementById('processing-state');
    var elapsed = document.getElementById('processing-elapsed');
    var refresh = document.getElementById('processing-refresh');
    var start = document.getElementById('processing-start');
    var cancel = document.getElementById('processing-cancel');
    var bboxPart = document.getElementById('processing-bbox');
    var bboxError = document.getElementById('bbox-error');
    var boundaryLine = document.getElementById('processing-boundary');
    var resolution = document.getElementById('processing-resolution');
    var sewerLine = document.getElementById('processing-sewer');
    var log = document.getElementById('processing-log');
    var fields = {
        north: document.getElementById('bbox-north'),
        south: document.getElementById('bbox-south'),
        east: document.getElementById('bbox-east'),
        west: document.getElementById('bbox-west'),
    };
    var defaults = {};
    for (var side in fields) defaults[side] = fields[side].value;

    // The states of GET bootstrap/status: the badge's text and colour
    var STATES = {
        idle: ['Bezczynne', 'nogat-admin-neutral'],
        running: ['Trwa', 'nogat-admin-info'],
        completed: ['Zakończone', 'nogat-admin-ok'],
        failed: ['Błąd lub przerwane', 'nogat-admin-failed'],
    };

    var sewer = null; // config of GET sewer/status
    var stream = null; // AbortController of the open log stream
    var timer = null;
    var ticket = 0;

    // ---------------------------------------------------------------- state

    function show(data) {
        var known = STATES[data.status] || [String(data.status), 'nogat-admin-neutral'];
        state.textContent = known[0];
        state.className = 'nogat-admin-badge ' + known[1];
        var running = data.status === 'running';
        start.disabled = running;
        cancel.disabled = !running;
        stopTimer();
        if (data.started_at) {
            var tick = function () {
                elapsed.textContent = admin.duration(Date.now() / 1000 - data.started_at);
            };
            tick();
            if (running) timer = setInterval(tick, 1000);
        } else {
            elapsed.textContent = '';
        }
        if (running && !stream) follow();
    }

    function stopTimer() {
        clearInterval(timer);
        timer = null;
    }

    function area() {
        return form.querySelector('input[name="processing-area"]:checked').value;
    }

    function showArea() {
        var boundary = admin.boundary;
        var byBoundary = area() === 'boundary';
        bboxPart.hidden = byBoundary;
        boundaryLine.hidden = !byBoundary;
        boundaryLine.replaceChildren();
        if (boundary) {
            boundaryLine.append(
                'Granica z pliku ' + boundary.name + ': ' + admin.number(boundary.area_km2) +
                ' km², ' + admin.number(boundary.n_features) + ' obiekt(y), ' + boundary.crs + '.',
            );
        } else {
            var link = admin.el('a', null, 'Granice i kanalizacja');
            link.href = '#boundaries';
            boundaryLine.append('Najpierw wgraj plik granicy w sekcji „', link, '”.');
        }
    }

    function showSewer() {
        sewerLine.replaceChildren();
        if (!sewer) return;
        var link = admin.el('a', null, 'Granice i kanalizacja');
        link.href = '#boundaries';
        var included = sewer.enabled && sewer.source_path;
        sewerLine.append(
            included
                ? 'Kanalizacja deszczowa: uwzględniona (plik ' + sewer.source_path + '; '
                : 'Kanalizacja deszczowa: nieuwzględniona (',
            link,
            ').',
        );
    }

    async function load() {
        var mine = ++ticket;
        status.note('Wczytywanie…');
        refresh.disabled = true;
        showArea();
        try {
            var data = await admin.request('bootstrap/status');
            var sewerStatus = await admin.request('sewer/status');
            if (mine !== ticket) return;
            sewer = sewerStatus.config || null;
            status.clear();
            show(data);
            showSewer();
        } catch (error) {
            if (mine !== ticket) return;
            status.note('');
            status.error(error);
        } finally {
            if (mine === ticket) refresh.disabled = false;
        }
    }

    // ---------------------------------------------------------------- the area

    /** The rectangle "W,S,E,N" of the four fields, or null with the problem shown. */
    function bbox() {
        var values = {};
        var problem = '';
        var wrong = [];
        for (var side in fields) {
            fields[side].removeAttribute('aria-invalid');
            values[side] = parseFloat(fields[side].value);
            if (isNaN(values[side])) wrong.push(fields[side]);
        }
        if (wrong.length) {
            problem = 'Wypełnij wszystkie cztery współrzędne.';
        } else if (values.west >= values.east) {
            problem = 'W (najmniejsza długość) musi być mniejsze niż E (największa długość).';
            wrong = [fields.west, fields.east];
        } else if (values.south >= values.north) {
            problem = 'S (najmniejsza szerokość) musi być mniejsze niż N (największa szerokość).';
            wrong = [fields.south, fields.north];
        }
        bboxError.textContent = problem;
        bboxError.hidden = !problem;
        for (var field of wrong) field.setAttribute('aria-invalid', 'true');
        if (problem) return null;
        return [values.west, values.south, values.east, values.north].join(',');
    }

    // ---------------------------------------------------------------- the run

    async function run(event) {
        event.preventDefault();
        status.error(null);
        var params = { resolution: resolution.value };
        if (area() === 'boundary') {
            if (!admin.boundary) {
                showArea();
                status.error(new Error('Najpierw wgraj plik granicy w sekcji „Granice i kanalizacja”.'));
                return;
            }
            params.boundary_file = admin.boundary.filename;
        } else {
            var rectangle = bbox();
            if (!rectangle) return;
            params.bbox = rectangle;
        }
        if (sewer && sewer.enabled && sewer.source_path) {
            params.sewer_enabled = true;
            params.sewer_source = sewer.source_path;
        }
        start.disabled = true;
        try {
            var result = await admin.request('bootstrap/start', { method: 'POST', json: params });
            log.textContent = '';
            status.note('Uruchomiono przetwarzanie (PID ' + result.pid + ').');
            show({ status: 'running', started_at: Date.now() / 1000 });
        } catch (error) {
            start.disabled = false;
            status.error(error);
        }
    }

    async function stop() {
        var confirmed = await admin.confirm({
            title: 'Przerwać przetwarzanie NMT?',
            text: 'Przerwany przebieg trzeba uruchomić od nowa.',
            confirm: 'Przerwij',
            opener: cancel,
        });
        if (!confirmed) return;
        try {
            await admin.request('bootstrap/cancel', { method: 'POST' });
            status.note('Przerwano przetwarzanie.');
        } catch (error) {
            status.error(error);
        }
        load();
    }

    /** Read the log as it is written; the stream sends every line from the first. */
    async function follow() {
        var controller = new AbortController();
        stream = controller;
        log.textContent = '';
        var done = '';
        try {
            var response = await admin.send('bootstrap/stream', { signal: controller.signal });
            var reader = response.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';
            for (;;) {
                var chunk = await reader.read();
                if (chunk.done) break;
                buffer += decoder.decode(chunk.value, { stream: true });
                var events = buffer.split('\n\n');
                buffer = events.pop();
                for (var text of events) {
                    if (text.indexOf('event: done') !== -1) {
                        done = text.slice(text.lastIndexOf('data: ') + 6).trim();
                    } else if (text.indexOf('data: ') === 0) {
                        append(text.slice(6));
                    }
                }
                if (done) break;
            }
            await reader.cancel();
        } catch (error) {
            if (error && error.name === 'AbortError') return;
            status.error(error);
        } finally {
            if (stream === controller) stream = null;
        }
        if (stream !== null || controller.signal.aborted) return;
        var ending = STATES[done] ? STATES[done][0] : 'połączenie przerwane';
        append('[Koniec przebiegu: ' + ending.toLowerCase() + ']');
        load();
    }

    function append(line) {
        var atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
        log.append((log.textContent ? '\n' : '') + line);
        if (atEnd) log.scrollTop = log.scrollHeight;
    }

    function clear() {
        ticket += 1;
        if (stream) stream.abort();
        stream = null;
        stopTimer();
        sewer = null;
        status.clear();
        state.textContent = STATES.idle[0];
        state.className = 'nogat-admin-badge ' + STATES.idle[1];
        elapsed.textContent = '';
        log.textContent = '';
        sewerLine.replaceChildren();
        bboxError.hidden = true;
        form.reset();
        for (var side in fields) {
            fields[side].value = defaults[side];
            fields[side].removeAttribute('aria-invalid');
        }
        start.disabled = false;
        cancel.disabled = true;
        refresh.disabled = false;
        showArea();
        picker.reset();
    }

    // ---------------------------------------------------------------- the map

    /**
     * The rectangle drawn on a map in a dialog, over the first raster base map of the kit's
     * catalogue that the deployment allows (GET /api/v1/basemaps: GUGiK's grey
     * OpenStreetMap by default, none without one), drawn by the kit's maplibreBasemap with
     * its credit (Nogat DEV-15.13, DEV-15.15; ADR-089). The map is MapLibre GL JS 6.14.0, as
     * the page's (Nogat's plan 2026-11-24-hydrograf-maplibre, M10): a mouse drag draws the
     * box, the map is never mouse-panned; without WebGL 2 the dialog says so in its place
     * and the four fields are filled by hand (M13).
     */
    var picker = (function () {
        var LIBRARY = '../vendor/maplibre-gl-6.14.0/maplibre-gl.mjs';
        var NO_WEBGL = 'Mapa wymaga przeglądarki z WebGL 2. Wpisz granice obszaru w pola formularza.';
        var NO_MAP = 'Nie udało się wczytać mapy. Wpisz granice obszaru w pola formularza.';
        var EMPTY = { type: 'FeatureCollection', features: [] };
        var dialog = document.getElementById('bbox-dialog');
        var opener = document.getElementById('bbox-map-open');
        var confirmButton = document.getElementById('bbox-confirm');
        var area = document.getElementById('bbox-map');
        var notice = document.getElementById('bbox-map-notice');
        var loading = null;  // a Promise of the map, or of null without one
        var map = null;
        var box = null;      // [west, south, east, north] drawn
        var anchor = null;   // the place where the drag began

        function round6(value) {
            return Math.round(value * 1e6) / 1e6;
        }

        function token(name) {
            return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        }

        /** Draw the box [west, south, east, north], or none. */
        function draw(drawn) {
            box = drawn;
            if (!map) return;
            map.getSource('box').setData(drawn ? {
                type: 'Feature',
                properties: {},
                geometry: {
                    type: 'Polygon',
                    coordinates: [[[drawn[0], drawn[1]], [drawn[2], drawn[1]], [drawn[2], drawn[3]],
                        [drawn[0], drawn[3]], [drawn[0], drawn[1]]]],
                },
            } : EMPTY);
        }

        function boxOf(a, b) {
            return [Math.min(a.lng, b.lng), Math.min(a.lat, b.lat), Math.max(a.lng, b.lng), Math.max(a.lat, b.lat)];
        }

        /**
         * Draw the base map through the kit; one whose provider does not answer leaves the
         * map and is said under it, the rectangle still drawn without it.
         */
        async function showBasemap() {
            var entries;
            try {
                var response = await fetch('/api/v1/basemaps');
                entries = response.ok ? await response.json() : [];
            } catch (error) {
                entries = [];
            }
            var entry = entries.find(function (candidate) {
                return candidate.kind === 'raster' && Array.isArray(candidate.blocks);
            });
            if (!entry) return;
            var kit = await import('../nogat/nogat-basemaps.js?v=f9df0ea391');
            function onFailure() {
                notice.textContent = kit.BASEMAP_TEXTS.failed + ': ' + entry.label +
                    '. Prostokąt można narysować także bez podkładu.';
                notice.hidden = false;
            }
            try {
                await kit.maplibreBasemap(entry, { map: map, before: 'box-fill', onFailure: onFailure });
            } catch (error) {
                // onFailure has said it
            }
        }

        /** The dialog says why there is no map; the confirmation stays disabled. */
        function unavailable(message, error) {
            console.warn('The area map is not drawn:', error && error.message ? error.message : error);
            var note = document.createElement('p');
            note.className = 'admin-map-unavailable';
            note.setAttribute('role', 'status');
            note.textContent = message;
            area.replaceChildren(note);
            return null;
        }

        /** A map without rotation, pitch or mouse panning, its box over the base map. */
        async function create() {
            var maplibregl = await import(LIBRARY);
            var accent = token('--accent');
            var created;
            try {
                created = new maplibregl.Map({
                    container: area,
                    style: {
                        version: 8,
                        sources: { box: { type: 'geojson', data: EMPTY } },
                        layers: [
                            { id: 'background', type: 'background', paint: { 'background-color': token('--surface-2') } },
                            { id: 'box-fill', type: 'fill', source: 'box', paint: { 'fill-color': accent, 'fill-opacity': 0.15 } },
                            { id: 'box-line', type: 'line', source: 'box', paint: { 'line-color': accent, 'line-width': 2 } },
                        ],
                    },
                    center: [19.0, 52.0],
                    zoom: 5,
                    dragPan: false,
                    dragRotate: false,
                    pitchWithRotate: false,
                    touchPitch: false,
                    maxPitch: 0,
                    boxZoom: false,
                    attributionControl: { compact: false },
                    locale: {
                        'Map.Title': 'Mapa',
                        'NavigationControl.ZoomIn': 'Przybliż',
                        'NavigationControl.ZoomOut': 'Oddal',
                    },
                });
            } catch (error) {
                return unavailable(error instanceof maplibregl.GPUInitializationError ? NO_WEBGL : NO_MAP, error);
            }
            created.touchZoomRotate.disableRotation();
            created.keyboard.disableRotation();
            // A tile that does not load leaves the map as it is (the kit reports a base map
            // that fails); anything else is a fault of this page
            created.on('error', function (event) {
                if (!event.sourceId) console.warn(event.error);
            });
            created.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-left');
            await new Promise(function (resolve) { created.once('load', resolve); });
            map = created;
            map.on('mousedown', function (event) {
                if (event.originalEvent.button !== 0) return;
                anchor = event.lngLat;
                confirmButton.disabled = true;
            });
            map.on('mousemove', function (event) {
                if (anchor) draw(boxOf(anchor, event.lngLat));
            });
            map.on('mouseup', function (event) {
                if (!anchor) return;
                var from = map.project(anchor);
                var drawn = boxOf(anchor, event.lngLat);
                anchor = null;
                if (Math.abs(from.x - event.point.x) < 5 && Math.abs(from.y - event.point.y) < 5) {
                    draw(null);
                    return;
                }
                draw(drawn);
                confirmButton.disabled = false;
            });
            map.getCanvasContainer().addEventListener('mouseleave', function () {
                anchor = null;
            });
            showBasemap().catch(function (error) {
                console.warn('The area map has no base map:', error.message);
            });
            return map;
        }

        async function open() {
            dialog.showModal();
            var values = {};
            for (var side in fields) values[side] = parseFloat(fields[side].value);
            var known = !isNaN(values.north) && !isNaN(values.south) &&
                !isNaN(values.east) && !isNaN(values.west);
            confirmButton.disabled = true;
            if (!loading) {
                loading = create().catch(function (error) { return unavailable(NO_MAP, error); });
            }
            if (!(await loading)) return;
            map.resize();
            confirmButton.disabled = !known;
            if (known) {
                draw([values.west, values.south, values.east, values.north]);
                map.fitBounds([[values.west, values.south], [values.east, values.north]], { padding: 40, animate: false });
            }
        }

        dialog.addEventListener('close', function () {
            anchor = null;
            if (dialog.returnValue !== 'confirm' || !box) return;
            fields.north.value = round6(box[3]);
            fields.south.value = round6(box[1]);
            fields.east.value = round6(box[2]);
            fields.west.value = round6(box[0]);
            bbox();
        });
        opener.addEventListener('click', open);

        return {
            reset: function () {
                draw(null);
            },
        };
    })();

    // ---------------------------------------------------------------- wiring

    for (var radio of form.querySelectorAll('input[name="processing-area"]')) {
        radio.addEventListener('change', showArea);
    }
    form.addEventListener('submit', run);
    cancel.addEventListener('click', stop);
    refresh.addEventListener('click', load);
    admin.section('processing', load, clear);
    showArea();
})();
