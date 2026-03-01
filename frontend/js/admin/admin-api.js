/**
 * Hydrograf Admin API client module.
 *
 * Handles communication with /api/admin/* endpoints.
 * Uses X-Admin-Key header for authentication.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var _apiKey = sessionStorage.getItem('admin_api_key') || '';

    /**
     * Store the admin API key in memory and sessionStorage.
     */
    function setApiKey(key) {
        _apiKey = key;
        sessionStorage.setItem('admin_api_key', key);
    }

    /**
     * Get the current admin API key.
     */
    function getApiKey() {
        return _apiKey;
    }

    /**
     * Build standard headers with auth.
     */
    function headers() {
        return {
            'Content-Type': 'application/json',
            'X-Admin-Key': _apiKey,
        };
    }

    /**
     * Generic request wrapper.
     * Handles 401/403 by clearing key and reloading.
     */
    async function request(method, path, body) {
        var opts = {
            method: method,
            headers: headers(),
        };
        if (body !== undefined) {
            opts.body = JSON.stringify(body);
        }

        var response = await fetch(path, opts);

        if (response.status === 401 || response.status === 403) {
            sessionStorage.removeItem('admin_api_key');
            window.location.reload();
            throw new Error('Brak autoryzacji');
        }

        if (!response.ok) {
            var errorData;
            try {
                errorData = await response.json();
            } catch (e) {
                throw new Error('Błąd serwera (' + response.status + ')');
            }
            throw new Error(errorData.detail || 'Błąd serwera (' + response.status + ')');
        }

        return response.json();
    }

    // --- Endpoint methods ---

    function getDashboard() {
        return request('GET', '/api/admin/dashboard');
    }

    function getResources() {
        return request('GET', '/api/admin/resources');
    }

    function getCleanupEstimate() {
        return request('GET', '/api/admin/cleanup/estimate');
    }

    function executeCleanup(targets) {
        return request('POST', '/api/admin/cleanup', { targets: targets });
    }

    function getBootstrapStatus() {
        return request('GET', '/api/admin/bootstrap/status');
    }

    function startBootstrap(params) {
        return request('POST', '/api/admin/bootstrap/start', params);
    }

    function cancelBootstrap() {
        return request('POST', '/api/admin/bootstrap/cancel');
    }

    /**
     * Stream bootstrap log lines via fetch + ReadableStream.
     *
     * Uses fetch (not EventSource) so we can send the X-Admin-Key header.
     *
     * @param {Function} onMessage - called with each log line (string)
     * @param {Function} onDone - called when stream ends, receives final status
     * @returns {Object} object with cancel() method to abort the stream
     */
    function streamBootstrapLogs(onMessage, onDone) {
        var aborted = false;
        var reader = null;

        var promise = (async function () {
            try {
                var response = await fetch('/api/admin/bootstrap/stream', {
                    headers: headers(),
                });

                if (!response.ok) {
                    if (onDone) onDone('error');
                    return;
                }

                reader = response.body.getReader();
                var decoder = new TextDecoder();
                var buffer = '';

                while (true) {
                    if (aborted) break;

                    var result = await reader.read();
                    if (result.done) break;

                    buffer += decoder.decode(result.value, { stream: true });
                    var chunks = buffer.split('\n\n');
                    buffer = chunks.pop();

                    for (var i = 0; i < chunks.length; i++) {
                        var chunk = chunks[i].trim();
                        if (!chunk) continue;

                        // Check for done event
                        if (chunk.indexOf('event: done') !== -1) {
                            var lines = chunk.split('\n');
                            var lastLine = lines[lines.length - 1];
                            var status = lastLine.replace('data: ', '');
                            if (onDone) onDone(status);
                            if (reader) reader.cancel();
                            return;
                        }

                        // Regular data line
                        if (chunk.indexOf('data: ') === 0) {
                            onMessage(chunk.substring(6));
                        }
                    }
                }

                if (!aborted && onDone) onDone('disconnected');
            } catch (e) {
                if (onDone) onDone('error');
            }
        })();

        return {
            cancel: function () {
                aborted = true;
                if (reader) {
                    reader.cancel();
                }
            },
            promise: promise,
        };
    }

    /**
     * Verify an API key by attempting to fetch the dashboard.
     *
     * @param {string} key - API key to verify
     * @returns {Promise<boolean>} true if key is valid
     */
    async function verifyKey(key) {
        try {
            var response = await fetch('/api/admin/dashboard', {
                headers: {
                    'Content-Type': 'application/json',
                    'X-Admin-Key': key,
                },
            });
            return response.ok;
        } catch (e) {
            return false;
        }
    }

    window.Hydrograf.adminApi = {
        setApiKey: setApiKey,
        getApiKey: getApiKey,
        headers: headers,
        request: request,
        getDashboard: getDashboard,
        getResources: getResources,
        getCleanupEstimate: getCleanupEstimate,
        executeCleanup: executeCleanup,
        getBootstrapStatus: getBootstrapStatus,
        startBootstrap: startBootstrap,
        cancelBootstrap: cancelBootstrap,
        streamBootstrapLogs: streamBootstrapLogs,
        verifyKey: verifyKey,
    };
})();
