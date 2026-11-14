/**
 * Hydrograf Depressions module (Blue Spots).
 *
 * Loads the depression overlay (a static image) into the layers panel.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var depressionsOverlay = null;
    var depressionsBounds = null;

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

                // Add to layers panel — "Warstwy podkładowe" group; the depressions
                // of the NMT put its line into the view's strip while on (DEV §20)
                if (Hydrograf.layers) {
                    var overlayGroup = document.getElementById('overlay-group-entries')
                        || document.getElementById('layers-list');
                    if (overlayGroup) {
                        Hydrograf.layers.addOverlayEntry(
                            overlayGroup,
                            'Zagłębienia',
                            function () { return depressionsOverlay; },
                            function () { return depressionsBounds; },
                            function (opacity) {
                                if (depressionsOverlay) depressionsOverlay.setOpacity(opacity);
                            },
                            30,
                            null,
                            null,
                            'elevation'
                        );
                    }
                }
            })
            .catch(function (err) {
                console.debug('Depressions overlay not available:', err.message);
            });
    }

    function init() {
        loadOverlay();
    }

    window.Hydrograf.depressions = {
        init: init,
    };
})();
