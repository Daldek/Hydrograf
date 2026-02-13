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

        var outlet = data.watershed.outlet;
        var duration = document.getElementById('hydro-duration').value;
        var probability = parseInt(document.getElementById('hydro-probability').value);

        var btn = document.getElementById('btn-generate-hydro');
        btn.disabled = true;
        btn.textContent = 'Generowanie...';

        try {
            var result = await Hydrograf.api.generateHydrograph(
                outlet.latitude, outlet.longitude, duration, probability
            );

            // Render hydrograph chart
            renderHydrographChart(result.hydrograph);

            // Render hietogram chart
            renderHietogramChart(result.precipitation);

            // Display summary
            var summary = document.getElementById('hydro-summary');
            summary.textContent =
                'Qmax: ' + result.hydrograph.peak_discharge_m3s.toFixed(2) + ' m³/s | ' +
                'tp: ' + result.hydrograph.time_to_peak_min.toFixed(0) + ' min | ' +
                'V: ' + result.hydrograph.total_volume_m3.toFixed(0) + ' m³';

            // Display water balance table
            displayWaterBalance(result.water_balance);

            document.getElementById('hydrograph-results').classList.remove('d-none');
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
    function renderHydrographChart(hydro) {
        if (_charts['chart-hydrograph']) { _charts['chart-hydrograph'].destroy(); }

        var canvas = document.getElementById('chart-hydrograph');
        if (!canvas || typeof Chart === 'undefined') return;

        _charts['chart-hydrograph'] = new Chart(canvas, {
            type: 'line',
            data: {
                labels: hydro.times_min,
                datasets: [{
                    label: 'Q [m³/s]',
                    data: hydro.discharge_m3s,
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
                            title: function (items) { return 't = ' + items[0].label + ' min'; },
                            label: function (ctx) { return 'Q = ' + ctx.parsed.y.toFixed(3) + ' m³/s'; },
                        },
                    },
                },
                scales: {
                    x: {
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
    function renderHietogramChart(precip) {
        if (_charts['chart-hietogram']) { _charts['chart-hietogram'].destroy(); }

        var canvas = document.getElementById('chart-hietogram');
        if (!canvas || typeof Chart === 'undefined') return;

        _charts['chart-hietogram'] = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: precip.times_min,
                datasets: [{
                    label: 'P [mm]',
                    data: precip.intensities_mm,
                    backgroundColor: 'rgba(10, 132, 255, 0.5)',
                    borderColor: '#0A84FF',
                    borderWidth: 1,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: function (items) { return 't = ' + items[0].label + ' min'; },
                            label: function (ctx) { return 'P = ' + ctx.parsed.y.toFixed(2) + ' mm'; },
                        },
                    },
                },
                scales: {
                    x: {
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

    function init() {
        var btn = document.getElementById('btn-generate-hydro');
        if (btn) {
            btn.addEventListener('click', generateHydrograph);
        }
    }

    window.Hydrograf.hydrograph = {
        init: init,
        initScenarioForm: initScenarioForm,
        generateHydrograph: generateHydrograph,
    };
})();
