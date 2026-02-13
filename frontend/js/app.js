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
        clickMode: 'watershed',
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
            ['Spadek cieku gł.', formatSlope(m.channel_slope_m_per_m)],
            ['CN', m.cn !== null && m.cn !== undefined ? String(m.cn) : '—'],
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
            ['Gęstość sieci Dd', formatValue(m.drainage_density_km_per_km2, 'km/km²', 2)],
            ['Częstość cieków Fs', formatValue(m.stream_frequency_per_km2, '1/km²', 2)],
            ['Liczba chropowatoś. Rn', formatRatio(m.ruggedness_number, 3)],
            ['Max rząd Strahlera', m.max_strahler_order !== null && m.max_strahler_order !== undefined ? String(m.max_strahler_order) : '—'],
        ]);

        fillTable(els.paramsOutlet, [
            ['Szerokość', formatValue(o.latitude, '°N', 6)],
            ['Długość', formatValue(o.longitude, '°E', 6)],
            ['Wysokość', formatValue(o.elevation_m, 'm n.p.m.', 1)],
            ['Liczba komórek', String(w.cell_count)],
        ]);

        // Charts: land cover donut
        if (w.land_cover_stats && w.land_cover_stats.categories && w.land_cover_stats.categories.length > 0) {
            Hydrograf.charts.renderLandCoverChart('chart-landcover', w.land_cover_stats.categories);
            document.getElementById('acc-landcover').classList.remove('collapsed');
        } else {
            Hydrograf.charts.destroyChart('chart-landcover');
            document.getElementById('acc-landcover').classList.add('collapsed');
        }

        // Chart: elevation histogram (from hypsometric curve data)
        if (w.hypsometric_curve && w.hypsometric_curve.length > 0 &&
            m.elevation_min_m != null && m.elevation_max_m != null) {
            Hydrograf.charts.renderElevationHistogram(
                'chart-hypsometric', w.hypsometric_curve,
                m.elevation_min_m, m.elevation_max_m
            );
        } else {
            Hydrograf.charts.destroyChart('chart-hypsometric');
        }

        // Hydrograph availability
        els.hydrographInfo.innerHTML = '';
        var badge = document.createElement('span');
        if (w.hydrograph_available) {
            badge.className = 'badge bg-success';
            badge.textContent = 'Hydrogram dostępny (SCS-CN)';
            document.getElementById('acc-hydrograph').classList.remove('collapsed');
            // Init hydrograph form
            if (Hydrograf.hydrograph) {
                Hydrograf.hydrograph.initScenarioForm();
            }
        } else {
            badge.className = 'badge bg-secondary';
            badge.textContent = 'Hydrogram niedostępny (zlewnia > 250 km²)';
            document.getElementById('acc-hydrograph').classList.add('collapsed');
        }
        els.hydrographInfo.appendChild(badge);

        // Profile: enable auto-profile if main stream available
        if (w.main_stream_geojson && Hydrograf.profile) {
            document.getElementById('btn-profile-auto').disabled = false;
        }
    }

    // ======== Floating panel management ========

    function showPanel() {
        els.panel.classList.remove('d-none');
        els.restoreBtn.classList.add('d-none');
    }

    function hidePanel() {
        els.panel.classList.add('d-none');
        els.restoreBtn.classList.add('d-none');
    }

    function minimizePanel() {
        els.panel.classList.add('d-none');
        els.restoreBtn.classList.remove('d-none');
    }

    function restorePanel() {
        els.panel.classList.remove('d-none');
        els.restoreBtn.classList.add('d-none');
    }

    function setLoading(loading) {
        state.isLoading = loading;

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
     * Handle map click with 300ms debounce.
     */
    function onMapClick(lat, lng) {
        if (state.isLoading) return;

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
            if (state.clickMode === 'select') {
                onSelectClick(lat, lng);
            } else {
                onWatershedClick(lat, lng);
            }
        }, 300);
    }

    /**
     * Handle watershed delineation click (default mode).
     */
    async function onWatershedClick(lat, lng) {
        hideError();
        setLoading(true);

        // Clear any selection highlights
        Hydrograf.map.clearCatchmentHighlights();
        Hydrograf.map.clearSelectionBoundary();

        try {
            var data = await Hydrograf.api.delineateWatershed(lat, lng);
            state.currentWatershed = data;

            Hydrograf.map.showWatershed(data.watershed.boundary_geojson);

            var outlet = data.watershed.outlet;
            Hydrograf.map.showOutlet(outlet.latitude, outlet.longitude, outlet.elevation_m);

            displayParameters(data);
            els.results.classList.remove('d-none');
        } catch (err) {
            Hydrograf.map.clearWatershed();
            showError(err.message);
        } finally {
            setLoading(false);
        }
    }

    /**
     * Handle stream selection click.
     */
    async function onSelectClick(lat, lng) {
        hideError();
        setLoading(true);

        // Clear previous watershed display
        Hydrograf.map.clearWatershed();

        // Determine active threshold from streams layer
        var threshold = Hydrograf.map.getStreamsThreshold() || 10000;

        try {
            var data = await Hydrograf.api.selectStream(lat, lng, threshold);

            // Show selection boundary
            Hydrograf.map.showSelectionBoundary(data.boundary_geojson);

            // Highlight upstream catchments
            if (data.upstream_segment_indices && data.upstream_segment_indices.length > 0) {
                Hydrograf.map.highlightUpstreamCatchments(data.upstream_segment_indices);
            }

            // Display full watershed stats if available, otherwise fallback to stream info
            if (data.watershed) {
                state.currentWatershed = data;

                // Show watershed boundary and outlet on map
                Hydrograf.map.showWatershed(data.watershed.boundary_geojson);
                var outlet = data.watershed.outlet;
                Hydrograf.map.showOutlet(outlet.latitude, outlet.longitude, outlet.elevation_m);

                displayParameters(data);
            } else {
                displayStreamInfo(data.stream);
            }
            els.results.classList.remove('d-none');
        } catch (err) {
            Hydrograf.map.clearCatchmentHighlights();
            Hydrograf.map.clearSelectionBoundary();
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
        ['acc-shape', 'acc-relief', 'acc-drainage', 'acc-landcover', 'acc-outlet',
         'acc-profile', 'acc-hydrograph'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.classList.add('collapsed');
        });

        // Clear charts
        Hydrograf.charts.destroyChart('chart-hypsometric');
        Hydrograf.charts.destroyChart('chart-landcover');

        // Clear relief table
        if (els.paramsRelief) els.paramsRelief.innerHTML = '';
    }

    async function checkSystemHealth() {
        try {
            var health = await Hydrograf.api.checkHealth();
            var statusEl = document.getElementById('system-status');
            if (health.status === 'healthy') {
                statusEl.textContent = 'System: OK';
                statusEl.className = 'navbar-text d-none d-md-inline text-light';
            } else {
                statusEl.textContent = 'System: problem z bazą danych';
                statusEl.className = 'navbar-text d-none d-md-inline text-warning';
            }
        } catch {
            var statusEl2 = document.getElementById('system-status');
            statusEl2.textContent = 'System: niedostępny';
            statusEl2.className = 'navbar-text d-none d-md-inline text-warning';
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
    }

    /**
     * Switch click mode between 'watershed' and 'select'.
     */
    function setClickMode(mode) {
        state.clickMode = mode;

        // Update button classes
        var btnWatershed = document.getElementById('mode-watershed');
        var btnSelect = document.getElementById('mode-select');
        if (btnWatershed && btnSelect) {
            btnWatershed.classList.toggle('mode-btn-active', mode === 'watershed');
            btnSelect.classList.toggle('mode-btn-active', mode === 'select');
        }

        // Clear previous results when switching mode
        Hydrograf.map.clearWatershed();
        Hydrograf.map.clearCatchmentHighlights();
        Hydrograf.map.clearSelectionBoundary();
        hidePanel();
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
            restoreBtn: document.getElementById('results-restore'),
            instruction: document.getElementById('panel-instruction'),
            loading: document.getElementById('panel-loading'),
            error: document.getElementById('panel-error'),
            errorMessage: document.getElementById('error-message'),
            results: document.getElementById('panel-results'),
            paramsBasic: document.getElementById('params-basic'),
            paramsShape: document.getElementById('params-shape'),
            paramsRelief: document.getElementById('params-relief'),
            paramsDrainage: document.getElementById('params-drainage'),
            paramsOutlet: document.getElementById('params-outlet'),
            hydrographInfo: document.getElementById('hydrograph-info'),
        };

        // Layers toggle
        document.getElementById('layers-toggle').addEventListener('click', toggleLayers);

        // Mode toolbar
        document.getElementById('mode-watershed').addEventListener('click', function () {
            setClickMode('watershed');
        });
        document.getElementById('mode-select').addEventListener('click', function () {
            setClickMode('select');
        });

        // Accordion collapse/expand (replaces inline onclick)
        document.querySelectorAll('.glass-accordion-header').forEach(function (header) {
            header.addEventListener('click', function () {
                this.parentElement.classList.toggle('collapsed');
            });
        });

        // Floating panel controls
        document.getElementById('results-close').addEventListener('click', hidePanel);
        document.getElementById('results-minimize').addEventListener('click', minimizePanel);
        document.getElementById('results-restore').addEventListener('click', restorePanel);

        // Make panel draggable (desktop only)
        if (window.innerWidth > 768) {
            Hydrograf.draggable.makeDraggable(
                els.panel,
                document.getElementById('results-header')
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
        showPanel: showPanel,
    };
})();
