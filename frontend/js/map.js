/**
 * Hydrograf Map module.
 *
 * Manages Leaflet map, watershed polygon, and outlet marker.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var map = null;
    var layerControl = null;
    var watershedLayer = null;
    var outletMarker = null;
    var clickEnabled = true;

    /**
     * Initialize the Leaflet map.
     *
     * @param {Function} onClickCallback - Called with (lat, lng) on map click
     */
    function init(onClickCallback) {
        map = L.map('map', {
            center: [51.9, 19.5],
            zoom: 7,
            zoomControl: true,
        });

        var osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
            maxZoom: 19,
        }).addTo(map);

        layerControl = L.control.layers(
            { 'OpenStreetMap': osm },
            {},
            { position: 'topright', collapsed: true }
        ).addTo(map);

        map.on('click', function (e) {
            if (!clickEnabled) return;
            if (onClickCallback) {
                onClickCallback(e.latlng.lat, e.latlng.lng);
            }
        });
    }

    /**
     * Display watershed boundary polygon on the map.
     *
     * @param {Object} geojsonFeature - GeoJSON Feature (Polygon)
     */
    function showWatershed(geojsonFeature) {
        clearWatershed();

        watershedLayer = L.geoJSON(geojsonFeature, {
            style: {
                color: '#28A745',
                weight: 2,
                fillColor: '#28A745',
                fillOpacity: 0.3,
            },
        }).addTo(map);

        map.fitBounds(watershedLayer.getBounds(), { padding: [20, 20] });
    }

    /**
     * Display outlet point marker.
     *
     * @param {number} lat - Latitude
     * @param {number} lng - Longitude
     * @param {number} elevation - Elevation in meters
     */
    function showOutlet(lat, lng, elevation) {
        if (outletMarker) {
            map.removeLayer(outletMarker);
        }

        outletMarker = L.circleMarker([lat, lng], {
            radius: 7,
            color: '#DC3545',
            fillColor: '#DC3545',
            fillOpacity: 0.8,
            weight: 2,
        }).addTo(map);

        outletMarker.bindTooltip(
            'Ujście: ' + elevation.toFixed(1) + ' m n.p.m.',
            { permanent: false, direction: 'top' }
        );
    }

    /**
     * Remove watershed polygon and outlet marker from map.
     */
    function clearWatershed() {
        if (watershedLayer) {
            map.removeLayer(watershedLayer);
            watershedLayer = null;
        }
        if (outletMarker) {
            map.removeLayer(outletMarker);
            outletMarker = null;
        }
    }

    /**
     * Disable map click events (during loading).
     */
    function disableClick() {
        clickEnabled = false;
    }

    /**
     * Enable map click events.
     */
    function enableClick() {
        clickEnabled = true;
    }

    /**
     * Get the layer control instance (for adding overlays externally).
     *
     * @returns {L.Control.Layers|null}
     */
    function getLayerControl() {
        return layerControl;
    }

    window.Hydrograf.map = {
        init: init,
        showWatershed: showWatershed,
        showOutlet: showOutlet,
        clearWatershed: clearWatershed,
        disableClick: disableClick,
        enableClick: enableClick,
        getLayerControl: getLayerControl,
    };
})();
