/**
 * Hydrograf advanced mode (Hydrogram section).
 *
 * Editable copy of the morphometry sent to POST /api/generate-hydrograph.
 * The delineated watershed object is never modified: "Parametry podstawowe"
 * keep the original values, edits only change the request payload.
 * State lives per watershed; a new delineation reloads the form.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var DEBOUNCE_MS = 300;

    // kind: 'pos' (> 0), 'elev' (any number), 'cn' (1-100, fractional allowed).
    // digits: display precision, also the input step (0.01 km, 0.1 m, ...).
    // scale: display value = request value * scale (slopes m/m shown in %).
    var FIELDS = [
        { key: 'area_km2', label: 'Powierzchnia zlewni', unit: 'km²', digits: 2, kind: 'pos' },
        { key: 'perimeter_km', label: 'Obwód zlewni', unit: 'km', digits: 2, kind: 'pos' },
        { key: 'length_km', label: 'Długość zlewni', unit: 'km', digits: 2, kind: 'pos' },
        { key: 'elevation_min_m', label: 'Wysokość min.', unit: 'm n.p.m.', digits: 1, kind: 'elev' },
        { key: 'elevation_max_m', label: 'Wysokość max.', unit: 'm n.p.m.', digits: 1, kind: 'elev' },
        { key: 'elevation_mean_m', label: 'Wysokość średnia', unit: 'm n.p.m.', digits: 1, kind: 'elev' },
        { key: 'mean_slope_m_per_m', label: 'Średni spadek terenu', unit: '%', digits: 2, kind: 'pos', scale: 100 },
        { key: 'channel_length_km', label: 'Długość cieku głównego', unit: 'km', digits: 2, kind: 'pos' },
        { key: 'channel_slope_m_per_m', label: 'Spadek cieku głównego', unit: '%', digits: 2, kind: 'pos', scale: 100 },
        // The inputs of Tc (ADR-070): Kirpich, NRCS and Kerby-Kirpich read the flow
        // path, FAA, Kerby and Kerby-Kirpich the overland segment
        { key: 'flow_path_length_km', label: 'Najdłuższa droga spływu (od punktu najdalszego hydraulicznie)', unit: 'km', digits: 2, kind: 'pos' },
        { key: 'flow_path_slope_m_per_m', label: 'Spadek najdłuższej drogi spływu', unit: '%', digits: 2, kind: 'pos', scale: 100 },
        { key: 'overland_length_km', label: 'Spływ powierzchniowy – długość', unit: 'km', digits: 3, kind: 'pos' },
        { key: 'overland_slope_m_per_m', label: 'Spływ powierzchniowy – spadek', unit: '%', digits: 2, kind: 'pos', scale: 100 },
        { key: 'length_to_centroid_km', label: 'Odległość do środka ciężkości Lc', unit: 'km', digits: 2, kind: 'pos' },
        { key: 'cn', label: 'CN (krzywa odpływu)', unit: '–', digits: 1, kind: 'cn' },
    ];

    var RESET_ICON = '<svg viewBox="0 0 16 16" aria-hidden="true">' +
        '<path d="M3.5 8a4.5 4.5 0 1 0 1.3-3.2"/><path d="M4.5 2v3h3"/></svg>';

    var _watershed = null;   // watershed response the form was filled from
    var _original = null;    // its morphometry (never modified)
    var _rows = {};          // key -> { field, wrap, input, reset, err, orig, shown }
    var _timer = null;
    var _areaLimit = null;   // km², area_limit_km2 of GET /api/scenarios
    var els = {};

    // ── Values ─────────────────────────────────────────────────────────

    function toDisplay(field, value) {
        if (value === null || value === undefined) return null;
        var scaled = value * (field.scale || 1);
        return Number(scaled.toFixed(field.digits));
    }

    function formatNumber(field, n) {
        return n === null ? '' : n.toFixed(field.digits);
    }

    /** Parsed input: null when empty, NaN when not a number. */
    function readInput(row) {
        var raw = row.input.value.trim();
        if (raw === '') {
            // type=number reports '' for unparseable text as well
            return row.input.validity && row.input.validity.badInput ? NaN : null;
        }
        return Number(raw.replace(',', '.'));
    }

    function isEdited(row) {
        var v = readInput(row);
        if (v === null) return row.shown !== null;
        if (isNaN(v)) return true;
        return row.shown === null || Math.abs(v - row.shown) > 1e-9;
    }

    function validateRow(row, values, edited) {
        var f = row.field;
        var v = values[f.key];
        // Values delivered by Hydrograf are sent as they are
        if (!edited[f.key] && !(f.key === 'elevation_max_m' && edited.elevation_min_m)) return '';
        if (v === null) return row.shown === null ? '' : 'Podaj wartość.';
        if (!isFinite(v)) return 'Podaj liczbę.';
        if (f.kind === 'pos' && v <= 0) return 'Wartość musi być dodatnia.';
        if (f.kind === 'cn' && (v < 1 || v > 100)) {
            return 'CN: liczba od 1 do 100 (np. 68.4).';
        }
        // The API refuses a larger catchment, as it does for a delineated one
        if (f.key === 'area_km2' && _areaLimit !== null && v > _areaLimit) {
            return 'Hietogram i hydrogram są liczone dla zlewni do ' +
                String(_areaLimit).replace('.', ',') + ' km².';
        }
        if (f.key === 'elevation_max_m') {
            var vmin = values.elevation_min_m;
            if (vmin !== null && isFinite(vmin) && v < vmin) {
                return 'Wysokość max. nie może być mniejsza od min.';
            }
        }
        return '';
    }

    /** Validate every field, refresh marks and errors. Returns the form state. */
    function evaluate() {
        var values = {};
        var edited = {};
        FIELDS.forEach(function (f) {
            values[f.key] = readInput(_rows[f.key]);
            edited[f.key] = isEdited(_rows[f.key]);
        });

        var changed = [];
        var errors = 0;
        FIELDS.forEach(function (f) {
            var row = _rows[f.key];
            var msg = validateRow(row, values, edited);
            if (edited[f.key]) changed.push(f);
            if (msg) errors++;

            row.wrap.classList.toggle('is-edited', edited[f.key]);
            row.wrap.classList.toggle('is-invalid', !!msg);
            row.input.setAttribute('aria-invalid', msg ? 'true' : 'false');
            row.reset.disabled = !edited[f.key];
            row.err.textContent = msg;
            row.err.classList.toggle('d-none', !msg);
            row.orig.textContent = edited[f.key]
                ? 'Hydrograf: ' + (row.shown === null ? 'brak' : formatNumber(f, row.shown) + (f.unit === '–' ? '' : ' ' + f.unit))
                : '';
            row.orig.classList.toggle('d-none', !edited[f.key]);
        });

        els.resetAll.disabled = changed.length === 0;
        els.invalid.classList.toggle('d-none', errors === 0);
        els.count.textContent = changed.length
            ? 'Zmienione: ' + changed.length
            : '';
        return { values: values, changed: changed, valid: errors === 0 };
    }

    /** Request morphometry: original copy with edited fields applied. */
    function buildMorphometry(state) {
        var morph = Object.assign({}, _original);
        state.changed.forEach(function (f) {
            var v = state.values[f.key];
            if (v === null) {
                delete morph[f.key];
            } else {
                morph[f.key] = f.scale ? v / f.scale : v;
            }
        });
        return morph;
    }

    // ── Watershed sync ─────────────────────────────────────────────────

    function load(data) {
        _watershed = data;
        _original = (data && data.watershed && data.watershed.morphometry) || null;
        FIELDS.forEach(function (f) {
            var row = _rows[f.key];
            row.shown = _original ? toDisplay(f, _original[f.key]) : null;
            row.input.value = formatNumber(f, row.shown);
            row.input.placeholder = row.shown === null ? 'brak' : '';
        });
        evaluate();
        updateNotice([]);
    }

    function sync() {
        var data = Hydrograf.app && Hydrograf.app.getCurrentWatershed();
        if (data && data !== _watershed) load(data);
    }

    // ── Results notice ─────────────────────────────────────────────────

    function updateNotice(changed) {
        if (!els.notice) return;
        els.notice.classList.toggle('d-none', changed.length === 0);
        els.noticeList.textContent = changed.map(function (f) {
            return f.label;
        }).join(', ');
    }

    // ── Hook for hydrograph.js ─────────────────────────────────────────

    /**
     * Morphometry for the hydrograph request of the given watershed.
     * Returns { valid, morphometry, changed }; valid is false while the advanced
     * form is on and has errors (the caller must not send the request), changed
     * lists the keys of the fields the person changed (the hand-off names them).
     */
    function requestMorphometry(data) {
        if (data !== _watershed) load(data);
        var original = _original;
        if (!els.toggle || !els.toggle.checked || !original) {
            updateNotice([]);
            return { valid: true, morphometry: original, changed: [] };
        }
        var state = evaluate();
        if (!state.valid) return { valid: false, morphometry: null, changed: [] };
        updateNotice(state.changed);
        return {
            valid: true,
            morphometry: state.changed.length ? buildMorphometry(state) : original,
            changed: state.changed.map(function (f) { return f.key; }),
        };
    }

    /**
     * Area limit of the hydrograph (GET /api/scenarios); the field "Powierzchnia
     * zlewni" accepts no more, like a delineated watershed.
     */
    function setAreaLimit(limit) {
        _areaLimit = typeof limit === 'number' && isFinite(limit) ? limit : null;
        var row = _rows.area_km2;
        if (!row) return;
        if (_areaLimit === null) row.input.removeAttribute('max');
        else row.input.max = String(_areaLimit);
        evaluate();
    }

    // ── Events ─────────────────────────────────────────────────────────

    function regenerate() {
        clearTimeout(_timer);
        _timer = null;
        if (Hydrograf.hydrograph) Hydrograf.hydrograph.generateHydrograph();
    }

    function scheduleRegenerate() {
        clearTimeout(_timer);
        _timer = setTimeout(regenerate, DEBOUNCE_MS);
    }

    // Every edit reaches hydrograph.js: while the form is invalid it sends
    // nothing and hides the earlier result
    function onFieldInput() {
        evaluate();
        scheduleRegenerate();
    }

    function resetRow(row) {
        row.input.value = formatNumber(row.field, row.shown);
    }

    function onToggle() {
        sync();
        var on = els.toggle.checked;
        els.form.classList.toggle('d-none', !on);
        var state = evaluate();
        // Edits change the payload only while the mode is on
        if (state.changed.length) regenerate();
    }

    function onResetAll() {
        FIELDS.forEach(function (f) { resetRow(_rows[f.key]); });
        evaluate();
        regenerate();
    }

    // ── Build ──────────────────────────────────────────────────────────

    function buildField(f) {
        var id = 'adv-' + f.key.replace(/_/g, '-');

        var wrap = document.createElement('div');
        wrap.className = 'adv-field';

        var label = document.createElement('label');
        label.htmlFor = id;
        label.textContent = f.label;
        var flag = document.createElement('span');
        flag.className = 'adv-flag';
        flag.textContent = 'zmieniono';
        label.appendChild(flag);

        var line = document.createElement('div');
        line.className = 'adv-line';

        var input = document.createElement('input');
        input.id = id;
        input.type = 'number';
        input.step = Math.pow(10, -f.digits).toFixed(f.digits);
        if (f.kind === 'cn') {
            input.min = '1';
            input.max = '100';
        }
        input.inputMode = 'decimal';
        input.setAttribute('aria-describedby', id + '-err ' + id + '-orig');

        var unit = document.createElement('span');
        unit.className = 'adv-unit';
        unit.textContent = f.unit;

        var reset = document.createElement('button');
        reset.type = 'button';
        reset.className = 'btn ghost sm icon adv-reset';
        reset.title = 'Przywróć wartość z Hydrografa';
        reset.setAttribute('aria-label', 'Przywróć wartość z Hydrografa: ' + f.label);
        reset.innerHTML = RESET_ICON;

        var orig = document.createElement('div');
        orig.id = id + '-orig';
        orig.className = 'adv-orig d-none';

        var err = document.createElement('div');
        err.id = id + '-err';
        err.className = 'adv-err d-none';

        line.appendChild(input);
        line.appendChild(unit);
        line.appendChild(reset);
        wrap.appendChild(label);
        wrap.appendChild(line);
        wrap.appendChild(orig);
        wrap.appendChild(err);

        var row = { field: f, wrap: wrap, input: input, reset: reset, err: err, orig: orig, shown: null };
        input.addEventListener('input', onFieldInput);
        reset.addEventListener('click', function () {
            resetRow(row);
            onFieldInput();
            input.focus();
        });
        return row;
    }

    function init() {
        els.toggle = document.getElementById('adv-toggle');
        els.form = document.getElementById('adv-form');
        els.fields = document.getElementById('adv-fields');
        els.resetAll = document.getElementById('adv-reset-all');
        els.invalid = document.getElementById('adv-invalid');
        els.count = document.getElementById('adv-count');
        els.notice = document.getElementById('adv-notice');
        els.noticeList = document.getElementById('adv-notice-list');
        if (!els.toggle || !els.form || !els.fields) return;

        FIELDS.forEach(function (f) {
            var row = buildField(f);
            _rows[f.key] = row;
            els.fields.appendChild(row.wrap);
        });

        els.toggle.addEventListener('change', onToggle);
        els.resetAll.addEventListener('click', onResetAll);
        load(null);
    }

    document.addEventListener('DOMContentLoaded', init);

    window.Hydrograf.advanced = {
        requestMorphometry: requestMorphometry,
        setAreaLimit: setAreaLimit,
    };
})();
