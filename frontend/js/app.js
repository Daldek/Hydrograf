/**
 * Hydrograf Application module.
 *
 * Orchestrates map clicks, API calls, floating results panel, and parameter display.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var state = {
        currentWatershed: null,
        // A selection that found a stream but no watershed (displayStreamInfo)
        currentStream: null,
        clickLat: null,
        clickLng: null,
        // 'browse', 'profile', 'identify' or one of the two of „Wybierz zlewnię”:
        // 'select' („Jedna zlewnia”) and 'network' („Sieć zlewni”)
        clickMode: 'browse',
        // The option of „Wybierz zlewnię” chosen last in this page ('select' or
        // 'network'); the mode returns to it
        selectTarget: 'select',
        // Number of the latest watershed selection; answers to older ones are dropped
        selection: 0,
        // What the panel and the map serve: 'watershed' (every mode but the option
        // „Sieć zlewni” of „Wybierz zlewnię”) or 'network' (js/network.js)
        view: 'watershed',
        // The parameter sections show the watershed (false after a network element)
        sectionsShowWatershed: true,
    };

    // The state of each view of the panel: its loading, its error and whether the
    // bin of the panel head has something to clear
    var views = {
        watershed: { loading: false, error: '', clearable: false },
        network: { loading: false, error: '', clearable: false },
    };

    var VIEW_TEXTS = {
        watershed: {
            title: 'Zlewnia', sheet: 'Zlewnia', loading: 'Wyznaczanie zlewni…',
            clear: 'Wyczyść wynik zlewni', close: 'Schowaj panel zlewni (wynik zostaje)',
        },
        network: {
            title: 'Sieć zlewni', sheet: 'Sieć', loading: 'Obliczanie charakterystyk…',
            clear: 'Wyczyść punkty i sieć', close: 'Schowaj panel sieci (punkty i wynik zostają)',
        },
    };

    var _clickDebounceTimer = null;

    // Poland bounding box (approximate)
    var BOUNDS = { latMin: 49.0, latMax: 55.0, lngMin: 14.0, lngMax: 24.2 };

    // DOM references (set on init)
    var els = {};

    function formatValue(val, unit, decimals) {
        if (val === null || val === undefined) return '—';
        return val.toFixed(decimals) + ' ' + unit;
    }

    function formatSlope(val) {
        if (val === null || val === undefined) return '—';
        return (val * 100).toFixed(2) + ' %';
    }

    function formatRatio(val, decimals) {
        if (val === null || val === undefined) return '—';
        return val.toFixed(decimals);
    }

    /** Split "12.34 km²" into ["12.34", "km²"]; non-numeric text stays whole. */
    function splitUnit(text) {
        var match = /^(-?[\d.]+)\s+(.+)$/.exec(text);
        return match ? [match[1], match[2]] : [text, ''];
    }

    function buildRow(label, value, infoKey) {
        var parts = splitUnit(value);
        var tr = document.createElement('tr');
        var th = document.createElement('th');
        var tdValue = document.createElement('td');
        var tdUnit = document.createElement('td');
        th.scope = 'row';
        th.innerHTML = label;
        if (infoKey) Hydrograf.info.attach(th, infoKey);
        tdValue.textContent = parts[0];
        tdUnit.className = 'u';
        tdUnit.textContent = parts[1];
        tr.appendChild(th);
        tr.appendChild(tdValue);
        tr.appendChild(tdUnit);
        return tr;
    }

    function fillTable(tbody, rows) {
        tbody.innerHTML = '';
        rows.forEach(function (row) {
            if (row[1] !== '—') {
                tbody.appendChild(buildRow(row[0], row[1], row[2]));
            }
        });
    }

    /** Polish plural: 1 klasa, 2–4 klasy, 5+ klas. */
    function plural(n, one, few, many) {
        if (n === 1) return one;
        var mod10 = n % 10;
        var mod100 = n % 100;
        return (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) ? few : many;
    }

    /** Short text in a results section header (right of its title). */
    function setMeta(sectionId, text) {
        var meta = document.querySelector('#' + sectionId + ' .meta');
        if (meta) meta.textContent = text || '';
    }

    /** Crumb in the top bar and subtitle of the results panel. */
    function setContext(crumb, sub) {
        els.crumb.textContent = crumb || '';
        els.crumbSep.hidden = !crumb;
        els.resultsSub.textContent = sub || '';
    }

    /** Key figures row above the result sections; hidden when nothing is known. */
    function renderSummary(m) {
        var items = [
            ['Powierzchnia', m.area_km2, 2, 'km²'],
            ['CN', m.cn, 1, ''],
            ['Wys. średnia', m.elevation_mean_m, 0, 'm n.p.m.'],
            ['Spadek', m.mean_slope_m_per_m != null ? m.mean_slope_m_per_m * 100 : null, 2, '%'],
        ].filter(function (item) { return item[1] !== null && item[1] !== undefined; });

        els.summary.innerHTML = '';
        items.forEach(function (item) {
            var kpi = document.createElement('div');
            var k = document.createElement('div');
            var v = document.createElement('div');
            kpi.className = 'kpi';
            k.className = 'k';
            v.className = 'v';
            k.textContent = item[0];
            v.textContent = item[1].toFixed(item[2]);
            if (item[3]) {
                var u = document.createElement('span');
                u.className = 'u';
                u.textContent = item[3];
                v.appendChild(document.createTextNode(' '));
                v.appendChild(u);
            }
            kpi.appendChild(k);
            kpi.appendChild(v);
            els.summary.appendChild(kpi);
        });
        els.summary.style.setProperty('--kpi-count', String(items.length));
        els.summary.classList.toggle('d-none', items.length === 0);
    }

    /**
     * Fill the parameter sections and the key figures with a watershed: the
     * delineated one, or an element of the network (js/network.js).
     * @param {Object} w - a WatershedResponse
     */
    function renderParameters(w) {
        var m = w.morphometry || {};
        var o = w.outlet;

        fillTable(els.paramsBasic, [
            ['Powierzchnia zlewni', formatValue(m.area_km2, 'km²', 2), 'area_km2'],
            ['Obwód zlewni', formatValue(m.perimeter_km, 'km', 2), 'perimeter_km'],
            ['Długość zlewni', formatValue(m.length_km, 'km', 2), 'length_km'],
            ['Średnia szerokość', formatValue(m.mean_width_km, 'km', 2), 'mean_width_km'],
            ['Wysokość min.', formatValue(m.elevation_min_m, 'm n.p.m.', 1), 'elevation_min_m'],
            ['Wysokość max.', formatValue(m.elevation_max_m, 'm n.p.m.', 1), 'elevation_max_m'],
            ['Wysokość średnia', formatValue(m.elevation_mean_m, 'm n.p.m.', 1), 'elevation_mean_m'],
            ['Średni spadek terenu', formatSlope(m.mean_slope_m_per_m), 'mean_slope_m_per_m'],
            ['Długość cieku głównego', formatValue(m.channel_length_km, 'km', 2), 'channel_length_km'],
            ['Długość cieku wg BDOT10k', formatValue(m.real_channel_length_km, 'km', 2), 'real_channel_length_km'],
            ['Spadek cieku głównego', formatSlope(m.channel_slope_m_per_m), 'channel_slope_m_per_m'],
            ['Najdłuższa droga spływu', formatValue(m.flow_path_length_km, 'km', 2), 'flow_path_length_km'],
            ['Spadek najdłuższej drogi spływu', formatSlope(m.flow_path_slope_m_per_m), 'flow_path_slope_m_per_m'],
            ['Spływ powierzchniowy – długość', formatValue(m.overland_length_km, 'km', 3), 'overland_length_km'],
            ['Spływ powierzchniowy – spadek', formatSlope(m.overland_slope_m_per_m), 'overland_slope_m_per_m'],
            ['Najdłuższa droga spływu od granicy zlewni', formatValue(m.divide_flow_path_km, 'km', 2), 'divide_flow_path_km'],
            ['CN (krzywa odpływu)', formatRatio(m.cn, 1), 'cn'],
            ['Ujście — szerokość φ', formatValue(o.latitude, '°N', 6), 'latitude'],
            ['Ujście — długość λ', formatValue(o.longitude, '°E', 6), 'longitude'],
            ['Ujście — wysokość', formatValue(o.elevation_m, 'm n.p.m.', 1), 'elevation_m'],
        ]);

        fillTable(els.paramsShape, [
            ['Wsk. zwartości C<sub>z</sub>', formatRatio(m.compactness_coefficient, 3), 'compactness_coefficient'],
            ['Wsk. kolistości C<sub>k</sub>', formatRatio(m.circularity_ratio, 3), 'circularity_ratio'],
            ['Wsk. wydłużenia C<sub>w</sub>', formatRatio(m.elongation_ratio, 3), 'elongation_ratio'],
            ['Wsk. formy C<sub>f</sub>', formatRatio(m.form_factor, 3), 'form_factor'],
            ['Wsk. lemniskaty C<sub>l</sub>', formatRatio(m.lemniscate_ratio, 3), 'lemniscate_ratio'],
        ]);

        fillTable(els.paramsRelief, [
            ['Wsk. rzeźby R', formatValue(m.relief_ratio, '‰', 2), 'relief_ratio'],
            ['Spadek działu wodnego R<sub>p</sub>', formatValue(m.divide_slope, '‰', 2), 'divide_slope'],
            ['Wsp. asymetrii α', formatRatio(m.asymmetry_coefficient, 3), 'asymmetry_coefficient'],
            ['Całka hipsometryczna HI', formatRatio(m.hypsometric_integral, 3), 'hypsometric_integral'],
        ]);

        fillTable(els.paramsDrainage, [
            ['Gęstość sieci D<sub>d</sub>', m.drainage_density_km_per_km2 != null
                ? formatValue(m.drainage_density_km_per_km2, 'km/km²', 2)
                : 'brak cieków BDOT', 'drainage_density_km_per_km2'],
            ['Częstość cieków F<sub>s</sub>', m.stream_frequency_per_km2 != null
                ? formatValue(m.stream_frequency_per_km2, '1/km²', 2)
                : 'brak cieków BDOT', 'stream_frequency_per_km2'],
            ['Liczba chropowatości R<sub>n</sub>', m.ruggedness_number != null
                ? formatRatio(m.ruggedness_number, 3)
                : 'brak cieków BDOT', 'ruggedness_number'],
            ['Max rząd Strahlera', m.max_strahler_order != null
                ? String(m.max_strahler_order)
                : 'brak cieków BDOT', 'max_strahler_order'],
            ['Pokrycie BDOT', m.real_channel_length_km != null && m.channel_length_km
                ? (100 * m.real_channel_length_km / m.channel_length_km).toFixed(0) + '%'
                : '—', 'bdot_coverage'],
        ]);

        // Charts: land cover donut
        if (w.land_cover_stats && w.land_cover_stats.categories && w.land_cover_stats.categories.length > 0) {
            Hydrograf.charts.renderLandCoverChart('chart-landcover', w.land_cover_stats.categories);
        } else {
            Hydrograf.charts.destroyChart('chart-landcover');
        }

        // HSG soil groups
        var accHsg = document.getElementById('acc-hsg');
        if (w.hsg_stats && w.hsg_stats.categories && w.hsg_stats.categories.length > 0) {
            if (accHsg) accHsg.classList.remove('d-none');
            Hydrograf.charts.renderHsgChart('chart-hsg', w.hsg_stats.categories);
        } else {
            if (accHsg) accHsg.classList.add('d-none');
            Hydrograf.charts.destroyChart('chart-hsg');
        }

        // Chart: hypsometric curve
        if (w.hypsometric_curve && w.hypsometric_curve.length > 0 &&
            m.elevation_min_m != null && m.elevation_max_m != null) {
            Hydrograf.charts.renderHypsometricChart(
                'chart-hypsometric', w.hypsometric_curve,
                m.elevation_min_m, m.elevation_max_m
            );
        } else {
            Hydrograf.charts.destroyChart('chart-hypsometric');
        }

        // Section header figures and key figures row
        var lcCount = w.land_cover_stats && w.land_cover_stats.categories ? w.land_cover_stats.categories.length : 0;
        var hsgCount = w.hsg_stats && w.hsg_stats.categories ? w.hsg_stats.categories.length : 0;
        setMeta('acc-basic', String(els.paramsBasic.rows.length));
        setMeta('acc-shape', String(els.paramsShape.rows.length));
        setMeta('acc-relief', m.hypsometric_integral != null ? 'HI ' + m.hypsometric_integral.toFixed(2) : '');
        setMeta('acc-drainage', m.max_strahler_order != null ? 'rząd ' + m.max_strahler_order : '');
        setMeta('acc-landcover', lcCount ? lcCount + ' ' + plural(lcCount, 'klasa', 'klasy', 'klas') : '');
        setMeta('acc-hsg', hsgCount ? hsgCount + ' ' + plural(hsgCount, 'grupa', 'grupy', 'grup') : '');
        renderSummary(m);
    }

    /**
     * Display the delineated watershed in the panel: its parameters and the page
     * context („Zlewnia … km²”, its outlet).
     */
    function displayParameters(data) {
        renderParameters(data.watershed);
        state.sectionsShowWatershed = true;
        displayParametersContext(data);
    }

    // ======== Results panel (right column / phone sheet, see shell.js) ========

    function showPanel() {
        Hydrograf.shell.open('right');
    }

    function hidePanel() {
        Hydrograf.shell.close('right');
    }

    /** Show the loading state, the error and the bin of the view the panel serves. */
    function renderStatus() {
        var v = views[state.view];
        Hydrograf.map.setLoadingCursor(v.loading);
        els.loading.classList.toggle('d-none', !v.loading);
        els.error.classList.toggle('d-none', !v.error);
        els.errorMessage.textContent = v.error;
        els.clear.disabled = !v.clearable;
    }

    /**
     * The panel shows its instruction (nothing to clear) or a selection: its
     * loading state, error or result, which the clear button removes.
     */
    function setInstruction(shown) {
        els.instruction.classList.toggle('d-none', !shown);
        views.watershed.clearable = !shown;
        if (state.view === 'watershed') renderStatus();
    }

    function setLoading(loading) {
        views.watershed.loading = loading;
        if (loading) {
            views.watershed.error = '';
            showPanel();
            setInstruction(false);
            els.results.classList.add('d-none');
        }
        if (state.view === 'watershed') renderStatus();
    }

    function showError(msg) {
        views.watershed.error = msg;
        showPanel();
        setInstruction(false);
    }

    function hideError() {
        views.watershed.error = '';
        if (state.view === 'watershed') renderStatus();
    }

    /**
     * Drop the pending watershed selection: its preview leaves the map and
     * its answers are ignored.
     */
    function cancelSelection() {
        state.selection += 1;
        if (_clickDebounceTimer) {
            clearTimeout(_clickDebounceTimer);
            _clickDebounceTimer = null;
        }
        Hydrograf.map.clearDelineatePreview();
    }

    /**
     * Clear the selection: the result, the error and the map overlays, then
     * close the panel. Used by the clear button and a double Escape; the ×
     * of the panel only hides it, so the result stays. In the option „Sieć zlewni”
     * the bin removes the points and the network instead (js/network.js).
     */
    function closeResults() {
        if (state.view === 'network') {
            if (Hydrograf.network) Hydrograf.network.clear();
            return;
        }
        cancelSelection();
        setLoading(false);
        Hydrograf.map.clearWatershed();
        Hydrograf.map.clearSelectionBoundary();
        Hydrograf.map.clearProfileLine();
        var autoInfo = document.getElementById('panel-auto-select-info');
        if (autoInfo) autoInfo.classList.add('d-none');
        if (Hydrograf.profile) Hydrograf.profile.hideProfilePanel();
        state.currentWatershed = null;
        state.currentStream = null;
        if (Hydrograf.handoff) Hydrograf.handoff.showWatershed(null);
        els.results.classList.add('d-none');
        views.watershed.error = '';
        setInstruction(true);
        setContext('', '');
        hidePanel();
    }

    /**
     * Switch what the panel and the map serve: the network in the option „Sieć
     * zlewni” of „Wybierz zlewnię”, the watershed otherwise. Each view keeps its
     * loading state, error and result; the sections of the parameters return to
     * the watershed when an element of the network had them.
     * @param {'watershed'|'network'} view
     */
    function setView(view) {
        if (view === state.view) return;
        if (view === 'network') {
            // A pending selection would fill the sections the network now uses
            cancelSelection();
            if (views.watershed.loading) {
                views.watershed.loading = false;
                if (!state.currentWatershed) setInstruction(true);
            }
        }
        state.view = view;
        var texts = VIEW_TEXTS[view];
        els.panel.dataset.view = view;
        els.title.textContent = texts.title;
        els.openResults.textContent = texts.sheet;
        els.loadingText.textContent = texts.loading;
        els.clear.setAttribute('aria-label', texts.clear);
        els.clear.title = texts.clear;
        els.close.setAttribute('aria-label', texts.close);
        Hydrograf.map.setWatershedShown(view === 'watershed');
        if (Hydrograf.handoff) Hydrograf.handoff.showView(view);
        if (view === 'network') {
            if (Hydrograf.network) Hydrograf.network.enter();
        } else {
            if (Hydrograf.network) Hydrograf.network.leave();
            showElementParameters(null);
            restoreWatershedSections();
        }
        renderStatus();
    }

    /** The sections and the context of the watershed again, after the network had them. */
    function restoreWatershedSections() {
        var data = state.currentWatershed;
        if (data) {
            if (!state.sectionsShowWatershed) displayParameters(data);
            else displayParametersContext(data);
        } else if (state.currentStream) {
            displayStreamInfo(state.currentStream);
        } else {
            setContext('', '');
        }
    }

    /** The context of the delineated watershed in the top bar and the panel head. */
    function displayParametersContext(data) {
        var m = data.watershed.morphometry || {};
        var o = data.watershed.outlet;
        setContext(
            m.area_km2 != null ? 'Zlewnia ' + formatValue(m.area_km2, 'km²', 2) : 'Zlewnia',
            'ujście ' + formatValue(o.latitude, '°N', 5) + ', ' + formatValue(o.longitude, '°E', 5)
        );
    }

    /**
     * The network's loading state, error and bin (js/network.js): `status` holds the
     * fields that change. Loading or an error opens the panel.
     * @param {{loading?: boolean, error?: string, clearable?: boolean}} status
     */
    function setNetworkStatus(status) {
        var v = views.network;
        if (status.loading !== undefined) v.loading = status.loading;
        if (status.error !== undefined) v.error = status.error || '';
        if (status.clearable !== undefined) v.clearable = status.clearable;
        if (state.view !== 'network') return;
        if (status.loading || status.error) showPanel();
        renderStatus();
    }

    /**
     * The parameters of an element of the network in the sections of „Wybierz
     * zlewnię” (without the hietogram and the hydrograph, which the network view
     * hides); null hides the sections.
     * @param {Object|null} watershed - the element's WatershedResponse
     */
    function showElementParameters(watershed) {
        if (watershed) {
            renderParameters(watershed);
            state.sectionsShowWatershed = false;
            els.panel.dataset.element = '';
        } else {
            delete els.panel.dataset.element;
        }
    }

    /**
     * Handle map click with 300ms debounce.
     */
    function onMapClick(lat, lng) {
        if (Hydrograf.diagnostics) {
            Hydrograf.diagnostics.log('map_click', { lat: lat, lng: lng, mode: state.clickMode });
        }

        // Browse mode — do nothing
        if (state.clickMode === 'browse') return;

        // Identify mode — read what is known at the point (js/identify.js)
        if (state.clickMode === 'identify') {
            if (Hydrograf.identify) Hydrograf.identify.identifyAt(lat, lng);
            return;
        }

        // Profile mode — re-activate drawing if not currently drawing
        if (state.clickMode === 'profile') {
            if (!Hydrograf.map.isDrawing || !Hydrograf.map.isDrawing()) {
                if (Hydrograf.profile) Hydrograf.profile.activateDrawProfile();
            }
            return;
        }

        // Check drawing mode
        if (Hydrograf.map.isDrawing && Hydrograf.map.isDrawing()) return;

        var inPoland = lat >= BOUNDS.latMin && lat <= BOUNDS.latMax &&
            lng >= BOUNDS.lngMin && lng <= BOUNDS.lngMax;
        var outside = 'Kliknij w granicach Polski (49–55°N, 14–24.2°E).';

        // „Wybierz zlewnię” → „Sieć zlewni”: the click places the closing section or the next point (js/network.js)
        if (state.clickMode === 'network') {
            if (!inPoland) setNetworkStatus({ error: outside });
            else if (Hydrograf.network) Hydrograf.network.addPoint(lat, lng);
            return;
        }

        if (!inPoland) {
            showError(outside);
            return;
        }

        // A new point replaces the pending selection at once; the debounce
        // prevents double API calls from rapid clicking.
        cancelSelection();
        var selection = state.selection;
        _clickDebounceTimer = setTimeout(function () {
            _clickDebounceTimer = null;
            onSelectClick(lat, lng, selection);
        }, 300);
    }

    /**
     * Handle stream selection click: the preview (sub-catchments filling up
     * the network) and the delineation are requested together; the result
     * replaces the preview whenever it arrives.
     */
    async function onSelectClick(lat, lng, selection) {
        hideError();
        setLoading(true);
        state.currentWatershed = null;
        state.currentStream = null;
        if (Hydrograf.handoff) Hydrograf.handoff.showWatershed(null);

        // Clear previous watershed display
        Hydrograf.map.clearWatershed();
        Hydrograf.map.clearSelectionBoundary();

        // Clear auto-select banner before new request
        var autoInfo = document.getElementById('panel-auto-select-info');
        if (autoInfo) autoInfo.classList.add('d-none');

        // Determine active threshold from streams layer
        var threshold = Hydrograf.map.getStreamsThreshold() || 100000;
        var settled = false;
        function isCurrent() { return selection === state.selection; }

        Hydrograf.api.previewWatershed(lat, lng, threshold)
            .then(function (preview) {
                if (isCurrent() && !settled) Hydrograf.map.showDelineatePreview(preview.catchments);
            })
            .catch(function () { /* no preview; the delineation reports errors */ });

        try {
            var data = await Hydrograf.api.delineateWatershed(lat, lng, threshold);
            if (!isCurrent()) return;
            settled = true;
            Hydrograf.map.clearDelineatePreview();

            // Show selection boundary
            if (data.watershed && data.watershed.boundary_geojson) {
                Hydrograf.map.showSelectionBoundary(data.watershed.boundary_geojson);
            }

            // Show info banner if threshold was escalated (the API words it in m²)
            if (data.info_message) {
                var autoMsg = document.getElementById('auto-select-message');
                if (autoMsg) {
                    autoMsg.textContent = 'Zlewnie cząstkowe niedostępne dla progu '
                        + Hydrograf.layers.formatThreshold(threshold) + '. Zaznaczono z progu '
                        + Hydrograf.layers.formatThreshold(data.display_threshold_m2) + '.';
                }
                if (autoInfo) autoInfo.classList.remove('d-none');
            }

            // Display full watershed stats if available, otherwise fallback to stream info
            if (data.watershed) {
                state.currentWatershed = data;
                state.clickLat = lat;
                state.clickLng = lng;

                // Show outlet marker (but NOT watershed polygon — selection boundary is enough)
                var outlet = data.watershed.outlet;
                Hydrograf.map.showOutlet(outlet.latitude, outlet.longitude, outlet.elevation_m);

                // Show main channel with BDOT highlighting
                if (data.watershed.main_stream_geojson) {
                    Hydrograf.map.showMainChannel(data.watershed.main_stream_geojson);
                }

                // The hydrograph metadata of the previous watershed goes with it
                els.hydrographInfo.innerHTML = '';
                displayParameters(data);

                // Show flow path overlays on map
                Hydrograf.map.showLongestFlowPath(data.watershed.longest_flow_path_geojson);
                Hydrograf.map.showDivideFlowPath(data.watershed.divide_flow_path_geojson);
            } else if (data.stream) {
                state.currentStream = data.stream;
                displayStreamInfo(data.stream);
            }

            // Show/hide hietogram + hydrograph sections based on API response
            var hydroAvail2 = data.watershed && data.watershed.hydrograph_available;
            ['acc-hietogram', 'acc-hydrograph'].forEach(function (id) {
                var section = document.getElementById(id);
                if (section) {
                    if (hydroAvail2) {
                        section.classList.remove('d-none');
                    } else {
                        section.classList.add('d-none');
                    }
                }
            });
            els.results.classList.remove('d-none');

            // Hand-off to Hydrolog: the watershed now, its hydrograph when it comes
            if (Hydrograf.handoff) Hydrograf.handoff.showWatershed(data);

            // Auto-generate hydrograph on first load
            if (hydroAvail2 && Hydrograf.hydrograph) {
                Hydrograf.hydrograph.generateHydrograph();
            }
        } catch (err) {
            if (!isCurrent()) return;
            settled = true;
            Hydrograf.map.clearDelineatePreview();
            Hydrograf.map.clearSelectionBoundary();
            state.currentWatershed = null;
            if (Hydrograf.handoff) Hydrograf.handoff.showWatershed(null);
            showError(err.message);
        } finally {
            if (isCurrent()) setLoading(false);
        }
    }

    /**
     * Display selected stream info in the results panel.
     */
    function displayStreamInfo(stream) {
        state.sectionsShowWatershed = true;
        fillTable(els.paramsBasic, [
            ['Segment', String(stream.segment_idx)],
            ['Rząd Strahlera', stream.strahler_order != null ? String(stream.strahler_order) : '—'],
            ['Długość', stream.length_m != null ? (stream.length_m / 1000).toFixed(2) + ' km' : '—'],
            ['Zlewnia', stream.upstream_area_km2 != null ? stream.upstream_area_km2.toFixed(2) + ' km²' : '—'],
        ]);

        // Collapse other sections
        ['acc-shape', 'acc-relief', 'acc-drainage', 'acc-landcover',
         'acc-hietogram', 'acc-hydrograph'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.open = false;
        });
        els.summary.classList.add('d-none');
        setContext('Ciek ' + stream.segment_idx, '');

        // Clear charts
        Hydrograf.charts.destroyChart('chart-hypsometric');
        Hydrograf.charts.destroyChart('chart-landcover');

        // Clear relief table
        if (els.paramsRelief) els.paramsRelief.innerHTML = '';
    }

    var MODE_HINTS = {
        browse: 'Przesuwaj i przybliżaj mapę',
        select: 'Kliknij na mapie w pobliżu cieku',
        network: 'Kliknij przekrój zamykający na cieku, potem punkty: ujścia dopływów i wodowskazy.',
        profile: 'Kliknij na mapie, aby zacząć rysować profil',
        identify: 'Kliknij na mapie, aby odczytać dane o punkcie',
    };

    /**
     * Show a radio of a segmented control as checked or not (roving tabindex).
     * @param {HTMLElement} btn
     * @param {boolean} on
     */
    function checkRadio(btn, on) {
        btn.classList.toggle('on', on);
        btn.setAttribute('aria-checked', String(on));
        btn.tabIndex = on ? 0 : -1;
    }

    /**
     * Switch click mode between 'browse', 'select', 'network', 'profile' and 'identify'.
     * 'select' and 'network' are the options „Jedna zlewnia” and „Sieć zlewni” of the
     * mode „Wybierz zlewnię”: its button is on for both, the tools over the map
     * (#select-tools) choose between them and the mode remembers the last one.
     */
    function setClickMode(mode) {
        state.clickMode = mode;
        if (Hydrograf.diagnostics) {
            Hydrograf.diagnostics.log('mode_change', { mode: mode });
        }

        var picking = mode === 'select' || mode === 'network';
        if (picking) state.selectTarget = mode;
        ['browse', 'select', 'profile', 'identify'].forEach(function (m) {
            checkRadio(document.getElementById('mode-' + m), m === mode || (m === 'select' && picking));
        });
        checkRadio(els.selectWatershed, state.selectTarget === 'select');
        checkRadio(els.selectNetwork, state.selectTarget === 'network');
        els.selectTools.hidden = !picking;
        els.hint.textContent = MODE_HINTS[mode];
        els.mapWrap.dataset.mode = mode;

        // Leaving profile mode cancels drawing and closes the profile drawer
        if (mode !== 'profile' && Hydrograf.profile) {
            Hydrograf.profile.hideProfilePanel();
        }

        // Leaving identify mode removes the point card and its marker
        if (mode !== 'identify' && Hydrograf.identify) {
            Hydrograf.identify.close();
        }

        // The panel and the map serve the network in its option, the watershed otherwise
        setView(mode === 'network' ? 'network' : 'watershed');

        // Panels: browsing frees the map, selecting a watershed or a network shows
        // the results column, profile and identify modes on phones drop any sheet
        // that would cover the profile drawer or the point card.
        if (mode === 'browse') {
            Hydrograf.shell.close('right');
        } else if (picking) {
            if (!Hydrograf.shell.isPhone()) Hydrograf.shell.open('right');
        } else if (Hydrograf.shell.isPhone()) {
            Hydrograf.shell.close('left');
            Hydrograf.shell.close('right');
        }

        // Cursor: crosshair for action modes, grab for browse
        var container = document.querySelector('.leaflet-container');
        if (container) {
            container.classList.toggle('cursor-crosshair', mode !== 'browse');
        }
    }

    function enterProfileMode() {
        setClickMode('profile');
        if (Hydrograf.profile) Hydrograf.profile.activateDrawProfile();
    }

    /**
     * Get current watershed data (for use by other modules).
     */
    function getCurrentWatershed() {
        return state.currentWatershed;
    }

    function init() {
        els = {
            instruction: document.getElementById('panel-instruction'),
            loading: document.getElementById('panel-loading'),
            error: document.getElementById('panel-error'),
            errorMessage: document.getElementById('error-message'),
            results: document.getElementById('panel-results'),
            summary: document.getElementById('results-summary'),
            paramsBasic: document.getElementById('params-basic'),
            paramsShape: document.getElementById('params-shape'),
            paramsRelief: document.getElementById('params-relief'),
            paramsDrainage: document.getElementById('params-drainage'),
            hydrographInfo: document.getElementById('hydrograph-info'),
            crumb: document.getElementById('crumb-context'),
            crumbSep: document.getElementById('crumb-sep'),
            resultsSub: document.getElementById('results-sub'),
            clear: document.getElementById('results-clear'),
            close: document.getElementById('results-close'),
            hint: document.getElementById('map-hint-text'),
            mapWrap: document.getElementById('map-wrap'),
            panel: document.getElementById('results-panel'),
            title: document.getElementById('results-title'),
            openResults: document.getElementById('open-results'),
            loadingText: document.getElementById('panel-loading-text'),
            selectTools: document.getElementById('select-tools'),
            selectWatershed: document.getElementById('select-watershed'),
            selectNetwork: document.getElementById('select-network'),
        };
        els.panel.dataset.view = state.view;

        // Mode toolbar and rail
        document.getElementById('mode-browse').addEventListener('click', function () {
            setClickMode('browse');
        });
        document.getElementById('mode-select').addEventListener('click', function () {
            setClickMode(state.selectTarget);
        });
        els.selectWatershed.addEventListener('click', function () {
            setClickMode('select');
        });
        els.selectNetwork.addEventListener('click', function () {
            setClickMode('network');
        });
        document.getElementById('mode-profile').addEventListener('click', enterProfileMode);
        document.getElementById('mode-identify').addEventListener('click', function () {
            setClickMode('identify');
        });
        document.getElementById('rail-map').addEventListener('click', function (e) {
            e.preventDefault();
            if (state.clickMode === 'profile') setClickMode('browse');
        });

        // Panel controls: × hides the panel (the result stays on the map and
        // the "Zlewnia" button brings it back), the clear button removes it
        els.close.addEventListener('click', hidePanel);
        els.clear.addEventListener('click', closeResults);

        // Escape: cancel drawing first, then close the point card, then
        // single = hide panel, double = clear result (like the clear button);
        // in the option „Sieć zlewni” it only hides the panel: the points stay
        var _escTimer = null;
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape') return;

            // A dialog is open (feedback, welcome) — the native <dialog> handles Escape alone
            if (document.querySelector('dialog[open]')) return;

            // Drawing check FIRST — cancel active drawing and stop
            if (Hydrograf.map && Hydrograf.map.isDrawing && Hydrograf.map.isDrawing()) {
                Hydrograf.map.cancelDrawing();
                return;
            }

            // An open point card closes next (identify mode stays on)
            if (Hydrograf.identify && Hydrograf.identify.isOpen()) {
                Hydrograf.identify.close();
                return;
            }

            if (state.view === 'network') {
                hidePanel();
                return;
            }

            if (!state.currentWatershed && !Hydrograf.shell.isOpen('right')) return;

            if (_escTimer) {
                clearTimeout(_escTimer);
                _escTimer = null;
                closeResults();
            } else {
                hidePanel();
                _escTimer = setTimeout(function () { _escTimer = null; }, 400);
            }
        });

        // Profile drawer: closing it leaves profile mode
        document.getElementById('profile-close').addEventListener('click', function () {
            setClickMode('browse');
        });

        // Try loading pre-generated tile metadata
        fetch('/tiles/tiles_metadata.json')
            .then(function (res) {
                if (!res.ok) throw new Error('No pre-generated tiles');
                return res.json();
            })
            .then(function (meta) { window.Hydrograf._tilesMeta = meta; })
            .catch(function () { /* Use API fallback */ });

        // Init map
        Hydrograf.map.init(onMapClick);

        // Init layers panel (delegated to layers.js)
        if (Hydrograf.layers) {
            Hydrograf.layers.init();
        }

        // Init profile module
        if (Hydrograf.profile) {
            Hydrograf.profile.init();
        }

        // Init identify module (point card of the identify mode)
        if (Hydrograf.identify) {
            Hydrograf.identify.init();
        }

        // Init the option „Sieć zlewni” of „Wybierz zlewnię” (its points, network and panel section)
        if (Hydrograf.network) {
            Hydrograf.network.init();
        }

        // Init hydrograph module
        if (Hydrograf.hydrograph) {
            Hydrograf.hydrograph.init();
        }

        // Export of the hietogram and its PMAXTP points (Hietogram section)
        if (Hydrograf.rainExport) {
            Hydrograf.rainExport.init();
        }

        // Init depressions module
        if (Hydrograf.depressions) {
            Hydrograf.depressions.init();
        }

        // Init feedback module
        if (Hydrograf.feedback) {
            Hydrograf.feedback.init();
        }

        // Welcome dialog (first visit, Instrukcja in the top bar)
        if (Hydrograf.welcome) {
            Hydrograf.welcome.init();
        }
    }

    document.addEventListener('DOMContentLoaded', init);

    window.Hydrograf.app = {
        init: init,
        getCurrentWatershed: getCurrentWatershed,
        getClickCoords: function () { return { lat: state.clickLat, lng: state.clickLng }; },
        getClickMode: function () { return state.clickMode; },
        showPanel: showPanel,
        // The panel in the view of „Sieć zlewni” (js/network.js)
        setContext: setContext,
        setNetworkStatus: setNetworkStatus,
        showElementParameters: showElementParameters,
    };
})();
