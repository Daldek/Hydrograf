/**
 * Hydrograf Layers module.
 *
 * Layers panel: overlay rows (checkbox, name, opacity slider), rows for the
 * results of external analyses (results.js), the base maps of Nogat's kit with
 * the flood hazard map overlay (MZP, WMS of Wody Polskie) above them, and one
 * zoom-to-extent action for all enabled overlays.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var _overlayRegistry = [];
    var _groups = {};
    var _rowCount = 0;

    // ===== Base maps (Nogat DEV-15.15, ADR-089) =====
    //
    // GET /api/v1/basemaps gives the entries of the kit's catalogue that the deployment
    // allows (its setting `basemaps`, a copy of its own in a provider's place), then its
    // own base maps, in the catalogue's shape. The kit's <nogat-basemaps> lists them and
    // „bez podkładu”, opens on the choice the browser keeps (`nogat-basemap`) while it is
    // offered, else on the first entry the catalogue marks as a default, and tells of a
    // person's choice by `change`. The kit's maplibreBasemap (through Hydrograf.map) draws
    // the chosen one under the overlays with its credit in the map's attribution: a raster
    // entry as image tiles, OpenFreeMap in the kit's grey style. An entry whose provider
    // fails is marked in the list and said on the map; nothing switches by itself.

    var basemaps = {
        element: null,  // the kit's <nogat-basemaps>
        shown: 'none',  // the id chosen, "none" for „bez podkładu”
    };

    /** The kit's base maps of js/nogat.js, or null without its module. */
    function basemapKit() {
        return (window.Hydrograf.nogat && window.Hydrograf.nogat.basemaps) || null;
    }

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
     * Put the kit's base-map switcher at the end of the group and give it the entries
     * of GET /api/v1/basemaps; without the kit's module or the answer no base map is drawn.
     */
    function createBaseMapSwitcher(group) {
        if (!basemapKit()) return;
        var element = document.createElement('nogat-basemaps');
        basemaps.element = element;
        group.appendChild(element);
        element.addEventListener('change', function (event) {
            showBaseMap(event.detail.id);
        });
        Hydrograf.map.onThemeChange(Hydrograf.map.repaintBasemap);
        Hydrograf.api.getBasemaps()
            .then(function (entries) {
                element.entries = entries;
                showBaseMap(element.value);
            })
            .catch(function (err) {
                console.warn('Base maps unknown, none is drawn:', err.message);
            });
    }

    /**
     * Draw the base map `id` under the overlays in place of the one drawn; "none"
     * (or an id not offered) draws none. The view stays.
     */
    function showBaseMap(id) {
        basemaps.shown = id;
        showBaseMapNotice(null);
        var entry = basemaps.element.entries.find(function (candidate) {
            return candidate.id === id;
        });
        if (!entry) {
            Hydrograf.map.removeBasemap();
            return;
        }
        Hydrograf.map.showBasemap(entry, {
            onFailure: function (failed) { onBaseMapFailure(failed, entry); },
        }).catch(function () {
            // onBaseMapFailure has marked the entry and said it on the map, or a later
            // choice replaced it
        });
    }

    /**
     * A base map's provider does not answer (its TileJSON or first tiles): the kit took
     * it off the map; the list marks the entry and, while it is the one chosen, the map
     * says so until the next choice.
     */
    function onBaseMapFailure(id, entry) {
        basemaps.element.fail(id);
        if (id !== basemaps.shown) return;
        showBaseMapNotice(entry);
    }

    /** The notice on the map of a base map that does not answer; null hides it. */
    function showBaseMapNotice(entry) {
        var notice = document.getElementById('basemap-notice');
        if (!notice) return;
        notice.hidden = !entry;
        if (!entry) {
            notice.textContent = '';
            return;
        }
        var texts = basemaps.element.texts;
        var label = (texts.labels && texts.labels[entry.id]) || entry.label;
        notice.textContent = texts.failed + ': ' + label + '. Wybierz inny podkład w panelu „Warstwy”.';
    }

    function noBounds() { return null; }

    /**
     * Register an overlay for #zoom-extent and, with `kind`, for the view's strip: a
     * layer of Hydrograf's data (`elevation`, `drainage`, `topography`, `soils`: the
     * kinds of `layers` of GET /api/v1/terms) puts the lines of its GUGiK and SoilGrids
     * data into the strip while it is on (Nogat DEV §20; showDataLines, after every
     * change in the panel).
     */
    function registerOverlay(label, cb, getBounds, kind) {
        _overlayRegistry.push({ label: label, cb: cb, getBounds: getBounds, kind: kind || null });
    }

    /** The strip's lines of the layers of Hydrograf's data that are on (js/attribution.js). */
    function showDataLines() {
        var kinds = {};
        _overlayRegistry.forEach(function (entry) {
            if (entry.kind && entry.cb.checked) kinds[entry.kind] = true;
        });
        var names = Object.keys(kinds);
        if (!names.length || !window.Hydrograf.terms) {
            Hydrograf.attribution.show('layers', null);
            return;
        }
        // In the order of the changes: every callback of one promise runs in turn
        Hydrograf.terms.ready.then(function (terms) {
            Hydrograf.attribution.show('layers', Hydrograf.attribution.merge(
                names.map(function (kind) { return terms.layers[kind] || null; })));
        });
    }

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

    /**
     * Add an overlay row: the checkbox shows and hides an overlay of the map, its slider
     * sets the overlay's opacity.
     * @param {HTMLElement} list - Group to append the row to.
     * @param {string} label - Layer name shown in the panel.
     * @param {Object} overlay - `id` of the map's overlay (Hydrograf.map); `load()`, which
     *     puts it on the map (hidden) unless it is there and returns, or promises, whether
     *     it is: a row whose overlay cannot be had unchecks itself; `bounds()`, its extent
     *     [west, south, east, north] for #zoom-extent, or null.
     * @param {number} defaultTransparency - Initial transparency in percent.
     * @param {function()=} onShow - Called when the layer is turned on (legend).
     * @param {function()=} onHide - Called when the layer is turned off.
     * @param {string=} kind - The kind of Hydrograf's data it shows (registerOverlay).
     * @returns {Object} The row entry of createLayerRow.
     */
    function addOverlayEntry(list, label, overlay, defaultTransparency, onShow, onHide, kind) {
        var entry = createLayerRow(list, label, function (opacity) {
            Hydrograf.map.setOverlayOpacity(overlay.id, opacity);
        }, defaultTransparency);
        var cb = entry.cb;

        registerOverlay(label, cb, overlay.bounds, kind);

        cb.addEventListener('change', function () {
            if (cb.checked) {
                Promise.resolve(overlay.load()).then(function (loaded) {
                    // The box may have been unchecked while loading
                    if (!cb.checked) return;
                    if (!loaded) {
                        cb.checked = false;
                        entry.row.classList.add('off');
                        showDataLines();
                        return;
                    }
                    Hydrograf.map.setOverlayShown(overlay.id, true);
                    entry.applyOpacity();
                    if (onShow) onShow();
                });
            } else {
                Hydrograf.map.setOverlayShown(overlay.id, false);
                if (onHide) onHide();
            }
            entry.row.classList.toggle('off', !cb.checked);
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
        var entry = createLayerRow(list, label, function (opacity) {
            Hydrograf.map.setOverlayOpacity('streams', opacity);
        }, 0);
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

        // Another threshold keeps the layer, its visibility and opacity
        select.addEventListener('change', function () {
            Hydrograf.map.setStreamsThreshold(parseInt(select.value, 10));
        });

        // MVT layers have no bounds of their own; use the DEM extent.
        registerOverlay(label, cb, Hydrograf.map.getDemBounds, 'drainage');

        cb.addEventListener('change', function () {
            if (cb.checked) {
                Hydrograf.map.ready.then(function (shown) {
                    if (!shown || !cb.checked) return;
                    Hydrograf.map.setStreamsThreshold(parseInt(select.value, 10));
                    Hydrograf.map.setOverlayShown('streams', true);
                    entry.applyOpacity();
                    Hydrograf.map.createStreamsLegend();
                });
            } else {
                Hydrograf.map.setOverlayShown('streams', false);
                Hydrograf.map.removeStreamsLegend();
            }
            entry.row.classList.toggle('off', !cb.checked);
            extra.classList.toggle('d-none', !cb.checked);
        });
    }

    /** A scale's denominator to two significant digits, as the hints write it: „34 000”. */
    function roundScale(scale) {
        var step = Math.pow(10, Math.max(0, Math.floor(Math.log10(scale)) - 1));
        return (Math.round(scale / step) * step).toLocaleString('pl-PL');
    }

    /**
     * Row of an analysis result (results.js): tile layer with the manifest's
     * opacity and extent, legend while on (its provider lines go to the view's
     * strip), description and source in an (i). The map draws a result from its
     * first tile level (the manifest's `min_zoom`, Nogat's plan
     * 2026-11-24-hydrograf-maplibre, open question 4): farther out the row says
     * „Przybliż mapę” while it is on.
     * Turning on or off a result with a water level redraws an open terrain
     * profile with or without its water surface.
     */
    function addResultEntry(list, result) {
        var id = 'result:' + result.id;
        function refreshProfile() {
            if (result.waterLevel && window.Hydrograf.profile) Hydrograf.profile.refresh();
        }
        var extra = document.createElement('div');
        extra.className = 'layer-extra d-none';
        var hint = document.createElement('span');
        hint.className = 'hint';
        extra.appendChild(hint);
        function syncHint() {
            var far = entry.cb.checked && !Hydrograf.map.withinZoom(id);
            var scale = far ? Hydrograf.map.firstScale(id) : null;
            hint.textContent = scale
                ? 'Przybliż mapę — wynik jest rysowany od skali ok. 1:' + roundScale(scale) + '.' : '';
            extra.classList.toggle('d-none', !scale);
        }
        var entry = addOverlayEntry(
            list,
            result.title,
            {
                id: id,
                load: function () { return Hydrograf.results.addLayer(result); },
                bounds: function () { return result.bounds; },
            },
            Math.round((1 - result.opacity) * 100),
            function () { Hydrograf.results.showLegend(result); refreshProfile(); syncHint(); },
            function () { Hydrograf.results.hideLegend(result); refreshProfile(); syncHint(); }
        );
        list.appendChild(extra);
        Hydrograf.map.onZoomEnd(syncHint);
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
     * The services draw depths only at 1:50 000 and larger scales: from zoom 13
     * (1:34 124 at a whole level). The layer's minzoom keeps it off the map
     * farther out, so nothing is asked of the service there; a layer's minzoom
     * never holds the map's zoom.
     */
    var MZP_MIN_ZOOM = 13;
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

    /**
     * The service's GetMap of a 512-px tile in EPSG:3857, its box filled by the map
     * (Archiwista's tileUrl): a third of the requests of 256-px tiles to a slow
     * service, at the resolution (and scale) of the zoom.
     */
    function mzpTiles(scenario) {
        return [mzpUrl(scenario) + '?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&LAYERS=' + scenario.layer +
            '&STYLES=&FORMAT=image/png&TRANSPARENT=true&CRS=EPSG:3857&WIDTH=512&HEIGHT=512' +
            '&BBOX={bbox-epsg-3857}'];
    }

    function mzpLegendTitle(scenario) {
        return 'Głębokość wody [m] — MZP, p\u00A0=\u00A0' + scenario.p + '\u00A0%';
    }

    /**
     * Overlay row of the flood hazard map in the base maps group: a checkbox
     * independent of the base map choice, drawn above any base map and the
     * DEM (the map's hazard slot). While on: the probability select and the zoom
     * hint below the row, the legend on the map. Another probability keeps the
     * layer, its visibility and opacity.
     */
    function addHazardEntry(group) {
        var label = 'Mapa zagrożenia powodziowego';
        var scenario = MZP_SCENARIOS[MZP_DEFAULT_SCENARIO];
        var added = false;

        var entry = createLayerRow(group, label, function (opacity) {
            Hydrograf.map.setOverlayOpacity('hazard', opacity);
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

        function node(tag, className, parent) {
            var created = document.createElement(tag);
            created.className = className;
            if (parent) parent.appendChild(created);
            return created;
        }
        var legendBox = node('div', 'layer-legend');
        var legendTitle = node('div', 'layer-legend-title', legendBox);
        legendTitle.textContent = mzpLegendTitle(scenario);
        MZP_CLASSES.forEach(function (c) {
            var item = node('div', 'legend-item', legendBox);
            node('span', 'legend-swatch', item).style.background = c.color;
            item.appendChild(document.createTextNode(' ' + c.label));
        });
        var legendHint = node('div', 'layer-legend-note', legendBox);
        legendHint.textContent = MZP_ZOOM_HINT;
        var legend = null;

        _overlayRegistry.push({ label: label, cb: cb, getBounds: noBounds });

        // The hints say to zoom in while the view is farther out than the layer's first zoom
        function sync() {
            var zoomedIn = Hydrograf.map.withinZoom('hazard');
            hint.hidden = zoomedIn;
            legendHint.hidden = zoomedIn;
        }
        Hydrograf.map.onZoomEnd(sync);

        select.addEventListener('change', function () {
            scenario = MZP_SCENARIOS[select.selectedIndex];
            legendTitle.textContent = mzpLegendTitle(scenario);
            Hydrograf.map.setTiles('hazard', mzpTiles(scenario));
        });

        cb.addEventListener('change', function () {
            if (cb.checked) {
                Hydrograf.map.ready.then(function (shown) {
                    if (!shown || !cb.checked) return;
                    if (!added) {
                        Hydrograf.map.showRaster('hazard', {
                            tiles: mzpTiles(scenario),
                            tileSize: 512,
                            layerMinzoom: MZP_MIN_ZOOM,
                            // The service is slow: a zoom in asks it only for the view
                            // the map ends at, never for the larger ones on the way
                            floorLevel: true,
                            opacity: 0.8,
                            attribution: MZP_ATTRIBUTION,
                            shown: false,
                        });
                        added = true;
                    }
                    Hydrograf.map.setOverlayShown('hazard', true);
                    entry.applyOpacity();
                    if (!legend) legend = Hydrograf.map.addControl(legendBox, 'bottom-left');
                    sync();
                });
            } else {
                Hydrograf.map.setOverlayShown('hazard', false);
                if (legend) legend.remove();
                legend = null;
            }
            entry.row.classList.toggle('off', !cb.checked);
            extra.classList.toggle('d-none', !cb.checked);
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
            if (!b) return;
            union = union
                ? [Math.min(union[0], b[0]), Math.min(union[1], b[1]), Math.max(union[2], b[2]), Math.max(union[3], b[3])]
                : b.slice();
        });
        Hydrograf.map.fitToBounds(union || Hydrograf.map.getDataBounds());
    }

    /** The extent of a GeoJSON overlay of the map, once loaded. */
    function overlayBounds(id) {
        return function () { return Hydrograf.map.overlayBounds(id); };
    }

    /** Fallback thresholds if backend is unavailable (those of the preprocessing). */
    var FALLBACK_THRESHOLDS = [10000, 100000, 1000000, 10000000];

    /**
     * Initialize the layers panel and bind #zoom-extent.
     */
    function init() {
        var list = document.getElementById('layers-list');
        if (!list) return;

        var zoomBtn = document.getElementById('zoom-extent');
        if (zoomBtn) zoomBtn.addEventListener('click', zoomToEnabledLayers);
        // After the row's own handler: a row whose layer is missing unchecks itself
        list.addEventListener('change', showDataLines);

        // ===== Overlay layers (depressions.js appends to #overlay-group-entries) =====
        var overlayGroup = createGroup(list, 'Warstwy podkładowe');
        overlayGroup.id = 'overlay-group-entries';

        addOverlayEntry(
            overlayGroup,
            'NMT (wysokości)',
            { id: 'dem', load: Hydrograf.map.loadDem, bounds: Hydrograf.map.getDemBounds },
            30,
            Hydrograf.map.createDemLegend,
            Hydrograf.map.removeDemLegend,
            'elevation'
        );

        // BDOT10k water bodies
        addOverlayEntry(
            overlayGroup,
            'Zbiorniki wodne (BDOT10k)',
            { id: 'bdot-lakes', load: Hydrograf.map.loadBdotLakes, bounds: overlayBounds('bdot-lakes') },
            0,
            null,
            null,
            'topography'
        );

        // BDOT10k streams
        addOverlayEntry(
            overlayGroup,
            'Cieki BDOT10k',
            { id: 'bdot-streams', load: Hydrograf.map.loadBdotStreams, bounds: overlayBounds('bdot-streams') },
            0,
            null,
            null,
            'topography'
        );

        // HSG soil groups: SoilGrids, the BDOT10k wetlands group D (ADR-078)
        addOverlayEntry(
            overlayGroup,
            'Grupy glebowe (HSG)',
            { id: 'hsg', load: Hydrograf.map.loadHsgLayer, bounds: overlayBounds('hsg') },
            0,
            Hydrograf.map.createHsgLegend,
            Hydrograf.map.removeHsgLegend,
            'soils'
        );

        // Land cover (BDOT10k) — MVT tiles, no own bounds: DEM extent
        addOverlayEntry(
            overlayGroup,
            'Pokrycie terenu (BDOT10k)',
            { id: 'landcover', load: Hydrograf.map.loadLandCover, bounds: Hydrograf.map.getDemBounds },
            30,
            Hydrograf.map.createLandCoverLegend,
            Hydrograf.map.removeLandCoverLegend,
            'topography'
        );

        // Sewer network overlay (MVT, no known extent): only when the server
        // holds sewer data (`layers availability`). A placeholder keeps the row's
        // place in the group while the answer is pending.
        var sewerSlot = document.createComment('sewer');
        overlayGroup.appendChild(sewerSlot);
        Hydrograf.api.getLayers()
            .then(function (answer) {
                if (!answer.result.sewer) {
                    sewerSlot.remove();
                    return;
                }
                var rows = document.createDocumentFragment();
                addOverlayEntry(
                    rows,
                    'Kanalizacja deszczowa',
                    { id: 'sewer', load: Hydrograf.map.loadSewer, bounds: noBounds },
                    50
                );
                sewerSlot.replaceWith(rows);
            })
            .catch(function (err) {
                sewerSlot.remove();
                console.warn('Layer availability unknown, sewer layer hidden:', err.message);
            });

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

        // Fetch available thresholds (`layers thresholds`), then build streams entry
        Hydrograf.api.getThresholds()
            .then(function (answer) {
                var streams = answer.result.streams;
                var streamsThresholds = streams && streams.length > 0
                    ? streams : FALLBACK_THRESHOLDS;
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

        // ===== Base maps (at the bottom of the panel) =====
        // The flood hazard map row sits above the kit's switcher of the base maps it is
        // drawn over.
        var baseGroup = createGroup(list, 'Podkłady kartograficzne');
        addHazardEntry(baseGroup);
        createBaseMapSwitcher(baseGroup);
    }

    window.Hydrograf.layers = {
        init: init,
        addOverlayEntry: addOverlayEntry,
        formatThreshold: formatThreshold,
        getBaseLayerName: function () { return basemaps.shown; },
        getActiveOverlays: function () {
            return _overlayRegistry
                .filter(function (entry) { return entry.cb.checked; })
                .map(function (entry) { return entry.label; });
        },
    };
})();
