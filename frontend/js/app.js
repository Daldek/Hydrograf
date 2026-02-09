/**
 * Hydrograf Application module.
 *
 * Orchestrates map clicks, API calls, and parameter display.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var state = {
        isLoading: false,
        currentWatershed: null,
    };

    // Poland bounding box (approximate)
    var BOUNDS = { latMin: 49.0, latMax: 55.0, lngMin: 14.0, lngMax: 24.2 };

    // DOM references (set on init)
    var els = {};

    /**
     * Format a numeric value with unit.
     *
     * @param {*} val - Value to format
     * @param {string} unit - Unit string
     * @param {number} decimals - Decimal places
     * @returns {string} Formatted string or '—' if null
     */
    function formatValue(val, unit, decimals) {
        if (val === null || val === undefined) return '—';
        return val.toFixed(decimals) + ' ' + unit;
    }

    /**
     * Format slope from m/m to %.
     *
     * @param {*} val - Slope in m/m
     * @returns {string} Formatted percentage or '—'
     */
    function formatSlope(val) {
        if (val === null || val === undefined) return '—';
        return (val * 100).toFixed(2) + ' %';
    }

    /**
     * Format a dimensionless ratio.
     *
     * @param {*} val - Value
     * @param {number} decimals - Decimal places
     * @returns {string} Formatted string or '—'
     */
    function formatRatio(val, decimals) {
        if (val === null || val === undefined) return '—';
        return val.toFixed(decimals);
    }

    /**
     * Build a table row (using textContent for safety).
     *
     * @param {string} label - Row label
     * @param {string} value - Formatted value
     * @returns {HTMLTableRowElement}
     */
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

    /**
     * Fill a table body with parameter rows, skipping null values.
     *
     * @param {HTMLElement} tbody - Target tbody element
     * @param {Array} rows - Array of [label, value] pairs
     */
    function fillTable(tbody, rows) {
        tbody.innerHTML = '';
        rows.forEach(function (row) {
            if (row[1] !== '—') {
                tbody.appendChild(buildRow(row[0], row[1]));
            }
        });
    }

    /**
     * Display watershed parameters in the side panel.
     *
     * @param {Object} data - API response (DelineateResponse)
     */
    function displayParameters(data) {
        var w = data.watershed;
        var m = w.morphometry || {};
        var o = w.outlet;

        // Basic parameters
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

        // Shape indices
        fillTable(els.paramsShape, [
            ['Wsp. zwartości Kc', formatRatio(m.compactness_coefficient, 3)],
            ['Wsp. kołowości Rc', formatRatio(m.circularity_ratio, 3)],
            ['Wsp. wydłużenia Re', formatRatio(m.elongation_ratio, 3)],
            ['Wsp. kształtu Ff', formatRatio(m.form_factor, 3)],
        ]);

        // Relief indices
        fillTable(els.paramsRelief, [
            ['Wsp. rzeźbowy Rh', formatRatio(m.relief_ratio, 4)],
            ['Całka hipsometryczna HI', formatRatio(m.hypsometric_integral, 3)],
        ]);

        // Drainage network
        fillTable(els.paramsDrainage, [
            ['Gęstość sieci Dd', formatValue(m.drainage_density_km_per_km2, 'km/km²', 2)],
            ['Częstość cieków Fs', formatValue(m.stream_frequency_per_km2, '1/km²', 2)],
            ['Liczba chropowatoś. Rn', formatRatio(m.ruggedness_number, 3)],
            ['Max rząd Strahlera', m.max_strahler_order !== null && m.max_strahler_order !== undefined ? String(m.max_strahler_order) : '—'],
        ]);

        // Outlet info
        fillTable(els.paramsOutlet, [
            ['Szerokość', formatValue(o.latitude, '°N', 6)],
            ['Długość', formatValue(o.longitude, '°E', 6)],
            ['Wysokość', formatValue(o.elevation_m, 'm n.p.m.', 1)],
            ['Liczba komórek', String(w.cell_count)],
        ]);

        // Hydrograph availability
        els.hydrographInfo.innerHTML = '';
        var badge = document.createElement('span');
        if (w.hydrograph_available) {
            badge.className = 'badge bg-success';
            badge.textContent = 'Hydrogram dostępny (SCS-CN)';
        } else {
            badge.className = 'badge bg-secondary';
            badge.textContent = 'Hydrogram niedostępny (zlewnia > 250 km²)';
        }
        els.hydrographInfo.appendChild(badge);
    }

    /**
     * Set loading state.
     *
     * @param {boolean} loading
     */
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

    /**
     * Show error message in panel.
     *
     * @param {string} msg - Error message (Polish)
     */
    function showError(msg) {
        showPanel();
        els.instruction.classList.add('d-none');
        els.error.classList.remove('d-none');
        els.errorMessage.textContent = msg;
    }

    /**
     * Hide error message.
     */
    function hideError() {
        els.error.classList.add('d-none');
    }

    /**
     * Handle map click — validate, call API, display results.
     *
     * @param {number} lat
     * @param {number} lng
     */
    async function onMapClick(lat, lng) {
        if (state.isLoading) return;

        // Validate: within Poland bounds
        if (lat < BOUNDS.latMin || lat > BOUNDS.latMax ||
            lng < BOUNDS.lngMin || lng > BOUNDS.lngMax) {
            showError('Kliknij w granicach Polski (49–55°N, 14–24.2°E).');
            return;
        }

        hideError();
        setLoading(true);

        try {
            var data = await Hydrograf.api.delineateWatershed(lat, lng);

            state.currentWatershed = data;

            // Show watershed on map
            Hydrograf.map.showWatershed(data.watershed.boundary_geojson);

            // Show outlet marker
            var outlet = data.watershed.outlet;
            Hydrograf.map.showOutlet(outlet.latitude, outlet.longitude, outlet.elevation_m);

            // Show parameters in panel
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
     * Check system health on startup.
     */
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
     * Show the right side panel (parameters).
     */
    function showPanel() {
        els.panelCol.classList.remove('d-none');
        els.mapCol.classList.remove('map-col-full');
        Hydrograf.map.invalidateSize();
    }

    /**
     * Hide the right side panel.
     */
    function hidePanel() {
        els.panelCol.classList.add('d-none');
        els.mapCol.classList.add('map-col-full');
        Hydrograf.map.invalidateSize();
    }

    /**
     * Build layers panel entries with checkboxes.
     */
    function initLayersPanel() {
        var list = document.getElementById('layers-list');

        var label = document.createElement('label');
        label.className = 'layer-item';
        var cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.addEventListener('change', function () {
            var layer = Hydrograf.map.getDemLayer();
            if (!layer) return;
            if (cb.checked) {
                layer.addTo(Hydrograf.map._getMap());
            } else {
                Hydrograf.map._getMap().removeLayer(layer);
            }
        });
        var text = document.createTextNode(' NMT (wysokości)');
        label.appendChild(cb);
        label.appendChild(text);
        list.appendChild(label);
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
     * Initialize application.
     */
    function init() {
        // Cache DOM references
        els = {
            mapCol: document.getElementById('map-col'),
            panelCol: document.getElementById('panel-col'),
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

        // Panel close button
        document.getElementById('panel-close').addEventListener('click', hidePanel);

        Hydrograf.map.init(onMapClick);
        initLayersPanel();
        checkSystemHealth();
    }

    document.addEventListener('DOMContentLoaded', init);

    window.Hydrograf.app = {
        init: init,
    };
})();
