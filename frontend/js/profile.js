/**
 * Hydrograf Profile module.
 *
 * Terrain profile in two modes: auto (main stream) and manual line drawing.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

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
            alert('Błąd profilu: ' + err.message);
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
                alert('Błąd profilu: ' + err.message);
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
