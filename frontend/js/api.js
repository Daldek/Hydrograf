/**
 * Hydrograf API client module.
 *
 * Handles communication with the backend API.
 * Uses relative URLs (same-origin via nginx proxy).
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    /**
     * fetch() that asks for Polish error texts: the API answers in English
     * without Accept-Language (AGI-6.4).
     */
    function apiFetch(url, options) {
        var opts = Object.assign({}, options);
        var headers = new Headers(opts.headers || {});
        if (!headers.has('Accept-Language')) headers.set('Accept-Language', 'pl');
        opts.headers = headers;
        return fetch(url, opts);
    }

    const ERROR_MESSAGES = {
        400: 'Nieprawidłowe żądanie. Sprawdź współrzędne i spróbuj ponownie.',
        404: 'Nie znaleziono linii spływu w tym miejscu. Kliknij bliżej linii spływu.',
        429: 'Zbyt wiele żądań. Poczekaj chwilę i spróbuj ponownie.',
        500: 'Błąd serwera. Spróbuj ponownie za chwilę.',
    };

    // Simple TTL cache for API results
    var _cache = new Map();
    var _CACHE_MAX = 50;
    var _CACHE_TTL = 300000; // 5 minutes

    function _cacheKey(prefix, args) {
        return prefix + ':' + Array.prototype.slice.call(arguments, 1).map(function(a) {
            return typeof a === 'number' ? a.toFixed(5) : String(a);
        }).join(',');
    }

    function _cacheGet(key) {
        var entry = _cache.get(key);
        if (!entry) return undefined;
        if (Date.now() - entry.ts > _CACHE_TTL) {
            _cache.delete(key);
            return undefined;
        }
        return entry.value;
    }

    function _cacheSet(key, value) {
        if (_cache.size >= _CACHE_MAX) {
            // Evict oldest entry
            var oldest = _cache.keys().next().value;
            _cache.delete(oldest);
        }
        _cache.set(key, { value: value, ts: Date.now() });
    }

    /**
     * Text of an API error, an application/problem+json document (ADR-059).
     * `detail` and the messages of `errors` are Polish because apiFetch sends
     * Accept-Language: pl. A validation error (it lists `errors`) shows the
     * message of its first invalid value (its `detail` only lists the JSON
     * Pointers, its hint points at `errors`); any other client error appends
     * its `hint` (e.g. "Kliknij w obszarze zlewni.").
     */
    function problemMessage(problem) {
        if (!problem || typeof problem.detail !== 'string') return null;
        if (Array.isArray(problem.errors)) {
            var first = problem.errors[0];
            return first && typeof first.message === 'string' ? first.message : problem.detail;
        }
        if (typeof problem.hint === 'string' && problem.status < 500) {
            return problem.detail + ' ' + problem.hint;
        }
        return problem.detail;
    }

    /**
     * Throw the error of a failed API response: an Error with the text for the
     * user, its HTTP `status` and the parsed `problem` document (null when the
     * body is not JSON), from which a form places `errors` at its fields.
     */
    async function handleError(response) {
        var problem = null;
        try {
            problem = await response.json();
        } catch { /* not JSON, e.g. an nginx error page: use the default */ }

        var error = new Error(
            problemMessage(problem) || ERROR_MESSAGES[response.status] ||
            'Nieoczekiwany błąd (' + response.status + '). Spróbuj ponownie.'
        );
        error.status = response.status;
        error.problem = problem;
        throw error;
    }

    /**
     * Get terrain profile along a line.
     *
     * @param {Object} lineGeojson - GeoJSON LineString geometry
     * @param {number} nSamples - Number of sample points
     * @param {Array<string>} [resultIds] - Analysis results whose water level is sampled too
     * @returns {Promise<Object>} { distances_m, elevations_m, total_length_m, water_levels }
     */
    async function getTerrainProfile(lineGeojson, nSamples, resultIds) {
        var ids = resultIds || [];
        var key = _cacheKey('tp', JSON.stringify(lineGeojson), nSamples, ids.join('|'));
        var cached = _cacheGet(key);
        if (cached) return cached;

        var payload = { geometry: lineGeojson, n_samples: nSamples || 100 };
        if (ids.length) payload.result_ids = ids;
        const response = await apiFetch('/api/terrain-profile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!response.ok) await handleError(response);
        var data = await response.json();
        _cacheSet(key, data);
        return data;
    }

    /**
     * Generate hydrograph for given parameters.
     * With opts.custom_precipitation ({ timestep_min, depths_mm }) the PMAXTP
     * design storm is replaced and duration/probability may be null.
     */
    async function generateHydrograph(lat, lng, duration, probability, opts) {
        var payload = {
            latitude: lat,
            longitude: lng,
        };
        if (duration != null) payload.duration = duration;
        if (probability != null) payload.probability = probability;
        if (opts) {
            if (opts.morphometry) payload.morphometry = opts.morphometry;
            if (opts.morphometry_origin) payload.morphometry_origin = opts.morphometry_origin;
            if (opts.custom_precipitation) payload.custom_precipitation = opts.custom_precipitation;
            if (opts.amc) payload.amc = opts.amc;
            if (opts.hietogram_type) payload.hietogram_type = opts.hietogram_type;
            if (opts.hietogram_alpha != null) payload.hietogram_alpha = opts.hietogram_alpha;
            if (opts.hietogram_beta != null) payload.hietogram_beta = opts.hietogram_beta;
            if (opts.uh_model) payload.uh_model = opts.uh_model;
            if (opts.tc_method) payload.tc_method = opts.tc_method;
            if (opts.nash_estimation) payload.nash_estimation = opts.nash_estimation;
            if (opts.snyder_ct != null) payload.snyder_ct = opts.snyder_ct;
            if (opts.snyder_cp != null) payload.snyder_cp = opts.snyder_cp;
            if (opts.tc_runoff_coeff != null) payload.tc_runoff_coeff = opts.tc_runoff_coeff;
            if (opts.tc_retardance != null) payload.tc_retardance = opts.tc_retardance;
            if (opts.tc_overland_length_km != null) payload.tc_overland_length_km = opts.tc_overland_length_km;
        }

        const response = await apiFetch('/api/generate-hydrograph', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!response.ok) await handleError(response);
        return response.json();
    }

    /**
     * Get available hydrograph scenarios.
     */
    async function getScenarios() {
        const response = await apiFetch('/api/scenarios');
        if (!response.ok) await handleError(response);
        return response.json();
    }

    /**
     * Optional layers available on this server, e.g. { sewer: false }.
     */
    async function getLayers() {
        const response = await apiFetch('/api/layers');
        if (!response.ok) await handleError(response);
        return response.json();
    }

    /**
     * Get filtered depressions as GeoJSON.
     *
     * @param {Object} filters - { min_volume, max_volume, min_area, max_area }
     * @returns {Promise<Object>} GeoJSON FeatureCollection
     */
    async function getDepressions(filters) {
        const params = new URLSearchParams();
        if (filters.min_volume !== undefined) params.set('min_volume', filters.min_volume);
        if (filters.max_volume !== undefined) params.set('max_volume', filters.max_volume);
        if (filters.min_area !== undefined) params.set('min_area', filters.min_area);
        if (filters.max_area !== undefined) params.set('max_area', filters.max_area);

        const response = await apiFetch('/api/depressions?' + params.toString());
        if (!response.ok) await handleError(response);
        return response.json();
    }

    /**
     * Delineate watershed at a given point.
     *
     * With threshold → precomputed mode (snap to stream network).
     * Without threshold → precise mode (on-the-fly delineation).
     *
     * @param {number} lat - Latitude (WGS84)
     * @param {number} lng - Longitude (WGS84)
     * @param {number} [threshold] - Flow accumulation threshold [m2] (optional)
     * @returns {Promise<Object>} { mode, stream, watershed, upstream_segment_indices, display_threshold_m2 }
     */
    async function delineateWatershed(lat, lng, threshold) {
        var key = _cacheKey('dw', lat, lng, threshold || 0);
        var cached = _cacheGet(key);
        if (cached) return cached;

        var body = {
            latitude: lat,
            longitude: lng,
        };
        if (threshold) {
            body.threshold_m2 = threshold;
        }

        var url = '/api/delineate-watershed?include_hypsometric_curve=true';
        const response = await apiFetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (!response.ok) await handleError(response);
        var data = await response.json();
        _cacheSet(key, data);
        return data;
    }

    /**
     * Sub-catchments a precomputed delineation will merge, one feature per BFS
     * depth from the outlet, for the animation while it is computed.
     *
     * @param {number} lat - Latitude (WGS84)
     * @param {number} lng - Longitude (WGS84)
     * @param {number} threshold - Flow accumulation threshold [m2]
     * @returns {Promise<Object>} { threshold_m2, segment_count, catchments }
     */
    async function previewWatershed(lat, lng, threshold) {
        const response = await apiFetch('/api/delineate-watershed/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ latitude: lat, longitude: lng, threshold_m2: threshold }),
        });

        if (!response.ok) await handleError(response);
        return response.json();
    }

    /**
     * What Hydrograf knows at a point (mode "Identyfikuj").
     *
     * @param {number} lat - Latitude (WGS84)
     * @param {number} lng - Longitude (WGS84)
     * @param {number} threshold - Flow accumulation threshold of the flow lines [m2]
     * @param {Array<string>} resultIds - Analysis results on the map whose water is read
     * @returns {Promise<Object>} { coordinates, elevation_m, slope_percent, water, stream,
     *     water_body, land_cover, soil_hsg, depression, subcatchment }
     */
    async function identifyPoint(lat, lng, threshold, resultIds) {
        var ids = resultIds || [];
        var key = _cacheKey('ip', lat, lng, threshold, ids.join('|'));
        var cached = _cacheGet(key);
        if (cached) return cached;

        const params = new URLSearchParams({ latitude: lat, longitude: lng });
        if (threshold !== undefined && threshold !== null) params.set('threshold_m2', threshold);
        ids.forEach(function (id) { params.append('result_ids', id); });
        const response = await apiFetch('/api/identify-point?' + params.toString());

        if (!response.ok) await handleError(response);
        var data = await response.json();
        _cacheSet(key, data);
        return data;
    }

    /**
     * Submit user feedback.
     *
     * @param {Object} payload - { message, contact, page_url, diagnostics }
     * @returns {Promise<Object>} { id, status }
     */
    async function submitFeedback(payload) {
        const response = await apiFetch('/api/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!response.ok) await handleError(response);
        return response.json();
    }

    window.Hydrograf.api = {
        getTerrainProfile: getTerrainProfile,
        generateHydrograph: generateHydrograph,
        getScenarios: getScenarios,
        getLayers: getLayers,
        getDepressions: getDepressions,
        delineateWatershed: delineateWatershed,
        previewWatershed: previewWatershed,
        identifyPoint: identifyPoint,
        submitFeedback: submitFeedback,
    };
})();
