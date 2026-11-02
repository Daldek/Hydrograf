/**
 * Hydrograf Layers module.
 *
 * Layers panel: overlay rows (checkbox, name, opacity slider), rows for the
 * results of external analyses (results.js), base map radio list with the
 * flood hazard map overlay (MZP, WMS of Wody Polskie) above it, and one
 * zoom-to-extent action for all enabled overlays.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var currentBaseLayer = null;
    var baseLayers = {};
    var DEFAULT_BASE_LAYER = 'openfreemap';
    var currentBaseLayerName = DEFAULT_BASE_LAYER;
    var _overlayRegistry = [];
    var _groups = {};
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
     * Create a panel group (section with a title) and add it to the list.
     * @param {HTMLElement} list - Panel container.
     * @param {string} label - Group title.
     * @param {?Node} [before] - Insert before this child; appended when omitted.
     * @returns {HTMLElement} The group section; rows are appended to it.
     */
    function createGroup(list, label, before) {
        var section = document.createElement('section');
        section.className = 'group';
        var title = document.createElement('h3');
        title.className = 'group-title';
        title.textContent = label;
        section.appendChild(title);
        list.insertBefore(section, before || null);
        _groups[label] = section;
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
            name: name,
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
     * @returns {Object} The row entry of createLayerRow.
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
        return entry;
    }

    /**
     * Flow accumulation threshold [m²] for display: hectares below 1 km²,
     * square kilometres from 1 km² (10 000 m² → "1 ha", 100 000 m² →
     * "10 ha", 1 000 000 m² → "1 km²"). The API keeps m².
     */
    function formatThreshold(value_m2) {
        var km2 = value_m2 >= 1e6;
        var value = km2 ? value_m2 / 1e6 : value_m2 / 1e4;
        return value.toLocaleString('pl-PL', { maximumFractionDigits: 2 }) + '\u00A0' + (km2 ? 'km\u00B2' : 'ha');
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
        threshLabel.textContent = 'Próg akumulacji spływu';
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
     * Row of an analysis result (results.js): tile layer with the manifest's
     * opacity and extent, legend while on, description and source in an (i).
     * Turning on or off a result with a water level redraws an open terrain
     * profile with or without its water surface.
     */
    function addResultEntry(list, result) {
        function getLayer() { return result.layer; }
        function refreshProfile() {
            if (result.waterLevel && window.Hydrograf.profile) Hydrograf.profile.refresh();
        }
        var entry = addAsyncOverlayEntry(
            list,
            result.title,
            getLayer,
            getLayer,
            function () { return result.bounds; },
            function (opacity) { result.layer.setOpacity(opacity); },
            Math.round((1 - result.opacity) * 100),
            function () { Hydrograf.results.showLegend(result); refreshProfile(); },
            function () { Hydrograf.results.hideLegend(result); refreshProfile(); }
        );
        // Long titles are cut with an ellipsis: the full one on hover
        entry.name.title = result.title;
        if (result.infoKey && window.Hydrograf.info && Hydrograf.info.attach(entry.row, result.infoKey, result.title)) {
            entry.row.classList.add('has-info');
        }
    }

    // ===== Flood hazard map (MZP) of Wody Polskie / ISOK =====

    /**
     * Water depth of the flood hazard maps (MZP, 2020 update) for river
     * floods: one ArcGIS WMS of Wody Polskie per probability, `layer` is the
     * service's "głębokość wody w [m]" layer. The sea flood layers of the same
     * services are left out.
     */
    var MZP_SCENARIOS = [
        { p: '0,2', years: 500, service: 'MZP20_Glebokosc_NiskiePrawdopodPowodzi', layer: '16' },
        { p: '1', years: 100, service: 'MZP20_Glebokosc_SredniePrawdopodPowodzi', layer: '16' },
        { p: '10', years: 10, service: 'MZP20_Glebokosc_WysokiePrawdopodPowodzi', layer: '1' },
    ];
    var MZP_DEFAULT_SCENARIO = 1;

    /**
     * The services draw depths only at 1:50 000 and larger scales, i.e. from
     * zoom 14. Below it the layer leaves the map instead of carrying minZoom,
     * which would stop the map zooming out while it is the only tile layer.
     */
    var MZP_MIN_ZOOM = 14;
    var MZP_ZOOM_HINT = 'Przybliż mapę — głębokości są rysowane od skali ok. 1:50\u00A0000.';

    /** Depth classes [m] in the colours the services draw them. */
    var MZP_CLASSES = [
        { label: '≤ 0,5', color: '#cfe8fa' },
        { label: '0,5–2,0', color: '#a7caf7' },
        { label: '2,0–4,0', color: '#7face3' },
        { label: '> 4,0', color: '#7f98b9' },
    ];

    var MZP_ATTRIBUTION = 'MZP &copy; <a href="https://wody.isok.gov.pl/imap_kzgw/?gpmap=gpMZP">Wody Polskie / ISOK</a>'
        + ' (<a href="https://creativecommons.org/licenses/by/4.0/deed.pl">CC BY 4.0</a>)';

    function mzpUrl(scenario) {
        return 'https://wody.isok.gov.pl/gpservices/KZGW/' + scenario.service + '/MapServer/WMSServer';
    }

    function mzpLegendTitle(scenario) {
        return 'Głębokość wody [m] — MZP, p\u00A0=\u00A0' + scenario.p + '\u00A0%';
    }

    /**
     * Overlay row of the flood hazard map in the base maps group: a checkbox
     * independent of the base map choice, drawn above any base map
     * (hazardPane). While on: the probability select and the zoom hint below
     * the row, the legend on the map. Another probability keeps the layer,
     * its visibility and opacity.
     */
    function addHazardEntry(group) {
        var label = 'Mapa zagrożenia powodziowego';
        var map = Hydrograf.map._getMap();
        var scenario = MZP_SCENARIOS[MZP_DEFAULT_SCENARIO];
        var layer = null;

        var entry = createLayerRow(group, label, function (opacity) {
            if (layer) layer.setOpacity(opacity);
        }, 20);
        var cb = entry.cb;
        entry.name.title = label + ' (MZP): głębokość wody, Wody Polskie / ISOK';

        var extra = document.createElement('div');
        extra.className = 'layer-extra d-none';
        var field = document.createElement('div');
        field.className = 'field';
        var selectLabel = document.createElement('label');
        selectLabel.htmlFor = 'mzp-scenario';
        selectLabel.textContent = 'Prawdopodobieństwo powodzi';
        var select = document.createElement('select');
        select.id = 'mzp-scenario';
        MZP_SCENARIOS.forEach(function (s) {
            var text = s.p + '\u00A0% — raz na ' + s.years + ' lat';
            select.add(new Option(text, s.service, false, s === scenario));
        });
        var hint = document.createElement('span');
        hint.className = 'hint';
        hint.textContent = MZP_ZOOM_HINT;
        field.appendChild(selectLabel);
        field.appendChild(select);
        field.appendChild(hint);
        extra.appendChild(field);
        group.appendChild(extra);

        var legendBox = L.DomUtil.create('div', 'layer-legend');
        var legendTitle = L.DomUtil.create('div', 'layer-legend-title', legendBox);
        legendTitle.textContent = mzpLegendTitle(scenario);
        MZP_CLASSES.forEach(function (c) {
            var item = L.DomUtil.create('div', 'legend-item', legendBox);
            L.DomUtil.create('span', 'legend-swatch', item).style.background = c.color;
            item.appendChild(document.createTextNode(' ' + c.label));
        });
        var legendHint = L.DomUtil.create('div', 'layer-legend-note', legendBox);
        legendHint.textContent = MZP_ZOOM_HINT;
        var legend = L.control({ position: 'bottomleft' });
        legend.onAdd = function () { return legendBox; };

        _overlayRegistry.push({ label: label, cb: cb, getBounds: noBounds });

        function sync() {
            var zoomedIn = map.getZoom() >= MZP_MIN_ZOOM;
            if (cb.checked && zoomedIn) {
                if (!map.hasLayer(layer)) layer.addTo(map);
            } else if (layer && map.hasLayer(layer)) {
                map.removeLayer(layer);
            }
            hint.hidden = zoomedIn;
            legendHint.hidden = zoomedIn;
        }

        select.addEventListener('change', function () {
            scenario = MZP_SCENARIOS[select.selectedIndex];
            legendTitle.textContent = mzpLegendTitle(scenario);
            if (layer) {
                layer.setUrl(mzpUrl(scenario), true);
                layer.setParams({ layers: scenario.layer });
            }
            if (window.Hydrograf.diagnostics) {
                Hydrograf.diagnostics.log('layer_change', { layer: label, scenario: scenario.service });
            }
        });

        cb.addEventListener('change', function () {
            if (cb.checked) {
                if (!layer) {
                    // 512 px images: a third of the requests to a slow
                    // service, at the resolution (and scale) of the zoom.
                    layer = L.tileLayer.wms(mzpUrl(scenario), {
                        layers: scenario.layer,
                        format: 'image/png',
                        transparent: true,
                        version: '1.3.0',
                        tileSize: 512,
                        opacity: 0.8,
                        maxZoom: 22,
                        pane: 'hazardPane',
                        attribution: MZP_ATTRIBUTION,
                    });
                    entry.applyOpacity();
                }
                map.on('zoomend', sync);
                legend.addTo(map);
            } else {
                map.off('zoomend', sync);
                legend.remove();
            }
            sync();
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

        // Sewer network overlay (MVT, no known extent): only when the server
        // holds sewer data (GET /api/layers). A placeholder keeps the row's
        // place in the group while the answer is pending.
        if (window.Hydrograf.sewer) {
            var sewerSlot = document.createComment('sewer');
            overlayGroup.appendChild(sewerSlot);
            Hydrograf.api.getLayers()
                .then(function (available) {
                    if (!available.sewer) {
                        sewerSlot.remove();
                        return;
                    }
                    var rows = document.createDocumentFragment();
                    addOverlayEntry(
                        rows,
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
                    sewerSlot.replaceWith(rows);
                })
                .catch(function (err) {
                    sewerSlot.remove();
                    console.warn('Layer availability unknown, sewer layer hidden:', err.message);
                });
        }

        // ===== Analysis results group =====
        // The streams row waits for the thresholds; its slot keeps it first.
        var resultsGroup = createGroup(list, 'Wyniki analiz');
        var streamsSlot = document.createComment('streams');
        resultsGroup.appendChild(streamsSlot);

        function placeStreamsEntry(thresholds) {
            var rows = document.createDocumentFragment();
            addStreamsEntry(rows, thresholds);
            streamsSlot.replaceWith(rows);
        }

        // Fetch available thresholds, then build streams entry
        fetch('/api/tiles/thresholds')
            .then(function (res) { return res.json(); })
            .then(function (data) {
                var streamsThresholds = data.streams && data.streams.length > 0
                    ? data.streams : FALLBACK_THRESHOLDS;
                placeStreamsEntry(streamsThresholds);
            })
            .catch(function () {
                placeStreamsEntry(FALLBACK_THRESHOLDS);
            });

        // Results of external analyses (manifest read by results.js) join the
        // group named in the manifest; a group that does not exist yet is
        // created above the base maps, so without results nothing is shown.
        var baseMapsSlot = document.createComment('result groups');
        list.appendChild(baseMapsSlot);
        if (window.Hydrograf.results) {
            Hydrograf.results.load().then(function (results) {
                results.forEach(function (result) {
                    addResultEntry(_groups[result.group] || createGroup(list, result.group, baseMapsSlot), result);
                });
            });
        }

        // ===== Base layers (at the bottom of the panel) =====
        // The flood hazard map row sits above the base map list it is drawn over.
        var baseGroup = createGroup(list, 'Podkłady kartograficzne');
        addHazardEntry(baseGroup);
        createBaseLayerList(baseGroup);
        setBaseLayer(DEFAULT_BASE_LAYER);
    }

    window.Hydrograf.layers = {
        init: init,
        addOverlayEntry: addOverlayEntry,
        formatThreshold: formatThreshold,
        getBaseLayerName: function () { return currentBaseLayerName; },
        getActiveOverlays: function () {
            return _overlayRegistry
                .filter(function (entry) { return entry.cb.checked; })
                .map(function (entry) { return entry.label; });
        },
    };
})();
