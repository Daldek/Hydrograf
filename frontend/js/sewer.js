/**
 * Sewer network overlay layer for Leaflet map.
 * Renders MVT tiles with sewer lines and nodes.
 */
(function () {
    'use strict';

    var sewerLayer = null;

    // Colours of the current theme from tokens.css (reset on theme change)
    var palette = null;

    function colors() {
        if (!palette) {
            var token = Hydrograf.map.token;
            palette = {
                line: token('--text-2'),
                node: token('--text-3'),
                inlet: token('--info'),
                outlet: token('--bad'),
                ring: token('--surface'),
            };
        }
        return palette;
    }

    // Vector tiles take their style when drawn: redraw if on the map
    Hydrograf.map.onThemeChange(function () {
        palette = null;
        var map = Hydrograf.map._getMap();
        if (sewerLayer && map && map.hasLayer(sewerLayer)) sewerLayer.redraw();
    });

    function createSewerLayer() {
        if (typeof L.vectorGrid === 'undefined') {
            console.warn('Leaflet.VectorGrid not available — sewer layer disabled');
            return null;
        }

        return L.vectorGrid.protobuf('/api/tiles/sewer/{z}/{x}/{y}.pbf', {
            vectorTileLayerStyles: {
                sewer_lines: function () {
                    return {
                        weight: 2,
                        color: colors().line,
                        opacity: 0.8,
                    };
                },
                sewer_nodes: function (properties) {
                    var c = colors();
                    var color = c.node;
                    if (properties.node_type === 'inlet') color = c.inlet;
                    if (properties.node_type === 'outlet') color = c.outlet;
                    return {
                        radius: 4,
                        fillColor: color,
                        fillOpacity: 0.9,
                        color: c.ring,
                        weight: 1,
                    };
                },
            },
            maxZoom: 20,
            minZoom: 10,
            interactive: true,
        });
    }

    function getSewerLayer() {
        if (!sewerLayer) {
            sewerLayer = createSewerLayer();
        }
        return sewerLayer;
    }

    window.Hydrograf = window.Hydrograf || {};
    window.Hydrograf.sewer = {
        getLayer: getSewerLayer,
    };
})();
