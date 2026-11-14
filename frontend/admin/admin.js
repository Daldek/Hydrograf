/**
 * Hydrograf admin panel: what its own sections share (Nogat DEV-15.13, ADR-086).
 *
 * The page is Nogat's <nogat-admin> shell (nogat/nogat-admin.js), which signs in with
 * the admin key and shows „Zgłoszenia”, „Statystyki” and „Stan”. Hydrograf's sections
 * („Zasoby”, „Przetwarzanie NMT”, „Czyszczenie”, „Granice i kanalizacja”) send their
 * requests through the shell's adminFetch, which adds the key and returns to the key
 * prompt on 401. A section loads its data when the shell shows it and drops whatever
 * it shows when the key is forgotten, so nothing of the panel stays on the page.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var shell = document.querySelector('nogat-admin');
    var NUMBER = new Intl.NumberFormat('pl-PL');
    var DECIMAL = new Intl.NumberFormat('pl-PL', { maximumFractionDigits: 1 });

    /**
     * Send a request below the admin API (`path` such as "resources").
     *
     * @param {string} path - the route below /api/admin/
     * @param {RequestInit} [init] - what fetch takes; a `json` member is sent as the body
     * @returns {Promise<Response>} the successful answer
     * @throws {Error} with a Polish message and the HTTP `status` (0 without an answer);
     *     after a 401 the shell is already back at its prompt
     */
    async function send(path, init) {
        var options = Object.assign({}, init || {});
        var headers = new Headers(options.headers || {});
        headers.set('Accept-Language', 'pl');
        if ('json' in options) {
            headers.set('Content-Type', 'application/json');
            options.body = JSON.stringify(options.json);
            delete options.json;
        }
        options.headers = headers;
        var response;
        try {
            response = await shell.adminFetch(path, options);
        } catch (error) {
            if (error && error.name === 'AbortError') throw error;
            throw failure('Brak połączenia z serwerem.', 0);
        }
        if (response.ok) return response;
        var problem;
        try {
            problem = await response.json();
        } catch (error) {
            problem = null;
        }
        var detail = problem && typeof problem.detail === 'string' ? problem.detail : '';
        throw failure(detail || 'Serwer odpowiedział błędem ' + response.status + '.', response.status);
    }

    /** The JSON of a successful answer of `send`. */
    async function request(path, init) {
        return (await send(path, init)).json();
    }

    function failure(message, status) {
        var error = new Error(message);
        error.status = status;
        return error;
    }

    /**
     * Run `show` whenever the shell shows the section `id`, and `clear` when the key is
     * forgotten („Wyloguj” or a 401).
     */
    function section(id, show, clear) {
        shell.addEventListener('nogat-admin-section', function (event) {
            if (event.detail.id === id) show();
        });
        shell.addEventListener('nogat-admin-signout', function () {
            for (var dialog of shell.querySelectorAll('dialog[open]')) {
                dialog.close('cancel');
            }
            clear();
        });
    }

    /** The error line and the note line of a section. */
    function lines(errorId, noteId) {
        var errorLine = document.getElementById(errorId);
        var noteLine = document.getElementById(noteId);
        return {
            /** Show an error; one after a 401 is not shown (the prompt is). */
            error: function (error) {
                if (error && error.status === 401) return;
                errorLine.textContent = error ? (error.message || String(error)) : '';
                errorLine.hidden = !error;
            },
            note: function (text) {
                noteLine.textContent = text || '';
            },
            clear: function () {
                errorLine.textContent = '';
                errorLine.hidden = true;
                noteLine.textContent = '';
            },
        };
    }

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function button(text, className) {
        var node = el('button', className || 'nogat-admin-button', text);
        node.type = 'button';
        return node;
    }

    /** Fill a <dl> with [label, value] pairs; a missing value shows as „–”. */
    function facts(list, pairs) {
        list.replaceChildren();
        for (var pair of pairs) {
            var value = pair[1];
            list.append(el('dt', null, pair[0]));
            list.append(el('dd', null, value === null || value === undefined || value === '' ? '–' : String(value)));
        }
    }

    function number(value) {
        return typeof value === 'number' && isFinite(value) ? NUMBER.format(value) : '–';
    }

    function megabytes(value) {
        return typeof value === 'number' && isFinite(value) ? DECIMAL.format(value) + ' MB' : '–';
    }

    function bytes(value) {
        if (typeof value !== 'number' || !isFinite(value)) return '–';
        var units = ['B', 'kB', 'MB', 'GB', 'TB'];
        var unit = 0;
        while (value >= 1000 && unit < units.length - 1) {
            value /= 1000;
            unit += 1;
        }
        return (unit ? DECIMAL.format(value) : NUMBER.format(value)) + ' ' + units[unit];
    }

    /** A duration in seconds as „1 godz. 3 min 12 s”. */
    function duration(seconds) {
        var total = Math.max(0, Math.floor(Number(seconds) || 0));
        var hours = Math.floor(total / 3600);
        var minutes = Math.floor((total % 3600) / 60);
        var parts = [];
        if (hours) parts.push(hours + ' godz.');
        if (hours || minutes) parts.push(minutes + ' min');
        parts.push((total % 60) + ' s');
        return parts.join(' ');
    }

    /**
     * Ask before something is deleted or stopped, in the kit's dialog: true for the
     * confirming button, false for „Anuluj”, Esc or a click outside. Focus returns to
     * `opener`.
     */
    function confirm(options) {
        var dialog = el('dialog', 'nogat-admin-dialog');
        var form = el('form', 'nogat-admin-dialog-body');
        form.method = 'dialog';
        var title = el('h2', null, options.title);
        title.id = 'admin-confirm-title';
        var text = el('p', null, options.text);
        var cancel = el('button', 'nogat-admin-button', 'Anuluj');
        cancel.value = 'cancel';
        var ok = el('button', 'nogat-admin-button nogat-admin-danger', options.confirm);
        ok.value = 'confirm';
        var actions = el('div', 'nogat-admin-dialog-actions');
        actions.append(cancel, ok);
        form.append(title, text, actions);
        dialog.append(form);
        dialog.setAttribute('aria-labelledby', title.id);
        dialog.addEventListener('click', function (event) {
            if (event.target === dialog) dialog.close('cancel');
        });
        (options.within || shell).append(dialog);
        return new Promise(function (resolve) {
            dialog.addEventListener('close', function () {
                var confirmed = dialog.returnValue === 'confirm';
                dialog.remove();
                if (options.opener && options.opener.isConnected) options.opener.focus();
                resolve(confirmed);
            });
            dialog.showModal();
            cancel.focus();
        });
    }

    window.Hydrograf.admin = {
        request: request,
        send: send,
        section: section,
        lines: lines,
        el: el,
        button: button,
        facts: facts,
        number: number,
        megabytes: megabytes,
        bytes: bytes,
        duration: duration,
        confirm: confirm,
        /** The boundary uploaded in „Granice i kanalizacja”, for „Przetwarzanie NMT”. */
        boundary: null,
    };
})();
