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

                // Add to layers panel — "Warstwy podkładowe" group
                if (Hydrograf.layers) {
                    var overlayGroup = document.getElementById('overlay-group-entries')
                        || document.getElementById('layers-list');
                    if (overlayGroup) {
                        Hydrograf.layers.addOverlayEntry(
                            overlayGroup,
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

            // Disable filter inputs and show loading cursor during fetch
            var filterInputs = [volMinEl, volMaxEl, areaMinEl, areaMaxEl];
            filterInputs.forEach(function (el) { el.disabled = true; });
            if (Hydrograf.map && Hydrograf.map.setLoadingCursor) {
                Hydrograf.map.setLoadingCursor(true);
            }

            fetchFiltered(minVol, maxVol, minArea, maxArea).then(function (geojson) {
                // Clear old layer
                if (geojsonLayer) {
                    Hydrograf.map._getMap().removeLayer(geojsonLayer);
                }

                geojsonLayer = L.geoJSON(geojson, {
                    style: function (feature) {
                        var vol = feature.properties.volume_m3 || 0;
                        var fillColor, fillOpacity;
                        if (vol < 1)         { fillColor = '#ffffb2'; fillOpacity = 0.5; }
                        else if (vol < 10)   { fillColor = '#fecc5c'; fillOpacity = 0.6; }
                        else if (vol < 100)  { fillColor = '#fd8d3c'; fillOpacity = 0.65; }
                        else if (vol < 1000) { fillColor = '#f03b20'; fillOpacity = 0.7; }
                        else                 { fillColor = '#bd0026'; fillOpacity = 0.8; }
                        return {
                            color: fillColor,
                            weight: 1,
                            fillColor: fillColor,
                            fillOpacity: fillOpacity,
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
            }).finally(function () {
                filterInputs.forEach(function (el) { el.disabled = false; });
                if (Hydrograf.map && Hydrograf.map.setLoadingCursor) {
                    Hydrograf.map.setLoadingCursor(false);
                }
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
