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
                    elapsedEl.textContent = formatElapsed(elapsed);
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
     * Handle Start button click.
     */
    async function handleStart() {
        var bboxInput = document.getElementById('bootstrap-bbox');
        var bbox = bboxInput ? bboxInput.value.trim() : '';

        if (!bbox) {
            alert('Podaj bounding box.');
            return;
        }

        var params = {
            bbox: bbox,
            skip_precipitation: document.getElementById('skip-precipitation').checked,
            skip_tiles: document.getElementById('skip-tiles').checked,
            skip_overlays: document.getElementById('skip-overlays').checked,
        };

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
            elapsedEl.textContent = formatElapsed(seconds);
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

    window.Hydrograf.adminBootstrap = {
        init: init,
        refresh: refreshStatus,
    };
})();
