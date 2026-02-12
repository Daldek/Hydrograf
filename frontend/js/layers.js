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
     * Switch base layer. Pass 'none' to disable all base layers.
     */
    function setBaseLayer(name) {
        var map = Hydrograf.map._getMap();
        if (!map) return;

        if (currentBaseLayer) {
            map.removeLayer(currentBaseLayer);
            currentBaseLayer = null;
        }

        if (name === 'none') return;

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
     * Overlay entry for async-loaded layers (BDOT10k GeoJSON).
     * getLayer returns the existing layer, loadLayer returns a Promise.
     */
    function addBdotOverlayEntry(list, label, getLayer, loadLayer, fitBounds, setOpacity, defaultTransparency) {
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
            var mapObj = Hydrograf.map._getMap();
            if (cb.checked) {
                var layer = getLayer();
                if (layer) {
                    layer.addTo(mapObj);
                } else {
                    loadLayer().then(function (l) {
                        if (l) l.addTo(mapObj);
                    });
                }
                sliderRow.classList.remove('d-none');
            } else {
                var existing = getLayer();
                if (existing && mapObj.hasLayer(existing)) {
                    mapObj.removeLayer(existing);
                }
                sliderRow.classList.add('d-none');
            }
        });

        list.appendChild(item);
    }

    /**
     * Format threshold value for display (e.g. 10000 → "10 000 m²").
     */
    function formatThreshold(value) {
        return value.toLocaleString('pl-PL') + ' m\u00B2';
    }

    /**
     * Populate a threshold <select> with values from the backend.
     */
    function populateThresholdSelect(select, thresholds) {
        // Clear existing options
        select.innerHTML = '';
        thresholds.forEach(function (t, idx) {
            var opt = document.createElement('option');
            opt.value = t;
            opt.textContent = formatThreshold(t);
            if (idx === 0) opt.selected = true;
            select.appendChild(opt);
        });
    }

    /**
     * Create a streams layer entry with checkbox, threshold selector, and opacity slider.
     */
    function addStreamsEntry(list, availableThresholds) {
        var item = document.createElement('div');
        item.className = 'layer-item';

        // Header row: checkbox + label + zoom button
        var headerRow = document.createElement('div');
        headerRow.className = 'layer-header';
        var cb = document.createElement('input');
        cb.type = 'checkbox';
        var text = document.createTextNode(' Cieki (Strahler)');
        var zoomBtn = document.createElement('button');
        zoomBtn.className = 'layer-zoom-btn';
        zoomBtn.title = 'Przybliż do zasięgu';
        zoomBtn.textContent = '\u2316';
        zoomBtn.addEventListener('click', function () { Hydrograf.map.fitStreamsBounds(); });
        headerRow.appendChild(cb);
        headerRow.appendChild(text);
        headerRow.appendChild(zoomBtn);
        item.appendChild(headerRow);

        // Controls wrapper (hidden until checkbox is on)
        var controlsRow = document.createElement('div');
        controlsRow.className = 'layer-opacity d-none';

        // Threshold selector
        var threshLabel = document.createElement('span');
        threshLabel.textContent = 'Próg FA:';
        var select = document.createElement('select');
        select.className = 'form-select form-select-sm';
        select.style.width = 'auto';
        select.style.display = 'inline-block';
        select.style.marginLeft = '4px';
        select.style.fontSize = '0.75rem';

        populateThresholdSelect(select, availableThresholds);

        select.addEventListener('change', function () {
            var layer = Hydrograf.map.loadStreamsVector(parseInt(select.value));
            if (cb.checked && layer) {
                layer.addTo(Hydrograf.map._getMap());
            }
        });

        controlsRow.appendChild(threshLabel);
        controlsRow.appendChild(select);

        // Opacity slider
        var sliderWrap = document.createElement('div');
        sliderWrap.style.marginTop = '4px';
        var sliderLabel = document.createElement('span');
        sliderLabel.textContent = 'Przezr.:';
        var slider = document.createElement('input');
        slider.type = 'range';
        slider.min = '0';
        slider.max = '100';
        slider.value = '0';
        var sliderValue = document.createElement('span');
        sliderValue.className = 'layer-opacity-val';
        sliderValue.textContent = '0%';
        slider.addEventListener('input', function () {
            var opacity = (100 - parseInt(slider.value)) / 100;
            Hydrograf.map.setStreamsOpacity(opacity);
            sliderValue.textContent = slider.value + '%';
        });
        sliderWrap.appendChild(sliderLabel);
        sliderWrap.appendChild(slider);
        sliderWrap.appendChild(sliderValue);
        controlsRow.appendChild(sliderWrap);
        item.appendChild(controlsRow);

        cb.addEventListener('change', function () {
            var map = Hydrograf.map._getMap();
            var layer;
            if (cb.checked) {
                layer = Hydrograf.map.getStreamsLayer();
                if (!layer) {
                    layer = Hydrograf.map.loadStreamsVector(parseInt(select.value));
                }
                if (layer) layer.addTo(map);
                controlsRow.classList.remove('d-none');
            } else {
                layer = Hydrograf.map.getStreamsLayer();
                if (layer && map.hasLayer(layer)) {
                    map.removeLayer(layer);
                }
                controlsRow.classList.add('d-none');
            }
        });

        list.appendChild(item);
    }

    /**
     * Create a catchments layer entry with checkbox, threshold selector, and opacity slider.
     */
    function addCatchmentsEntry(list, availableThresholds) {
        var item = document.createElement('div');
        item.className = 'layer-item';

        // Header row: checkbox + label + zoom button
        var headerRow = document.createElement('div');
        headerRow.className = 'layer-header';
        var cb = document.createElement('input');
        cb.type = 'checkbox';
        var text = document.createTextNode(' Zlewnie cząstkowe');
        var zoomBtn = document.createElement('button');
        zoomBtn.className = 'layer-zoom-btn';
        zoomBtn.title = 'Przybliż do zasięgu';
        zoomBtn.textContent = '\u2316';
        zoomBtn.addEventListener('click', function () { Hydrograf.map.fitCatchmentsBounds(); });
        headerRow.appendChild(cb);
        headerRow.appendChild(text);
        headerRow.appendChild(zoomBtn);
        item.appendChild(headerRow);

        // Controls wrapper (hidden until checkbox is on)
        var controlsRow = document.createElement('div');
        controlsRow.className = 'layer-opacity d-none';

        // Threshold selector
        var threshLabel = document.createElement('span');
        threshLabel.textContent = 'Próg FA:';
        var select = document.createElement('select');
        select.className = 'form-select form-select-sm';
        select.style.width = 'auto';
        select.style.display = 'inline-block';
        select.style.marginLeft = '4px';
        select.style.fontSize = '0.75rem';

        populateThresholdSelect(select, availableThresholds);

        select.addEventListener('change', function () {
            var layer = Hydrograf.map.loadCatchmentsVector(parseInt(select.value));
            if (cb.checked && layer) {
                layer.addTo(Hydrograf.map._getMap());
            }
        });

        controlsRow.appendChild(threshLabel);
        controlsRow.appendChild(select);

        // Opacity slider
        var sliderWrap = document.createElement('div');
        sliderWrap.style.marginTop = '4px';
        var sliderLabel = document.createElement('span');
        sliderLabel.textContent = 'Przezr.:';
        var slider = document.createElement('input');
        slider.type = 'range';
        slider.min = '0';
        slider.max = '100';
        slider.value = '0';
        var sliderValue = document.createElement('span');
        sliderValue.className = 'layer-opacity-val';
        sliderValue.textContent = '0%';
        slider.addEventListener('input', function () {
            var opacity = (100 - parseInt(slider.value)) / 100;
            Hydrograf.map.setCatchmentsOpacity(opacity);
            sliderValue.textContent = slider.value + '%';
        });
        sliderWrap.appendChild(sliderLabel);
        sliderWrap.appendChild(slider);
        sliderWrap.appendChild(sliderValue);
        controlsRow.appendChild(sliderWrap);
        item.appendChild(controlsRow);

        cb.addEventListener('change', function () {
            var map = Hydrograf.map._getMap();
            var layer;
            if (cb.checked) {
                layer = Hydrograf.map.getCatchmentsLayer();
                if (!layer) {
                    layer = Hydrograf.map.loadCatchmentsVector(parseInt(select.value));
                }
                if (layer) layer.addTo(map);
                controlsRow.classList.remove('d-none');
            } else {
                layer = Hydrograf.map.getCatchmentsLayer();
                if (layer && map.hasLayer(layer)) {
                    map.removeLayer(layer);
                }
                controlsRow.classList.add('d-none');
            }
        });

        list.appendChild(item);
    }

    /** Fallback thresholds if backend is unavailable. */
    var FALLBACK_THRESHOLDS = [100, 1000, 10000, 100000];

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

        createBaseLayerEntry(list, 'none', 'Brak', null);

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

        // BDOT10k water bodies
        addBdotOverlayEntry(
            list,
            'Zbiorniki wodne (BDOT10k)',
            function () { return Hydrograf.map.getBdotLakesLayer(); },
            function () { return Hydrograf.map.loadBdotLakes(); },
            Hydrograf.map.fitBdotBounds,
            Hydrograf.map.setBdotLakesOpacity,
            0
        );

        // BDOT10k streams
        addBdotOverlayEntry(
            list,
            'Cieki BDOT10k',
            function () { return Hydrograf.map.getBdotStreamsLayer(); },
            function () { return Hydrograf.map.loadBdotStreams(); },
            Hydrograf.map.fitBdotBounds,
            Hydrograf.map.setBdotStreamsOpacity,
            0
        );

        // Placeholder for stream/catchment entries (async populated)
        var streamsPlaceholder = document.createElement('div');
        list.appendChild(streamsPlaceholder);

        // ===== Analysis results group =====
        list.appendChild(createGroupHeader('Wyniki analiz'));

        // Fetch available thresholds, then build stream/catchment entries
        fetch('/api/tiles/thresholds')
            .then(function (res) { return res.json(); })
            .then(function (data) {
                var streamsThresholds = data.streams && data.streams.length > 0
                    ? data.streams : FALLBACK_THRESHOLDS;
                var catchmentsThresholds = data.catchments && data.catchments.length > 0
                    ? data.catchments : streamsThresholds;
                addStreamsEntry(streamsPlaceholder, streamsThresholds);
                addCatchmentsEntry(streamsPlaceholder, catchmentsThresholds);
            })
            .catch(function () {
                addStreamsEntry(streamsPlaceholder, FALLBACK_THRESHOLDS);
                addCatchmentsEntry(streamsPlaceholder, FALLBACK_THRESHOLDS);
            });

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
