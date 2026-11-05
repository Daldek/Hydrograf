/**
 * Hydrograf Hydrograph module.
 *
 * Hietogram form (precipitation), hydrograph form (UH model),
 * charts, water balance table. Auto-regenerates on parameter change.
 * The number fields are checked against the limits of the API before a
 * request; an invalid field (or a server error at it) shows its message under
 * it, and the result of an earlier calculation is hidden until it is fixed.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var scenariosLoaded = false;
    var _debounceTimer = null;
    var _DEBOUNCE_MS = 300;
    var _requestId = 0;

    // ── Number fields ──────────────────────────────────────────────────

    // The limits of the API (HydrographRequest): gt is an exclusive lower
    // bound, min and max are inclusive. `key` is the request field, which is
    // also the JSON Pointer /body/<key> of a server validation error; `part`
    // is the element whose choice (hydrographParts) puts the field in use.
    var NUMBER_FIELDS = [
        { id: 'hydro-alpha', key: 'hietogram_alpha', label: '\u03b1', section: 'Hietogram', part: 'beta-params', gt: 0, max: 20 },
        { id: 'hydro-beta', key: 'hietogram_beta', label: '\u03b2', section: 'Hietogram', part: 'beta-params', gt: 0, max: 20 },
        { id: 'hydro-nash-n', key: 'nash_n', label: 'N (zbiorniki)', section: 'Hydrogram', part: 'nash-n-row', gt: 0, max: 20 },
        { id: 'hydro-tc-runoff-coeff', key: 'tc_runoff_coeff', label: 'C (sp\u0142yw)', section: 'Hydrogram', part: 'tc-runoff-coeff-col', min: 0, max: 1, optional: true },
        { id: 'hydro-tc-retardance', key: 'tc_retardance', label: 'N (op\u00f3r)', section: 'Hydrogram', part: 'tc-retardance-col', min: 0.02, max: 0.8 },
        { id: 'hydro-tc-overland-length', key: 'tc_overland_length_km', label: 'L sp\u0142ywu', section: 'Hydrogram', part: 'tc-overland-col', gt: 0, max: 5 },
        { id: 'hydro-snyder-ct', key: 'snyder_ct', label: 'Ct', section: 'Hydrogram', part: 'snyder-ct-col', gt: 0 },
        { id: 'hydro-snyder-cp', key: 'snyder_cp', label: 'Cp', section: 'Hydrogram', part: 'snyder-cp-col', gt: 0, max: 1 },
    ];
    var FIELD_BY_KEY = {};
    NUMBER_FIELDS.forEach(function (field) { FIELD_BY_KEY[field.key] = field; });

    /** A number as Polish text shows it: 0.8 -> "0,8". */
    function plNumber(n) {
        return String(n).replace('.', ',');
    }

    /** Choices of the forms that decide which fields a request uses. */
    function choices() {
        var model = document.getElementById('hydro-uh-model').value;
        var estimation = document.getElementById('hydro-nash-estimation').value;
        return {
            hietogram: document.getElementById('hydro-hietogram-type').value,
            model: model,
            estimation: estimation,
            // Tc for SCS, Snyder and Nash from_tc
            needsTc: model !== 'nash' || estimation === 'from_tc',
            tc: document.getElementById('hydro-tc-method').value,
        };
    }

    /** The parts of the Hydrogram form the choices use, by element id. */
    function hydrographParts(c) {
        var kerby = c.tc === 'kerby' || c.tc === 'kerby_kirpich';
        return {
            'nash-params': c.model === 'nash',
            'tc-method-params': c.needsTc,
            'nash-n-row': c.model === 'nash' && c.estimation === 'from_tc',
            'tc-runoff-coeff-col': c.needsTc && c.tc === 'faa',
            'tc-retardance-col': c.needsTc && kerby,
            'tc-overland-col': c.needsTc && (c.tc === 'faa' || kerby),
            'snyder-ct-col': c.model === 'snyder',
            'snyder-cp-col': c.model === 'snyder',
        };
    }

    /** Whether the request sends the field: α and β only with a PMAXTP Beta storm. */
    function inUse(field, c, customRain) {
        if (field.part === 'beta-params') return !customRain && c.hietogram === 'beta';
        return hydrographParts(c)[field.part];
    }

    /**
     * Check a field the request uses against the API limits:
     * { value, error }; value is null for an empty optional field.
     */
    function checkNumber(field, c) {
        var input = document.getElementById(field.id);
        var raw = input.value.trim();
        if (raw === '') {
            // type=number reports '' for text it cannot parse as well
            if (input.validity && input.validity.badInput) return { value: null, error: 'Podaj liczb\u0119.' };
            // Kerby-Kirpich estimates L when it is empty, FAA and Kerby need it
            if (field.optional || (field.key === 'tc_overland_length_km' && c.tc === 'kerby_kirpich')) {
                return { value: null, error: '' };
            }
            if (field.key === 'tc_overland_length_km') {
                return { value: null, error: 'Metoda ' + (c.tc === 'faa' ? 'FAA' : 'Kerby') + ' wymaga d\u0142ugo\u015bci sp\u0142ywu L.' };
            }
            return { value: null, error: 'Podaj warto\u015b\u0107.' };
        }
        var v = Number(raw.replace(',', '.'));
        var error = '';
        if (!isFinite(v)) error = 'Podaj liczb\u0119.';
        else if (field.gt !== undefined && !(v > field.gt)) error = 'Warto\u015b\u0107 musi by\u0107 wi\u0119ksza od ' + plNumber(field.gt) + '.';
        else if (field.min !== undefined && v < field.min) error = 'Warto\u015b\u0107 nie mo\u017ce by\u0107 mniejsza ni\u017c ' + plNumber(field.min) + '.';
        else if (field.max !== undefined && v > field.max) error = 'Warto\u015b\u0107 nie mo\u017ce by\u0107 wi\u0119ksza ni\u017c ' + plNumber(field.max) + '.';
        return { value: error ? null : v, error: error };
    }

    /** Show the message of a field under it, or clear it (''). */
    function setFieldError(field, message) {
        var input = document.getElementById(field.id);
        var wrap = input.closest('.field');
        var err = document.getElementById(field.id + '-err');
        if (!err && message) {
            err = document.createElement('div');
            err.id = field.id + '-err';
            err.className = 'field-err';
            wrap.appendChild(err);
            input.setAttribute('aria-describedby', err.id);
        }
        wrap.classList.toggle('is-invalid', !!message);
        input.setAttribute('aria-invalid', message ? 'true' : 'false');
        if (err) {
            err.textContent = message;
            err.classList.toggle('d-none', !message);
        }
    }

    /**
     * Read the fields the request uses and mark each one; the fields out of
     * use lose their marks. Returns { values: { key: number|null }, invalid }.
     */
    function readNumberFields(c, customRain) {
        var values = {};
        var invalid = [];
        NUMBER_FIELDS.forEach(function (field) {
            var used = inUse(field, c, customRain);
            var checked = used ? checkNumber(field, c) : { value: null, error: '' };
            setFieldError(field, checked.error);
            if (checked.error) invalid.push(field);
            else if (used) values[field.key] = checked.value;
        });
        return { values: values, invalid: invalid };
    }

    function fieldName(field) {
        return field.label + ' (' + field.section + ')';
    }

    // ── Errors and stale results ───────────────────────────────────────

    /** Messages of the calculation in the Hietogram and Hydrogram sections; '' hides one. */
    function showCalcErrors(hietogram, hydrograph) {
        [['hietogram-error', hietogram], ['hydro-error', hydrograph]].forEach(function (pair) {
            var el = document.getElementById(pair[0]);
            el.querySelector('.calc-error-text').textContent = pair[1];
            el.classList.toggle('d-none', !pair[1]);
        });
    }

    /** Why no calculation runs: the invalid fields by name, '' for none. */
    function blockedMessage(names) {
        if (!names.length) return '';
        return 'Popraw zaznaczone pola: ' + names.join(', ') +
            '. Do tego czasu hietogram i hydrogram nie s\u0105 przeliczane.';
    }

    /** Hide the result of an earlier calculation: it no longer matches the form. */
    function hideResults() {
        document.getElementById('hietogram-results').classList.add('d-none');
        document.getElementById('hydrograph-results').classList.add('d-none');
        document.getElementById('hydrograph-info').textContent = '';
        // The hand-off to Hydrolog keeps the watershed without the hidden result
        if (Hydrograf.handoff) Hydrograf.handoff.showHydrograph(Hydrograf.app.getCurrentWatershed(), null);
    }

    /**
     * Place the invalid values of a server validation error at their fields;
     * return the message for the sections.
     */
    function serverErrorMessage(err) {
        var problem = err && err.problem;
        var errors = problem && Array.isArray(problem.errors) ? problem.errors : [];
        if (!errors.length) return err.message;
        var fields = [];
        var other = [];
        errors.forEach(function (e) {
            var field = FIELD_BY_KEY[String(e.pointer || '').replace(/^\/body\//, '')];
            if (field) {
                setFieldError(field, e.message);
                fields.push(fieldName(field));
            } else {
                other.push(e.message);
            }
        });
        return (fields.length ? 'Popraw zaznaczone pola: ' + fields.join(', ') + '. ' : '') + other.join(' ');
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

            if (Hydrograf.customRain) {
                Hydrograf.customRain.setMaxSteps(scenarios.custom_precipitation_max_steps);
            }
            if (Hydrograf.advanced) {
                Hydrograf.advanced.setAreaLimit(scenarios.area_limit_km2);
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
        // Advanced mode may replace the morphometry and an own rainfall series
        // the PMAXTP design storm; no request while a form is invalid, and the
        // earlier result is hidden because it no longer matches the form
        var morph = Hydrograf.advanced
            ? Hydrograf.advanced.requestMorphometry(data)
            : { valid: true, morphometry: data.watershed.morphometry || null, changed: [] };
        var rain = Hydrograf.customRain
            ? Hydrograf.customRain.request(data)
            : { active: false, valid: true, series: null };
        var c = choices();
        var fields = readNumberFields(c, rain.active);

        var myId = ++_requestId;
        var invalid = fields.invalid.map(fieldName);
        if (invalid.length || !rain.valid || !morph.valid) {
            hideResults();
            // The own series and the advanced mode name their errors in their own section
            showCalcErrors(
                blockedMessage(invalid.concat(morph.valid ? [] : ['tryb zaawansowany (Hydrogram)'])),
                blockedMessage(invalid.concat(rain.valid ? [] : ['w\u0142asna seria opadu (Hietogram)']))
            );
            return;
        }

        var duration = null;
        var probability = null;
        var values = fields.values;

        try {
            var opts = {
                morphometry: morph.morphometry,
                amc: document.getElementById('hydro-amc').value,
                uh_model: c.model,
            };
            if (morph.morphometry) {
                // Where the morphometry came from: the hand-off of the response names it
                opts.morphometry_origin = {
                    latitude: data.watershed.outlet.latitude,
                    longitude: data.watershed.outlet.longitude,
                    changed: morph.changed,
                };
            }
            if (rain.active) {
                opts.custom_precipitation = rain.series;
            } else {
                duration = document.getElementById('hydro-duration').value;
                probability = parseFloat(document.getElementById('hydro-probability').value);
                opts.hietogram_type = c.hietogram;
                if (c.hietogram === 'beta') {
                    opts.hietogram_alpha = values.hietogram_alpha;
                    opts.hietogram_beta = values.hietogram_beta;
                }
            }
            if (c.needsTc) {
                opts.tc_method = c.tc;
                // Tc extra parameters; an empty optional one is left to the API
                ['tc_runoff_coeff', 'tc_retardance', 'tc_overland_length_km'].forEach(function (key) {
                    if (values[key] != null) opts[key] = values[key];
                });
            }
            if (c.model === 'nash') {
                opts.nash_estimation = c.estimation;
                if (c.estimation === 'from_tc') opts.nash_n = values.nash_n;
            }
            if (c.model === 'snyder') {
                opts.snyder_ct = values.snyder_ct;
                opts.snyder_cp = values.snyder_cp;
            }

            var result = await Hydrograf.api.generateHydrograph(
                click.lat, click.lng, duration, probability, opts
            );

            if (myId !== _requestId) return;

            showCalcErrors('', '');
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
            if (Hydrograf.handoff) Hydrograf.handoff.showHydrograph(data, result.handoff);
        } catch (err) {
            if (myId !== _requestId) return;
            console.warn('Hydrograph error:', err.message);
            hideResults();
            var message = serverErrorMessage(err);
            showCalcErrors(message, message);
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
        if (meta.nash_forest_pct != null) {
            rows.push(['Lasy W', meta.nash_forest_pct.toFixed(1) + '%', 'nash_forest_pct']);
        }
        if (meta.nash_urban_pct != null) {
            rows.push(['Tereny zurbanizowane U', meta.nash_urban_pct.toFixed(1) + '%', 'nash_urban_pct']);
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
        var c = choices();
        var parts = hydrographParts(c);
        Object.keys(parts).forEach(function (id) {
            document.getElementById(id).classList.toggle('d-none', !parts[id]);
        });
        // FAA and Kerby need L; Kerby-Kirpich estimates it when it is empty
        document.getElementById('hydro-tc-overland-length').placeholder =
            c.tc === 'kerby_kirpich' ? 'auto' : 'wymagane';
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
