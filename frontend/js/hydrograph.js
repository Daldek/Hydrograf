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
    var _debounceTimer = null;
    var _DEBOUNCE_MS = 300;
    var _requestId = 0;

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

            if (Hydrograf.customRain) {
                Hydrograf.customRain.setMaxSteps(scenarios.custom_precipitation_max_steps);
            }

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
        var uhModel = document.getElementById('hydro-uh-model').value;
        // Advanced mode may replace the morphometry and an own rainfall series
        // the PMAXTP design storm; no request while either form is invalid
        var morph = Hydrograf.advanced
            ? Hydrograf.advanced.requestMorphometry(data)
            : { valid: true, morphometry: data.watershed.morphometry || null };
        var rain = Hydrograf.customRain
            ? Hydrograf.customRain.request(data)
            : { active: false, valid: true, series: null };
        if (!morph.valid || !rain.valid) return;

        var myId = ++_requestId;
        var duration = null;
        var probability = null;

        try {
            var opts = {
                morphometry: morph.morphometry,
                amc: document.getElementById('hydro-amc').value,
                uh_model: uhModel,
            };
            if (rain.active) {
                opts.custom_precipitation = rain.series;
            } else {
                duration = document.getElementById('hydro-duration').value;
                probability = parseFloat(document.getElementById('hydro-probability').value);
                opts.hietogram_type = document.getElementById('hydro-hietogram-type').value;
                opts.hietogram_alpha = parseFloat(document.getElementById('hydro-alpha').value) || 2.0;
                opts.hietogram_beta = parseFloat(document.getElementById('hydro-beta').value) || 5.0;
            }
            if (uhModel !== 'nash' || document.getElementById('hydro-nash-estimation').value === 'from_tc') {
                opts.tc_method = document.getElementById('hydro-tc-method').value;
                // TC extra params
                if (opts.tc_method === 'faa') {
                    var cVal = document.getElementById('hydro-tc-runoff-coeff').value;
                    if (cVal) opts.tc_runoff_coeff = parseFloat(cVal);
                }
                if (opts.tc_method === 'kerby' || opts.tc_method === 'kerby_kirpich') {
                    opts.tc_retardance = parseFloat(
                        document.getElementById('hydro-tc-retardance').value
                    ) || 0.4;
                }
                if (opts.tc_method === 'faa' || opts.tc_method === 'kerby' || opts.tc_method === 'kerby_kirpich') {
                    var ovVal = document.getElementById('hydro-tc-overland-length').value;
                    if (ovVal) opts.tc_overland_length_km = parseFloat(ovVal);
                }
            }
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

            // Hietogram and hydrograph: filled line charts, each on its own time range
            var precip = result.precipitation;
            if (Hydrograf.customRain) Hydrograf.customRain.noteResult(data, precip);
            Hydrograf.charts.renderHietogramChart(
                'chart-hietogram', precip.times_min,
                precip.intensities_mm, precip.effective_mm || [],
                {
                    step: precip.timestep_min,
                    source: precip.source === 'custom'
                        ? 'w\u0142asna seria'
                        : 'PMAXTP ' + duration + ', p = ' + precip.probability_percent + '%',
                }
            );
            Hydrograf.charts.renderHydrographChart(
                'chart-hydrograph', result.hydrograph.times_min,
                result.hydrograph.discharge_m3s
            );

            // Summary: Qmax | tp | V, each with its (i)
            var summary = document.getElementById('hydro-summary');
            summary.textContent = '';
            [
                ['Qmax', result.hydrograph.peak_discharge_m3s.toFixed(2) + ' m\u00b3/s', 'peak_discharge_m3s'],
                ['tp', result.hydrograph.time_to_peak_min.toFixed(0) + ' min', 'time_to_peak_min'],
                ['V', result.hydrograph.total_volume_m3.toFixed(0) + ' m\u00b3', 'total_volume_m3'],
            ].forEach(function (stat) {
                var item = document.createElement('span');
                item.className = 'hydro-stat';
                item.textContent = stat[0] + ': ' + stat[1];
                Hydrograf.info.attach(item, stat[2], stat[0]);
                summary.appendChild(item);
            });

            displayPrecipBalance(result.water_balance, result.metadata);
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

    function displayPrecipBalance(wb, meta) {
        var container = document.getElementById('hietogram-balance');
        container.innerHTML = '';

        var table = document.createElement('table');
        table.className = 'balance-table';

        var rows = [
            ['Opad ca\u0142kowity', wb.total_precip_mm.toFixed(1) + ' mm', 'total_precip_mm'],
            ['Opad efektywny', wb.total_effective_mm.toFixed(1) + ' mm', 'total_effective_mm'],
            ['Wsp. odp\u0142ywu', wb.runoff_coefficient.toFixed(3), 'runoff_coefficient'],
            ['CN u\u017cyty', wb.cn_used.toFixed(1) + (meta.amc ? ' (AMC ' + meta.amc + ')' : ''), 'cn_used'],
            ['Retencja S', wb.retention_mm.toFixed(1) + ' mm', 'retention_mm'],
            ['Straty pocz\u0105tkowe Ia', wb.initial_abstraction_mm.toFixed(1) + ' mm', 'initial_abstraction_mm'],
        ];

        rows.forEach(function (row) {
            var tr = document.createElement('tr');
            var td1 = document.createElement('td');
            td1.textContent = row[0];
            Hydrograf.info.attach(td1, row[2]);
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
        'faa': 'FAA',
        'kerby': 'Kerby',
        'kerby_kirpich': 'Kerby-Kirpich',
    };
    var UH_MODEL_LABELS = {
        'scs': 'SCS',
        'nash': 'Nash',
        'snyder': 'Snyder',
    };
    var NASH_EST_LABELS = {
        'from_tc': 'z Tc (deprecated)',
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
            rows.push(['Metoda Tc', TC_METHOD_LABELS[meta.tc_method] || meta.tc_method, 'tc_method']);
        }
        if (meta.tc_min != null) {
            rows.push(['Tc', meta.tc_min.toFixed(1) + ' min', 'tc_min']);
        }
        rows.push(['Hydrogram jedn.', uhLabel, 'uh_model']);

        if (meta.nash_n != null) {
            rows.push(['Nash N', meta.nash_n.toFixed(2), 'nash_n']);
            rows.push(['Nash K', meta.nash_k_min.toFixed(1) + ' min', 'nash_k_min']);
        }
        if (meta.nash_urban_fraction != null) {
            rows.push(['Urbanizacja U', (meta.nash_urban_fraction * 100).toFixed(1) + '%', 'nash_urban_fraction']);
        }
        if (meta.nash_effective_precip_mm != null) {
            rows.push(['Pe (Nash)', meta.nash_effective_precip_mm.toFixed(1) + ' mm', 'nash_effective_precip_mm']);
        }
        if (meta.nash_duration_h != null) {
            var dMin = Math.round(meta.nash_duration_h * 60);
            rows.push(['D efektywny', dMin + ' min (' + meta.nash_duration_h.toFixed(2) + ' h)', 'nash_duration_h']);
        }

        rows.forEach(function (row) {
            var tr = document.createElement('tr');
            var td1 = document.createElement('td');
            td1.textContent = row[0];
            Hydrograf.info.attach(td1, row[2]);
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

    /**
     * Show the fields the selected model uses. The form is one 2-column grid,
     * so the visible fields close up: for Nash its estimation sits next to
     * "Model UH" and "Metoda Tc" follows only when the estimation needs Tc.
     */
    function updateHydrographFields() {
        var model = document.getElementById('hydro-uh-model').value;
        var estimation = document.getElementById('hydro-nash-estimation').value;
        var method = document.getElementById('hydro-tc-method').value;
        var nash = model === 'nash';
        // Tc method for SCS, Snyder and Nash from_tc
        var needsTc = !nash || estimation === 'from_tc';
        var kerby = method === 'kerby' || method === 'kerby_kirpich';
        var visible = {
            'nash-params': nash,
            'tc-method-params': needsTc,
            'nash-n-row': nash && estimation === 'from_tc',
            'tc-runoff-coeff-col': needsTc && method === 'faa',
            'tc-retardance-col': needsTc && kerby,
            'tc-overland-col': needsTc && (method === 'faa' || kerby),
            'snyder-ct-col': model === 'snyder',
            'snyder-cp-col': model === 'snyder',
        };
        Object.keys(visible).forEach(function (id) {
            document.getElementById(id).classList.toggle('d-none', !visible[id]);
        });
    }

    // ── Init ───────────────────────────────────────────────────────────

    var _INPUT_IDS = [
        'hydro-duration', 'hydro-probability', 'hydro-hietogram-type',
        'hydro-alpha', 'hydro-beta', 'hydro-amc',
        'hydro-uh-model', 'hydro-tc-method',
        'hydro-nash-estimation', 'hydro-nash-n',
        'hydro-snyder-ct', 'hydro-snyder-cp',
        'hydro-tc-runoff-coeff', 'hydro-tc-retardance',
        'hydro-tc-overland-length',
    ];

    function init() {
        initScenarioForm();

        var hietogramType = document.getElementById('hydro-hietogram-type');
        if (hietogramType) {
            hietogramType.addEventListener('change', updateHietogramVisibility);
        }

        ['hydro-uh-model', 'hydro-nash-estimation', 'hydro-tc-method'].forEach(function (id) {
            var select = document.getElementById(id);
            if (select) select.addEventListener('change', updateHydrographFields);
        });
        updateHietogramVisibility();
        updateHydrographFields();

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
