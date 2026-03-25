/**
 * Hydrograf Application module.
 *
 * Orchestrates map clicks, API calls, floating results panel, and parameter display.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var state = {
        isLoading: false,
        currentWatershed: null,
        clickLat: null,
        clickLng: null,
        clickMode: 'browse',
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

    function buildRow(label, value) {
        var tr = document.createElement('tr');
        var tdLabel = document.createElement('td');
        var tdValue = document.createElement('td');
        tdLabel.textContent = label;
        tdValue.textContent = value;
        tr.appendChild(tdLabel);
        tr.appendChild(tdValue);
        return tr;
    }

    function fillTable(tbody, rows) {
        tbody.innerHTML = '';
        rows.forEach(function (row) {
            if (row[1] !== '—') {
                tbody.appendChild(buildRow(row[0], row[1]));
            }
        });
    }

    /**
     * Display watershed parameters in the floating panel.
     */
    function displayParameters(data) {
        var w = data.watershed;
        var m = w.morphometry || {};
        var o = w.outlet;

        fillTable(els.paramsBasic, [
            ['Powierzchnia', formatValue(m.area_km2, 'km²', 2)],
            ['Obwód', formatValue(m.perimeter_km, 'km', 2)],
            ['Długość', formatValue(m.length_km, 'km', 2)],
            ['Szerokość średnia', formatValue(m.mean_width_km, 'km', 2)],
            ['Wys. min', formatValue(m.elevation_min_m, 'm n.p.m.', 1)],
            ['Wys. max', formatValue(m.elevation_max_m, 'm n.p.m.', 1)],
            ['Wys. średnia', formatValue(m.elevation_mean_m, 'm n.p.m.', 1)],
            ['Spadek średni', formatSlope(m.mean_slope_m_per_m)],
            ['Długość cieku gł.', formatValue(m.channel_length_km, 'km', 2)],
            ['  w tym ciek BDOT', formatValue(m.real_channel_length_km, 'km', 2)],
            ['Droga spływu', formatValue(m.hydraulic_length_km, 'km', 2)],
            ['Spadek cieku gł.', formatSlope(m.channel_slope_m_per_m)],
            ['Droga spływu', formatValue(m.longest_flow_path_km, 'km', 2)],
            ['Droga z działu', formatValue(m.divide_flow_path_km, 'km', 2)],
            ['CN', m.cn !== null && m.cn !== undefined ? String(m.cn) : '—'],
            ['Ujście φ', formatValue(o.latitude, '°N', 6)],
            ['Ujście λ', formatValue(o.longitude, '°E', 6)],
            ['Ujście H', formatValue(o.elevation_m, 'm n.p.m.', 1)],
        ]);

        fillTable(els.paramsShape, [
            ['Wsp. zwartości Kc', formatRatio(m.compactness_coefficient, 3)],
            ['Wsp. kołowości Rc', formatRatio(m.circularity_ratio, 3)],
            ['Wsp. wydłużenia Re', formatRatio(m.elongation_ratio, 3)],
            ['Wsp. kształtu Ff', formatRatio(m.form_factor, 3)],
        ]);

        fillTable(els.paramsRelief, [
            ['Wsp. rzeźbowy Rh', formatRatio(m.relief_ratio, 4)],
            ['Całka hipsometryczna HI', formatRatio(m.hypsometric_integral, 3)],
        ]);

        fillTable(els.paramsDrainage, [
            ['Gęstość sieci Dd', m.drainage_density_km_per_km2 != null
                ? formatValue(m.drainage_density_km_per_km2, 'km/km²', 2)
                : 'brak cieków BDOT'],
            ['Częstość cieków Fs', m.stream_frequency_per_km2 != null
                ? formatValue(m.stream_frequency_per_km2, '1/km²', 2)
                : 'brak cieków BDOT'],
            ['Liczba chropowatoś. Rn', m.ruggedness_number != null
                ? formatRatio(m.ruggedness_number, 3)
                : 'brak cieków BDOT'],
            ['Max rząd Strahlera', m.max_strahler_order != null
                ? String(m.max_strahler_order)
                : 'brak cieków BDOT'],
            ['Pokrycie BDOT', m.real_channel_length_km != null && m.channel_length_km
                ? (100 * m.real_channel_length_km / m.channel_length_km).toFixed(0) + '%'
                : '—'],
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

        // Hydrograph section — show conditionally based on API response
        els.hydrographInfo.innerHTML = '';

    }

    // ======== Docked panel management ========

    function showPanel() {
        els.panel.classList.remove('d-none');
        expandPanel();
    }

    function hidePanel() {
        els.panel.classList.add('d-none');
        els.panel.classList.add('results-hidden');
        els.toggleBtn.classList.add('d-none');
        els.toggleBtn.classList.remove('results-open');
        Hydrograf.map.shiftZoomControls(false);
    }

    function expandPanel() {
        els.panel.classList.remove('results-hidden');
        els.toggleBtn.classList.remove('d-none');
        els.toggleBtn.classList.add('results-open');
        els.toggleBtn.innerHTML = '&#8250;';
        Hydrograf.map.shiftZoomControls(true);
    }

    function collapsePanel() {
        els.panel.classList.add('results-hidden');
        els.toggleBtn.classList.remove('results-open');
        els.toggleBtn.innerHTML = '&#8249;';
        Hydrograf.map.shiftZoomControls(false);
    }

    function togglePanel() {
        if (els.panel.classList.contains('results-hidden')) {
            expandPanel();
        } else {
            collapsePanel();
        }
    }

    function setLoading(loading) {
        state.isLoading = loading;
        Hydrograf.map.setLoadingCursor(loading);

        if (loading) {
            showPanel();
            els.instruction.classList.add('d-none');
            els.loading.classList.remove('d-none');
            els.error.classList.add('d-none');
            els.results.classList.add('d-none');
            Hydrograf.map.disableClick();
        } else {
            els.loading.classList.add('d-none');
            Hydrograf.map.enableClick();
        }
    }

    function showError(msg) {
        showPanel();
        els.instruction.classList.add('d-none');
        els.error.classList.remove('d-none');
        els.errorMessage.textContent = msg;
    }

    function hideError() {
        els.error.classList.add('d-none');
    }

    /**
     * Close results panel and clear all map overlays.
     * Used by "×" button and Escape key.
     */
    function closeResults() {
        Hydrograf.map.clearWatershed();
        Hydrograf.map.clearSelectionBoundary();
        Hydrograf.map.clearProfileLine();
        var autoInfo = document.getElementById('panel-auto-select-info');
        if (autoInfo) autoInfo.classList.add('d-none');
        if (Hydrograf.profile) Hydrograf.profile.hideProfilePanel();
        state.currentWatershed = null;
        hidePanel();
    }

    /**
     * Handle map click with 300ms debounce.
     */
    function onMapClick(lat, lng) {
        if (state.isLoading) return;

        // Browse mode — do nothing
        if (state.clickMode === 'browse') return;

        // Profile mode — re-activate drawing if not currently drawing
        if (state.clickMode === 'profile') {
            if (!Hydrograf.map.isDrawing || !Hydrograf.map.isDrawing()) {
                if (Hydrograf.profile) Hydrograf.profile.activateDrawProfile();
            }
            return;
        }

        // Check drawing mode
        if (Hydrograf.map.isDrawing && Hydrograf.map.isDrawing()) return;

        if (lat < BOUNDS.latMin || lat > BOUNDS.latMax ||
            lng < BOUNDS.lngMin || lng > BOUNDS.lngMax) {
            showError('Kliknij w granicach Polski (49–55°N, 14–24.2°E).');
            return;
        }

        // Debounce: prevent double API calls from rapid clicking
        if (_clickDebounceTimer) clearTimeout(_clickDebounceTimer);
        _clickDebounceTimer = setTimeout(function () {
            _clickDebounceTimer = null;
            onSelectClick(lat, lng);
        }, 300);
    }

    /**
     * Handle stream selection click.
     */
    async function onSelectClick(lat, lng) {
        hideError();
        setLoading(true);
        state.currentWatershed = null;

        // Clear previous watershed display
        Hydrograf.map.clearWatershed();

        // Clear auto-select banner before new request
        var autoInfo = document.getElementById('panel-auto-select-info');
        if (autoInfo) autoInfo.classList.add('d-none');

        // Determine active threshold from streams layer
        var threshold = Hydrograf.map.getStreamsThreshold() || 100000;

        try {
            var data = await Hydrograf.api.selectStream(lat, lng, threshold);

            // Show selection boundary
            Hydrograf.map.showSelectionBoundary(data.boundary_geojson);

            // Show info banner if threshold was escalated
            if (data.info_message) {
                var autoMsg = document.getElementById('auto-select-message');
                if (autoMsg) autoMsg.textContent = data.info_message;
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

                displayParameters(data);

                // Show flow path overlays on map
                Hydrograf.map.showLongestFlowPath(data.watershed.longest_flow_path_geojson);
                Hydrograf.map.showDivideFlowPath(data.watershed.divide_flow_path_geojson);
            } else {
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

            // Auto-generate hydrograph on first load
            if (hydroAvail2 && Hydrograf.hydrograph) {
                Hydrograf.hydrograph.generateHydrograph();
            }
        } catch (err) {
            Hydrograf.map.clearSelectionBoundary();
            state.currentWatershed = null;
            showError(err.message);
        } finally {
            setLoading(false);
        }
    }

    /**
     * Display selected stream info in the results panel.
     */
    function displayStreamInfo(stream) {
        fillTable(els.paramsBasic, [
            ['Segment', String(stream.segment_idx)],
            ['Rząd Strahlera', stream.strahler_order != null ? String(stream.strahler_order) : '—'],
            ['Długość', stream.length_m != null ? (stream.length_m / 1000).toFixed(2) + ' km' : '—'],
            ['Zlewnia', stream.upstream_area_km2 != null ? stream.upstream_area_km2.toFixed(2) + ' km²' : '—'],
        ]);

        // Hide other accordions
        ['acc-shape', 'acc-relief', 'acc-drainage', 'acc-landcover',
         'acc-hietogram', 'acc-hydrograph'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.classList.add('collapsed');
        });

        // Clear charts
        Hydrograf.charts.destroyChart('chart-hypsometric');
        Hydrograf.charts.destroyChart('chart-landcover');

        // Clear relief table
        if (els.paramsRelief) els.paramsRelief.innerHTML = '';
    }

    function removeRetryButton() {
        var existing = document.getElementById('health-retry-btn');
        if (existing) existing.remove();
    }

    function showRetryButton() {
        removeRetryButton();
        var statusEl = document.getElementById('system-status');
        if (!statusEl || !statusEl.parentNode) return;
        var retryBtn = document.createElement('button');
        retryBtn.id = 'health-retry-btn';
        retryBtn.className = 'btn btn-sm btn-outline-warning ms-2';
        retryBtn.textContent = 'Ponów';
        retryBtn.addEventListener('click', function () { checkSystemHealth(); });
        statusEl.parentNode.insertBefore(retryBtn, statusEl.nextSibling);
    }

    async function checkSystemHealth() {
        try {
            var health = await Hydrograf.api.checkHealth();
            var statusEl = document.getElementById('system-status');
            if (health.status === 'healthy') {
                statusEl.textContent = 'System: OK';
                statusEl.className = 'navbar-text d-none d-md-inline text-light';
                removeRetryButton();
            } else {
                statusEl.textContent = 'System: problem z bazą danych';
                statusEl.className = 'navbar-text d-none d-md-inline text-warning';
                showRetryButton();
            }
        } catch {
            var statusEl2 = document.getElementById('system-status');
            statusEl2.textContent = 'System: niedostępny';
            statusEl2.className = 'navbar-text d-none d-md-inline text-warning';
            showRetryButton();
        }
    }

    /**
     * Toggle layers panel visibility.
     */
    function toggleLayers() {
        var panel = document.getElementById('layers-panel');
        var btn = document.getElementById('layers-toggle');
        panel.classList.toggle('layers-hidden');
        btn.classList.toggle('layers-open');
        var isOpen = !panel.classList.contains('layers-hidden');
        btn.setAttribute('aria-expanded', String(isOpen));
        btn.innerHTML = isOpen ? '&#8249;' : '&#8250;';
    }

    /**
     * Switch click mode between 'browse', 'select', and 'profile'.
     */
    function setClickMode(mode) {
        state.clickMode = mode;

        // Update button classes
        var btnBrowse = document.getElementById('mode-browse');
        var btnSelect = document.getElementById('mode-select');
        var btnProfile = document.getElementById('mode-profile');
        [btnBrowse, btnSelect, btnProfile].forEach(function (btn) {
            if (!btn) return;
            var m = btn.id.replace('mode-', '');
            btn.classList.toggle('mode-btn-active', m === mode);
            btn.setAttribute('aria-checked', String(m === mode));
        });

        // Cancel active drawing when leaving profile mode
        if (mode !== 'profile' && Hydrograf.map.isDrawing()) {
            Hydrograf.map.cancelDrawing();
        }

        // Cursor: crosshair for action modes, grab for browse
        var container = document.querySelector('.leaflet-container');
        if (container) {
            container.classList.toggle('cursor-crosshair', mode !== 'browse');
        }
    }

    /**
     * Get current watershed data (for use by other modules).
     */
    function getCurrentWatershed() {
        return state.currentWatershed;
    }

    function init() {
        els = {
            panel: document.getElementById('results-panel'),
            toggleBtn: document.getElementById('results-toggle-btn'),
            instruction: document.getElementById('panel-instruction'),
            loading: document.getElementById('panel-loading'),
            error: document.getElementById('panel-error'),
            errorMessage: document.getElementById('error-message'),
            results: document.getElementById('panel-results'),
            paramsBasic: document.getElementById('params-basic'),
            paramsShape: document.getElementById('params-shape'),
            paramsRelief: document.getElementById('params-relief'),
            paramsDrainage: document.getElementById('params-drainage'),
            hydrographInfo: document.getElementById('hydrograph-info'),
        };

        // Hide hietogram + hydrograph sections initially (shown conditionally when data is available)
        ['acc-hietogram', 'acc-hydrograph'].forEach(function (id) {
            var section = document.getElementById(id);
            if (section) section.classList.add('d-none');
        });

        // Layers toggle
        document.getElementById('layers-toggle').addEventListener('click', toggleLayers);

        // Mode toolbar
        document.getElementById('mode-browse').addEventListener('click', function () {
            setClickMode('browse');
        });
        document.getElementById('mode-select').addEventListener('click', function () {
            setClickMode('select');
        });
        document.getElementById('mode-profile').addEventListener('click', function () {
            setClickMode('profile');
            if (Hydrograf.profile) Hydrograf.profile.activateDrawProfile();
        });

        // Accordion collapse/expand (replaces inline onclick)
        document.querySelectorAll('.glass-accordion-header').forEach(function (header) {
            header.setAttribute('tabindex', '0');
            header.addEventListener('click', function () {
                var acc = this.parentElement;
                acc.classList.toggle('collapsed');
                if (!acc.classList.contains('collapsed')) {
                    var canvas = acc.querySelector('canvas');
                    if (canvas && Hydrograf.charts) {
                        setTimeout(function () { Hydrograf.charts.resizeChart(canvas.id); }, 50);
                    }
                }
            });
            header.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    var acc = this.parentElement;
                    acc.classList.toggle('collapsed');
                    if (!acc.classList.contains('collapsed')) {
                        var canvas = acc.querySelector('canvas');
                        if (canvas && Hydrograf.charts) {
                            setTimeout(function () { Hydrograf.charts.resizeChart(canvas.id); }, 50);
                        }
                    }
                }
            });
        });

        // Panel controls
        document.getElementById('results-close').addEventListener('click', closeResults);
        document.getElementById('results-toggle-btn').addEventListener('click', togglePanel);

        // Escape: cancel drawing first, then single = collapse, double = close (like ×)
        var _escTimer = null;
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape') return;

            // Drawing check FIRST — cancel active drawing and stop
            if (Hydrograf.map && Hydrograf.map.isDrawing && Hydrograf.map.isDrawing()) {
                Hydrograf.map.cancelDrawing();
                return;
            }

            if (els.panel.classList.contains('d-none')) return;

            if (_escTimer) {
                clearTimeout(_escTimer);
                _escTimer = null;
                closeResults();
            } else {
                if (!els.panel.classList.contains('results-hidden')) {
                    collapsePanel();
                }
                _escTimer = setTimeout(function () { _escTimer = null; }, 400);
            }
        });

        // Profile panel: close button + draggable
        var profilePanel = document.getElementById('profile-panel');
        var profileClose = document.getElementById('profile-close');
        if (profileClose) {
            profileClose.addEventListener('click', function () {
                if (Hydrograf.profile) Hydrograf.profile.hideProfilePanel();
            });
        }
        if (profilePanel && window.innerWidth > 768) {
            Hydrograf.draggable.makeDraggable(
                profilePanel,
                document.getElementById('profile-header')
            );
        }

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

        // Init hydrograph module
        if (Hydrograf.hydrograph) {
            Hydrograf.hydrograph.init();
        }

        // Init depressions module
        if (Hydrograf.depressions) {
            Hydrograf.depressions.init();
        }

        checkSystemHealth();
    }

    document.addEventListener('DOMContentLoaded', init);

    window.Hydrograf.app = {
        init: init,
        getCurrentWatershed: getCurrentWatershed,
        getClickCoords: function () { return { lat: state.clickLat, lng: state.clickLng }; },
        showPanel: showPanel,
    };
})();
