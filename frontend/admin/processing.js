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

    /** The rectangle drawn on a Leaflet map of GUGiK's grey OpenStreetMap, in a dialog. */
    var picker = (function () {
        var dialog = document.getElementById('bbox-dialog');
        var opener = document.getElementById('bbox-map-open');
        var confirmButton = document.getElementById('bbox-confirm');
        var map = null;
        var rectangle = null;
        var anchor = null;

        function round6(value) {
            return Math.round(value * 1e6) / 1e6;
        }

        function draw(bounds) {
            if (rectangle) map.removeLayer(rectangle);
            var colour = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
            rectangle = L.rectangle(bounds, { color: colour, weight: 2, fillOpacity: 0.15 }).addTo(map);
        }

        function create() {
            map = L.map(document.getElementById('bbox-map'), { center: [52.0, 19.0], zoom: 6 });
            L.tileLayer(
                'https://mapy.geoportal.gov.pl/wss/ext/OSM/BaseMap/wmts/osm_3857/GLOBAL_WEBMERCATOR/{z}/{x}/{y}.png',
                {
                    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, ' +
                        '<a href="https://www.geoportal.gov.pl">GUGiK</a>',
                    className: 'basemap-grey',
                    maxZoom: 19,
                },
            ).addTo(map);
            map.on('mousedown', function (event) {
                if (event.originalEvent.button !== 0) return;
                anchor = event.latlng;
                map.dragging.disable();
                confirmButton.disabled = true;
            });
            map.on('mousemove', function (event) {
                if (anchor) draw(L.latLngBounds(anchor, event.latlng));
            });
            map.on('mouseup', function (event) {
                if (!anchor) return;
                var bounds = L.latLngBounds(anchor, event.latlng);
                anchor = null;
                map.dragging.enable();
                var corner = map.latLngToContainerPoint(bounds.getNorthEast());
                var other = map.latLngToContainerPoint(bounds.getSouthWest());
                if (Math.abs(corner.x - other.x) < 5 && Math.abs(corner.y - other.y) < 5) {
                    if (rectangle) map.removeLayer(rectangle);
                    rectangle = null;
                    return;
                }
                draw(bounds);
                confirmButton.disabled = false;
            });
            map.getContainer().addEventListener('mouseleave', function () {
                if (!anchor) return;
                anchor = null;
                map.dragging.enable();
            });
        }

        function open() {
            dialog.showModal();
            if (!map) create();
            map.invalidateSize();
            var values = {};
            for (var side in fields) values[side] = parseFloat(fields[side].value);
            var known = !isNaN(values.north) && !isNaN(values.south) &&
                !isNaN(values.east) && !isNaN(values.west);
            confirmButton.disabled = !known;
            if (known) {
                var bounds = L.latLngBounds([values.south, values.west], [values.north, values.east]);
                draw(bounds);
                map.fitBounds(bounds, { padding: [40, 40] });
            }
        }

        dialog.addEventListener('close', function () {
            anchor = null;
            if (map) map.dragging.enable();
            if (dialog.returnValue !== 'confirm' || !rectangle) return;
            var bounds = rectangle.getBounds();
            fields.north.value = round6(bounds.getNorth());
            fields.south.value = round6(bounds.getSouth());
            fields.east.value = round6(bounds.getEast());
            fields.west.value = round6(bounds.getWest());
            bbox();
        });
        opener.addEventListener('click', open);

        return {
            reset: function () {
                if (map && rectangle) map.removeLayer(rectangle);
                rectangle = null;
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
