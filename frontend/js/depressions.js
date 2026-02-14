/**
 * Hydrograf Depressions module (Blue Spots).
 *
 * Loads depression overlay and provides SCALGO-style dual sliders
 * for filtering by volume and area.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var depressionsOverlay = null;
    var depressionsBounds = null;
    var geojsonLayer = null;
    var debounceTimer = null;

    /**
     * Load depressions overlay from static files.
     */
    function loadOverlay() {
        fetch('/data/depressions.json')
            .then(function (res) {
                if (!res.ok) throw new Error('Depressions metadata not found');
                return res.json();
            })
            .then(function (meta) {
                depressionsBounds = L.latLngBounds(meta.bounds);
                depressionsOverlay = L.imageOverlay('/data/depressions.png', depressionsBounds, {
                    opacity: 0.7,
                    attribution: 'Zagłębienia (blue spots)',
                });

                // Add to layers panel if available
                if (Hydrograf.layers) {
                    var list = document.getElementById('layers-list');
                    if (list) {
                        Hydrograf.layers.addOverlayEntry(
                            list,
                            'Zagłębienia',
                            function () { return depressionsOverlay; },
                            function () {
                                if (depressionsBounds) {
                                    Hydrograf.map._getMap().fitBounds(depressionsBounds, { padding: [20, 20] });
                                }
                            },
                            function (opacity) {
                                if (depressionsOverlay) depressionsOverlay.setOpacity(opacity);
                            },
                            30
                        );
                    }
                }
            })
            .catch(function (err) {
                console.debug('Depressions overlay not available:', err.message);
            });
    }

    /**
     * Fetch filtered depressions as GeoJSON from the API.
     */
    async function fetchFiltered(minVol, maxVol, minArea, maxArea) {
        var result = await Hydrograf.api.getDepressions({
            min_volume: minVol,
            max_volume: maxVol,
            min_area: minArea,
            max_area: maxArea,
        });
        return result;
    }

    /**
     * Update display after slider change (debounced).
     */
    function updateDisplay() {
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
            // Read slider values (if they exist)
            var volMinEl = document.getElementById('dep-vol-min');
            var volMaxEl = document.getElementById('dep-vol-max');
            var areaMinEl = document.getElementById('dep-area-min');
            var areaMaxEl = document.getElementById('dep-area-max');
            if (!volMinEl || !volMaxEl || !areaMinEl || !areaMaxEl) return;

            var minVol = parseFloat(volMinEl.value || '0');
            var maxVol = parseFloat(volMaxEl.value || '999999');
            var minArea = parseFloat(areaMinEl.value || '100');
            var maxArea = parseFloat(areaMaxEl.value || '999999');

            fetchFiltered(minVol, maxVol, minArea, maxArea).then(function (geojson) {
                // Clear old layer
                if (geojsonLayer) {
                    Hydrograf.map._getMap().removeLayer(geojsonLayer);
                }

                geojsonLayer = L.geoJSON(geojson, {
                    style: function (feature) {
                        var depth = feature.properties.max_depth_m || 0;
                        var opacity = Math.min(0.8, 0.3 + depth * 0.5);
                        return {
                            color: '#4169E1',
                            weight: 1,
                            fillColor: '#4169E1',
                            fillOpacity: opacity,
                        };
                    },
                    onEachFeature: function (feature, layer) {
                        var p = feature.properties;
                        layer.bindTooltip(
                            'V: ' + p.volume_m3.toFixed(1) + ' m³<br>' +
                            'A: ' + p.area_m2.toFixed(0) + ' m²<br>' +
                            'Głęb. max: ' + p.max_depth_m.toFixed(2) + ' m',
                            { direction: 'top' }
                        );
                    },
                }).addTo(Hydrograf.map._getMap());

                // Update count
                var countEl = document.getElementById('dep-count');
                if (countEl) {
                    var count = geojson.features ? geojson.features.length : 0;
                    countEl.textContent = count + ' zagłębień';
                }
            }).catch(function (err) {
                console.debug('Depression filter error:', err.message);
            });
        }, 300);
    }

    function init() {
        loadOverlay();
    }

    window.Hydrograf.depressions = {
        init: init,
        loadOverlay: loadOverlay,
        fetchFiltered: fetchFiltered,
        updateDisplay: updateDisplay,
    };
})();
