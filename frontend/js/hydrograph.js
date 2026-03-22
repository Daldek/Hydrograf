/**
 * Hydrograf Hydrograph module.
 *
 * Hietogram form (precipitation), hydrograph form (UH model),
 * charts, water balance table. Auto-regenerates on parameter change.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var scenariosLoaded = false;
    var _charts = {};
    var _debounceTimer = null;
    var _DEBOUNCE_MS = 300;
    var _requestId = 0;

    // ── Chart helpers ──────────────────────────────────────────────────

    function _ensureLineChart(canvasId, yLabel, tooltipFn) {
        if (_charts[canvasId]) return _charts[canvasId];
        var canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined') return null;
        var chart = new Chart(canvas, {
            type: 'line',
            data: { datasets: [{
                label: yLabel,
                data: [],
                borderColor: '#0A84FF',
                backgroundColor: 'rgba(10, 132, 255, 0.1)',
                fill: true,
                tension: 0.3,
                pointRadius: 0,
                borderWidth: 2,
            }] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 400, easing: 'easeInOutQuart' },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        intersect: false,
                        mode: 'index',
                        callbacks: {
                            title: function (items) { return 't = ' + items[0].parsed.x + ' min'; },
                            label: tooltipFn,
                        },
                    },
                },
                scales: {
                    x: {
                        type: 'linear',
                        min: 0,
                        max: 60,
                        title: { display: true, text: 'Czas [min]', font: { size: 10 } },
                        ticks: { font: { size: 9 }, maxTicksLimit: 8 },
                    },
                    y: {
                        title: { display: true, text: yLabel, font: { size: 10 } },
                        ticks: { font: { size: 9 } },
                        beginAtZero: true,
                    },
                },
            },
        });
        _charts[canvasId] = chart;
        return chart;
    }

    function _ensureHietogramChart(canvasId) {
        if (_charts[canvasId]) return _charts[canvasId];
        var canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined') return null;
        var chart = new Chart(canvas, {
            type: 'bar',
            data: { labels: [], datasets: [
                {
                    label: 'Opad ca\u0142kowity [mm]',
                    data: [],
                    backgroundColor: 'rgba(10, 132, 255, 0.35)',
                    borderColor: '#0A84FF',
                    borderWidth: 1,
                    borderRadius: 1,
                    order: 2,
                },
                {
                    label: 'Opad efektywny [mm]',
                    data: [],
                    backgroundColor: 'rgba(10, 132, 255, 0.8)',
                    borderColor: '#0A84FF',
                    borderWidth: 1,
                    borderRadius: 1,
                    order: 1,
                },
            ] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 400, easing: 'easeInOutQuart' },
                plugins: {
                    legend: { display: true, labels: { boxWidth: 12, font: { size: 9 } } },
                    tooltip: {
                        callbacks: {
                            title: function (items) { return items[0].label + ' min'; },
                            label: function (ctx) { return ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(2) + ' mm'; },
                        },
                    },
                },
                scales: {
                    x: {
                        title: { display: true, text: 'Czas [min]', font: { size: 10 } },
                        ticks: { font: { size: 9 }, maxTicksLimit: 12 },
                    },
                    y: {
                        title: { display: true, text: 'P [mm]', font: { size: 10 } },
                        ticks: { font: { size: 9 } },
                        beginAtZero: true,
                    },
                },
            },
        });
        _charts[canvasId] = chart;
        return chart;
    }

    // ── Scenarios ──────────────────────────────────────────────────────

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
            durSelect.value = '1h';

            probSelect.innerHTML = '';
            scenarios.probabilities.forEach(function (p) {
                var opt = document.createElement('option');
                opt.value = String(p);
                opt.textContent = p + '%';
                probSelect.appendChild(opt);
            });
            probSelect.value = '10';

            scenariosLoaded = true;
        } catch (err) {
            console.warn('Failed to load scenarios:', err.message);
        }
    }

    // ── Auto-regeneration ──────────────────────────────────────────────

    function scheduleRegenerate() {
        if (_debounceTimer) clearTimeout(_debounceTimer);
        _debounceTimer = setTimeout(generateHydrograph, _DEBOUNCE_MS);
    }

    async function generateHydrograph() {
        var data = Hydrograf.app.getCurrentWatershed();
        if (!data) return;
        if (!data.watershed.hydrograph_available) return;

        var click = Hydrograf.app.getClickCoords();
        var duration = document.getElementById('hydro-duration').value;
        var probability = parseFloat(document.getElementById('hydro-probability').value);
        var hietogramType = document.getElementById('hydro-hietogram-type').value;
        var alpha = parseFloat(document.getElementById('hydro-alpha').value) || 2.0;
        var beta = parseFloat(document.getElementById('hydro-beta').value) || 5.0;
        var uhModel = document.getElementById('hydro-uh-model').value;

        var myId = ++_requestId;

        try {
            var opts = {
                morphometry: data.watershed.morphometry || null,
                hietogram_type: hietogramType,
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

            if (myId !== _requestId) return;

            document.getElementById('hietogram-results').classList.remove('d-none');
            document.getElementById('hydrograph-results').classList.remove('d-none');

            // Hietogram — bar chart with total + effective, own time range
            var precip = result.precipitation;
            var hietoChart = _ensureHietogramChart('chart-hietogram');
            if (hietoChart) {
                hietoChart.data.labels = precip.times_min.map(function (t) { return String(t); });
                hietoChart.data.datasets[0].data = precip.intensities_mm.slice();
                hietoChart.data.datasets[1].data = (precip.effective_mm || []).slice();
                hietoChart.update('default');
            }

            // Hydrograph — line chart
            var hydroTimes = result.hydrograph.times_min;
            var maxTimeMin = hydroTimes[hydroTimes.length - 1];
            var hydroChart = _ensureLineChart(
                'chart-hydrograph', 'Q [m\u00b3/s]',
                function (ctx) { return 'Q = ' + ctx.parsed.y.toFixed(3) + ' m\u00b3/s'; }
            );
            if (hydroChart) {
                var hydroData = hydroTimes.map(function (t, i) {
                    return { x: t, y: result.hydrograph.discharge_m3s[i] };
                });
                hydroChart.data.datasets[0].data = hydroData;
                hydroChart.options.scales.x.max = maxTimeMin;
                hydroChart.update('default');
            }

            // Summary
            var summary = document.getElementById('hydro-summary');
            summary.textContent =
                'Qmax: ' + result.hydrograph.peak_discharge_m3s.toFixed(2) + ' m\u00b3/s | ' +
                'tp: ' + result.hydrograph.time_to_peak_min.toFixed(0) + ' min | ' +
                'V: ' + result.hydrograph.total_volume_m3.toFixed(0) + ' m\u00b3';

            displayPrecipBalance(result.water_balance);
            displayMetadata(result.metadata);
        } catch (err) {
            if (myId !== _requestId) return;
            console.warn('Hydrograph error:', err.message);
            var summary2 = document.getElementById('hydro-summary');
            summary2.textContent = 'B\u0142\u0105d: ' + err.message;
            document.getElementById('hydrograph-results').classList.remove('d-none');
        }
    }

    // ── Water balance & metadata tables ────────────────────────────────

    function displayPrecipBalance(wb) {
        var container = document.getElementById('hietogram-balance');
        container.innerHTML = '';

        var table = document.createElement('table');
        table.className = 'balance-table';

        var rows = [
            ['Opad ca\u0142kowity', wb.total_precip_mm.toFixed(1) + ' mm'],
            ['Opad efektywny', wb.total_effective_mm.toFixed(1) + ' mm'],
            ['Wsp. odp\u0142ywu', wb.runoff_coefficient.toFixed(3)],
            ['CN u\u017cyty', String(wb.cn_used)],
            ['Retencja S', wb.retention_mm.toFixed(1) + ' mm'],
            ['Straty pocz\u0105tkowe Ia', wb.initial_abstraction_mm.toFixed(1) + ' mm'],
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
        'euler_ii': 'DVWK (Euler II)',
    };

    function displayMetadata(meta) {
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

    // ── Visibility toggles ─────────────────────────────────────────────

    function updateHietogramVisibility() {
        var htype = document.getElementById('hydro-hietogram-type').value;
        var betaParams = document.getElementById('beta-params');
        betaParams.classList.toggle('d-none', htype !== 'beta');
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

    // ── Init ───────────────────────────────────────────────────────────

    var _INPUT_IDS = [
        'hydro-duration', 'hydro-probability', 'hydro-hietogram-type',
        'hydro-alpha', 'hydro-beta',
        'hydro-uh-model', 'hydro-nash-estimation', 'hydro-nash-n',
        'hydro-snyder-ct', 'hydro-snyder-cp',
    ];

    function init() {
        initScenarioForm();

        var hietogramType = document.getElementById('hydro-hietogram-type');
        if (hietogramType) {
            hietogramType.addEventListener('change', updateHietogramVisibility);
        }

        var uhSelect = document.getElementById('hydro-uh-model');
        if (uhSelect) {
            uhSelect.addEventListener('change', updateNashVisibility);
        }
        var nashEst = document.getElementById('hydro-nash-estimation');
        if (nashEst) {
            nashEst.addEventListener('change', updateNashVisibility);
        }

        // Auto-regenerate on any parameter change
        _INPUT_IDS.forEach(function (id) {
            var el = document.getElementById(id);
            if (!el) return;
            var evt = (el.tagName === 'SELECT') ? 'change' : 'input';
            el.addEventListener(evt, scheduleRegenerate);
        });
    }

    window.Hydrograf.hydrograph = {
        init: init,
        initScenarioForm: initScenarioForm,
        generateHydrograph: generateHydrograph,
    };
})();
