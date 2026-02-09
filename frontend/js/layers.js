/**
 * Hydrograf Layers module.
 *
 * Accordion-style layers panel with groups, base layer switching,
 * and per-layer settings (opacity, zoom-to-extent).
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var currentBaseLayer = null;
    var baseLayers = {};

    /**
     * Create a group header element.
     */
    function createGroupHeader(label) {
        var div = document.createElement('div');
        div.className = 'layer-group-header';
        div.textContent = label;
        return div;
    }

    /**
     * Create a base layer radio entry.
     */
    function createBaseLayerEntry(list, name, label, tileLayerFn) {
        var item = document.createElement('div');
        item.className = 'layer-item';
        var headerRow = document.createElement('div');
        headerRow.className = 'layer-header';
        var radio = document.createElement('input');
        radio.type = 'radio';
        radio.name = 'base-layer';
        radio.value = name;
        var text = document.createTextNode(' ' + label);
        headerRow.appendChild(radio);
        headerRow.appendChild(text);
        item.appendChild(headerRow);

        radio.addEventListener('change', function () {
            if (radio.checked) {
                setBaseLayer(name);
            }
        });

        // Check OSM by default
        if (name === 'osm') {
            radio.checked = true;
        }

        baseLayers[name] = tileLayerFn;
        list.appendChild(item);
    }

    /**
     * Switch base layer.
     */
    function setBaseLayer(name) {
        var map = Hydrograf.map._getMap();
        if (!map) return;

        if (currentBaseLayer) {
            map.removeLayer(currentBaseLayer);
        }

        var factory = baseLayers[name];
        if (factory) {
            currentBaseLayer = factory();
            currentBaseLayer.addTo(map);
            currentBaseLayer.bringToBack();
        }
    }

    /**
     * Create an overlay layer entry with checkbox, zoom, and opacity slider.
     */
    function addOverlayEntry(list, label, getLayer, fitBounds, setOpacity, defaultTransparency) {
        var item = document.createElement('div');
        item.className = 'layer-item';

        var headerRow = document.createElement('div');
        headerRow.className = 'layer-header';
        var cb = document.createElement('input');
        cb.type = 'checkbox';
        var text = document.createTextNode(' ' + label);
        var zoomBtn = document.createElement('button');
        zoomBtn.className = 'layer-zoom-btn';
        zoomBtn.title = 'Przybliż do zasięgu';
        zoomBtn.textContent = '\u2316';
        zoomBtn.addEventListener('click', function () { fitBounds(); });
        headerRow.appendChild(cb);
        headerRow.appendChild(text);
        headerRow.appendChild(zoomBtn);
        item.appendChild(headerRow);

        // Opacity slider
        var sliderRow = document.createElement('div');
        sliderRow.className = 'layer-opacity d-none';
        var sliderLabel = document.createElement('span');
        sliderLabel.textContent = 'Przezr.:';
        var slider = document.createElement('input');
        slider.type = 'range';
        slider.min = '0';
        slider.max = '100';
        slider.value = String(defaultTransparency);
        var sliderValue = document.createElement('span');
        sliderValue.className = 'layer-opacity-val';
        sliderValue.textContent = defaultTransparency + '%';
        slider.addEventListener('input', function () {
            var opacity = (100 - slider.value) / 100;
            setOpacity(opacity);
            sliderValue.textContent = slider.value + '%';
        });
        sliderRow.appendChild(sliderLabel);
        sliderRow.appendChild(slider);
        sliderRow.appendChild(sliderValue);
        item.appendChild(sliderRow);

        cb.addEventListener('change', function () {
            var layer = getLayer();
            if (!layer) return;
            if (cb.checked) {
                layer.addTo(Hydrograf.map._getMap());
                sliderRow.classList.remove('d-none');
            } else {
                Hydrograf.map._getMap().removeLayer(layer);
                sliderRow.classList.add('d-none');
            }
        });

        list.appendChild(item);
    }

    /**
     * Initialize the layers panel.
     */
    function init() {
        var list = document.getElementById('layers-list');
        if (!list) return;

        // ===== Base layers =====
        list.appendChild(createGroupHeader('Podkłady kartograficzne'));

        createBaseLayerEntry(list, 'osm', 'OpenStreetMap', function () {
            return L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
                maxZoom: 19,
            });
        });

        createBaseLayerEntry(list, 'esri', 'Ortofotomapa (ESRI)', function () {
            return L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                attribution: '&copy; Esri, Maxar, Earthstar Geographics',
                maxZoom: 19,
            });
        });

        createBaseLayerEntry(list, 'topo', 'OpenTopoMap', function () {
            return L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; <a href="https://opentopomap.org">OpenTopoMap</a>',
                maxZoom: 17,
            });
        });

        // Set initial base layer
        setBaseLayer('osm');

        // ===== Overlay layers =====
        list.appendChild(createGroupHeader('Warstwy podkładowe'));

        addOverlayEntry(
            list,
            'NMT (wysokości)',
            Hydrograf.map.getDemLayer,
            Hydrograf.map.fitDemBounds,
            Hydrograf.map.setDemOpacity,
            30
        );

        addOverlayEntry(
            list,
            'Cieki (Strahler)',
            Hydrograf.map.getStreamsLayer,
            Hydrograf.map.fitStreamsBounds,
            Hydrograf.map.setStreamsOpacity,
            0
        );

        // ===== Analysis results group =====
        list.appendChild(createGroupHeader('Wyniki analiz'));

        addOverlayEntry(
            list,
            'Zlewnia',
            Hydrograf.map.getWatershedLayer,
            function () {
                var layer = Hydrograf.map.getWatershedLayer();
                if (layer) {
                    Hydrograf.map._getMap().fitBounds(layer.getBounds(), { padding: [20, 20] });
                }
            },
            function (opacity) {
                var layer = Hydrograf.map.getWatershedLayer();
                if (layer) {
                    layer.setStyle({ fillOpacity: opacity * 0.5, opacity: opacity });
                }
            },
            0
        );

        // Depressions entry will be added by depressions.js if available
    }

    window.Hydrograf.layers = {
        init: init,
        addOverlayEntry: addOverlayEntry,
        createGroupHeader: createGroupHeader,
    };
})();
