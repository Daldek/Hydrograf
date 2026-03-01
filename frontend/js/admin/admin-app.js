/**
 * Hydrograf Admin — Main application orchestrator.
 *
 * Handles auth flow, panel initialization, and periodic refresh.
 */
(function () {
    'use strict';

    var _refreshTimer = null;
    var REFRESH_INTERVAL_MS = 30000; // 30 seconds

    // ----------------------------------------------------------------
    // Helpers
    // ----------------------------------------------------------------

    /**
     * Build a stat-item HTML snippet.
     */
    function statItem(label, value) {
        return '<div class="stat-item">' +
               '<span class="stat-label">' + escapeHtml(label) + '</span>' +
               '<span class="stat-value">' + escapeHtml(String(value)) + '</span>' +
               '</div>';
    }

    /**
     * Format uptime seconds to human readable.
     */
    function formatUptime(seconds) {
        var s = Math.round(seconds);
        var d = Math.floor(s / 86400);
        s %= 86400;
        var h = Math.floor(s / 3600);
        s %= 3600;
        var m = Math.floor(s / 60);

        var parts = [];
        if (d > 0) parts.push(d + 'd');
        if (h > 0) parts.push(h + 'h');
        parts.push(m + 'min');
        return parts.join(' ');
    }

    /**
     * Format number with locale separators.
     */
    function formatNumber(n) {
        if (typeof n !== 'number') return String(n);
        return n.toLocaleString('pl-PL');
    }

    /**
     * Escape HTML special characters.
     */
    function escapeHtml(str) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    /**
     * Format seconds to human-readable elapsed time.
     *
     * @param {number} seconds - Elapsed seconds
     * @returns {string} e.g. "3min 45s"
     */
    function formatElapsed(seconds) {
        if (seconds < 0) seconds = 0;
        var min = Math.floor(seconds / 60);
        var sec = seconds % 60;
        if (min > 0) {
            return min + 'min ' + sec + 's';
        }
        return sec + 's';
    }

    // ----------------------------------------------------------------
    // Shared utilities (used by other admin modules)
    // ----------------------------------------------------------------

    window.Hydrograf = window.Hydrograf || {};
    window.Hydrograf.adminUtils = {
        escapeHtml: escapeHtml,
        formatNumber: formatNumber,
        formatElapsed: formatElapsed,
    };

    // ----------------------------------------------------------------
    // Auth flow
    // ----------------------------------------------------------------

    /**
     * Show the auth overlay and bind handlers.
     */
    function showAuth() {
        // First check if auth is even required (empty key = auth disabled)
        tryAuth('').then(function (success) {
            if (success) return; // Auth disabled — already logged in

            var overlay = document.getElementById('auth-overlay');
            var input = document.getElementById('auth-key-input');
            var btn = document.getElementById('auth-submit-btn');
            var errorDiv = document.getElementById('auth-error');

            if (overlay) overlay.classList.remove('d-none');

            function doLogin() {
                var key = input ? input.value.trim() : '';
                if (!key) return;

                btn.disabled = true;
                errorDiv.classList.add('d-none');

                tryAuth(key).then(function (ok) {
                    if (!ok) {
                        errorDiv.classList.remove('d-none');
                        btn.disabled = false;
                        if (input) {
                            input.value = '';
                            input.focus();
                        }
                    }
                });
            }

            if (btn) {
                btn.addEventListener('click', doLogin);
            }
            if (input) {
                input.addEventListener('keydown', function (e) {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        doLogin();
                    }
                });
                input.focus();
            }
        });
    }

    /**
     * Try to authenticate with the given key.
     *
     * @param {string} key - API key to verify
     * @returns {Promise<boolean>} true if auth succeeded
     */
    async function tryAuth(key) {
        var valid = await window.Hydrograf.adminApi.verifyKey(key);
        if (!valid) return false;

        window.Hydrograf.adminApi.setApiKey(key);

        // Hide overlay, show main content
        var overlay = document.getElementById('auth-overlay');
        var main = document.getElementById('admin-main');
        if (overlay) overlay.classList.add('d-none');
        if (main) main.classList.remove('d-none');

        initPanels();
        return true;
    }

    // ----------------------------------------------------------------
    // Panel loading
    // ----------------------------------------------------------------

    /**
     * Initialize all panels and start periodic refresh.
     */
    function initPanels() {
        loadDashboard();
        loadResources();
        loadCleanup();
        window.Hydrograf.adminBootstrap.init();

        // Auto-refresh every 30s
        if (_refreshTimer) clearInterval(_refreshTimer);
        _refreshTimer = setInterval(function () {
            loadDashboard();
            loadResources();
            window.Hydrograf.adminBootstrap.refresh();
        }, REFRESH_INTERVAL_MS);
    }

    /**
     * Load and render the dashboard panel.
     */
    async function loadDashboard() {
        try {
            var data = await window.Hydrograf.adminApi.getDashboard();
            renderDashboard(data);

            // Update navbar badge
            var navBadge = document.getElementById('nav-status-badge');
            if (navBadge) {
                navBadge.textContent = data.status === 'healthy' ? 'Healthy' : 'Unhealthy';
                navBadge.className = 'badge badge-' + (data.status === 'healthy' ? 'healthy' : 'unhealthy');
            }
        } catch (e) {
            var el = document.getElementById('dashboard-content');
            if (el) el.innerHTML = '<p class="text-danger small">Błąd: ' + escapeHtml(e.message) + '</p>';
        }
    }

    /**
     * Render dashboard data into the panel.
     */
    function renderDashboard(data) {
        var el = document.getElementById('dashboard-content');
        if (!el) return;

        var html = '';

        // Stats grid
        html += '<div class="stat-grid">';
        html += statItem('Status', data.status === 'healthy' ? 'Healthy' : 'Unhealthy');
        html += statItem('Wersja', data.version);
        html += statItem('Uptime', formatUptime(data.uptime_s));
        html += statItem('Baza danych', data.database);
        html += '</div>';

        // Tables
        html += '<h6 class="admin-section-title">Tabele</h6>';
        html += '<table class="admin-table">';
        html += '<thead><tr><th>Tabela</th><th>Wiersze</th></tr></thead>';
        html += '<tbody>';
        var tableNames = Object.keys(data.tables);
        for (var i = 0; i < tableNames.length; i++) {
            var name = tableNames[i];
            html += '<tr><td>' + escapeHtml(name) + '</td><td>' + formatNumber(data.tables[name]) + '</td></tr>';
        }
        html += '</tbody></table>';

        // Disk usage
        html += '<h6 class="admin-section-title">Dysk</h6>';
        html += '<table class="admin-table">';
        html += '<thead><tr><th>Zasób</th><th>MB</th></tr></thead>';
        html += '<tbody>';
        var diskKeys = Object.keys(data.disk);
        for (var j = 0; j < diskKeys.length; j++) {
            var dkey = diskKeys[j];
            var dlabel = dkey.replace(/_/g, ' ').replace(' mb', '');
            html += '<tr><td>' + escapeHtml(dlabel) + '</td><td>' + formatNumber(data.disk[dkey]) + '</td></tr>';
        }
        html += '</tbody></table>';

        el.innerHTML = html;
    }

    /**
     * Load and render the resources panel.
     */
    async function loadResources() {
        try {
            var data = await window.Hydrograf.adminApi.getResources();
            renderResources(data);
        } catch (e) {
            var el = document.getElementById('resources-content');
            if (el) el.innerHTML = '<p class="text-danger small">Błąd: ' + escapeHtml(e.message) + '</p>';
        }
    }

    /**
     * Render resources data into the panel.
     */
    function renderResources(data) {
        var el = document.getElementById('resources-content');
        if (!el) return;

        var html = '';

        // Process stats
        html += '<div class="stat-grid">';
        html += statItem('CPU', data.process.cpu_percent + '%');
        html += statItem('RAM', data.process.memory_mb + ' MB');
        html += statItem('RAM %', data.process.memory_percent + '%');
        html += statItem('PID', data.process.pid);
        html += statItem('Wątki', data.process.threads);
        html += statItem('DB size', data.db_size_mb + ' MB');
        html += '</div>';

        // DB pool table
        html += '<h6 class="admin-section-title">Pula połączeń DB</h6>';
        html += '<table class="admin-table">';
        html += '<thead><tr><th>Parametr</th><th>Wartość</th></tr></thead>';
        html += '<tbody>';
        html += '<tr><td>Pool size</td><td>' + escapeHtml(String(data.db_pool.pool_size)) + '</td></tr>';
        html += '<tr><td>Checked out</td><td>' + escapeHtml(String(data.db_pool.checked_out)) + '</td></tr>';
        html += '<tr><td>Overflow</td><td>' + escapeHtml(String(data.db_pool.overflow)) + '</td></tr>';
        html += '<tr><td>Checked in</td><td>' + escapeHtml(String(data.db_pool.checked_in)) + '</td></tr>';
        html += '</tbody></table>';

        // Catchment graph info
        html += '<h6 class="admin-section-title">Catchment Graph</h6>';
        html += '<table class="admin-table">';
        html += '<thead><tr><th>Parametr</th><th>Wartość</th></tr></thead>';
        html += '<tbody>';
        html += '<tr><td>Załadowany</td><td>' + escapeHtml(String(data.catchment_graph.loaded ? 'Tak' : 'Nie')) + '</td></tr>';
        html += '<tr><td>Węzły</td><td>' + escapeHtml(String(formatNumber(data.catchment_graph.nodes))) + '</td></tr>';
        if (data.catchment_graph.threshold_m2 && data.catchment_graph.threshold_m2.length > 0) {
            html += '<tr><td>Thresholds</td><td>' + escapeHtml(String(data.catchment_graph.threshold_m2.join(', '))) + '</td></tr>';
        }
        html += '</tbody></table>';

        el.innerHTML = html;
    }

    /**
     * Load and render the cleanup panel.
     */
    async function loadCleanup() {
        try {
            var data = await window.Hydrograf.adminApi.getCleanupEstimate();
            renderCleanup(data);
        } catch (e) {
            var el = document.getElementById('cleanup-content');
            if (el) el.innerHTML = '<p class="text-danger small">Błąd: ' + escapeHtml(e.message) + '</p>';
        }
    }

    /**
     * Render cleanup targets into the panel.
     */
    function renderCleanup(data) {
        var el = document.getElementById('cleanup-content');
        if (!el) return;

        if (!data.targets || data.targets.length === 0) {
            el.innerHTML = '<p class="text-secondary small">Brak celów do czyszczenia.</p>';
            return;
        }

        var html = '';
        for (var i = 0; i < data.targets.length; i++) {
            var target = data.targets[i];
            html += '<div class="cleanup-target">';
            html += '<div class="cleanup-target-info">';
            html += '<span class="cleanup-target-label">' + escapeHtml(target.label) + '</span><br>';
            html += '<span class="cleanup-target-size">' + formatNumber(target.size_mb) + ' MB</span>';
            html += '</div>';
            html += '<button class="btn btn-outline-danger btn-sm cleanup-delete-btn" data-target="' + escapeHtml(target.key) + '">';
            html += 'Usuń</button>';
            html += '</div>';
        }

        el.innerHTML = html;

        // Bind delete buttons
        var buttons = el.querySelectorAll('.cleanup-delete-btn');
        for (var j = 0; j < buttons.length; j++) {
            buttons[j].addEventListener('click', function () {
                var targetKey = this.getAttribute('data-target');
                handleCleanup(targetKey);
            });
        }
    }

    /**
     * Handle cleanup for a single target.
     */
    async function handleCleanup(targetKey) {
        if (!confirm('Czy na pewno usunąć: ' + targetKey + '?')) {
            return;
        }

        try {
            var result = await window.Hydrograf.adminApi.executeCleanup([targetKey]);

            if (result.results && result.results.length > 0) {
                var r = result.results[0];
                if (r.status === 'ok') {
                    alert('Wyczyszczono: ' + targetKey);
                } else {
                    alert('Błąd: ' + (r.detail || 'Nieznany błąd'));
                }
            }

            // Reload cleanup + dashboard to reflect changes
            loadCleanup();
            loadDashboard();
        } catch (e) {
            alert('Błąd: ' + e.message);
        }
    }

    // ----------------------------------------------------------------
    // Initialization
    // ----------------------------------------------------------------

    document.addEventListener('DOMContentLoaded', function () {
        var savedKey = sessionStorage.getItem('admin_api_key');

        if (savedKey) {
            // Try the saved key
            tryAuth(savedKey).then(function (success) {
                if (!success) {
                    showAuth();
                }
            });
        } else {
            showAuth();
        }
    });
})();
