/**
 * Hydrograf API client module.
 *
 * Handles communication with the backend API.
 * Uses relative URLs (same-origin via nginx proxy).
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    const ERROR_MESSAGES = {
        400: 'Nieprawidłowe żądanie. Sprawdź współrzędne i spróbuj ponownie.',
        404: 'Nie znaleziono cieku w tym miejscu. Kliknij bliżej linii cieku.',
        429: 'Zbyt wiele żądań. Poczekaj chwilę i spróbuj ponownie.',
        500: 'Błąd serwera. Spróbuj ponownie za chwilę.',
    };

    /**
     * Generic error handler for API responses.
     */
    async function handleError(response) {
        let message = ERROR_MESSAGES[response.status];
        if (!message) {
            message = 'Nieoczekiwany błąd (' + response.status + '). Spróbuj ponownie.';
        }

        if (response.status === 404 || response.status === 400) {
            try {
                const data = await response.json();
                if (data.detail) message = data.detail;
            } catch { /* use default */ }
        }

        throw new Error(message);
    }

    /**
     * Delineate watershed for given coordinates.
     */
    async function delineateWatershed(lat, lng) {
        const response = await fetch('/api/delineate-watershed?include_hypsometric_curve=true', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ latitude: lat, longitude: lng }),
        });

        if (!response.ok) await handleError(response);
        return response.json();
    }

    /**
     * Check system health.
     */
    async function checkHealth() {
        const response = await fetch('/health');
        if (!response.ok) throw new Error('System niedostępny');
        return response.json();
    }

    /**
     * Get terrain profile along a line.
     *
     * @param {Object} lineGeojson - GeoJSON LineString geometry
     * @param {number} nSamples - Number of sample points
     * @returns {Promise<Object>} { distances_m, elevations_m, total_length_m }
     */
    async function getTerrainProfile(lineGeojson, nSamples) {
        const response = await fetch('/api/terrain-profile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ geometry: lineGeojson, n_samples: nSamples || 100 }),
        });

        if (!response.ok) await handleError(response);
        return response.json();
    }

    /**
     * Generate hydrograph for given parameters.
     */
    async function generateHydrograph(lat, lng, duration, probability) {
        const response = await fetch('/api/generate-hydrograph', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                latitude: lat,
                longitude: lng,
                duration: duration,
                probability: probability,
            }),
        });

        if (!response.ok) await handleError(response);
        return response.json();
    }

    /**
     * Get available hydrograph scenarios.
     */
    async function getScenarios() {
        const response = await fetch('/api/scenarios');
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

        const response = await fetch('/api/depressions?' + params.toString());
        if (!response.ok) await handleError(response);
        return response.json();
    }

    window.Hydrograf.api = {
        delineateWatershed: delineateWatershed,
        checkHealth: checkHealth,
        getTerrainProfile: getTerrainProfile,
        generateHydrograph: generateHydrograph,
        getScenarios: getScenarios,
        getDepressions: getDepressions,
    };
})();
