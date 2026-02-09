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
     * Delineate watershed for given coordinates.
     *
     * @param {number} lat - Latitude (WGS84)
     * @param {number} lng - Longitude (WGS84)
     * @returns {Promise<Object>} Watershed response
     * @throws {Error} With Polish user-friendly message
     */
    async function delineateWatershed(lat, lng) {
        const response = await fetch('/api/delineate-watershed', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ latitude: lat, longitude: lng }),
        });

        if (!response.ok) {
            let message = ERROR_MESSAGES[response.status];
            if (!message) {
                message = 'Nieoczekiwany błąd (' + response.status + '). Spróbuj ponownie.';
            }

            // Try to extract detail from API response
            if (response.status === 404) {
                try {
                    const data = await response.json();
                    if (data.detail) {
                        message = data.detail;
                    }
                } catch {
                    // Use default message
                }
            }

            throw new Error(message);
        }

        return response.json();
    }

    /**
     * Check system health.
     *
     * @returns {Promise<Object>} Health response
     */
    async function checkHealth() {
        const response = await fetch('/health');
        if (!response.ok) {
            throw new Error('System niedostępny');
        }
        return response.json();
    }

    window.Hydrograf.api = {
        delineateWatershed: delineateWatershed,
        checkHealth: checkHealth,
    };
})();
