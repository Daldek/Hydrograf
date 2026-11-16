/**
 * Hydrograf admin panel: the section „Zasoby” (GET /api/admin/resources).
 *
 * The API process (CPU, memory, threads), the database (size, connection pool, rows
 * of the tables), the catchment graph in memory and the size of the data on disk.
 */
(function () {
    'use strict';

    var admin = window.Hydrograf.admin;
    var panels = document.getElementById('resources-panels');
    var refresh = document.getElementById('resources-refresh');
    var status = admin.lines('resources-error', 'resources-note');
    var ticket = 0;

    // The data directories of GET /api/admin/resources `disk`, in the order shown
    var DISK = [
        ['nmt_data_mb', 'NMT i rastry pochodne'],
        ['frontend_data_mb', 'Dane warstw mapy'],
        ['frontend_tiles_mb', 'Kafelki'],
        ['cache_mb', 'Pamięć podręczna pobrań'],
        ['total_mb', 'Razem'],
    ];

    function panel(title, pairs) {
        var card = admin.el('div', 'admin-panel');
        var list = admin.el('dl', 'nogat-admin-facts admin-facts');
        admin.facts(list, pairs);
        card.append(admin.el('h3', 'admin-panel-title', title), list);
        return card;
    }

    function tablesOf(tables) {
        var scroll = admin.el('div', 'nogat-admin-scroll');
        var table = admin.el('table', 'nogat-admin-table');
        var head = admin.el('thead');
        var row = admin.el('tr');
        for (var label of ['Tabela', 'Wiersze']) {
            var cell = admin.el('th', null, label);
            cell.scope = 'col';
            row.append(cell);
        }
        head.append(row);
        var body = admin.el('tbody');
        for (var name of Object.keys(tables)) {
            var line = admin.el('tr');
            var title = admin.el('th', null, name);
            title.scope = 'row';
            line.append(title, admin.el('td', null, admin.number(tables[name])));
            body.append(line);
        }
        table.append(head, body);
        scroll.append(table);
        return scroll;
    }

    function draw(data) {
        var process = data.process || {};
        var pool = data.db_pool || {};
        var graph = data.catchment_graph || {};
        var disk = data.disk || {};
        var database = panel('Baza danych', [
            ['Rozmiar', admin.megabytes(data.db_size_mb)],
            ['Pula połączeń', admin.number(pool.pool_size)],
            ['W użyciu', admin.number(pool.checked_out)],
            ['Wolne', admin.number(pool.checked_in)],
            ['Ponad pulę', admin.number(pool.overflow)],
        ]);
        database.append(tablesOf(data.tables || {}));
        var thresholds = (graph.threshold_m2 || []).map(admin.number).join(', ');
        panels.replaceChildren(
            panel('Proces API', [
                ['CPU', admin.number(process.cpu_percent) + ' %'],
                ['Pamięć', admin.megabytes(process.memory_mb)],
                ['Udział pamięci', admin.number(process.memory_percent) + ' %'],
                ['Wątki', admin.number(process.threads)],
                ['PID', process.pid],
            ]),
            database,
            panel('Graf zlewni', [
                ['Wczytany', graph.loaded ? 'tak' : 'nie'],
                ['Zlewnie cząstkowe', admin.number(graph.nodes)],
                ['Progi', thresholds ? thresholds + ' m²' : ''],
            ]),
            panel('Dane na dysku', DISK.map(function (entry) {
                return [entry[1], admin.megabytes(disk[entry[0]])];
            })),
        );
    }

    async function load() {
        var mine = ++ticket;
        status.note('Wczytywanie…');
        refresh.disabled = true;
        try {
            var data = await admin.request('resources');
            if (mine !== ticket) return;
            status.clear();
            draw(data);
        } catch (error) {
            if (mine !== ticket) return;
            status.note('');
            status.error(error);
        } finally {
            if (mine === ticket) refresh.disabled = false;
        }
    }

    function clear() {
        ticket += 1;
        status.clear();
        panels.replaceChildren();
        refresh.disabled = false;
    }

    refresh.addEventListener('click', load);
    admin.section('resources', load, clear);
})();
