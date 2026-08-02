/**
 * Hydrograf Diagnostics — session event ring buffer for feedback reports.
 *
 * Collects recent user actions (map clicks, mode/layer changes, API calls,
 * JS errors) in memory only. Nothing leaves the browser until the user
 * submits the feedback form with diagnostics enabled.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var MAX_EVENTS = 50;
    var MAX_SNAPSHOT_BYTES = 100000;
    var events = [];

    var HYDROGRAPH_INPUT_IDS = [
        'hydro-duration', 'hydro-probability', 'hydro-hietogram-type',
        'hydro-alpha', 'hydro-beta', 'hydro-uh-model', 'hydro-tc-method',
        'hydro-tc-runoff-coeff', 'hydro-tc-retardance',
        'hydro-tc-overland-length', 'hydro-nash-estimation', 'hydro-nash-n',
        'hydro-snyder-ct', 'hydro-snyder-cp',
    ];

    function log(type, data) {
        events.push({ t: new Date().toISOString(), type: type, data: data || {} });
        if (events.length > MAX_EVENTS) {
            events.shift();
        }
    }

    window.addEventListener('error', function (e) {
        log('js_error', {
            message: String(e.message || '').slice(0, 300),
            source: e.filename ? e.filename + ':' + e.lineno : null,
            stack: e.error && e.error.stack ? String(e.error.stack).slice(0, 500) : null,
        });
    });

    window.addEventListener('unhandledrejection', function (e) {
        var reason = e.reason;
        log('js_error', {
            message: String(reason && reason.message ? reason.message : reason).slice(0, 300),
            stack: reason && reason.stack ? String(reason.stack).slice(0, 500) : null,
        });
    });

    // Wrap global fetch for same-origin API calls: captures endpoint, status,
    // duration and the backend-issued X-Request-ID (joins with server logs).
    var _origFetch = window.fetch;
    window.fetch = function (input, init) {
        var url = typeof input === 'string' ? input : (input && input.url) || '';
        if (url.indexOf('/api/') !== 0 && url !== '/health') {
            return _origFetch.apply(window, arguments);
        }
        if (url.indexOf('/api/tiles/') === 0) {
            // MVT tile requests (streams/landcover/sewer via Leaflet.VectorGrid)
            // fire dozens of times per pan/zoom — logging them would evict
            // every meaningful event from the ring buffer.
            return _origFetch.apply(window, arguments);
        }
        var started = Date.now();
        var method = (init && init.method) || 'GET';
        var bodySummary = (init && typeof init.body === 'string')
            ? init.body.slice(0, 500)
            : null;
        return _origFetch.apply(window, arguments).then(
            function (response) {
                log('api_call', {
                    endpoint: url,
                    method: method,
                    status: response.status,
                    duration_ms: Date.now() - started,
                    request_id: response.headers.get('X-Request-ID'),
                    params: bodySummary,
                });
                return response;
            },
            function (err) {
                log('api_call', {
                    endpoint: url,
                    method: method,
                    status: null,
                    duration_ms: Date.now() - started,
                    error: String(err).slice(0, 200),
                });
                throw err;
            }
        );
    };

    function readHydrographSettings() {
        var settings = {};
        HYDROGRAPH_INPUT_IDS.forEach(function (id) {
            var el = document.getElementById(id);
            if (el && el.value !== '') {
                settings[id.replace('hydro-', '')] = el.value;
            }
        });
        return settings;
    }

    function watershedSummary(data) {
        // Scalar fields only — the boundary GeoJSON would blow the size limit.
        if (!data || !data.watershed) return null;
        var summary = {};
        Object.keys(data.watershed).forEach(function (key) {
            var value = data.watershed[key];
            if (value === null || typeof value !== 'object') {
                summary[key] = value;
            }
        });
        return summary;
    }

    function readWorkspace() {
        var ws = {};
        try {
            var map = Hydrograf.map && Hydrograf.map._getMap && Hydrograf.map._getMap();
            if (map) {
                var center = map.getCenter();
                ws.map = {
                    center: { lat: center.lat, lng: center.lng },
                    zoom: map.getZoom(),
                    baseLayer: (Hydrograf.layers && Hydrograf.layers.getBaseLayerName)
                        ? Hydrograf.layers.getBaseLayerName() : null,
                    activeOverlays: (Hydrograf.layers && Hydrograf.layers.getActiveOverlays)
                        ? Hydrograf.layers.getActiveOverlays() : [],
                };
            }
            if (Hydrograf.app) {
                ws.mode = Hydrograf.app.getClickMode ? Hydrograf.app.getClickMode() : null;
                ws.clickCoords = Hydrograf.app.getClickCoords();
                ws.watershed = watershedSummary(Hydrograf.app.getCurrentWatershed());
                if (ws.watershed && Hydrograf.map.getStreamsThreshold) {
                    ws.watershed.streams_threshold_m2 = Hydrograf.map.getStreamsThreshold();
                }
            }
            ws.hydrograph = readHydrographSettings();
            if (Hydrograf.profile && Hydrograf.profile.getLineLatLngs) {
                ws.profileLine = Hydrograf.profile.getLineLatLngs();
            }
        } catch (err) {
            ws.error = String(err).slice(0, 200);
        }
        return ws;
    }

    function snapshot() {
        var payload = {
            events: events.slice(),
            workspace: readWorkspace(),
            env: {
                userAgent: navigator.userAgent,
                viewport: { width: window.innerWidth, height: window.innerHeight },
                url: window.location.href,
                timestamp: new Date().toISOString(),
            },
        };
        while (JSON.stringify(payload).length > MAX_SNAPSHOT_BYTES && payload.events.length > 0) {
            payload.events.splice(0, 10);
        }
        return payload;
    }

    window.Hydrograf.diagnostics = {
        log: log,
        snapshot: snapshot,
    };
})();
