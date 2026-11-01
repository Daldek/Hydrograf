/**
 * Hydrograf Profile module.
 *
 * Terrain profile via manual line drawing on the map.
 * Renders in the profile drawer at the bottom of the map (#profile-drawer).
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
        clearProfileError();
        var isDemError = /503|DEM|dane wysoko/.test(message);
        var text = isDemError
            ? 'DEM niedostępny — profil terenu wymaga wgranych danych wysokościowych'
            : 'Nie udało się pobrać profilu terenu';
        var alertEl = document.createElement('p');
        alertEl.className = 'notice warn profile-error-alert';
        alertEl.setAttribute('role', 'alert');
        var textSpan = document.createElement('span');
        textSpan.textContent = text;
        alertEl.appendChild(textSpan);
        container.parentElement.insertBefore(alertEl, container);
    }

    function clearProfileError() {
        var drawer = document.getElementById('profile-drawer');
        var existing = drawer && drawer.querySelector('.profile-error-alert');
        if (existing) existing.remove();
    }

    /** Drawer subtitle: line length and elevation range. */
    function setProfileSummary(distances, elevations) {
        var el = document.getElementById('profile-summary');
        if (!el) return;
        var valid = (elevations || []).filter(function (h) { return h !== null && h !== undefined; });
        if (!distances || distances.length === 0 || valid.length === 0) {
            el.textContent = '';
            return;
        }
        var lengthKm = distances[distances.length - 1] / 1000;
        el.textContent = 'Długość ' + lengthKm.toFixed(2) + ' km · H ' +
            Math.min.apply(null, valid).toFixed(0) + '–' +
            Math.max.apply(null, valid).toFixed(0) + ' m n.p.m.';
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
     * Renders result in the profile drawer (#profile-drawer).
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
                // Ensure drawer is visible BEFORE rendering the chart
                var drawer = document.getElementById('profile-drawer');
                if (drawer) drawer.hidden = false;
                clearProfileError();
                setProfileSummary(result.distances_m, result.elevations_m);
                Hydrograf.charts.renderProfileChart(
                    'chart-profile-standalone',
                    result.distances_m,
                    result.elevations_m,
                    onChartHover,
                    onChartHoverEnd
                );

                // Resize after render to ensure correct dimensions
                setTimeout(function () {
                    if (Hydrograf.charts) Hydrograf.charts.resizeChart('chart-profile-standalone');
                }, 50);
            }).catch(function (err) {
                console.warn('Profile error:', err.message);
                var drawer = document.getElementById('profile-drawer');
                if (drawer) drawer.hidden = false;
                setProfileSummary(null, null);
                showProfileError('chart-profile-standalone', err.message || 'Błąd');
            });
        });
    }

    /**
     * Hide profile drawer, clear drawn line, destroy standalone chart.
     */
    function hideProfilePanel() {
        var drawer = document.getElementById('profile-drawer');
        if (drawer) drawer.hidden = true;
        clearProfileError();
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
        getLineLatLngs: function () { return _lineLatLngs; },
    };
})();
