/**
 * Hydrograf Profile module.
 *
 * Terrain profile via manual line drawing on the map.
 * Renders in a standalone floating panel (#profile-panel).
 * Hover over chart shows corresponding point on the map line.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    // Store drawn line coords (lat/lng pairs) for hover interpolation
    var _lineLatLngs = null;

    /**
     * Show an inline error message near the profile chart canvas.
     */
    function showProfileError(canvasId, message) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;
        var container = canvas.parentElement;
        var existing = container.querySelector('.profile-error-alert');
        if (existing) existing.remove();
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
     * Handle chart hover — show marker on map at corresponding position.
     * @param {number} fraction - 0..1 along the line
     */
    function onChartHover(fraction) {
        if (!_lineLatLngs || _lineLatLngs.length < 2) return;

        // Compute cumulative distances between vertices
        var dists = [0];
        for (var i = 1; i < _lineLatLngs.length; i++) {
            var prev = _lineLatLngs[i - 1];
            var cur = _lineLatLngs[i];
            var dlat = cur[0] - prev[0];
            var dlng = cur[1] - prev[1];
            dists.push(dists[i - 1] + Math.sqrt(dlat * dlat + dlng * dlng));
        }
        var totalDist = dists[dists.length - 1];
        if (totalDist === 0) return;

        var targetDist = fraction * totalDist;

        // Find segment
        for (var j = 1; j < dists.length; j++) {
            if (targetDist <= dists[j]) {
                var segFrac = (targetDist - dists[j - 1]) / (dists[j] - dists[j - 1]);
                var lat = _lineLatLngs[j - 1][0] + segFrac * (_lineLatLngs[j][0] - _lineLatLngs[j - 1][0]);
                var lng = _lineLatLngs[j - 1][1] + segFrac * (_lineLatLngs[j][1] - _lineLatLngs[j - 1][1]);
                Hydrograf.map.showProfileHoverMarker(lat, lng);
                return;
            }
        }
        // Edge case: at the very end
        var last = _lineLatLngs[_lineLatLngs.length - 1];
        Hydrograf.map.showProfileHoverMarker(last[0], last[1]);
    }

    /**
     * Handle chart hover end — remove marker from map.
     */
    function onChartHoverEnd() {
        Hydrograf.map.clearProfileHoverMarker();
    }

    /**
     * Activate draw-profile mode.
     * Renders result in the standalone floating panel (#profile-panel).
     */
    function activateDrawProfile() {
        hideProfilePanel();

        Hydrograf.map.startDrawing(function (coords) {
            // coords: [[lat, lng], ...] — store for hover interpolation
            _lineLatLngs = coords;

            // Build GeoJSON line (lon, lat order)
            var lineGeojson = {
                type: 'LineString',
                coordinates: coords.map(function (c) { return [c[1], c[0]]; }),
            };

            Hydrograf.api.getTerrainProfile(lineGeojson, 100).then(function (result) {
                Hydrograf.charts.renderProfileChart(
                    'chart-profile-standalone',
                    result.distances_m,
                    result.elevations_m,
                    onChartHover,
                    onChartHoverEnd
                );

                var panel = document.getElementById('profile-panel');
                if (panel) panel.classList.remove('d-none');
            }).catch(function (err) {
                console.warn('Profile error:', err.message);
                var panel = document.getElementById('profile-panel');
                if (panel) panel.classList.remove('d-none');
                showProfileError('chart-profile-standalone', err.message || 'Błąd');
            });
        });
    }

    /**
     * Hide profile panel, clear drawn line, destroy standalone chart.
     */
    function hideProfilePanel() {
        var panel = document.getElementById('profile-panel');
        if (panel) panel.classList.add('d-none');
        Hydrograf.map.cancelDrawing();
        Hydrograf.map.clearProfileLine();
        Hydrograf.map.clearProfileHoverMarker();
        Hydrograf.charts.destroyChart('chart-profile-standalone');
        _lineLatLngs = null;
    }

    /**
     * Deactivate profile and clean up.
     */
    function deactivateProfile() {
        Hydrograf.map.cancelDrawing();
        Hydrograf.map.clearProfileLine();
        Hydrograf.map.clearProfileHoverMarker();
        Hydrograf.charts.destroyChart('chart-profile-standalone');
        _lineLatLngs = null;
    }

    function init() {
        // No buttons to bind — drawing is activated via mode toolbar
    }

    window.Hydrograf.profile = {
        init: init,
        activateDrawProfile: activateDrawProfile,
        deactivateProfile: deactivateProfile,
        hideProfilePanel: hideProfilePanel,
    };
})();
