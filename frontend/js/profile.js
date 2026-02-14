/**
 * Hydrograf Profile module.
 *
 * Terrain profile in two modes: auto (main stream) and manual line drawing.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    /**
     * Show an inline error message near the profile chart canvas.
     */
    function showProfileError(message) {
        var canvas = document.getElementById('chart-profile');
        if (!canvas) return;
        var container = canvas.parentElement;
        // Remove any existing profile error alert
        var existing = container.querySelector('.profile-error-alert');
        if (existing) existing.remove();
        // Determine message based on error content
        var isDemError = /503|DEM|dane wysoko/.test(message);
        var text = isDemError
            ? 'DEM niedostępny — profil terenu wymaga wgranych danych wysokościowych'
            : 'Nie udało się pobrać profilu terenu';
        var alertDiv = document.createElement('div');
        alertDiv.className = 'alert alert-warning alert-dismissible small py-1 px-2 mb-1 profile-error-alert';
        alertDiv.setAttribute('role', 'alert');
        alertDiv.innerHTML = text +
            '<button type="button" class="btn-close btn-close-sm" style="padding:0.15rem 0.25rem;font-size:0.65rem;" aria-label="Zamknij"></button>';
        alertDiv.querySelector('.btn-close').addEventListener('click', function () {
            alertDiv.remove();
        });
        container.insertBefore(alertDiv, canvas);
    }

    /**
     * Activate auto-profile using main stream geometry from watershed response.
     */
    async function activateAutoProfile() {
        var data = Hydrograf.app.getCurrentWatershed();
        if (!data || !data.watershed.main_stream_geojson) return;

        var lineGeojson = data.watershed.main_stream_geojson;

        try {
            var result = await Hydrograf.api.getTerrainProfile(lineGeojson, 100);
            Hydrograf.charts.renderProfileChart(
                'chart-profile',
                result.distances_m,
                result.elevations_m
            );
            Hydrograf.map.showProfileLine(lineGeojson.coordinates);
        } catch (err) {
            console.warn('Profile error:', err.message);
            showProfileError(err.message);
        }
    }

    /**
     * Activate draw-profile mode.
     */
    function activateDrawProfile() {
        deactivateProfile();

        Hydrograf.map.startDrawing(function (coords) {
            // Drawing complete
            var lineGeojson = {
                type: 'LineString',
                coordinates: coords.map(function (c) { return [c[1], c[0]]; }),
            };

            Hydrograf.api.getTerrainProfile(lineGeojson, 100).then(function (result) {
                Hydrograf.charts.renderProfileChart(
                    'chart-profile',
                    result.distances_m,
                    result.elevations_m
                );
            }).catch(function (err) {
                console.warn('Profile error:', err.message);
                showProfileError(err.message);
            });
        });
    }

    /**
     * Deactivate profile and clean up.
     */
    function deactivateProfile() {
        Hydrograf.map.cancelDrawing();
        Hydrograf.map.clearProfileLine();
        Hydrograf.charts.destroyChart('chart-profile');
    }

    function init() {
        var btnAuto = document.getElementById('btn-profile-auto');
        var btnDraw = document.getElementById('btn-profile-draw');

        if (btnAuto) {
            btnAuto.addEventListener('click', activateAutoProfile);
        }
        if (btnDraw) {
            btnDraw.addEventListener('click', activateDrawProfile);
        }
    }

    window.Hydrograf.profile = {
        init: init,
        activateAutoProfile: activateAutoProfile,
        activateDrawProfile: activateDrawProfile,
        deactivateProfile: deactivateProfile,
    };
})();
