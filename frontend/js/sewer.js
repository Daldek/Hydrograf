/**
 * Sewer network overlay layer for Leaflet map.
 * Renders MVT tiles with sewer lines and nodes.
 */
(function () {
    'use strict';

    var sewerLayer = null;

    function createSewerLayer() {
        if (typeof L.vectorGrid === 'undefined') {
            console.warn('Leaflet.VectorGrid not available — sewer layer disabled');
            return null;
        }

        return L.vectorGrid.protobuf('/api/tiles/sewer/{z}/{x}/{y}.pbf', {
            vectorTileLayerStyles: {
                sewer_lines: function (properties) {
                    return {
                        weight: 2,
                        color: '#6366f1',
                        opacity: 0.8,
                    };
                },
                sewer_nodes: function (properties) {
                    var color = '#94a3b8';
                    if (properties.node_type === 'inlet') color = '#3b82f6';
                    if (properties.node_type === 'outlet') color = '#ef4444';
                    return {
                        radius: 4,
                        fillColor: color,
                        fillOpacity: 0.9,
                        color: '#fff',
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
