/**
 * Hydrograf admin panel: the section „Czyszczenie” (GET cleanup/estimate, POST cleanup).
 *
 * Each target of the API with the space it takes, and „Usuń” after a confirmation;
 * `scripts.clean` deletes its files and tables.
 */
(function () {
    'use strict';

    var admin = window.Hydrograf.admin;
    var status = admin.lines('cleanup-error', 'cleanup-note');
    var list = document.getElementById('cleanup-targets');
    var refresh = document.getElementById('cleanup-refresh');
    var ticket = 0;

    function row(target) {
        var item = admin.el('li', 'admin-target');
        var info = admin.el('div');
        info.append(
            admin.el('span', 'admin-target-name', target.label),
            admin.el('span', 'admin-target-size', admin.megabytes(target.size_mb)),
        );
        var remove = admin.button('Usuń', 'nogat-admin-button nogat-admin-danger');
        remove.addEventListener('click', function () {
            clean(target, remove);
        });
        item.append(info, remove);
        return item;
    }

    async function load() {
        var mine = ++ticket;
        status.note('Wczytywanie…');
        refresh.disabled = true;
        try {
            var data = await admin.request('cleanup/estimate');
            if (mine !== ticket) return;
            status.error(null);
            status.note('');
            list.replaceChildren.apply(list, (data.targets || []).map(row));
            if (!list.children.length) list.append(admin.el('li', 'admin-line', 'Nie ma czego czyścić.'));
        } catch (error) {
            if (mine !== ticket) return;
            status.note('');
            status.error(error);
        } finally {
            if (mine === ticket) refresh.disabled = false;
        }
    }

    async function clean(target, opener) {
        var confirmed = await admin.confirm({
            title: 'Usunąć: ' + target.label + '?',
            text: 'Usuniętych danych nie da się przywrócić; odtworzy je dopiero przetwarzanie NMT.',
            confirm: 'Usuń',
            opener: opener,
        });
        if (!confirmed) return;
        status.error(null);
        status.note('Usuwanie…');
        opener.disabled = true;
        var done = '';
        var failed = null;
        try {
            var data = await admin.request('cleanup', { method: 'POST', json: { targets: [target.key] } });
            var result = (data.results || [])[0] || {};
            if (result.status === 'ok') {
                done = 'Usunięto: ' + target.label + ' (' + admin.number(result.total_files) +
                    ' plików, ' + admin.bytes(result.total_size) + ').';
            } else {
                failed = new Error('Nie udało się usunąć: ' + target.label + '. ' + (result.detail || ''));
            }
        } catch (error) {
            failed = error;
        }
        if (failed && failed.status === 401) return;
        await load();
        status.note(done);
        status.error(failed);
    }

    function clear() {
        ticket += 1;
        status.clear();
        list.replaceChildren();
        refresh.disabled = false;
    }

    refresh.addEventListener('click', load);
    admin.section('cleanup', load, clear);
})();
