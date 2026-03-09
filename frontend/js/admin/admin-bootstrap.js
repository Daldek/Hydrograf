/**
 * Hydrograf Admin — Bootstrap pipeline management module.
 *
 * Handles starting, cancelling, and monitoring the bootstrap subprocess.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var _stream = null;
    var _elapsedTimer = null;
    var _boundaryFilename = null;

    /**
     * Initialize bootstrap panel — bind event handlers, load initial status.
     */
    function init() {
        var startBtn = document.getElementById('bootstrap-start-btn');
        var cancelBtn = document.getElementById('bootstrap-cancel-btn');

        if (startBtn) {
            startBtn.addEventListener('click', handleStart);
        }
        if (cancelBtn) {
            cancelBtn.addEventListener('click', handleCancel);
        }

        // Area mode toggle (bbox vs boundary file)
        document.querySelectorAll('input[name="area-mode"]').forEach(function (radio) {
            radio.addEventListener('change', function () {
                var bboxSection = document.getElementById('area-bbox-section');
                var boundarySection = document.getElementById('area-boundary-section');
                if (this.value === 'bbox') {
                    bboxSection.classList.remove('d-none');
                    boundarySection.classList.add('d-none');
                } else {
                    bboxSection.classList.add('d-none');
                    boundarySection.classList.remove('d-none');
                }
            });
        });

        // Boundary file upload handler
        var boundaryInput = document.getElementById('boundary-file');
        if (boundaryInput) {
            boundaryInput.addEventListener('change', handleBoundaryUpload);
        }

        refreshStatus();
    }

    /**
     * Refresh bootstrap status from API.
     */
    async function refreshStatus() {
        try {
            var data = await window.Hydrograf.adminApi.getBootstrapStatus();
            updateStatusUI(data);
        } catch (e) {
            // Ignore errors during refresh
        }
    }

    /**
     * Update UI elements based on bootstrap status data.
     */
    function updateStatusUI(data) {
        var badge = document.getElementById('bootstrap-status-badge');
        var startBtn = document.getElementById('bootstrap-start-btn');
        var cancelBtn = document.getElementById('bootstrap-cancel-btn');

        if (badge) {
            badge.textContent = data.status;
            badge.className = 'badge badge-' + mapStatusToBadge(data.status);
        }

        var isRunning = data.status === 'running';

        if (startBtn) {
            startBtn.disabled = isRunning;
        }
        if (cancelBtn) {
            cancelBtn.disabled = !isRunning;
        }

        // If running and we have a start time, show elapsed
        if (isRunning && data.started_at) {
            startElapsedTimer(data.started_at);
            // Also start streaming if not already
            if (!_stream) {
                startStreaming();
            }
        } else {
            stopElapsedTimer();
            if (data.started_at) {
                var elapsed = Math.round(Date.now() / 1000 - data.started_at);
                var elapsedEl = document.getElementById('bootstrap-elapsed');
                if (elapsedEl && elapsed > 0) {
                    elapsedEl.textContent = window.Hydrograf.adminUtils.formatElapsed(elapsed);
                }
            }
        }
    }

    /**
     * Map status string to badge CSS class suffix.
     */
    function mapStatusToBadge(status) {
        switch (status) {
            case 'running': return 'running';
            case 'completed': return 'completed';
            case 'failed': return 'failed';
            default: return 'idle';
        }
    }

    /**
     * Read bbox from 4 compass fields, validate, return as comma string or null.
     */
    function readAndValidateBbox() {
        var n = document.getElementById('bbox-north');
        var s = document.getElementById('bbox-south');
        var e = document.getElementById('bbox-east');
        var w = document.getElementById('bbox-west');
        var errEl = document.getElementById('bbox-validation-error');

        if (!n || !s || !e || !w) return null;

        var north = parseFloat(n.value);
        var south = parseFloat(s.value);
        var east = parseFloat(e.value);
        var west = parseFloat(w.value);

        // Clear previous error
        if (errEl) {
            errEl.classList.add('d-none');
            errEl.textContent = '';
        }
        [n, s, e, w].forEach(function (el) {
            el.classList.remove('is-invalid');
        });

        // Check empty / NaN
        if (isNaN(west) || isNaN(south) || isNaN(east) || isNaN(north)) {
            showBboxError('Wypełnij wszystkie pola bounding box.', [n, s, e, w]);
            return null;
        }

        // Check ordering
        if (west >= east) {
            showBboxError('W (min lon) musi być mniejsze niż E (max lon).', [w, e]);
            return null;
        }
        if (south >= north) {
            showBboxError('S (min lat) musi być mniejsze niż N (max lat).', [s, n]);
            return null;
        }

        return west + ',' + south + ',' + east + ',' + north;
    }

    /**
     * Show validation error under bbox fields.
     */
    function showBboxError(message, fields) {
        var errEl = document.getElementById('bbox-validation-error');
        if (errEl) {
            errEl.textContent = message;
            errEl.classList.remove('d-none');
        }
        fields.forEach(function (el) {
            if (el) el.classList.add('is-invalid');
        });
    }

    /**
     * Handle boundary file selection — upload and display metadata.
     */
    async function handleBoundaryUpload() {
        var file = this.files[0];
        if (!file) return;

        var infoDiv = document.getElementById('boundary-info');
        var errorDiv = document.getElementById('boundary-error');
        infoDiv.classList.add('d-none');
        errorDiv.classList.add('d-none');
        _boundaryFilename = null;

        try {
            var data = await window.Hydrograf.adminApi.uploadBoundary(file);
            _boundaryFilename = data.filename;
            document.getElementById('boundary-crs').textContent = data.crs;
            document.getElementById('boundary-features').textContent = data.n_features;
            document.getElementById('boundary-area').textContent = data.area_km2.toFixed(2);
            document.getElementById('boundary-bbox-display').textContent =
                data.bbox_wgs84.map(function (v) { return v.toFixed(4); }).join(', ');
            infoDiv.classList.remove('d-none');
        } catch (err) {
            errorDiv.textContent = err.message || 'Upload failed';
            errorDiv.classList.remove('d-none');
        }
    }

    /**
     * Handle Start button click.
     */
    async function handleStart() {
        var mode = document.querySelector('input[name="area-mode"]:checked').value;

        var params = {
            skip_precipitation: document.getElementById('skip-precipitation').checked,
            skip_tiles: document.getElementById('skip-tiles').checked,
            skip_overlays: document.getElementById('skip-overlays').checked,
        };

        if (mode === 'boundary') {
            if (!_boundaryFilename) {
                var errorDiv = document.getElementById('boundary-error');
                if (errorDiv) {
                    errorDiv.textContent = 'Najpierw wgraj plik z granicą obszaru.';
                    errorDiv.classList.remove('d-none');
                }
                return;
            }
            params.boundary_file = _boundaryFilename;
        } else {
            var bbox = readAndValidateBbox();
            if (!bbox) return;
            params.bbox = bbox;
        }

        try {
            clearLog();
            var result = await window.Hydrograf.adminApi.startBootstrap(params);
            appendLog('[Bootstrap started, PID: ' + result.pid + ']');
            startStreaming();
            startElapsedTimer(Date.now() / 1000);

            // Update buttons immediately
            var startBtn = document.getElementById('bootstrap-start-btn');
            var cancelBtn = document.getElementById('bootstrap-cancel-btn');
            var badge = document.getElementById('bootstrap-status-badge');
            if (startBtn) startBtn.disabled = true;
            if (cancelBtn) cancelBtn.disabled = false;
            if (badge) {
                badge.textContent = 'running';
                badge.className = 'badge badge-running';
            }
        } catch (e) {
            appendLog('[ERROR] ' + e.message);
        }
    }

    /**
     * Handle Cancel button click.
     */
    async function handleCancel() {
        if (!confirm('Czy na pewno anulować bootstrap?')) {
            return;
        }

        try {
            await window.Hydrograf.adminApi.cancelBootstrap();
            appendLog('[Bootstrap cancelled]');
            stopStreaming();
            refreshStatus();
        } catch (e) {
            appendLog('[ERROR] ' + e.message);
        }
    }

    /**
     * Start streaming bootstrap log lines.
     */
    function startStreaming() {
        if (_stream) {
            _stream.cancel();
        }

        _stream = window.Hydrograf.adminApi.streamBootstrapLogs(
            function onMessage(line) {
                appendLog(line);
            },
            function onDone(status) {
                _stream = null;
                appendLog('[Pipeline finished: ' + status + ']');
                stopElapsedTimer();
                refreshStatus();
            }
        );
    }

    /**
     * Stop the active log stream and elapsed timer.
     */
    function stopStreaming() {
        if (_stream) {
            _stream.cancel();
            _stream = null;
        }
        stopElapsedTimer();
    }

    /**
     * Start the elapsed time counter.
     *
     * @param {number} startedAt - Unix timestamp (seconds) when bootstrap started
     */
    function startElapsedTimer(startedAt) {
        stopElapsedTimer();

        var elapsedEl = document.getElementById('bootstrap-elapsed');
        if (!elapsedEl) return;

        function tick() {
            var seconds = Math.round(Date.now() / 1000 - startedAt);
            elapsedEl.textContent = window.Hydrograf.adminUtils.formatElapsed(seconds);
        }

        tick();
        _elapsedTimer = setInterval(tick, 1000);
    }

    /**
     * Stop the elapsed time counter.
     */
    function stopElapsedTimer() {
        if (_elapsedTimer) {
            clearInterval(_elapsedTimer);
            _elapsedTimer = null;
        }
    }

    /**
     * Append a line to the bootstrap log.
     */
    function appendLog(line) {
        var logEl = document.getElementById('bootstrap-log');
        if (!logEl) return;

        if (logEl.textContent) {
            logEl.textContent += '\n' + line;
        } else {
            logEl.textContent = line;
        }

        // Auto-scroll to bottom
        logEl.scrollTop = logEl.scrollHeight;
    }

    /**
     * Clear the bootstrap log.
     */
    function clearLog() {
        var logEl = document.getElementById('bootstrap-log');
        if (logEl) {
            logEl.textContent = '';
        }
    }

    window.Hydrograf.adminBootstrap = {
        init: init,
        refresh: refreshStatus,
    };
})();
