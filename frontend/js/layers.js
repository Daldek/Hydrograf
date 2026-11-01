/**
 * Hydrograf Layers module.
 *
 * Layers panel: overlay rows (checkbox, name, opacity slider), base map
 * radio list, and one zoom-to-extent action for all enabled overlays.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var currentBaseLayer = null;
    var baseLayers = {};
    var DEFAULT_BASE_LAYER = 'openfreemap';
    var currentBaseLayerName = DEFAULT_BASE_LAYER;
    var _overlayRegistry = [];
    var _rowCount = 0;

    var GUGIK_OSM_URL = 'https://mapy.geoportal.gov.pl/wss/ext/OSM/BaseMap/wmts/osm_3857/GLOBAL_WEBMERCATOR/{z}/{x}/{y}.png';

    /** GUGiK OSM raster (Poland only), desaturated by the .basemap-grey class. */
    function createGugikOsmLayer() {
        return L.tileLayer(GUGIK_OSM_URL, {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, <a href="https://www.geoportal.gov.pl">GUGiK</a>',
            className: 'basemap-grey',
            maxZoom: 19,
        });
    }

    /** OpenFreeMap vector basemap; falls back to GUGiK when MapLibre is missing. */
    function createOpenFreeMapLayer() {
        if (typeof L.maplibreGL !== 'function') {
            console.warn('MapLibre GL Leaflet not loaded — falling back to OSM GUGiK basemap');
            return createGugikOsmLayer();
        }
        return L.maplibreGL({
            style: 'https://tiles.openfreemap.org/styles/positron',
            attribution: '<a href="https://openfreemap.org">OpenFreeMap</a> &copy; <a href="https://www.openmaptiles.org/">OpenMapTiles</a> Data from <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        });
    }

    function createEsriOrthoLayer() {
        return L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            attribution: '&copy; Esri, Maxar, Earthstar Geographics',
            maxZoom: 19,
        });
    }

    /** Base maps in panel order; `create` null means no base map. */
    var BASEMAPS = [
        { name: 'openfreemap', label: 'OpenFreeMap szary', create: createOpenFreeMapLayer },
        { name: 'gugik-osm', label: 'OSM GUGiK szary (tylko Polska)', create: createGugikOsmLayer },
        { name: 'esri-ortho', label: 'Ortofotomapa ESRI', create: createEsriOrthoLayer },
        { name: 'none', label: 'bez podkładu', create: null },
    ];

    /**
     * Create a panel group (section with a title) and append it to the list.
     * @param {HTMLElement} list - Panel container.
     * @param {string} label - Group title.
     * @returns {HTMLElement} The group section; rows are appended to it.
     */
    function createGroup(list, label) {
        var section = document.createElement('section');
        section.className = 'group';
        var title = document.createElement('h3');
        title.className = 'group-title';
        title.textContent = label;
        section.appendChild(title);
        list.appendChild(section);
        return section;
    }

    /**
     * Build the base map radio list.
     */
    function createBaseLayerList(group) {
        var radioList = document.createElement('div');
        radioList.className = 'radio-list';
        radioList.setAttribute('role', 'radiogroup');
        radioList.setAttribute('aria-label', 'Podkład kartograficzny');

        BASEMAPS.forEach(function (basemap) {
            var lbl = document.createElement('label');
            var radio = document.createElement('input');
            radio.type = 'radio';
            radio.name = 'basemap';
            radio.value = basemap.name;
            radio.checked = basemap.name === DEFAULT_BASE_LAYER;
            radio.addEventListener('change', function () {
                if (radio.checked) setBaseLayer(basemap.name);
            });
            lbl.appendChild(radio);
            lbl.appendChild(document.createTextNode(' ' + basemap.label));
            radioList.appendChild(lbl);
            baseLayers[basemap.name] = basemap.create;
        });

        group.appendChild(radioList);
    }

    /**
     * Switch base layer. Pass 'none' to disable all base layers.
     */
    function setBaseLayer(name) {
        currentBaseLayerName = name;
        if (window.Hydrograf.diagnostics) {
            Hydrograf.diagnostics.log('layer_change', { baseLayer: name });
        }

        var map = Hydrograf.map._getMap();
        if (!map) return;

        if (currentBaseLayer) {
            map.removeLayer(currentBaseLayer);
            currentBaseLayer = null;
        }

        var factory = baseLayers[name];
        if (factory) {
            currentBaseLayer = factory();
            currentBaseLayer.addTo(map);
            // The MapLibre layer has no bringToBack; it sits in tilePane below overlays anyway.
            if (typeof currentBaseLayer.bringToBack === 'function') {
                currentBaseLayer.bringToBack();
            }
        }
    }

    /**
     * Bounds getter for a layer that exposes getBounds() once loaded.
     */
    function layerBounds(getLayer) {
        return function () {
            var layer = getLayer();
            return layer && typeof layer.getBounds === 'function' ? layer.getBounds() : null;
        };
    }

    function noBounds() { return null; }

    /**
     * Build a layer row: checkbox, name, opacity slider and value.
     * The slider shows opacity in percent (100 − transparency).
     */
    function createLayerRow(list, label, setOpacity, defaultTransparency) {
        var id = 'ly-' + (++_rowCount);
        var defaultOpacity = String(100 - defaultTransparency);

        var row = document.createElement('div');
        row.className = 'layer off';

        var cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.id = id;

        var name = document.createElement('label');
        name.className = 'name';
        name.htmlFor = id;
        name.textContent = label;

        var range = document.createElement('input');
        range.type = 'range';
        range.min = '0';
        range.max = '100';
        range.value = defaultOpacity;
        range.setAttribute('aria-label', 'Krycie: ' + label);

        var val = document.createElement('span');
        val.className = 'val';
        val.textContent = defaultOpacity + '%';

        range.addEventListener('input', function () {
            setOpacity(parseInt(range.value, 10) / 100);
            val.textContent = range.value + '%';
        });

        row.appendChild(cb);
        row.appendChild(name);
        row.appendChild(range);
        row.appendChild(val);
        list.appendChild(row);

        return {
            row: row,
            cb: cb,
            /** Re-apply a slider moved while the layer was not loaded yet. */
            applyOpacity: function () {
                if (range.value !== defaultOpacity) setOpacity(parseInt(range.value, 10) / 100);
            },
        };
    }

    function logLayerChange(label, visible) {
        if (window.Hydrograf.diagnostics) {
            Hydrograf.diagnostics.log('layer_change', { layer: label, visible: visible });
        }
    }

    /**
     * Add an overlay row for a layer that already exists (or is created synchronously).
     * @param {HTMLElement} list - Group to append the row to.
     * @param {string} label - Layer name shown in the panel.
     * @param {function(): ?L.Layer} getLayer - Returns the layer (null if unavailable).
     * @param {function(): ?L.LatLngBounds} getBounds - Layer extent for #zoom-extent.
     * @param {function(number)} setOpacity - Called with opacity 0..1.
     * @param {number} defaultTransparency - Initial transparency in percent.
     */
    function addOverlayEntry(list, label, getLayer, getBounds, setOpacity, defaultTransparency) {
        var entry = createLayerRow(list, label, setOpacity, defaultTransparency);
        var cb = entry.cb;

        _overlayRegistry.push({ label: label, cb: cb, getBounds: getBounds });

        cb.addEventListener('change', function () {
            var layer = getLayer();
            if (!layer) {
                cb.checked = false;
                return;
            }
            var map = Hydrograf.map._getMap();
            if (cb.checked) {
                layer.addTo(map);
                entry.applyOpacity();
            } else {
                map.removeLayer(layer);
            }
            entry.row.classList.toggle('off', !cb.checked);
            logLayerChange(label, cb.checked);
        });
    }

    /**
     * Overlay row for async-loaded layers (GeoJSON, MVT).
     * getLayer returns the existing layer, loadLayer returns a Promise of it.
     */
    function addAsyncOverlayEntry(list, label, getLayer, loadLayer, getBounds, setOpacity, defaultTransparency, onShow, onHide) {
        var entry = createLayerRow(list, label, setOpacity, defaultTransparency);
        var cb = entry.cb;

        _overlayRegistry.push({ label: label, cb: cb, getBounds: getBounds });

        // One load at a time: a second check while the first load is pending
        // must not build a second layer (it would be orphaned on the map and
        // no later uncheck could remove it).
        var pendingLoad = null;

        cb.addEventListener('change', function () {
            var mapObj = Hydrograf.map._getMap();
            if (cb.checked) {
                var layer = getLayer();
                if (layer) {
                    layer.addTo(mapObj);
                    entry.applyOpacity();
                } else if (!pendingLoad) {
                    pendingLoad = Promise.resolve(loadLayer()).then(function (l) {
                        pendingLoad = null;
                        // The box may have been unchecked while loading.
                        if (l && cb.checked && !mapObj.hasLayer(l)) {
                            l.addTo(mapObj);
                            entry.applyOpacity();
                        }
                    }, function (err) {
                        pendingLoad = null;
                        throw err;
                    });
                }
                if (onShow) onShow();
            } else {
                var existing = getLayer();
                if (existing && mapObj.hasLayer(existing)) {
                    mapObj.removeLayer(existing);
                }
                if (onHide) onHide();
            }
            entry.row.classList.toggle('off', !cb.checked);
            logLayerChange(label, cb.checked);
        });
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
        thresholds.forEach(function (t) {
            var opt = document.createElement('option');
            opt.value = t;
            opt.textContent = formatThreshold(t);
            if (t === 100000) opt.selected = true;
            select.appendChild(opt);
        });
    }

    /**
     * Streams row (MVT) with the flow accumulation threshold below it.
     */
    function addStreamsEntry(list, availableThresholds) {
        var label = 'Linie spływu';
        var entry = createLayerRow(list, label, Hydrograf.map.setStreamsOpacity, 0);
        var cb = entry.cb;

        // Threshold selector (shown while the layer is on)
        var extra = document.createElement('div');
        extra.className = 'layer-extra d-none';
        var field = document.createElement('div');
        field.className = 'field';
        var threshLabel = document.createElement('label');
        threshLabel.htmlFor = 'fa-threshold';
        threshLabel.textContent = 'Próg FA';
        var select = document.createElement('select');
        select.id = 'fa-threshold';
        populateThresholdSelect(select, availableThresholds);
        field.appendChild(threshLabel);
        field.appendChild(select);
        extra.appendChild(field);
        list.appendChild(extra);

        select.addEventListener('change', function () {
            var layer = Hydrograf.map.loadStreamsVector(parseInt(select.value, 10));
            if (cb.checked && layer) {
                layer.addTo(Hydrograf.map._getMap());
                entry.applyOpacity();
            }
        });

        // MVT layers have no bounds of their own; use the DEM extent.
        _overlayRegistry.push({ label: label, cb: cb, getBounds: Hydrograf.map.getDemBounds });

        cb.addEventListener('change', function () {
            var map = Hydrograf.map._getMap();
            var layer;
            if (cb.checked) {
                layer = Hydrograf.map.getStreamsLayer();
                if (!layer) {
                    layer = Hydrograf.map.loadStreamsVector(parseInt(select.value, 10));
                }
                if (layer) {
                    layer.addTo(map);
                    entry.applyOpacity();
                }
                Hydrograf.map.createStreamsLegend();
            } else {
                layer = Hydrograf.map.getStreamsLayer();
                if (layer && map.hasLayer(layer)) {
                    map.removeLayer(layer);
                }
                Hydrograf.map.removeStreamsLegend();
            }
            entry.row.classList.toggle('off', !cb.checked);
            extra.classList.toggle('d-none', !cb.checked);
            logLayerChange(label, cb.checked);
        });
    }

    /**
     * Fit the map to the union of the enabled overlays' extents; with nothing
     * enabled (or no extent known yet) fit to the data extent.
     */
    function zoomToEnabledLayers() {
        var union = null;
        _overlayRegistry.forEach(function (entry) {
            if (!entry.cb.checked) return;
            var b = entry.getBounds();
            if (!b || !b.isValid()) return;
            if (union) {
                union.extend(b);
            } else {
                // Copy: extend() mutates and b may be a module's own bounds.
                union = L.latLngBounds(b.getSouthWest(), b.getNorthEast());
            }
        });
        Hydrograf.map.fitToBounds(union || Hydrograf.map.getDataBounds());
    }

    /** Fallback thresholds if backend is unavailable. */
    var FALLBACK_THRESHOLDS = [1000, 10000, 100000];

    /**
     * Initialize the layers panel and bind #zoom-extent.
     */
    function init() {
        var list = document.getElementById('layers-list');
        if (!list) return;

        var zoomBtn = document.getElementById('zoom-extent');
        if (zoomBtn) zoomBtn.addEventListener('click', zoomToEnabledLayers);

        // ===== Overlay layers (depressions.js appends to #overlay-group-entries) =====
        var overlayGroup = createGroup(list, 'Warstwy podkładowe');
        overlayGroup.id = 'overlay-group-entries';

        addOverlayEntry(
            overlayGroup,
            'NMT (wysokości)',
            Hydrograf.map.getDemLayer,
            Hydrograf.map.getDemBounds,
            Hydrograf.map.setDemOpacity,
            30
        );

        // BDOT10k water bodies
        addAsyncOverlayEntry(
            overlayGroup,
            'Zbiorniki wodne (BDOT10k)',
            Hydrograf.map.getBdotLakesLayer,
            Hydrograf.map.loadBdotLakes,
            layerBounds(Hydrograf.map.getBdotLakesLayer),
            Hydrograf.map.setBdotLakesOpacity,
            0
        );

        // BDOT10k streams
        addAsyncOverlayEntry(
            overlayGroup,
            'Cieki BDOT10k',
            Hydrograf.map.getBdotStreamsLayer,
            Hydrograf.map.loadBdotStreams,
            layerBounds(Hydrograf.map.getBdotStreamsLayer),
            Hydrograf.map.setBdotStreamsOpacity,
            0
        );

        // HSG soil groups
        addAsyncOverlayEntry(
            overlayGroup,
            'Grupy glebowe (HSG)',
            Hydrograf.map.getHsgLayer,
            Hydrograf.map.loadHsgLayer,
            layerBounds(Hydrograf.map.getHsgLayer),
            Hydrograf.map.setHsgOpacity,
            0,
            Hydrograf.map.createHsgLegend,
            Hydrograf.map.removeHsgLegend
        );

        // Land cover (BDOT10k) — MVT tiles, no own bounds: DEM extent
        addAsyncOverlayEntry(
            overlayGroup,
            'Pokrycie terenu (BDOT10k)',
            Hydrograf.map.getLandCoverLayer,
            Hydrograf.map.loadLandCoverVector,
            Hydrograf.map.getDemBounds,
            Hydrograf.map.setLandCoverOpacity,
            30,
            Hydrograf.map.createLandCoverLegend,
            Hydrograf.map.removeLandCoverLegend
        );

        // Sewer network overlay (MVT, no known extent)
        if (window.Hydrograf.sewer) {
            addOverlayEntry(
                overlayGroup,
                'Kanalizacja deszczowa',
                function () { return window.Hydrograf.sewer.getLayer(); },
                noBounds,
                function (opacity) {
                    var layer = window.Hydrograf.sewer.getLayer();
                    var container = layer && layer.getContainer();
                    if (container) container.style.opacity = opacity;
                },
                50
            );
        }

        // ===== Analysis results group =====
        var resultsGroup = createGroup(list, 'Wyniki analiz');

        // Fetch available thresholds, then build streams entry
        fetch('/api/tiles/thresholds')
            .then(function (res) { return res.json(); })
            .then(function (data) {
                var streamsThresholds = data.streams && data.streams.length > 0
                    ? data.streams : FALLBACK_THRESHOLDS;
                addStreamsEntry(resultsGroup, streamsThresholds);
            })
            .catch(function () {
                addStreamsEntry(resultsGroup, FALLBACK_THRESHOLDS);
            });

        // ===== Base layers (at the bottom of the panel) =====
        createBaseLayerList(createGroup(list, 'Podkłady kartograficzne'));
        setBaseLayer(DEFAULT_BASE_LAYER);
    }

    window.Hydrograf.layers = {
        init: init,
        addOverlayEntry: addOverlayEntry,
        getBaseLayerName: function () { return currentBaseLayerName; },
        getActiveOverlays: function () {
            return _overlayRegistry
                .filter(function (entry) { return entry.cb.checked; })
                .map(function (entry) { return entry.label; });
        },
    };
})();
