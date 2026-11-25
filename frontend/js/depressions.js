/**
 * Hydrograf Depressions module (Blue Spots).
 *
 * Loads the depression overlay (a static image) into the layers panel.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var added = false;

    /** The image on the map, hidden, unless it is there; whether it is. */
    function addImage(bounds) {
        return Hydrograf.map.ready.then(function (shown) {
            if (!shown) return false;
            if (!added) {
                Hydrograf.map.showImage('depressions', {
                    url: '/data/depressions.png',
                    bounds: bounds,
                    opacity: 0.7,
                    attribution: 'Zagłębienia (blue spots)',
                    shown: false,
                });
                added = true;
            }
            return true;
        });
    }

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
                // [[south, west], [north, east]] of the metadata
                var bounds = [meta.bounds[0][1], meta.bounds[0][0], meta.bounds[1][1], meta.bounds[1][0]];

                // Add to layers panel — "Warstwy podkładowe" group; the depressions
                // of the NMT put its line into the view's strip while on (DEV §20)
                if (Hydrograf.layers) {
                    var overlayGroup = document.getElementById('overlay-group-entries')
                        || document.getElementById('layers-list');
                    if (overlayGroup) {
                        Hydrograf.layers.addOverlayEntry(
                            overlayGroup,
                            'Zagłębienia',
                            {
                                id: 'depressions',
                                load: function () { return addImage(bounds); },
                                bounds: function () { return bounds; },
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
