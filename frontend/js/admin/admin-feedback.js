/**
 * Hydrograf Admin — Feedback panel.
 *
 * SECURITY: feedback content is anonymous user input rendered in the
 * admin browser (admin key in localStorage). Build DOM exclusively via
 * createElement/textContent — never innerHTML with submission data.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    function el(tag, className, textValue) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (textValue !== undefined && textValue !== null) {
            node.textContent = String(textValue);
        }
        return node;
    }

    function renderEventsTimeline(diagnostics) {
        var container = el('div');
        if (!diagnostics || !Array.isArray(diagnostics.events) || diagnostics.events.length === 0) {
            container.appendChild(el('p', 'text-secondary small', 'Brak dziennika zdarzeń.'));
            return container;
        }
        var table = el('table', 'admin-table');
        var tbody = el('tbody');
        diagnostics.events.forEach(function (ev) {
            var tr = el('tr');
            tr.appendChild(el('td', 'small text-secondary text-nowrap',
                (ev.t || '').replace('T', ' ').slice(11, 19)));
            tr.appendChild(el('td', 'small', ev.type || ''));
            var dataCell = el('td', 'small');
            dataCell.appendChild(el('pre', 'feedback-event-data', JSON.stringify(ev.data || {})));
            tr.appendChild(dataCell);
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        container.appendChild(table);
        return container;
    }

    function textLine(label, value) {
        return el('p', 'small text-secondary', label + ': ' + value);
    }

    /** The view the report came from: {view, station, parameters, app_version}. */
    function renderContext(context) {
        var wrap = el('div');
        wrap.appendChild(textLine('Widok', context.view || '—'));
        if (context.station !== null && context.station !== undefined) {
            wrap.appendChild(textLine('Stacja', context.station));
        }
        wrap.appendChild(textLine('Wersja aplikacji', context.app_version || '—'));
        if (context.parameters) {
            wrap.appendChild(el('h6', 'admin-section-title', 'Parametry'));
            wrap.appendChild(el('pre', 'feedback-event-data',
                JSON.stringify(context.parameters, null, 2)));
        }
        return wrap;
    }

    /** What the old form sent: {contact, page_url, user_agent, diagnostics}, each may be null. */
    function renderLegacy(legacy) {
        var wrap = el('div');
        wrap.appendChild(el('h6', 'admin-section-title', 'Zgłoszenie ze starego formularza'));
        if (legacy.contact) wrap.appendChild(textLine('Kontakt', legacy.contact));
        if (legacy.page_url) wrap.appendChild(textLine('URL', legacy.page_url));
        if (legacy.user_agent) wrap.appendChild(textLine('Przeglądarka', legacy.user_agent));
        var diagnostics = legacy.diagnostics;
        if (diagnostics && diagnostics.workspace) {
            wrap.appendChild(el('h6', 'admin-section-title', 'Obszar roboczy'));
            wrap.appendChild(el('pre', 'feedback-event-data',
                JSON.stringify(diagnostics.workspace, null, 2)));
        }
        wrap.appendChild(el('h6', 'admin-section-title', 'Zdarzenia'));
        wrap.appendChild(renderEventsTimeline(diagnostics));
        return wrap;
    }

    function renderDetails(item) {
        var wrap = el('div', 'feedback-details');
        wrap.appendChild(el('p', 'small feedback-message', item.message));
        if (item.context) wrap.appendChild(renderContext(item.context));
        if (item.legacy) wrap.appendChild(renderLegacy(item.legacy));
        return wrap;
    }

    var unreadCount = 0;

    function showUnreadCount() {
        var badge = document.getElementById('feedback-unread-badge');
        if (unreadCount > 0) {
            badge.textContent = String(unreadCount);
            badge.classList.remove('d-none');
        } else {
            badge.classList.add('d-none');
        }
    }

    function renderList(data) {
        var content = document.getElementById('feedback-content');
        content.replaceChildren();

        unreadCount = data.unread_count;
        showUnreadCount();

        if (!data.items.length) {
            content.appendChild(el('p', 'text-secondary small', 'Brak zgłoszeń.'));
            return;
        }

        data.items.forEach(function (item) {
            var row = el('div', 'feedback-row');
            var header = el('div', 'feedback-row-header');
            header.appendChild(el('span', 'small text-secondary text-nowrap',
                (item.created_at || '').replace('T', ' ').slice(0, 16)));
            var excerpt = item.message.length > 80
                ? item.message.slice(0, 80) + '…'
                : item.message;
            var excerptEl = el('span', 'small feedback-excerpt', excerpt);
            header.appendChild(excerptEl);
            var newBadge = el('span', 'badge bg-danger', 'nowe');
            header.appendChild(newBadge);

            var readBtn = el('button', 'btn btn-outline-secondary btn-sm text-nowrap');
            readBtn.type = 'button';

            function showReadState() {
                excerptEl.classList.toggle('fw-bold', !item.is_read);
                newBadge.classList.toggle('d-none', item.is_read);
                readBtn.textContent = item.is_read ? 'Oznacz nieprzeczytane' : 'Oznacz przeczytane';
            }

            // Optimistic: the row and the counter change at once and are
            // restored when the PATCH fails.
            function setRead(isRead) {
                if (item.is_read === isRead) return;
                item.is_read = isRead;
                unreadCount += isRead ? -1 : 1;
                showReadState();
                showUnreadCount();
                window.Hydrograf.adminApi.setFeedbackRead(item.id, isRead).catch(function (err) {
                    item.is_read = !isRead;
                    unreadCount += isRead ? 1 : -1;
                    showReadState();
                    showUnreadCount();
                    window.alert('Błąd zapisu: ' + err.message);
                });
            }

            readBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                setRead(!item.is_read);
            });
            header.appendChild(readBtn);

            var deleteBtn = el('button', 'btn btn-outline-danger btn-sm', 'Usuń');
            deleteBtn.type = 'button';
            deleteBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                if (!window.confirm('Usunąć zgłoszenie #' + item.id + '?')) return;
                window.Hydrograf.adminApi.deleteFeedback(item.id).then(load).catch(function (err) {
                    window.alert('Błąd usuwania: ' + err.message);
                });
            });
            header.appendChild(deleteBtn);
            showReadState();

            var details = renderDetails(item);
            details.classList.add('d-none');

            header.addEventListener('click', function () {
                details.classList.toggle('d-none');
                setRead(true);
            });

            row.appendChild(header);
            row.appendChild(details);
            content.appendChild(row);
        });
    }

    async function load() {
        try {
            var data = await window.Hydrograf.adminApi.getFeedback();
            renderList(data);
        } catch (e) {
            var content = document.getElementById('feedback-content');
            if (content) {
                content.replaceChildren(el('p', 'text-danger small', 'Błąd: ' + e.message));
            }
        }
    }

    window.Hydrograf.adminFeedback = {
        init: load,
        refresh: load,
    };
})();
