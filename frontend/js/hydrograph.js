/**
 * Hydrograf Hydrograph module.
 *
 * Scenario form, hydrograph chart, hietogram chart, water balance table.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var scenariosLoaded = false;
    var _charts = {};

    /**
     * Fetch available scenarios and populate dropdowns.
     */
    async function initScenarioForm() {
        if (scenariosLoaded) return;

        try {
            var scenarios = await Hydrograf.api.getScenarios();

            var durSelect = document.getElementById('hydro-duration');
            var probSelect = document.getElementById('hydro-probability');

            durSelect.innerHTML = '';
            scenarios.durations.forEach(function (d) {
                var opt = document.createElement('option');
                opt.value = d;
                opt.textContent = d;
                durSelect.appendChild(opt);
            });
            // Default to 1h
            durSelect.value = '1h';

            probSelect.innerHTML = '';
            scenarios.probabilities.forEach(function (p) {
                var opt = document.createElement('option');
                opt.value = String(p);
                opt.textContent = p + '%';
                probSelect.appendChild(opt);
            });
            // Default to 10%
            probSelect.value = '10';

            scenariosLoaded = true;
        } catch (err) {
            console.warn('Failed to load scenarios:', err.message);
        }
    }

    /**
     * Generate hydrograph and render charts.
     */
    async function generateHydrograph() {
        var data = Hydrograf.app.getCurrentWatershed();
        if (!data) return;
        if (!data.watershed.hydrograph_available) return;

        // Use original click coordinates (inside catchment), not outlet (on boundary)
        var click = Hydrograf.app.getClickCoords();
        var duration = document.getElementById('hydro-duration').value;
        var probability = parseFloat(document.getElementById('hydro-probability').value);
        var alpha = parseFloat(document.getElementById('hydro-alpha').value) || 2.0;
        var beta = parseFloat(document.getElementById('hydro-beta').value) || 5.0;
        var uhModel = document.getElementById('hydro-uh-model').value;

        var btn = document.getElementById('btn-generate-hydro');
        btn.disabled = true;
        btn.textContent = 'Generowanie...';

        try {
            var opts = {
                morphometry: data.watershed.morphometry || null,
                hietogram_alpha: alpha,
                hietogram_beta: beta,
                uh_model: uhModel,
            };
            if (uhModel === 'nash') {
                opts.nash_estimation = document.getElementById('hydro-nash-estimation').value;
                if (opts.nash_estimation === 'from_tc') {
                    opts.nash_n = parseFloat(document.getElementById('hydro-nash-n').value) || 3.0;
                }
            }
            if (uhModel === 'snyder') {
                opts.snyder_ct = parseFloat(document.getElementById('hydro-snyder-ct').value) || 1.5;
                opts.snyder_cp = parseFloat(document.getElementById('hydro-snyder-cp').value) || 0.6;
            }
            var result = await Hydrograf.api.generateHydrograph(
                click.lat, click.lng, duration, probability, opts
            );

            // Show results container BEFORE rendering charts
            // (Chart.js responsive mode needs non-zero container dimensions)
            document.getElementById('hydrograph-results').classList.remove('d-none');

            // Common time axis for both charts
            var hydroTimes = result.hydrograph.times_min;
            var maxTimeMin = hydroTimes[hydroTimes.length - 1];

            // Render hydrograph chart
            renderHydrographChart(result.hydrograph, maxTimeMin);

            // Render hietogram
            renderHietogramChart(result.precipitation, maxTimeMin);

            // Display summary
            var summary = document.getElementById('hydro-summary');
            summary.textContent =
                'Qmax: ' + result.hydrograph.peak_discharge_m3s.toFixed(2) + ' m³/s | ' +
                'tp: ' + result.hydrograph.time_to_peak_min.toFixed(0) + ' min | ' +
                'V: ' + result.hydrograph.total_volume_m3.toFixed(0) + ' m³';

            // Display water balance table
            displayWaterBalance(result.water_balance);

            // Display model metadata
            displayMetadata(result.metadata, result.water_balance);
        } catch (err) {
            console.warn('Hydrograph error:', err.message);
            var summary2 = document.getElementById('hydro-summary');
            summary2.textContent = 'Błąd: ' + err.message;
            document.getElementById('hydrograph-results').classList.remove('d-none');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Generuj';
        }
    }

    /**
     * Render hydrograph (discharge vs time) chart.
     */
    function renderHydrographChart(hydro, maxTimeMin) {
        if (_charts['chart-hydrograph']) {
            _charts['chart-hydrograph'].destroy();
            delete _charts['chart-hydrograph'];
        }

        var canvas = document.getElementById('chart-hydrograph');
        if (!canvas || typeof Chart === 'undefined') return;

        var xyData = hydro.times_min.map(function (t, i) {
            return { x: t, y: hydro.discharge_m3s[i] };
        });

        _charts['chart-hydrograph'] = new Chart(canvas, {
            type: 'line',
            data: {
                datasets: [{
                    label: 'Q [m³/s]',
                    data: xyData,
                    borderColor: '#0A84FF',
                    backgroundColor: 'rgba(10, 132, 255, 0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    borderWidth: 2,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        intersect: false,
                        mode: 'index',
                        callbacks: {
                            title: function (items) { return 't = ' + items[0].parsed.x + ' min'; },
                            label: function (ctx) { return 'Q = ' + ctx.parsed.y.toFixed(3) + ' m³/s'; },
                        },
                    },
                },
                scales: {
                    x: {
                        type: 'linear',
                        min: 0,
                        max: maxTimeMin,
                        title: { display: true, text: 'Czas [min]', font: { size: 10 } },
                        ticks: { font: { size: 9 }, maxTicksLimit: 8 },
                    },
                    y: {
                        title: { display: true, text: 'Q [m³/s]', font: { size: 10 } },
                        ticks: { font: { size: 9 } },
                        beginAtZero: true,
                    },
                },
            },
        });
    }

    /**
     * Render hietogram (precipitation intensities) chart.
     */
    function renderHietogramChart(precip, maxTimeMin) {
        if (_charts['chart-hietogram']) {
            _charts['chart-hietogram'].destroy();
            delete _charts['chart-hietogram'];
        }

        var canvas = document.getElementById('chart-hietogram');
        if (!canvas || typeof Chart === 'undefined') return;

        var xyData = [];
        // Start from 0
        if (precip.times_min.length === 0 || precip.times_min[0] !== 0) {
            xyData.push({ x: 0, y: 0 });
        }
        precip.times_min.forEach(function (t, i) {
            xyData.push({ x: t, y: precip.intensities_mm[i] });
        });
        // Extend to end of axis
        var lastTime = precip.times_min[precip.times_min.length - 1];
        if (lastTime < maxTimeMin) {
            xyData.push({ x: lastTime + (precip.timestep_min || 5), y: 0 });
        }

        _charts['chart-hietogram'] = new Chart(canvas, {
            type: 'line',
            data: {
                datasets: [{
                    label: 'P [mm]',
                    data: xyData,
                    borderColor: '#0A84FF',
                    backgroundColor: 'rgba(10, 132, 255, 0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    borderWidth: 2,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        intersect: false,
                        mode: 'index',
                        callbacks: {
                            title: function (items) { return 't = ' + items[0].parsed.x + ' min'; },
                            label: function (ctx) { return 'P = ' + ctx.parsed.y.toFixed(2) + ' mm'; },
                        },
                    },
                },
                scales: {
                    x: {
                        type: 'linear',
                        min: 0,
                        max: maxTimeMin,
                        title: { display: true, text: 'Czas [min]', font: { size: 10 } },
                        ticks: { font: { size: 9 }, maxTicksLimit: 8 },
                    },
                    y: {
                        title: { display: true, text: 'P [mm]', font: { size: 10 } },
                        ticks: { font: { size: 9 } },
                        beginAtZero: true,
                    },
                },
            },
        });
    }

    /**
     * Display water balance table.
     */
    function displayWaterBalance(wb) {
        var container = document.getElementById('hydro-balance');
        container.innerHTML = '';

        var table = document.createElement('table');
        table.className = 'balance-table';

        var rows = [
            ['Opad całkowity', wb.total_precip_mm.toFixed(1) + ' mm'],
            ['Opad efektywny', wb.total_effective_mm.toFixed(1) + ' mm'],
            ['Wsp. odpływu', wb.runoff_coefficient.toFixed(3)],
            ['CN użyty', String(wb.cn_used)],
            ['Retencja S', wb.retention_mm.toFixed(1) + ' mm'],
            ['Straty początkowe Ia', wb.initial_abstraction_mm.toFixed(1) + ' mm'],
        ];

        rows.forEach(function (row) {
            var tr = document.createElement('tr');
            var td1 = document.createElement('td');
            td1.textContent = row[0];
            var td2 = document.createElement('td');
            td2.textContent = row[1];
            tr.appendChild(td1);
            tr.appendChild(td2);
            table.appendChild(tr);
        });

        container.appendChild(table);
    }

    var TC_METHOD_LABELS = {
        'kirpich': 'Kirpich',
        'nrcs': 'NRCS',
        'giandotti': 'Giandotti',
    };
    var UH_MODEL_LABELS = {
        'scs': 'SCS',
        'nash': 'Nash',
        'snyder': 'Snyder',
    };
    var NASH_EST_LABELS = {
        'from_tc': 'z Tc',
        'from_lutz': 'Lutz',
        'from_urban_regression': 'Regresja urban.',
    };
    var HIETOGRAM_LABELS = {
        'beta': 'Beta',
        'block': 'Blokowy',
        'euler_ii': 'Euler II',
    };

    function displayMetadata(meta, wb) {
        var container = document.getElementById('hydrograph-info');
        container.innerHTML = '';

        var table = document.createElement('table');
        table.className = 'balance-table';

        var uhLabel = UH_MODEL_LABELS[meta.uh_model] || meta.uh_model;
        if (meta.nash_estimation) {
            uhLabel += ' (' + (NASH_EST_LABELS[meta.nash_estimation] || meta.nash_estimation) + ')';
        }

        var rows = [];
        if (meta.tc_method != null) {
            rows.push(['Metoda Tc', TC_METHOD_LABELS[meta.tc_method] || meta.tc_method]);
        }
        if (meta.tc_min != null) {
            rows.push(['Tc', meta.tc_min.toFixed(1) + ' min']);
        }
        rows.push(['Hydrogram jedn.', uhLabel]);
        rows.push(['Hietogram', HIETOGRAM_LABELS[meta.hietogram_type] || meta.hietogram_type]);

        if (meta.nash_n != null) {
            rows.push(['Nash N', meta.nash_n.toFixed(2)]);
            rows.push(['Nash K', meta.nash_k_min.toFixed(1) + ' min']);
        }
        if (meta.nash_urban_fraction != null) {
            rows.push(['Urbanizacja U', (meta.nash_urban_fraction * 100).toFixed(1) + '%']);
        }
        if (meta.nash_effective_precip_mm != null) {
            rows.push(['Pe (Nash)', meta.nash_effective_precip_mm.toFixed(1) + ' mm']);
        }
        if (meta.nash_duration_h != null) {
            var dMin = Math.round(meta.nash_duration_h * 60);
            rows.push(['D efektywny', dMin + ' min (' + meta.nash_duration_h.toFixed(2) + ' h)']);
        }

        rows.forEach(function (row) {
            var tr = document.createElement('tr');
            var td1 = document.createElement('td');
            td1.textContent = row[0];
            var td2 = document.createElement('td');
            td2.textContent = row[1];
            tr.appendChild(td1);
            tr.appendChild(td2);
            table.appendChild(tr);
        });

        container.appendChild(table);
    }

    function updateNashVisibility() {
        var model = document.getElementById('hydro-uh-model').value;
        var nashParams = document.getElementById('nash-params');
        var nashNRow = document.getElementById('nash-n-row');
        var snyderParams = document.getElementById('snyder-params');
        var estimation = document.getElementById('hydro-nash-estimation').value;

        if (model === 'nash') {
            nashParams.classList.remove('d-none');
            nashNRow.classList.toggle('d-none', estimation !== 'from_tc');
        } else {
            nashParams.classList.add('d-none');
            nashNRow.classList.add('d-none');
        }
        snyderParams.classList.toggle('d-none', model !== 'snyder');
    }

    function init() {
        initScenarioForm();
        var btn = document.getElementById('btn-generate-hydro');
        if (btn) {
            btn.addEventListener('click', generateHydrograph);
        }
        var uhSelect = document.getElementById('hydro-uh-model');
        if (uhSelect) {
            uhSelect.addEventListener('change', updateNashVisibility);
        }
        var nashEst = document.getElementById('hydro-nash-estimation');
        if (nashEst) {
            nashEst.addEventListener('change', updateNashVisibility);
        }
    }

    window.Hydrograf.hydrograph = {
        init: init,
        initScenarioForm: initScenarioForm,
        generateHydrograph: generateHydrograph,
    };
})();
