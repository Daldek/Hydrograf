/**
 * Hydrograf Profile module.
 *
 * Terrain profile via manual line drawing on the map.
 * Renders in the profile drawer at the bottom of the map (#profile-drawer).
 * Hover over chart shows corresponding point on the map line.
 * Analysis results with a water level that are shown on the map add their
 * water surface where the line crosses them (results.js, API result_ids);
 * the provider lines of the water it shows (from the response) go to the view's
 * strip while the drawer is open (attribution.js).
 * Samples off the DEM (API dem_gaps) are gaps of the chart, left out of the
 * elevation range; a line wholly off the DEM gets a message instead.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    // Store drawn line coords (lat/lng pairs) for hover interpolation
    var _lineLatLngs = null;

    // Number of the latest profile request; answers to older ones are dropped
    var _request = 0;

    /**
     * Show a notice above the profile chart: a warning about the line, or
     * (error) why there is no profile.
     */
    function showProfileNotice(text, error) {
        var canvas = document.getElementById('chart-profile-standalone');
        if (!canvas) return;
        var container = canvas.parentElement;
        clearProfileNotice();
        var note = document.createElement('p');
        note.className = 'notice warn profile-notice';
        note.setAttribute('role', error ? 'alert' : 'status');
        var textSpan = document.createElement('span');
        textSpan.textContent = text;
        note.appendChild(textSpan);
        container.parentElement.insertBefore(note, container);
    }

    function clearProfileNotice() {
        var drawer = document.getElementById('profile-drawer');
        var existing = drawer && drawer.querySelector('.profile-notice');
        if (existing) existing.remove();
    }

    /** Text for a failed profile request, by the reason of the API problem. */
    function profileErrorText(err) {
        var problem = err && err.problem;
        var reason = problem && problem.details && problem.details.reason;
        if (reason === 'no_elevation_data') {
            return 'Linia leży poza zasięgiem NMT: brak danych wysokościowych.';
        }
        if (reason === 'dem_unavailable') {
            return 'NMT niedostępny: profil terenu wymaga wgranych danych wysokościowych.';
        }
        // Another API problem has its own Polish text; a network failure does not
        return problem ? err.message : 'Nie udało się pobrać profilu terenu.';
    }

    /** Elevations of the profile with null where the DEM has no data (a gap). */
    function terrainLine(result) {
        var gaps = result.dem_gaps || [];
        return result.elevations_m.map(function (h, i) { return gaps[i] ? null : h; });
    }

    /** Drawer subtitle: line length and elevation range of the samples with DEM data. */
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
     * Water surface of each shown result the line crosses, for the chart:
     * [{ title, levels }] with a level only where it lies above the terrain.
     */
    function waterSeries(result, shown, elevations) {
        return (result.water_levels || []).map(function (wl) {
            var source = shown.filter(function (r) { return r.id === wl.result_id; })[0];
            var levels = wl.levels_m.map(function (level, i) {
                return level !== null && elevations[i] !== null && level > elevations[i] ? level : null;
            });
            var wet = levels.some(function (level) { return level !== null; });
            return source && wet ? { title: source.title, levels: levels } : null;
        }).filter(Boolean);
    }

    /** The provider lines of the water the chart shows (`result`, the response, or null) to the view's strip. */
    function showProviderLines(result) {
        Hydrograf.attribution.show('profile', result);
    }

    function clearProviderLines() {
        Hydrograf.attribution.show('profile', null);
    }

    /**
     * Fetch the profile of the drawn line, with the water level of the results
     * shown on the map, and render it in the profile drawer (#profile-drawer).
     */
    function loadProfile() {
        var request = ++_request;
        var shown = Hydrograf.results ? Hydrograf.results.shownWaterLevels() : [];

        // Build GeoJSON line (lon, lat order)
        var lineGeojson = {
            type: 'LineString',
            coordinates: _lineLatLngs.map(function (c) { return [c[1], c[0]]; }),
        };
        var ids = shown.map(function (r) { return r.id; });

        Hydrograf.api.getTerrainProfile(lineGeojson, 100, ids).then(function (result) {
            // A newer line, a redraw or a closed drawer took its place
            if (request !== _request) return;
            // Ensure drawer is visible BEFORE rendering the chart
            var drawer = document.getElementById('profile-drawer');
            if (drawer) drawer.hidden = false;
            var elevations = terrainLine(result);
            var gaps = elevations.filter(function (h) { return h === null; }).length;
            clearProfileNotice();
            if (gaps) {
                showProfileNotice('Część linii (' + Math.round(100 * gaps / elevations.length) +
                    '% próbek) leży poza zasięgiem NMT: wykres ma tam przerwę.', false);
            }
            setProfileSummary(result.distances_m, elevations);
            var water = waterSeries(result, shown, elevations);
            Hydrograf.charts.renderProfileChart(
                'chart-profile-standalone',
                result.distances_m,
                elevations,
                onChartHover,
                onChartHoverEnd,
                water
            );
            showProviderLines(water.length ? result : null);

            // Resize after render to ensure correct dimensions
            setTimeout(function () {
                if (Hydrograf.charts) Hydrograf.charts.resizeChart('chart-profile-standalone');
            }, 50);
        }).catch(function (err) {
            if (request !== _request) return;
            console.warn('Profile error:', err.message);
            var drawer = document.getElementById('profile-drawer');
            if (drawer) drawer.hidden = false;
            setProfileSummary(null, null);
            // No chart of an earlier line under the message
            Hydrograf.charts.destroyChart('chart-profile-standalone');
            showProviderLines(null);
            showProfileNotice(profileErrorText(err), true);
        });
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
            loadProfile();
        });
    }

    /**
     * Draw the open profile again: a result with a water level was turned on
     * or off in the "Warstwy" panel.
     */
    function refresh() {
        var drawer = document.getElementById('profile-drawer');
        if (_lineLatLngs && drawer && !drawer.hidden) loadProfile();
    }

    /**
     * Hide profile drawer, clear drawn line, destroy standalone chart.
     */
    function hideProfilePanel() {
        var drawer = document.getElementById('profile-drawer');
        if (drawer) drawer.hidden = true;
        clearProfileNotice();
        Hydrograf.map.cancelDrawing();
        Hydrograf.map.clearProfileLine();
        Hydrograf.map.clearProfileHoverMarker();
        Hydrograf.charts.destroyChart('chart-profile-standalone');
        clearProviderLines();
        _lineLatLngs = null;
        _request++;
    }

    /**
     * Deactivate profile and clean up.
     */
    function deactivateProfile() {
        Hydrograf.map.cancelDrawing();
        Hydrograf.map.clearProfileLine();
        Hydrograf.map.clearProfileHoverMarker();
        Hydrograf.charts.destroyChart('chart-profile-standalone');
        clearProviderLines();
        _lineLatLngs = null;
        _request++;
    }

    function init() {
        // No buttons to bind — drawing is activated via mode toolbar
    }

    window.Hydrograf.profile = {
        init: init,
        activateDrawProfile: activateDrawProfile,
        deactivateProfile: deactivateProfile,
        hideProfilePanel: hideProfilePanel,
        refresh: refresh,
        getLineLatLngs: function () { return _lineLatLngs; },
    };
})();
