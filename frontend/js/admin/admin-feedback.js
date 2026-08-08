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

    function renderDetails(item) {
        var wrap = el('div', 'feedback-details');
        wrap.appendChild(el('p', 'small feedback-message', item.message));
        if (item.contact) {
            wrap.appendChild(el('p', 'small text-secondary', 'Kontakt: ' + item.contact));
        }
        if (item.page_url) {
            wrap.appendChild(el('p', 'small text-secondary', 'URL: ' + item.page_url));
        }
        if (item.user_agent) {
            wrap.appendChild(el('p', 'small text-secondary', 'Przeglądarka: ' + item.user_agent));
        }
        if (item.diagnostics && item.diagnostics.workspace) {
            wrap.appendChild(el('h6', 'admin-section-title', 'Obszar roboczy'));
            wrap.appendChild(el('pre', 'feedback-event-data',
                JSON.stringify(item.diagnostics.workspace, null, 2)));
        }
        wrap.appendChild(el('h6', 'admin-section-title', 'Zdarzenia'));
        wrap.appendChild(renderEventsTimeline(item.diagnostics));
        return wrap;
    }

    function renderList(data) {
        var content = document.getElementById('feedback-content');
        content.replaceChildren();

        var badge = document.getElementById('feedback-unread-badge');
        if (data.unread_count > 0) {
            badge.textContent = String(data.unread_count);
            badge.classList.remove('d-none');
        } else {
            badge.classList.add('d-none');
        }

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
            header.appendChild(el('span', 'small feedback-excerpt' + (item.is_read ? '' : ' fw-bold'), excerpt));
            var newBadge = null;
            if (!item.is_read) {
                newBadge = el('span', 'badge bg-danger', 'nowe');
                header.appendChild(newBadge);
            }

            var deleteBtn = el('button', 'btn btn-outline-danger btn-sm', 'Usuń');
            deleteBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                if (!window.confirm('Usunąć zgłoszenie #' + item.id + '?')) return;
                window.Hydrograf.adminApi.deleteFeedback(item.id).then(load).catch(function (err) {
                    window.alert('Błąd usuwania: ' + err.message);
                });
            });
            header.appendChild(deleteBtn);

            var details = renderDetails(item);
            details.classList.add('d-none');

            header.addEventListener('click', function () {
                details.classList.toggle('d-none');
                if (!item.is_read) {
                    item.is_read = true;
                    if (newBadge) newBadge.remove();
                    window.Hydrograf.adminApi.markFeedbackRead(item.id);
                }
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
