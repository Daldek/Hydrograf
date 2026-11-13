/**
 * Hydrograf own rainfall series (Hietogram section).
 *
 * "Źródło opadu" switches between the PMAXTP design storm and an own series:
 * a table of depths per time step, typed in, pasted from a spreadsheet or
 * imported from CSV. While the own series is active hydrograph.js sends it as
 * `custom_precipitation` instead of duration, probability and hietogram.
 * A series loaded from the current PMAXTP hietogram stays derived from PMAXTP
 * through edits, pastes and a new size: it is sent with `derived_from: 'pmaxtp'`
 * and hands the provider lines of that result to the view's strip while the
 * table is shown (attribution.js) until "Wyczyść", a CSV import or a new watershed.
 * The series belongs to one delineated watershed; a new delineation resets it.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var DEBOUNCE_MS = 300;
    var DEFAULT_DURATION_MIN = 60;
    var DEFAULT_STEP_MIN = 5;
    var MAX_STEP_MIN = 1440;            // API limit of timestep_min (one day)
    var EPS = 1e-6;
    var NUMBER_RE = /^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i;
    var LETTER_RE = /[a-ząćęłńóśźż_]/i;

    var _maxSteps = 2000;               // replaced by custom_precipitation_max_steps (/api/scenarios)
    var _watershed = null;              // watershed response the series belongs to
    var _custom = false;                // "Własna seria" selected
    var _cells = [];                    // depth texts by step index (may outlast a shorter table)
    var _step = DEFAULT_STEP_MIN;       // step of the rendered rows [min]
    var _pmaxtp = null;                 // { watershed, step, depths, lines } of the last PMAXTP result
    var _derived = null;                // provider lines of the PMAXTP result the series was copied from; null for own data
    var _timer = null;
    var els = {};

    // ── Numbers ────────────────────────────────────────────────────────

    /** Parsed number: null when empty, NaN when not a number; decimal comma allowed. */
    function parseNumber(text) {
        var s = String(text).replace(/\s+/g, '').replace(',', '.');
        if (s === '') return null;
        return NUMBER_RE.test(s) ? Number(s) : NaN;
    }

    /** Header text such as "opad [mm]": letters and not a number (1e3 is a number). */
    function isLabel(text) {
        return LETTER_RE.test(text) && Number.isNaN(parseNumber(text));
    }

    /** Minutes without floating point noise (0.1 * 3 → "0.3"). */
    function fmt(value) {
        return String(Number(value.toFixed(3)));
    }

    /** Polish plural: 1 krok, 2–4 kroki, 5+ kroków. */
    function plural(n, one, few, many) {
        if (n === 1) return one;
        var mod10 = n % 10;
        var mod100 = n % 100;
        return (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) ? few : many;
    }

    function steps(n) {
        return n + ' ' + plural(n, 'krok', 'kroki', 'kroków');
    }

    // ── Duration and step ──────────────────────────────────────────────

    /** Valid step from its field [min], or null. */
    function readStep() {
        var step = parseNumber(els.step.value);
        return step !== null && isFinite(step) && step > 0 && step <= MAX_STEP_MIN ? step : null;
    }

    /** Table size from the two fields: { n, step } or { error, field }. */
    function readDims() {
        var step = readStep();
        var duration = parseNumber(els.duration.value);
        if (step === null) {
            return {
                error: 'Krok czasowy: podaj liczbę minut większą od 0, najwyżej ' + MAX_STEP_MIN + ' (1 doba).',
                field: els.step,
            };
        }
        if (duration === null || !isFinite(duration) || duration <= 0) {
            return { error: 'Czas trwania: podaj liczbę minut większą od 0.', field: els.duration };
        }
        var n = Math.round(duration / step);
        if (n < 1 || Math.abs(n * step - duration) > EPS * Math.max(1, duration)) {
            return {
                error: 'Czas trwania musi być wielokrotnością kroku czasowego (' + fmt(step) + ' min).',
                field: els.duration,
            };
        }
        if (n > _maxSteps) {
            return {
                error: 'Za dużo kroków: ' + n + ' (limit ' + _maxSteps + '). Zwiększ krok czasowy albo skróć czas trwania.',
                field: els.duration,
            };
        }
        return { n: n, step: step };
    }

    function setDims(n, step) {
        els.step.value = fmt(step);
        els.duration.value = fmt(n * step);
    }

    // ── Table ──────────────────────────────────────────────────────────

    function setRowTime(tr, i) {
        var end = fmt((i + 1) * _step);
        tr.cells[0].textContent = end;
        tr.cells[1].firstChild.setAttribute('aria-label',
            'Opad [mm] w kroku ' + (i + 1) + ' (' + fmt(i * _step) + '–' + end + ' min)');
    }

    function buildRow(i) {
        var tr = document.createElement('tr');
        var th = document.createElement('th');
        th.scope = 'row';
        var td = document.createElement('td');
        var input = document.createElement('input');
        input.type = 'text';
        input.inputMode = 'decimal';
        input.autocomplete = 'off';
        input.spellcheck = false;
        input.placeholder = '0';
        input.value = _cells[i] || '';
        td.appendChild(input);
        tr.appendChild(th);
        tr.appendChild(td);
        setRowTime(tr, i);
        return tr;
    }

    /** Show n rows of the given step; rows are added or removed at the end. */
    function renderRows(n, step) {
        var body = els.rows;
        var stepChanged = step !== _step;
        _step = step;
        while (body.rows.length > n) body.deleteRow(-1);
        if (stepChanged) {
            for (var i = 0; i < body.rows.length; i++) setRowTime(body.rows[i], i);
        }
        var frag = document.createDocumentFragment();
        for (var j = body.rows.length; j < n; j++) frag.appendChild(buildRow(j));
        body.appendChild(frag);
    }

    /** Write _cells into the rendered inputs (after paste, import, clear). */
    function fillInputs() {
        var rows = els.rows.rows;
        for (var i = 0; i < rows.length; i++) rows[i].cells[1].firstChild.value = _cells[i] || '';
    }

    function cellInput(target) {
        return target && target.tagName === 'INPUT' && els.rows.contains(target) ? target : null;
    }

    function rowIndex(input) {
        return input.closest('tr').sectionRowIndex;
    }

    // ── State ──────────────────────────────────────────────────────────

    function markInvalid(input, invalid) {
        input.classList.toggle('is-invalid', invalid);
        input.setAttribute('aria-invalid', invalid ? 'true' : 'false');
    }

    /**
     * Validate the fields and the table, refresh rows, marks, sum and errors.
     * Returns { valid, step, depths }.
     */
    function refresh() {
        var dims = readDims();
        markInvalid(els.duration, dims.field === els.duration);
        markInvalid(els.step, dims.field === els.step);

        var error = dims.error || '';
        var depths = [];
        var sum = 0;
        if (!error) {
            renderRows(dims.n, dims.step);
            var rows = els.rows.rows;
            for (var i = 0; i < dims.n; i++) {
                var input = rows[i].cells[1].firstChild;
                var v = parseNumber(_cells[i] || '');
                var bad = '';
                if (v !== null && !isFinite(v)) {
                    bad = 'Wiersz ' + (i + 1) + ' (' + fmt((i + 1) * dims.step) + ' min): „' +
                        _cells[i].trim() + '” nie jest liczbą.';
                } else if (v !== null && v < 0) {
                    bad = 'Wiersz ' + (i + 1) + ' (' + fmt((i + 1) * dims.step) + ' min): opad nie może być ujemny.';
                }
                markInvalid(input, !!bad);
                if (bad && !error) error = bad;
                var depth = bad || v === null ? 0 : v;
                depths.push(depth);
                sum += depth;
            }
        }

        var empty = !error && sum <= 0;
        els.sum.classList.toggle('d-none', !!dims.error);
        els.sum.textContent = dims.error ? '' :
            'Suma: ' + sum.toFixed(2) + ' mm · ' + steps(dims.n) + ' po ' + fmt(dims.step) + ' min';
        els.invalid.classList.toggle('d-none', !error);
        els.invalidText.textContent = error ? error + ' Do tego czasu hydrogram nie jest przeliczany.' : '';
        if (empty && !els.msgText.textContent) {
            showMessage('info', 'Wpisz wysokości opadu (suma musi być większa od 0 mm), wklej je z arkusza albo zaimportuj plik CSV.', true);
        } else if (!empty && els.msg.dataset.hint) {
            showMessage(null, '');
        }

        return { valid: !error && !empty, step: dims.step, depths: depths };
    }

    /** Message under the table: import/paste result or the empty-series hint. */
    function showMessage(kind, text, hint) {
        els.msg.classList.toggle('d-none', !text);
        els.msg.classList.toggle('bad', kind === 'bad');
        els.msg.setAttribute('role', kind === 'bad' ? 'alert' : 'status');
        els.msgText.textContent = text;
        if (hint) els.msg.dataset.hint = '1';
        else delete els.msg.dataset.hint;
    }

    /** Replace the series (PMAXTP copy, CSV import); the caller refreshes. */
    function setSeries(step, depths) {
        _cells = depths.map(function (d) { return String(d); });
        setDims(depths.length, step);
        fillInputs();
    }

    /** The series as a copy of a PMAXTP result (its provider lines), or the user's own data (null). */
    function setDerived(lines) {
        _derived = lines;
        // In the view's strip while the table is laid out (attribution.js)
        Hydrograf.attribution.show('custom-rain', lines, [els.form]);
    }

    function updateLoadButton() {
        els.load.disabled = !(_pmaxtp && _pmaxtp.watershed === _watershed);
        els.load.title = els.load.disabled
            ? 'Brak hietogramu PMAXTP dla tej zlewni: przełącz źródło na PMAXTP, aby go obliczyć.'
            : '';
    }

    function setSourceUi() {
        [[els.srcPmaxtp, !_custom], [els.srcCustom, _custom]].forEach(function (pair) {
            pair[0].classList.toggle('on', pair[1]);
            pair[0].setAttribute('aria-checked', String(pair[1]));
            pair[0].tabIndex = pair[1] ? 0 : -1;
        });
        els.pmaxtpForm.classList.toggle('d-none', _custom);
        els.form.classList.toggle('d-none', !_custom);
    }

    /** New watershed: PMAXTP again, empty series with the default size. */
    function reset(data) {
        _watershed = data;
        _custom = false;
        _cells = [];
        setDerived(null);
        if (_pmaxtp && _pmaxtp.watershed !== data) _pmaxtp = null;
        els.duration.value = String(DEFAULT_DURATION_MIN);
        els.step.value = String(DEFAULT_STEP_MIN);
        showMessage(null, '');
        fillInputs();
        refresh();
        setSourceUi();
        updateLoadButton();
    }

    function sync() {
        var data = Hydrograf.app && Hydrograf.app.getCurrentWatershed();
        if (data && data !== _watershed) reset(data);
    }

    // ── Recalculation ──────────────────────────────────────────────────

    function regenerate() {
        clearTimeout(_timer);
        _timer = null;
        if (Hydrograf.hydrograph) Hydrograf.hydrograph.generateHydrograph();
    }

    function scheduleRegenerate() {
        clearTimeout(_timer);
        _timer = setTimeout(regenerate, DEBOUNCE_MS);
    }

    /**
     * After any change of the series: recalculate. While the series is invalid
     * hydrograph.js sends nothing and hides the earlier result.
     */
    function changed() {
        refresh();
        scheduleRegenerate();
    }

    // ── Paste ──────────────────────────────────────────────────────────

    /**
     * Values of pasted text: one per line or tab-separated (a spreadsheet row);
     * from a block of several columns the last filled column is taken.
     * A leading header cell (text that is not a number) is skipped.
     */
    function splitPaste(text) {
        var lines = text.replace(/\r\n?/g, '\n').replace(/\n+$/, '').split('\n');
        var values;
        if (lines.length > 1) {
            values = lines.map(function (line) {
                var cells = line.split('\t').map(function (c) { return c.trim(); })
                    .filter(function (c) { return c !== ''; });
                return cells.length ? cells[cells.length - 1] : '';
            });
        } else {
            values = lines[0].split('\t').map(function (c) { return c.trim(); });
        }
        if (values.length > 1 && isLabel(values[0])) values.shift();
        return values;
    }

    function onPaste(e) {
        var input = cellInput(e.target);
        if (!input || !e.clipboardData) return;
        var values = splitPaste(e.clipboardData.getData('text/plain'));
        if (values.length < 2) return;      // one value: the browser pastes it
        e.preventDefault();

        var dims = readDims();
        if (dims.error) {
            showMessage('bad', 'Nie wklejono: ' + dims.error);
            return;
        }
        var start = rowIndex(input);
        var end = start + values.length;
        if (end > _maxSteps) {
            showMessage('bad', 'Nie wklejono ' + values.length + ' wartości od wiersza ' + (start + 1) +
                ': szereg przekroczyłby limit ' + _maxSteps + ' kroków.');
            return;
        }
        values.forEach(function (v, k) { _cells[start + k] = v; });
        if (end > dims.n) setDims(end, dims.step);
        showMessage('info', 'Wklejono ' + values.length + ' wartości od wiersza ' + (start + 1) +
            (end > dims.n ? '; czas trwania wydłużono do ' + fmt(end * dims.step) + ' min.' : '.'));
        fillInputs();
        changed();
    }

    // ── CSV import ─────────────────────────────────────────────────────

    /** Split a CSV line on `sep` outside double quotes; quotes are removed. */
    function splitCsvLine(line, sep) {
        var cells = [];
        var cell = '';
        var quoted = false;
        for (var i = 0; i < line.length; i++) {
            var ch = line[i];
            if (ch === '"') {
                if (quoted && line[i + 1] === '"') { cell += '"'; i++; }
                else quoted = !quoted;
            } else if (ch === sep && !quoted) {
                cells.push(cell.trim());
                cell = '';
            } else {
                cell += ch;
            }
        }
        cells.push(cell.trim());
        while (cells.length > 1 && cells[cells.length - 1] === '') cells.pop();
        return cells;
    }

    /**
     * Parse an own series from CSV text.
     * One column: depths [mm] with the current step. Two columns: time [min]
     * (end of each step, or 0 for the start of the first one) and depth [mm]
     * with a uniform step. Optional header row; separator `,` `;` or tab;
     * decimal comma with `;` or tab (and in quoted cells).
     * Returns { depths, step, columns } or { error } (Polish, with the line).
     */
    function parseCsv(text, currentStep) {
        var rows = [];
        text.replace(/^\uFEFF/, '').split(/\r\n|\r|\n/).forEach(function (line, i) {
            if (line.trim() !== '') rows.push({ line: i + 1, text: line });
        });
        if (!rows.length) return { error: 'plik jest pusty.' };

        var sep = null;
        if (rows.some(function (r) { return r.text.indexOf('\t') >= 0; })) sep = '\t';
        else if (rows.some(function (r) { return r.text.indexOf(';') >= 0; })) sep = ';';
        else if (rows.some(function (r) { return r.text.indexOf(',') >= 0; })) sep = ',';
        rows.forEach(function (r) { r.cells = sep ? splitCsvLine(r.text, sep) : [r.text.trim()]; });

        var header = rows[0].cells.some(isLabel) ? rows.shift() : null;
        if (!rows.length) return { error: 'plik zawiera tylko nagłówek, bez wartości.' };

        // A one-column header over "1,5"-style rows: one column with decimal commas
        if (sep === ',' && header && header.cells.length === 1 &&
            rows.every(function (r) { return r.cells.length === 2; })) {
            rows.forEach(function (r) { r.cells = [r.text.trim()]; });
        }

        var columns = rows[0].cells.length;
        if (columns > 2) {
            return {
                error: 'wiersz ' + rows[0].line + ': ' + columns + ' ' + plural(columns, 'kolumna', 'kolumny', 'kolumn') +
                    ' — oczekiwano jednej (opad) albo dwóch (czas, opad).',
            };
        }
        if (rows.length > _maxSteps) {
            return {
                error: 'plik ma ' + rows.length + ' ' + plural(rows.length, 'wiersz', 'wiersze', 'wierszy') +
                    ' z wartościami — limit to ' + _maxSteps + ' kroków.',
            };
        }

        var times = [];
        var depths = [];
        for (var i = 0; i < rows.length; i++) {
            var r = rows[i];
            if (r.cells.length !== columns) {
                return { error: 'wiersz ' + r.line + ': liczba kolumn (' + r.cells.length + ') inna niż w wierszu ' + rows[0].line + ' (' + columns + ').' };
            }
            var depthText = r.cells[columns - 1];
            var depth = parseNumber(depthText);
            if (depth === null || !isFinite(depth)) {
                return { error: 'wiersz ' + r.line + ': opad „' + depthText + '” nie jest liczbą.' };
            }
            if (depth < 0) {
                return { error: 'wiersz ' + r.line + ': opad nie może być ujemny (' + depthText + ').' };
            }
            depths.push(depth);
            if (columns === 2) {
                var t = parseNumber(r.cells[0]);
                if (t === null || !isFinite(t)) {
                    return { error: 'wiersz ' + r.line + ': czas „' + r.cells[0] + '” nie jest liczbą.' };
                }
                times.push(t);
            }
        }

        if (columns === 1) {
            if (!currentStep) {
                return { error: 'plik ma jedną kolumnę (opad), więc potrzebny jest poprawny krok czasowy — popraw pole „Krok czasowy”.' };
            }
            return { depths: depths, step: currentStep, columns: 1 };
        }

        // Two columns: times at the end of each step (step, 2·step, …) or from 0
        var step = times.length > 1 ? times[1] - times[0] : times[0];
        var tol = EPS * Math.max(1, Math.abs(step));
        if (!(step > tol)) {
            return { error: 'wiersz ' + rows[Math.min(1, rows.length - 1)].line + ': czas musi rosnąć o stały krok większy od 0.' };
        }
        if (step > MAX_STEP_MIN) {
            return { error: 'krok czasowy ' + fmt(step) + ' min przekracza ' + MAX_STEP_MIN + ' min (1 doba).' };
        }
        var fromZero = Math.abs(times[0]) <= tol;
        if (!fromZero && Math.abs(times[0] - step) > tol) {
            return {
                error: 'wiersz ' + rows[0].line + ': pierwszy czas (' + fmt(times[0]) + ' min) powinien być równy krokowi (' +
                    fmt(step) + ' min — koniec pierwszego kroku) albo 0.' + commaHint(sep, header),
            };
        }
        for (var k = 1; k < times.length; k++) {
            var expected = times[0] + k * step;
            if (Math.abs(times[k] - expected) > tol) {
                return {
                    error: 'wiersz ' + rows[k].line + ': nierówny krok czasowy (oczekiwano ' + fmt(expected) +
                        ' min, jest ' + fmt(times[k]) + ' min).' + commaHint(sep, header),
                };
            }
        }
        return { depths: depths, step: step, columns: 2 };
    }

    /** Rows like "1,5" without a header may be one column with decimal commas. */
    function commaHint(sep, header) {
        return sep === ',' && !header
            ? ' Jeśli to jedna kolumna z przecinkiem dziesiętnym, zapisz plik z separatorem „;” albo z kropką dziesiętną.'
            : '';
    }

    function onFileChosen() {
        var file = els.file.files && els.file.files[0];
        els.file.value = '';                // the same file can be chosen again
        if (!file) return;
        sync();
        file.text().then(function (text) {
            var parsed = parseCsv(text, readStep());
            if (parsed.error) {
                showMessage('bad', 'Import CSV „' + file.name + '”: ' + parsed.error);
                return;
            }
            setSeries(parsed.step, parsed.depths);
            setDerived(null);
            showMessage('info', 'Zaimportowano ' + steps(parsed.depths.length) + ' po ' + fmt(parsed.step) +
                ' min z pliku „' + file.name + '”' +
                (parsed.columns === 2 ? ' (kolumny czas i opad).' : ' (kolumna opadu).'));
            changed();
        }, function () {
            showMessage('bad', 'Nie udało się odczytać pliku „' + file.name + '”.');
        });
    }

    // ── Events ─────────────────────────────────────────────────────────

    function setSource(custom) {
        sync();
        if (custom === _custom) return;
        _custom = custom;
        setSourceUi();
        clearTimeout(_timer);
        if (custom) refresh();
        // Own series: recalculated once it is valid; PMAXTP: back to the design storm
        regenerate();
    }

    function onCellInput(e) {
        var input = cellInput(e.target);
        if (!input) return;
        _cells[rowIndex(input)] = input.value;
        if (!els.msg.dataset.hint) showMessage(null, '');
        changed();
    }

    /** Enter and arrows move between the depth cells, like a spreadsheet. */
    function onCellKey(e) {
        var input = cellInput(e.target);
        if (!input) return;
        var d = e.key === 'Enter' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowUp' ? -1 : 0;
        if (!d) return;
        var row = els.rows.rows[rowIndex(input) + d];
        if (!row) return;
        e.preventDefault();
        var next = row.cells[1].firstChild;
        next.focus();
        next.select();
    }

    function onDimsInput() {
        if (!els.msg.dataset.hint) showMessage(null, '');
        changed();
    }

    function onLoad() {
        sync();
        if (!_pmaxtp || _pmaxtp.watershed !== _watershed) return;
        setSeries(_pmaxtp.step, _pmaxtp.depths);
        setDerived(_pmaxtp.lines);
        showMessage('info', 'Wczytano bieżący hietogram PMAXTP: ' + steps(_pmaxtp.depths.length) +
            ' po ' + fmt(_pmaxtp.step) + ' min.');
        changed();
    }

    function onClear() {
        sync();
        _cells = [];
        setDerived(null);
        showMessage(null, '');
        fillInputs();
        changed();
    }

    // ── Hooks for hydrograph.js ────────────────────────────────────────

    /**
     * Rainfall for the hydrograph request of the given watershed.
     * Returns { active, valid, series }: active when the own series is
     * selected; valid false while it has errors or no rain (the caller must
     * not send the request); series = { timestep_min, depths_mm }, with
     * derived_from 'pmaxtp' while it is a copy of a PMAXTP hietogram.
     */
    function request(data) {
        if (!els.form) return { active: false, valid: true, series: null };
        if (data !== _watershed) reset(data);
        if (!_custom) return { active: false, valid: true, series: null };
        var state = refresh();
        if (!state.valid) return { active: true, valid: false, series: null };
        var series = { timestep_min: state.step, depths_mm: state.depths };
        if (_derived) series.derived_from = 'pmaxtp';
        return { active: true, valid: true, series: series };
    }

    /**
     * Remember the PMAXTP series of a hydrograph response and its provider lines
     * ("Wczytaj z bieżącego hietogramu").
     */
    function noteResult(data, result) {
        var precip = result && result.precipitation;
        if (!els.form || !precip || precip.source !== 'pmaxtp') return;
        _pmaxtp = {
            watershed: data,
            step: precip.timestep_min,
            depths: precip.intensities_mm.slice(),
            lines: Hydrograf.attribution.lines(result),
        };
        updateLoadButton();
    }

    /** Step limit of the API (custom_precipitation_max_steps). */
    function setMaxSteps(n) {
        if (!(n > 0)) return;
        _maxSteps = n;
        if (els.form) refresh();
    }

    // ── Init ───────────────────────────────────────────────────────────

    function init() {
        els.form = document.getElementById('custom-rain');
        if (!els.form) {
            els = {};
            return;
        }
        els.srcPmaxtp = document.getElementById('rain-source-pmaxtp');
        els.srcCustom = document.getElementById('rain-source-custom');
        els.pmaxtpForm = document.getElementById('pmaxtp-form');
        els.duration = document.getElementById('custom-rain-duration');
        els.step = document.getElementById('custom-rain-step');
        els.rows = document.getElementById('custom-rain-rows');
        els.load = document.getElementById('custom-rain-load');
        els.importBtn = document.getElementById('custom-rain-import');
        els.clear = document.getElementById('custom-rain-clear');
        els.file = document.getElementById('custom-rain-file');
        els.sum = document.getElementById('custom-rain-sum');
        els.msg = document.getElementById('custom-rain-msg');
        els.msgText = document.getElementById('custom-rain-msg-text');
        els.invalid = document.getElementById('custom-rain-invalid');
        els.invalidText = document.getElementById('custom-rain-invalid-text');

        els.srcPmaxtp.addEventListener('click', function () { setSource(false); });
        els.srcCustom.addEventListener('click', function () { setSource(true); });
        els.duration.addEventListener('input', onDimsInput);
        els.step.addEventListener('input', onDimsInput);
        els.rows.addEventListener('input', onCellInput);
        els.rows.addEventListener('paste', onPaste);
        els.rows.addEventListener('keydown', onCellKey);
        els.load.addEventListener('click', onLoad);
        els.importBtn.addEventListener('click', function () { els.file.click(); });
        els.file.addEventListener('change', onFileChosen);
        els.clear.addEventListener('click', onClear);

        refresh();
        updateLoadButton();
    }

    document.addEventListener('DOMContentLoaded', init);

    window.Hydrograf.customRain = {
        request: request,
        noteResult: noteResult,
        setMaxSteps: setMaxSteps,
    };
})();
