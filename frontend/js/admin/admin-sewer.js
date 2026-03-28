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

            // Update toggle state from config and expose source path for bootstrap
            var toggle = document.getElementById('sewer-enabled-toggle');
            if (toggle && data.config) {
                toggle.checked = data.config.enabled;
                window.Hydrograf._sewerSourcePath = data.config.source_path || null;
                window.Hydrograf._sewerSourceLayer = null;
            }

            if (data.loaded) {
                var types = Object.entries(data.node_types || {}).map(function (e) {
                    return e[0] + ': ' + e[1];
                }).join(', ');
                el.innerHTML =
                    '<p><strong>Status:</strong> <span style="color:#22c55e">Przetworzone</span></p>' +
                    '<p>Węzły: ' + data.nodes + (types ? ' (' + types + ')' : '') + '</p>' +
                    '<p>Krawędzie: ' + data.edges + '</p>';
            } else if (data.config && data.config.source_path) {
                el.innerHTML =
                    '<p><strong>Status:</strong> <span style="color:#f59e0b">Plik wgrany</span></p>' +
                    '<p class="text-secondary small">Plik: ' +
                    window.Hydrograf.adminUtils.escapeHtml(data.config.source_path) +
                    '</p>' +
                    '<p class="text-secondary small">Uruchom analizę, aby przetworzyć dane</p>';
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
                    var safeTypes = data.geometry_types.map(function (t) {
                        return window.Hydrograf.adminUtils.escapeHtml(String(t));
                    }).join(', ');
                    var formatLabel = {
                        'points_only': 'Format A (punkty z downstream_id)',
                        'points_and_lines': 'Format B (punkty + linie)',
                        'lines_only': 'Tylko linie',
                        'unknown': 'Nierozpoznany format',
                    };
                    var fmt = formatLabel[data.detected_format] || data.detected_format;
                    var layers = data.layers && data.layers.length
                        ? ' | Warstwy: ' + data.layers.join(', ')
                        : '';
                    resultEl.innerHTML =
                        '<span class="text-success">Wgrany: ' + data.features + ' obiektów' +
                        ' (' + safeTypes + ')</span><br>' +
                        '<small class="text-muted">' + fmt + layers + '</small>';

                    // Auto-configure source path to uploaded file
                    var sourcePath = 'data/sewer/' + data.filename;
                    await fetch('/api/admin/sewer/config', {
                        method: 'POST',
                        headers: {
                            'X-Admin-Key': apiKey,
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ enabled: true, source_path: sourcePath }),
                    });

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
     * Toggle sewer enabled/disabled in pipeline config.
     *
     * @param {boolean} enabled
     */
    async function toggleSewerEnabled(enabled) {
        var resultEl = document.getElementById('sewer-upload-result');

        try {
            var apiKey = window.Hydrograf.adminApi.getApiKey();
            var resp = await fetch('/api/admin/sewer/config', {
                method: 'POST',
                headers: {
                    'X-Admin-Key': apiKey,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ enabled: enabled }),
            });

            var data = await resp.json();

            if (resultEl) {
                if (resp.ok) {
                    resultEl.innerHTML =
                        '<p style="color:#22c55e">' +
                        (enabled ? 'Kanalizacja włączona' : 'Kanalizacja wyłączona') +
                        '</p>';
                } else {
                    resultEl.innerHTML =
                        '<p style="color:#ef4444">Błąd: ' +
                        window.Hydrograf.adminUtils.escapeHtml(data.detail || 'Nieznany błąd') +
                        '</p>';
                }
            }
            loadSewerStatus();
        } catch (e) {
            if (resultEl) {
                resultEl.innerHTML = '<p style="color:#ef4444">Błąd zapisu konfiguracji</p>';
            }
        }
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

        var toggle = document.getElementById('sewer-enabled-toggle');
        if (toggle) {
            toggle.addEventListener('change', function () {
                toggleSewerEnabled(this.checked);
            });
        }

        loadSewerStatus();
    }

    window.Hydrograf.adminSewer = {
        init: init,
        loadSewerStatus: loadSewerStatus,
    };
})();
