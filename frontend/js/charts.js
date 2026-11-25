/**
 * Hydrograf Charts module.
 *
 * Every chart of Hydrograf is drawn by the chart module of Nogat's kit
 * (nogat/nogat-chart.js and nogat-chart.css, Nogat DEV-15.16, ECO-090; ADR-090), which
 * js/nogat.js hands on as Hydrograf.nogat.chart: the hypsometric curve, the land cover
 * and the soil groups as one bar per class with its share, the terrain profile (its
 * readout moves the marker on the map), the hietogram and the hydrograph. The kit draws
 * each into its container as an SVG at the container's width, and again when that width
 * changes (a panel resized, a section opened), with a readout by pointer, finger and keys.
 * A chart over a time, a distance or a share of the area shows a range of it: a drag over
 * the plot selects the range, Ctrl with the wheel or two fingers zoom around the cursor,
 * Shift with a drag or a drag with the middle button pans, a double click, the key 0 and
 * „Cały zakres” show the whole; the bar under the chart holds „−”, „+”, „Cały zakres” and
 * the range shown, a lone „+” before a zoom. The colours are classes in the tokens, of
 * nogat-chart.css and of css/app.css (the land cover, the soil groups, the terrain and the
 * water), so a change of theme needs no redraw.
 *
 * „PNG” at a chart saves it as shown (the range shown, without the readout) with the lines
 * of the providers of its data under it (Nogat DEV-20.5), by the kit's toPng, as
 * hydrograf_<content>[_<qualifiers>].png (Nogat DEV-19.21).
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    // The charts drawn, by the id of their container: the kit's handle and the PNG's
    // file name and the source of its provider lines (a response: attribution, terms_notice)
    var charts = {};

    // The land cover classes: label, the class of their bar (css/app.css) and the colour
    // of their overlay on the map, a token or a mix of two (the mixes of the classes)
    var LAND_COVER = {
        'grunt_orny': { label: 'Grunty orne', cls: 'lc-arable', color: ['--warn'] },
        'las': { label: 'Lasy', cls: 'lc-forest', color: ['--accent-green'] },
        '\u0142\u0105ka': { label: '\u0141\u0105ki i pastwiska', cls: 'lc-meadow', color: ['--ok', '--surface', 0.5] },
        'zabudowa_mieszkaniowa': { label: 'Zabudowa mieszkaniowa', cls: 'lc-residential', color: ['--text-3'] },
        'zabudowa_przemys\u0142owa': { label: 'Zabudowa przemys\u0142owa', cls: 'lc-industrial', color: ['--text-2'] },
        'droga': { label: 'Drogi', cls: 'lc-road', color: ['--text-3', '--surface', 0.5] },
        'woda': { label: 'Wody', cls: 'lc-water', color: ['--info'] },
        'inny': { label: 'Inne', cls: 'share-other', color: ['--line-2'] },
    };

    // Hydrologic soil groups: label, bar class and colour (shades of --warn-ink)
    var HSG = {
        'A': { label: 'A: przepuszczalne', cls: 'hsg-a', color: ['--warn-ink', '--surface', 0.22] },
        'B': { label: 'B: \u015brednio przepuszczalne', cls: 'hsg-b', color: ['--warn-ink', '--surface', 0.45] },
        'C': { label: 'C: s\u0142abo przepuszczalne', cls: 'hsg-c', color: ['--warn-ink', '--surface', 0.7] },
        'D': { label: 'D: nieprzepuszczalne', cls: 'hsg-d', color: ['--warn-ink'] },
    };

    // A class or group without an entry above
    var OTHER = { cls: 'share-other', color: ['--line-2'] };

    var WATER = 'Zwierciad\u0142o wody';

    // A share chart: the height of a class's row and of the frame around the rows [px]
    var SHARE_ROW = 30;
    var SHARE_FRAME = 60;

    // ── The kit ────────────────────────────────────────────────────────

    /** The kit's chart module (js/nogat.js), null until the module has run. */
    function kit() {
        return (Hydrograf.nogat && Hydrograf.nogat.chart) || null;
    }

    /** A number as the charts write it: Polish, a decimal comma, the minus sign U+2212. */
    function num(value, digits) {
        return kit().format.number(value, digits);
    }

    /** Minutes as the time axes write them: h:mm. */
    function clock(minutes) {
        return kit().format.time(minutes);
    }

    // ── Map colours ────────────────────────────────────────────────────

    /** The colour of a palette entry, [token] or [token, token, weight], in the current theme. */
    function paletteColor(entry) {
        var map = Hydrograf.map;
        if (entry.length === 1) return map.token(entry[0]);
        return map.mix(map.token(entry[0]), map.token(entry[1]), entry[2]);
    }

    /** The colour of a land cover class on the map, as its bar in the chart. */
    function landCoverColor(category) {
        return paletteColor((LAND_COVER[category] || OTHER).color);
    }

    /** The colour of a hydrologic soil group on the map, as its bar in the chart. */
    function hsgColor(group) {
        return paletteColor((HSG[group] || OTHER).color);
    }

    // ── Drawing ────────────────────────────────────────────────────────

    /**
     * Draw a chart of `spec` into the element `id`, or draw the one there again (the kit
     * keeps the range shown while the data are the same); `png` is its PNG: { name,
     * source }, the file name and the response whose provider lines go under it.
     */
    function draw(id, spec, png) {
        var el = document.getElementById(id);
        var chart = kit();
        if (!el || !chart) return;
        var entry = charts[id];
        if (entry) entry.handle.update(spec);
        else entry = charts[id] = { handle: chart.draw(el, spec) };
        entry.png = png;
        showPngError(id, '');
        pngButtons(id).forEach(function (button) { button.hidden = false; });
    }

    /** Remove the chart of the element `id` with its readout, bar and legend. */
    function destroyChart(id) {
        var entry = charts[id];
        if (entry) {
            entry.handle.destroy();
            delete charts[id];
        }
        showPngError(id, '');
        pngButtons(id).forEach(function (button) { button.hidden = true; });
    }

    /** Text after the chart's title, e.g. the time step. */
    function setChartNote(id, text) {
        var el = document.getElementById(id);
        var box = el && el.closest('.chart');
        var note = box && box.querySelector('.chart-note');
        if (note) note.textContent = text;
    }

    // ── PNG ────────────────────────────────────────────────────────────

    /** The „PNG” buttons of the chart `id`. */
    function pngButtons(id) {
        return Array.prototype.slice.call(document.querySelectorAll('[data-chart-png="' + id + '"]'));
    }

    /** Say under the chart `id` why its PNG was not saved, or ('') say nothing. */
    function showPngError(id, message) {
        var el = document.getElementById(id);
        if (!el) return;
        var note = el.parentNode.querySelector('.chart-png-error[data-chart="' + id + '"]');
        if (!message) {
            if (note) note.remove();
            return;
        }
        if (!note) {
            note = document.createElement('p');
            note.className = 'notice bad chart-png-error';
            note.dataset.chart = id;
            note.setAttribute('role', 'alert');
            el.insertAdjacentElement('afterend', note);
        }
        note.textContent = message;
    }

    /** Save the chart `id` as shown as a PNG with its provider lines under it. */
    function savePng(id) {
        var entry = charts[id];
        if (!entry) return;
        var lines = Hydrograf.attribution.lines(entry.png.source);
        var name = entry.png.name;
        kit().toPng(entry.handle.svg, { footer: lines.attribution.concat(lines.terms_notice) })
            .then(function (blob) {
                showPngError(id, '');
                Hydrograf.api.saveFile(name, blob);
            })
            .catch(function (err) {
                showPngError(id, err.message);
            });
    }

    document.addEventListener('click', function (e) {
        var button = e.target.closest('[data-chart-png]');
        if (button) savePng(button.dataset.chartPng);
    });

    // ── Watershed charts ───────────────────────────────────────────────

    /**
     * The shares of the classes as one horizontal bar each (the kit's band axis): the
     * class and its figure (CN, area) left of the bar, the share right of it.
     *
     * @param {string} id - Container element ID
     * @param {Array} rows - [{ label, cls, extra, percentage }]
     * @param {string} title - The chart's name
     * @param {Object} png - { name, source } of its PNG
     */
    function renderShares(id, rows, title, png) {
        // The names in bold 12 px and the figures in 10 px monospace, by their characters
        var names = rows.reduce(function (most, row) {
            return Math.max(most, 7 * row.label.length, 6 * row.extra.length);
        }, 0);
        draw(id, {
            title: title,
            x: { label: 'Udzia\u0142 [%]' },
            y: { scale: 'band', width: Math.min(200, Math.max(90, names + 16)) },
            series: [{
                id: 'shares',
                data: rows.map(function (row) {
                    return {
                        x: row.percentage,
                        y: row.label,
                        sub: row.extra,
                        cls: row.cls,
                        text: num(row.percentage, 1) + ' %',
                    };
                }),
            }],
            fit: { ratio: 0, minHeight: SHARE_FRAME + SHARE_ROW * rows.length },
        }, png);
    }

    /**
     * Render land cover shares, one bar per class, the largest first.
     *
     * @param {string} id - Container element ID
     * @param {Array} categories - Array of { category, percentage, area_m2, cn_value }:
     *     cn_value is the CN of the class over its soil groups (AMC II)
     * @param {Object} source - The response whose provider lines go under its PNG
     */
    function renderLandCoverChart(id, categories, source) {
        var rows = categories.slice().sort(function (a, b) {
            return b.percentage - a.percentage;
        }).map(function (cat) {
            var cls = LAND_COVER[cat.category];
            return {
                label: cls ? cls.label : cat.category,
                cls: (cls || OTHER).cls,
                extra: cat.cn_value != null ? 'CN ' + num(cat.cn_value, 1) : '',
                percentage: cat.percentage,
            };
        });
        renderShares(id, rows, 'Udzia\u0142 form pokrycia terenu',
            { name: 'hydrograf_land-cover.png', source: source });
    }

    /**
     * Render HSG soil group shares, one bar per group, A to D.
     *
     * @param {string} id - Container element ID
     * @param {Array} categories - Array of { group, percentage, area_m2 }
     * @param {Object} source - The response whose provider lines go under its PNG
     */
    function renderHsgChart(id, categories, source) {
        var rows = categories.slice().sort(function (a, b) {
            return String(a.group).localeCompare(String(b.group));
        }).map(function (cat) {
            var grp = HSG[cat.group];
            return {
                label: grp ? grp.label : String(cat.group),
                cls: (grp || OTHER).cls,
                extra: cat.area_m2 != null ? num(cat.area_m2 / 1e6, 2) + ' km\u00b2' : '',
                percentage: cat.percentage,
            };
        });
        renderShares(id, rows, 'Udzia\u0142 hydrologicznych grup glebowych',
            { name: 'hydrograf_soil-groups.png', source: source });
    }

    /**
     * Render the hypsometric curve: x the share of the area at or above an elevation
     * (0–100 %), y the elevation [m a.s.l.].
     *
     * @param {string} id - Container element ID
     * @param {Array} curveData - Array of { relative_height, relative_area }
     *        where relative_area = fraction of total area ABOVE that height
     * @param {number} elevMin - Minimum elevation [m a.s.l.]
     * @param {number} elevMax - Maximum elevation [m a.s.l.]
     * @param {Object} source - The response whose provider lines go under its PNG
     */
    function renderHypsometricChart(id, curveData, elevMin, elevMax, source) {
        var elevRange = elevMax - elevMin;
        if (!curveData || curveData.length < 2 || !(elevRange > 0)) {
            destroyChart(id);
            return;
        }
        var points = curveData.map(function (p) {
            return [p.relative_area * 100, elevMin + p.relative_height * elevRange];
        }).sort(function (a, b) { return a[0] - b[0]; });
        draw(id, {
            title: 'Krzywa hipsometryczna',
            x: { label: 'Pow. powy\u017cej [%]', min: 0, max: 100, digits: 0 },
            y: { label: 'Wysoko\u015b\u0107 [m n.p.m.]', unit: 'm n.p.m.', zero: false, digits: 1 },
            series: [{ id: 'curve', kind: 'area', cls: 's3', label: 'Wysoko\u015b\u0107', data: points }],
            readout: { x: function (x) { return 'Pow. powy\u017cej: ' + num(x, 0) + ' %'; } },
            fit: { ratio: 0.62, minHeight: 200 },
        }, { name: 'hydrograf_hypsometric-curve.png', source: source });
    }

    /** The indexes of the values that stand alone between gaps (nothing to draw a line to). */
    function isolated(values) {
        var out = [];
        values.forEach(function (value, i) {
            var before = i === 0 || values[i - 1] === null;
            var after = i === values.length - 1 || values[i + 1] === null;
            if (value !== null && before && after) out.push(i);
        });
        return out;
    }

    /**
     * Render the terrain profile, with the water surface of analysis results filled
     * between the terrain and the water level where wet. The readout over a sample puts
     * the marker on the map at its distance along the line.
     *
     * @param {string} id - Container element ID
     * @param {Array} distances - Distance values [m]
     * @param {Array} elevations - Elevation values [m], null where the DEM has no data (a gap)
     * @param {Function} [onHover] - Callback(fraction) when the readout moves, fraction 0..1
     * @param {Function} [onHoverEnd] - Callback when the readout hides
     * @param {Array} [water] - [{ title, levels }]: water level [m] per sample, null where dry
     * @param {Object} [source] - The response whose provider lines go under its PNG
     */
    function renderProfileChart(id, distances, elevations, onHover, onHoverEnd, water, source) {
        water = water || [];
        var km = distances.map(function (d) { return d / 1000; });
        var sample = new Map(km.map(function (x, i) { return [x, i]; }));
        var total = distances[distances.length - 1];
        var series = [{
            id: 'terrain',
            kind: 'area',
            cls: 'terrain',
            label: 'Teren',
            digits: water.length ? 2 : 1,
            data: km.map(function (x, i) { return [x, elevations[i]]; }),
        }];
        water.forEach(function (w, n) {
            series.push(
                // Filled down to the terrain where the water lies above it
                {
                    id: 'water-' + n,
                    kind: 'band',
                    cls: 'water',
                    readout: false,
                    legend: false,
                    data: km.map(function (x, i) {
                        return [x, w.levels[i] === null ? null : elevations[i], w.levels[i]];
                    }),
                },
                {
                    id: 'level-' + n,
                    kind: 'line',
                    cls: 'water',
                    label: WATER + ' \u2014 ' + w.title,
                    digits: 2,
                    data: km.map(function (x, i) { return [x, w.levels[i]]; }),
                },
                // A wet sample between dry ones has no line to draw: a dot
                {
                    id: 'wet-' + n,
                    kind: 'points',
                    cls: 'water',
                    readout: false,
                    legend: false,
                    data: isolated(w.levels).map(function (i) { return [km[i], w.levels[i]]; }),
                }
            );
        });

        /** The readout's heading: the distance and the water depth there. */
        function heading(x) {
            var i = sample.get(x);
            var depths = [];
            water.forEach(function (w) {
                var level = i === undefined ? null : w.levels[i];
                if (level === null) return;
                var depth = num(level - elevations[i], 2) + ' m';
                depths.push(water.length > 1 ? w.title + ' ' + depth : depth);
            });
            return num(x, 2) + ' km' + (depths.length ? ' \u00b7 g\u0142\u0119boko\u015b\u0107 ' + depths.join(', ') : '');
        }

        draw(id, {
            title: water.length ? 'Profil terenu i zwierciad\u0142o wody' : 'Profil terenu',
            x: { label: 'Odleg\u0142o\u015b\u0107 [km]', digits: 2 },
            y: { label: 'H [m n.p.m.]', unit: 'm n.p.m.', zero: false },
            series: series,
            readout: { series: 'terrain', x: heading },
            onReadout: function (index) {
                if (index === null) {
                    if (onHoverEnd) onHoverEnd();
                } else if (onHover && total > 0) {
                    onHover(distances[index] / total);
                }
            },
            legend: water.length > 0,
            fit: { ratio: 0, minHeight: 170 },
        }, { name: 'hydrograf_terrain-profile.png', source: source });
    }

    // ── Rainfall-runoff charts ─────────────────────────────────────────

    /** The highest point of [[x, y], …]: its index, or -1 when none is above zero. */
    function peakOf(points) {
        var peak = -1;
        points.forEach(function (point, i) {
            if (point[1] > 0 && (peak < 0 || point[1] > points[peak][1])) peak = i;
        });
        return peak;
    }

    /**
     * Render the hietogram: total and effective precipitation per time step as bars,
     * the largest step marked.
     *
     * @param {string} id - Container element ID
     * @param {Array} times - Step times [min], the ends of the steps
     * @param {Array} total - Total precipitation per step [mm]
     * @param {Array} effective - Effective precipitation per step [mm]
     * @param {Object} [opts] - { step: time step [min], origin: rainfall origin shown in
     *     the title, file: the PNG's name, lines: the response whose provider lines go
     *     under it }
     */
    function renderHietogramChart(id, times, total, effective, opts) {
        if (!times.length) return;
        opts = opts || {};
        var step = opts.step != null ? opts.step : (times.length > 1 ? times[1] - times[0] : times[0]);
        var stepText = String(Number(step.toFixed(3)));
        setChartNote(id, (opts.origin ? opts.origin + ' \u00b7 ' : '') + 'krok ' + stepText + ' min');

        /** A step's bar from its start to its end. */
        function bars(values) {
            return times.map(function (end, i) { return [end - step, values[i] || 0]; });
        }

        /** The time of a step that starts at `start`: „4:45–4:50”. */
        function stepTime(start) {
            return clock(start) + '\u2013' + clock(start + step);
        }

        var totalBars = bars(total);
        var peak = peakOf(totalBars);
        var marks = peak < 0 ? [] : [{
            kind: 'peak',
            x: totalBars[peak][0] + step / 2,
            y: totalBars[peak][1],
            label: 'Pmax ' + num(totalBars[peak][1], 2) + ' mm \u00b7 ' + stepTime(totalBars[peak][0]),
        }];
        draw(id, {
            title: 'Hietogram opadu',
            x: { label: 'Czas [{unit}]', scale: 'time' },
            y: { label: 'P [mm / ' + stepText + ' min]', unit: 'mm', digits: 2 },
            series: [
                { id: 'total', kind: 'bars', cls: 'bar-p', label: 'Opad ca\u0142kowity', width: step, data: totalBars },
                { id: 'effective', kind: 'bars', cls: 'bar-pe', label: 'Opad efektywny', width: step, data: bars(effective) },
            ],
            marks: marks,
            readout: { series: 'total', x: stepTime },
            legend: true,
            fit: { ratio: 0.5, minHeight: 170 },
        }, { name: opts.file, source: opts.lines });
    }

    /**
     * Render the outflow hydrograph with its peak marked.
     *
     * @param {string} id - Container element ID
     * @param {Array} times - Times [min]
     * @param {Array} discharge - Discharge [m³/s]
     * @param {Object} [opts] - { file: the PNG's name, lines: the response whose provider
     *     lines go under it }
     */
    function renderHydrographChart(id, times, discharge, opts) {
        if (!times.length) return;
        opts = opts || {};
        var points = times.map(function (t, i) { return [t, discharge[i] || 0]; });
        // A series starting after t = 0 rises from the axis
        if (times[0] > 0) points.unshift([0, 0]);
        var peak = peakOf(points);
        var marks = peak < 0 ? [] : [{
            kind: 'peak',
            x: points[peak][0],
            y: points[peak][1],
            label: 'Qmax ' + num(points[peak][1], 2) + ' m\u00b3/s \u00b7 ' + clock(points[peak][0]),
        }];
        draw(id, {
            title: 'Hydrogram odp\u0142ywu',
            x: { label: 'Czas [{unit}]', scale: 'time' },
            y: { label: 'Q [m\u00b3/s]', unit: 'm\u00b3/s' },
            series: [{ id: 'q', kind: 'area', cls: 's1', label: 'Przep\u0142yw Q', data: points }],
            marks: marks,
            readout: true,
            legend: true,
            fit: { ratio: 0.52, minHeight: 180 },
        }, { name: opts.file, source: opts.lines });
    }

    window.Hydrograf.charts = {
        renderLandCoverChart: renderLandCoverChart,
        renderHsgChart: renderHsgChart,
        renderHypsometricChart: renderHypsometricChart,
        renderProfileChart: renderProfileChart,
        renderHietogramChart: renderHietogramChart,
        renderHydrographChart: renderHydrographChart,
        destroyChart: destroyChart,
        landCoverColor: landCoverColor,
        hsgColor: hsgColor,
    };
})();
