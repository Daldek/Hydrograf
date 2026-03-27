/**
 * Hydrograf Admin — Sewer network management panel.
 *
 * Handles status display, file upload, and data deletion
 * for the sewer network layer.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    /**
     * Load and render sewer network status.
     */
    async function loadSewerStatus() {
        var el = document.getElementById('sewer-status');
        if (!el) return;

        try {
            var apiKey = window.Hydrograf.adminApi.getApiKey();
            var resp = await fetch('/api/admin/sewer/status', {
                headers: { 'X-Admin-Key': apiKey },
            });

            if (resp.status === 401 || resp.status === 403) {
                localStorage.removeItem('admin_api_key');
                window.location.reload();
                return;
            }

            var data = await resp.json();

            if (data.loaded) {
                var types = Object.entries(data.node_types || {}).map(function (e) {
                    return e[0] + ': ' + e[1];
                }).join(', ');
                el.innerHTML =
                    '<p><strong>Status:</strong> <span style="color:#22c55e">Załadowano</span></p>' +
                    '<p>Węzły: ' + data.nodes + (types ? ' (' + types + ')' : '') + '</p>' +
                    '<p>Krawędzie: ' + data.edges + '</p>';
            } else {
                el.innerHTML = '<p><strong>Status:</strong> Brak danych</p>';
            }
        } catch (e) {
            el.innerHTML = '<p class="text-danger small">Błąd ładowania statusu</p>';
        }
    }

    /**
     * Handle sewer file upload.
     *
     * @param {HTMLInputElement} input - file input element
     */
    async function handleSewerUpload(input) {
        if (!input.files.length) return;

        var resultEl = document.getElementById('sewer-upload-result');
        if (resultEl) {
            resultEl.innerHTML = '<p class="text-secondary small">Wysyłanie...</p>';
        }

        var formData = new FormData();
        formData.append('file', input.files[0]);

        try {
            var apiKey = window.Hydrograf.adminApi.getApiKey();
            var resp = await fetch('/api/admin/sewer/upload', {
                method: 'POST',
                headers: { 'X-Admin-Key': apiKey },
                body: formData,
            });

            var data = await resp.json();

            if (resultEl) {
                if (resp.ok) {
                    resultEl.innerHTML =
                        '<p style="color:#22c55e">' + window.Hydrograf.adminUtils.escapeHtml(data.message) + '</p>' +
                        '<p>Obiektów: ' + data.features + ', typy: ' + data.geometry_types.join(', ') + '</p>';
                    loadSewerStatus();
                } else {
                    resultEl.innerHTML =
                        '<p style="color:#ef4444">Błąd: ' +
                        window.Hydrograf.adminUtils.escapeHtml(data.detail || 'Nieznany błąd') +
                        '</p>';
                }
            }
        } catch (e) {
            if (resultEl) {
                resultEl.innerHTML = '<p style="color:#ef4444">Błąd uploadu</p>';
            }
        }

        input.value = '';
    }

    /**
     * Delete all sewer network data.
     */
    async function deleteSewer() {
        if (!confirm('Usunąć dane kanalizacji?')) return;

        var resultEl = document.getElementById('sewer-upload-result');

        try {
            var apiKey = window.Hydrograf.adminApi.getApiKey();
            var resp = await fetch('/api/admin/sewer/delete', {
                method: 'DELETE',
                headers: { 'X-Admin-Key': apiKey },
            });

            var data = await resp.json();

            if (resultEl) {
                resultEl.innerHTML =
                    '<p style="color:#f59e0b">' +
                    window.Hydrograf.adminUtils.escapeHtml(data.message) +
                    '</p>';
            }
            loadSewerStatus();
        } catch (e) {
            if (resultEl) {
                resultEl.innerHTML = '<p style="color:#ef4444">Błąd usuwania</p>';
            }
        }
    }

    /**
     * Initialize sewer panel — bind event listeners.
     */
    function init() {
        var uploadInput = document.getElementById('sewer-upload-input');
        if (uploadInput) {
            uploadInput.addEventListener('change', function () {
                handleSewerUpload(this);
            });
        }

        var deleteBtn = document.getElementById('sewer-delete-btn');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', deleteSewer);
        }

        loadSewerStatus();
    }

    window.Hydrograf.adminSewer = {
        init: init,
        loadSewerStatus: loadSewerStatus,
    };
})();
