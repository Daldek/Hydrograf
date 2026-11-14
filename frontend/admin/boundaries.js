/**
 * Hydrograf admin panel: the section „Granice i kanalizacja”.
 *
 * The boundary of an area for „Przetwarzanie NMT” (POST bootstrap/upload-boundary, kept
 * in this page as window.Hydrograf.admin.boundary) and the storm sewer network: its
 * state (GET sewer/status), its file (POST sewer/upload, then PUT sewer/config with the
 * file) and whether the DEM processing includes it (PUT sewer/config).
 */
(function () {
    'use strict';

    var admin = window.Hydrograf.admin;
    var status = admin.lines('boundaries-error', 'boundaries-note');
    var refresh = document.getElementById('boundaries-refresh');
    var boundaryFile = document.getElementById('boundary-file');
    var boundaryFacts = document.getElementById('boundary-facts');
    var sewerFacts = document.getElementById('sewer-facts');
    var sewerEnabled = document.getElementById('sewer-enabled');
    var sewerFile = document.getElementById('sewer-file');
    var uploadFacts = document.getElementById('sewer-upload-facts');
    var ticket = 0;

    // detected_format of POST sewer/upload
    var FORMATS = {
        points_only: 'punkty z downstream_id',
        points_and_lines: 'punkty i linie',
        lines_only: 'tylko linie',
        unknown: 'nierozpoznany',
    };

    function coordinates(bbox) {
        return (bbox || []).map(function (value) {
            return Number(value).toFixed(4);
        }).join(', ');
    }

    function showBoundary() {
        var boundary = admin.boundary;
        boundaryFacts.hidden = !boundary;
        if (!boundary) return;
        admin.facts(boundaryFacts, [
            ['Plik', boundary.name],
            ['Układ współrzędnych', boundary.crs],
            ['Obiekty', admin.number(boundary.n_features)],
            ['Powierzchnia', admin.number(boundary.area_km2) + ' km²'],
            ['Zasięg (WGS84)', coordinates(boundary.bbox_wgs84)],
        ]);
    }

    function showSewer(data) {
        var config = data.config || {};
        var types = Object.keys(data.node_types || {}).map(function (type) {
            return type + ': ' + admin.number(data.node_types[type]);
        }).join(', ');
        var state = 'brak danych';
        if (data.loaded) state = 'przetworzona';
        else if (config.source_path) state = 'plik wgrany, przetworzy go przetwarzanie NMT';
        admin.facts(sewerFacts, [
            ['Stan', state],
            ['Węzły', data.loaded ? admin.number(data.nodes) + (types ? ' (' + types + ')' : '') : ''],
            ['Odcinki', data.loaded ? admin.number(data.edges) : ''],
            ['Plik', config.source_path],
        ]);
        sewerEnabled.checked = Boolean(config.enabled);
    }

    async function load() {
        var mine = ++ticket;
        status.note('Wczytywanie…');
        refresh.disabled = true;
        showBoundary();
        try {
            var data = await admin.request('sewer/status');
            if (mine !== ticket) return;
            status.clear();
            showSewer(data);
        } catch (error) {
            if (mine !== ticket) return;
            status.note('');
            status.error(error);
        } finally {
            if (mine === ticket) refresh.disabled = false;
        }
    }

    async function uploadBoundary() {
        var file = boundaryFile.files[0];
        if (!file) return;
        status.error(null);
        status.note('Wysyłanie granicy…');
        var body = new FormData();
        body.append('file', file);
        try {
            var data = await admin.request('bootstrap/upload-boundary', { method: 'POST', body: body });
            admin.boundary = Object.assign({ name: file.name }, data);
            showBoundary();
            status.note('Wgrano granicę ' + file.name + '; wybierz ją jako obszar w sekcji „Przetwarzanie NMT”.');
        } catch (error) {
            status.note('');
            status.error(error);
        }
        boundaryFile.value = '';
    }

    async function uploadSewer() {
        var file = sewerFile.files[0];
        if (!file) return;
        status.error(null);
        status.note('Wysyłanie sieci kanalizacji…');
        uploadFacts.hidden = true;
        var body = new FormData();
        body.append('file', file);
        try {
            var data = await admin.request('sewer/upload', { method: 'POST', body: body });
            admin.facts(uploadFacts, [
                ['Wgrany plik', file.name],
                ['Obiekty', admin.number(data.features)],
                ['Geometrie', (data.geometry_types || []).join(', ')],
                ['Format', FORMATS[data.detected_format] || data.detected_format],
                ['Warstwy', (data.layers || []).join(', ')],
            ]);
            uploadFacts.hidden = false;
            await admin.request('sewer/config', {
                method: 'PUT',
                json: { enabled: true, source_path: 'data/sewer/' + data.filename },
            });
            status.note('Wgrano sieć kanalizacji; przetworzy ją następne przetwarzanie NMT.');
        } catch (error) {
            status.note('');
            status.error(error);
        }
        sewerFile.value = '';
        refreshSewer();
    }

    async function toggleSewer() {
        var enabled = sewerEnabled.checked;
        status.error(null);
        try {
            await admin.request('sewer/config', { method: 'PUT', json: { enabled: enabled } });
            status.note(enabled
                ? 'Przetwarzanie NMT uwzględni kanalizację deszczową.'
                : 'Przetwarzanie NMT pominie kanalizację deszczową.');
        } catch (error) {
            sewerEnabled.checked = !enabled;
            status.note('');
            status.error(error);
        }
        refreshSewer();
    }

    /** The state of the sewer again, without touching the lines of the section. */
    async function refreshSewer() {
        var mine = ++ticket;
        try {
            var data = await admin.request('sewer/status');
            if (mine === ticket) showSewer(data);
        } catch (error) {
            if (mine === ticket) status.error(error);
        }
    }

    function clear() {
        ticket += 1;
        admin.boundary = null;
        status.clear();
        boundaryFile.value = '';
        sewerFile.value = '';
        sewerEnabled.checked = false;
        boundaryFacts.replaceChildren();
        boundaryFacts.hidden = true;
        sewerFacts.replaceChildren();
        uploadFacts.replaceChildren();
        uploadFacts.hidden = true;
        refresh.disabled = false;
    }

    boundaryFile.addEventListener('change', uploadBoundary);
    sewerFile.addEventListener('change', uploadSewer);
    sewerEnabled.addEventListener('change', toggleSewer);
    refresh.addEventListener('click', load);
    admin.section('boundaries', load, clear);
})();
