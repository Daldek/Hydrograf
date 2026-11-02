/**
 * Hydrograf Charts module.
 *
 * Chart.js wrappers for the hypsometric curve, land cover and HSG share bars,
 * hietogram, hydrograph, terrain profile and elevation histogram.
 *
 * Every colour, the font and its size come from tokens.css (read with
 * getComputedStyle). Each chart registers a styler that re-applies those
 * colours, so a theme change (data-theme attribute or the OS scheme) restyles
 * all live charts in place.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    // Chart instances and their stylers by canvas ID
    var charts = {};
    var stylers = {};

    // Current token colours (see readTheme)
    var theme = null;

    // Land cover classes: label and colour (token, or a mix of two tokens)
    var LAND_COVER = {
        'grunt_orny': { label: 'Grunty orne', color: ['--warn'] },
        'las': { label: 'Lasy', color: ['--accent-green'] },
        '\u0142\u0105ka': { label: '\u0141\u0105ki i pastwiska', color: ['--ok', '--surface', 0.5] },
        'zabudowa_mieszkaniowa': { label: 'Zabudowa mieszkaniowa', color: ['--text-3'] },
        'zabudowa_przemys\u0142owa': { label: 'Zabudowa przemys\u0142owa', color: ['--text-2'] },
        'droga': { label: 'Drogi', color: ['--text-3', '--surface', 0.5] },
        'woda': { label: 'Wody', color: ['--info'] },
        'inny': { label: 'Inne', color: ['--line-2'] },
    };

    // Hydrologic soil groups: label and colour (shades of --warn-ink)
    var HSG = {
        'A': { label: 'A: przepuszczalne', color: ['--warn-ink', '--surface', 0.22] },
        'B': { label: 'B: \u015brednio przepuszczalne', color: ['--warn-ink', '--surface', 0.45] },
        'C': { label: 'C: s\u0142abo przepuszczalne', color: ['--warn-ink', '--surface', 0.7] },
        'D': { label: 'D: nieprzepuszczalne', color: ['--warn-ink'] },
    };

    var OTHER_COLOR = ['--line-2'];

    // ── Theme ──────────────────────────────────────────────────────────

    var _colorCtx = null;

    function token(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

    /**
     * Parse any CSS colour the canvas understands into [r, g, b, a].
     */
    function parseColor(color) {
        if (!_colorCtx) _colorCtx = document.createElement('canvas').getContext('2d');
        _colorCtx.fillStyle = '#000000';
        _colorCtx.fillStyle = color;
        var s = _colorCtx.fillStyle;
        if (s.charAt(0) === '#') {
            return [
                parseInt(s.slice(1, 3), 16),
                parseInt(s.slice(3, 5), 16),
                parseInt(s.slice(5, 7), 16),
                1,
            ];
        }
        var parts = s.replace(/^rgba?\(|\)$/g, '').split(',').map(parseFloat);
        return [parts[0], parts[1], parts[2], parts.length > 3 ? parts[3] : 1];
    }

    /** Colour with the given opacity. */
    function alpha(color, a) {
        var c = parseColor(color);
        return 'rgba(' + c[0] + ', ' + c[1] + ', ' + c[2] + ', ' + a + ')';
    }

    /** `weight` of colour a mixed with colour b (like color-mix in srgb). */
    function mix(a, b, weight) {
        var ca = parseColor(a);
        var cb = parseColor(b);
        var out = [0, 1, 2].map(function (i) {
            return Math.round(ca[i] * weight + cb[i] * (1 - weight));
        });
        return 'rgb(' + out.join(', ') + ')';
    }

    /** Resolve a palette entry: [token] or [token, token, weight]. */
    function paletteColor(entry) {
        if (entry.length === 1) return token(entry[0]);
        return mix(token(entry[0]), token(entry[1]), entry[2]);
    }

    function readTheme() {
        return {
            text: token('--text'),
            text2: token('--text-2'),
            text3: token('--text-3'),
            line: token('--line'),
            line2: token('--line-2'),
            surface: token('--surface'),
            info: token('--info'),
            green: token('--accent-green'),
            warnBg: token('--warn-bg'),
            font: token('--font-sans'),
            fontSize: parseFloat(token('--text-xs')) || 11,
            radius: parseFloat(token('--radius-sm')) || 6,
            radiusXs: parseFloat(token('--radius-xs')) || 4,
            pad: parseFloat(token('--space-2')) || 8,
        };
    }

    /** Chart.js defaults that do not change with the theme: font and tooltip box. */
    function applyDefaults(c) {
        var d = Chart.defaults;
        d.font.family = c.font;
        d.font.size = c.fontSize;
        var tt = d.plugins.tooltip;
        tt.borderWidth = 1;
        tt.cornerRadius = c.radius;
        tt.padding = c.pad;
        tt.boxPadding = c.radiusXs;
        tt.usePointStyle = true;
    }

    function currentTheme() {
        if (!theme) {
            theme = readTheme();
            applyDefaults(theme);
        }
        return theme;
    }

    function child(obj, key) {
        if (!obj[key]) obj[key] = {};
        return obj[key];
    }

    /**
     * Theme colours of the axes and tooltip, set on each chart: Chart.js keeps
     * resolved scale options, so changed defaults would not reach live charts.
     */
    function styleCommon(target, c) {
        var scales = target.options.scales || {};
        Object.keys(scales).forEach(function (key) {
            var s = scales[key];
            child(s, 'ticks').color = c.text3;
            child(s, 'title').color = c.text3;
            child(s, 'grid').color = c.line;
            child(s, 'border').color = c.line2;
        });
        var tt = child(child(target.options, 'plugins'), 'tooltip');
        tt.backgroundColor = c.surface;
        tt.titleColor = c.text;
        tt.bodyColor = c.text2;
        tt.footerColor = c.text2;
        tt.borderColor = c.line;
    }

    function refreshTheme() {
        if (typeof Chart === 'undefined') return;
        theme = readTheme();
        applyDefaults(theme);
        Object.keys(charts).forEach(function (id) {
            styleCommon(charts[id], theme);
            stylers[id](charts[id], theme);
            paintLegend(id, charts[id]);
            // Not 'none': in that mode Chart.js keeps shared element options (bar fills)
            charts[id].update();
        });
    }

    // ── Registry ───────────────────────────────────────────────────────

    /**
     * Create a chart: style the config with the current tokens, build it and
     * keep the styler for theme changes. `styler(target, theme)` works on the
     * config before creation and on the chart afterwards (both expose
     * `data.datasets` and `options`); it sets `legendColor` on datasets that
     * have an HTML legend marker.
     */
    function createChart(canvas, config, styler) {
        var c = currentTheme();
        styleCommon(config, c);
        styler(config, c);
        var chart = new Chart(canvas, config);
        charts[canvas.id] = chart;
        stylers[canvas.id] = styler;
        paintLegend(canvas.id, chart);
        return chart;
    }

    /**
     * Destroy an existing chart on a canvas, with its HTML legend.
     */
    function destroyChart(canvasId) {
        if (charts[canvasId]) {
            charts[canvasId].destroy();
            delete charts[canvasId];
            delete stylers[canvasId];
        }
        var legend = document.getElementById(canvasId + '-legend');
        if (legend) legend.remove();
    }

    /**
     * Resize an existing chart (useful after container becomes visible).
     * @param {string} canvasId - Canvas element ID
     */
    function resizeChart(canvasId) {
        if (charts[canvasId]) charts[canvasId].resize();
    }

    function resizeAll() {
        Object.keys(charts).forEach(resizeChart);
    }

    /** Current colour of a land cover class (map overlay and legend). */
    function landCoverColor(category) {
        var entry = LAND_COVER[category];
        return paletteColor(entry ? entry.color : OTHER_COLOR);
    }

    /** Current colour of a hydrologic soil group (map overlay and legend). */
    function hsgColor(group) {
        var entry = HSG[group];
        return paletteColor(entry ? entry.color : OTHER_COLOR);
    }

    // ── HTML legends ───────────────────────────────────────────────────

    /**
     * Replace the legend after the canvas container with a fresh element.
     */
    function newLegend(canvas, tagName, className) {
        var id = canvas.id + '-legend';
        var old = document.getElementById(id);
        if (old) old.remove();
        var el = document.createElement(tagName);
        el.id = id;
        el.className = className;
        canvas.parentNode.insertAdjacentElement('afterend', el);
        return el;
    }

    /** Line legend (mockup .chart-legend): one swatch per dataset. */
    function lineLegend(canvas, labels) {
        var el = newLegend(canvas, 'div', 'chart-legend');
        labels.forEach(function (label) {
            var item = document.createElement('span');
            var sw = document.createElement('i');
            sw.className = 'sw';
            item.appendChild(sw);
            item.appendChild(document.createTextNode(label));
            el.appendChild(item);
        });
    }

    /** Share legend (mockup .share-list): class, extra figure and percentage. */
    function shareLegend(canvas, rows) {
        var el = newLegend(canvas, 'ul', 'share-list');
        rows.forEach(function (row) {
            var li = document.createElement('li');
            var dot = document.createElement('i');
            dot.className = 'dot';
            var label = document.createElement('span');
            label.textContent = row.label;
            var x = document.createElement('span');
            x.className = 'x';
            x.textContent = row.extra;
            var pct = document.createElement('span');
            pct.className = 'pct';
            pct.textContent = row.percentage.toFixed(1) + '%';
            li.appendChild(dot);
            li.appendChild(label);
            li.appendChild(x);
            li.appendChild(pct);
            el.appendChild(li);
        });
    }

    /** Colour legend markers from the datasets' `legendColor`. */
    function paintLegend(canvasId, target) {
        var legend = document.getElementById(canvasId + '-legend');
        if (!legend) return;
        var markers = legend.querySelectorAll('.sw, .dot');
        target.data.datasets.forEach(function (ds, i) {
            if (markers[i] && ds.legendColor) markers[i].style.background = ds.legendColor;
        });
    }

    // ── Shared pieces ──────────────────────────────────────────────────

    /**
     * Inline plugin: peak marker (dashed drop line, dot and label box, as in
     * the mockup) on the maximum of one dataset.
     *
     * @param {number} datasetIndex - Dataset whose maximum is marked
     * @param {Function} labelFn - (x, y) => label text
     */
    function peakPlugin(datasetIndex, labelFn) {
        return {
            id: 'hydrografPeak',
            afterDatasetsDraw: function (chart) {
                var meta = chart.getDatasetMeta(datasetIndex);
                var data = chart.data.datasets[datasetIndex].data;
                if (!meta || meta.hidden || !data.length) return;

                var peak = 0;
                for (var i = 1; i < data.length; i++) {
                    if (data[i].y > data[peak].y) peak = i;
                }
                var point = meta.data[peak];
                if (!point || !(data[peak].y > 0)) return;

                var c = currentTheme();
                var area = chart.chartArea;
                var ctx = chart.ctx;
                var x = point.x;
                var y = point.y;

                ctx.save();
                ctx.beginPath();
                ctx.setLineDash([3, 3]);
                ctx.lineWidth = 1;
                ctx.strokeStyle = c.text3;
                ctx.moveTo(x, y);
                ctx.lineTo(x, area.bottom);
                ctx.stroke();
                ctx.setLineDash([]);

                ctx.beginPath();
                ctx.arc(x, y, 4, 0, 2 * Math.PI);
                ctx.fillStyle = c.surface;
                ctx.fill();
                ctx.lineWidth = 2;
                ctx.strokeStyle = c.info;
                ctx.stroke();

                var text = labelFn(data[peak].x, data[peak].y);
                ctx.font = 'bold ' + c.fontSize + 'px ' + c.font;
                var padX = 7;
                var boxW = ctx.measureText(text).width + 2 * padX;
                var boxH = c.fontSize + 9;
                var boxX = x + 10;
                if (boxX + boxW > area.right) boxX = x - 10 - boxW;
                if (boxX < area.left) boxX = area.left;
                var boxY = Math.min(Math.max(y - boxH / 2, area.top), area.bottom - boxH);

                ctx.beginPath();
                ctx.roundRect(boxX + 0.5, boxY + 0.5, boxW, boxH, c.radiusXs);
                ctx.fillStyle = c.surface;
                ctx.fill();
                ctx.lineWidth = 1;
                ctx.strokeStyle = c.line2;
                ctx.stroke();

                ctx.fillStyle = c.text;
                ctx.textBaseline = 'middle';
                ctx.fillText(text, boxX + padX, boxY + boxH / 2 + 1);
                ctx.restore();
            },
        };
    }

    /** Scales of a time series: linear minutes on x from 0, values from zero on y. */
    function timeScales(yTitle) {
        return {
            x: {
                type: 'linear',
                min: 0,
                title: { display: true, text: 'Czas [min]' },
                ticks: { maxTicksLimit: 8 },
                grid: { display: false },
            },
            y: {
                beginAtZero: true,
                title: { display: true, text: yTitle },
                ticks: { maxTicksLimit: 6 },
                border: { display: false },
            },
        };
    }

    /** Share of each class as one horizontal stacked bar. */
    function renderShareBar(canvasId, rows, ariaLabel) {
        destroyChart(canvasId);

        var canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined') return;

        canvas.parentNode.classList.add('chart-stack');
        canvas.setAttribute('aria-label', ariaLabel);
        shareLegend(canvas, rows);

        var total = rows.reduce(function (sum, r) { return sum + r.percentage; }, 0);

        createChart(canvas, {
            type: 'bar',
            data: {
                labels: [''],
                datasets: rows.map(function (r, i) {
                    return {
                        label: r.label,
                        data: [r.percentage],
                        borderWidth: { top: 0, right: 0, bottom: 0, left: i > 0 ? 1 : 0 },
                        borderSkipped: false,
                        barPercentage: 1,
                        categoryPercentage: 1,
                    };
                }),
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                events: [],
                layout: { padding: 0 },
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: false },
                },
                scales: {
                    x: { stacked: true, display: false, min: 0, max: total },
                    y: { stacked: true, display: false },
                },
            },
        }, function (target, c) {
            target.data.datasets.forEach(function (ds, i) {
                ds.backgroundColor = paletteColor(rows[i].color);
                ds.borderColor = c.surface;
                ds.legendColor = ds.backgroundColor;
            });
        });
    }

    // ── Watershed charts ───────────────────────────────────────────────

    /**
     * Render land cover shares as a stacked bar with a class list.
     *
     * @param {string} canvasId - Canvas element ID
     * @param {Array} categories - Array of { category, percentage, area_m2, cn_value }
     */
    function renderLandCoverChart(canvasId, categories) {
        var rows = categories.slice().sort(function (a, b) {
            return b.percentage - a.percentage;
        }).map(function (cat) {
            var cls = LAND_COVER[cat.category];
            return {
                label: cls ? cls.label : cat.category,
                color: cls ? cls.color : OTHER_COLOR,
                extra: cat.cn_value != null ? 'CN ' + cat.cn_value : '',
                percentage: cat.percentage,
            };
        });
        renderShareBar(canvasId, rows, 'Udzia\u0142 form pokrycia terenu');
    }

    /**
     * Render HSG soil group shares as a stacked bar with a group list.
     *
     * @param {string} canvasId - Canvas element ID
     * @param {Array} categories - Array of { group, percentage, area_m2 }
     */
    function renderHsgChart(canvasId, categories) {
        var rows = categories.slice().sort(function (a, b) {
            return String(a.group).localeCompare(String(b.group));
        }).map(function (cat) {
            var grp = HSG[cat.group];
            return {
                label: grp ? grp.label : cat.group,
                color: grp ? grp.color : OTHER_COLOR,
                extra: cat.area_m2 != null ? (cat.area_m2 / 1e6).toFixed(2) + ' km\u00b2' : '',
                percentage: cat.percentage,
            };
        });
        renderShareBar(canvasId, rows, 'Udzia\u0142 hydrologicznych grup glebowych');
    }

    /**
     * Render hypsometric curve chart.
     *
     * X axis: % of area at or above given elevation (0–100, step 20).
     * Y axis: elevation [m a.s.l.].
     *
     * @param {string} canvasId - Canvas element ID
     * @param {Array} curveData - Array of { relative_height, relative_area }
     *        where relative_area = fraction of total area ABOVE that height
     * @param {number} elevMin - Minimum elevation [m a.s.l.]
     * @param {number} elevMax - Maximum elevation [m a.s.l.]
     */
    function renderHypsometricChart(canvasId, curveData, elevMin, elevMax) {
        destroyChart(canvasId);

        var canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined') return;
        if (!curveData || curveData.length < 2) return;

        var elevRange = elevMax - elevMin;
        if (elevRange <= 0) return;

        // Convert: X = % area above (relative_area * 100), Y = elevation
        // Sort by area-above descending so curve goes from (100%, elevMin) to (0%, elevMax)
        var points = curveData.map(function (p) {
            return {
                elevation: elevMin + p.relative_height * elevRange,
                areaAbovePct: p.relative_area * 100,
            };
        });
        points.sort(function (a, b) { return b.areaAbovePct - a.areaAbovePct; });

        createChart(canvas, {
            type: 'scatter',
            data: {
                datasets: [{
                    label: 'Krzywa hipsometryczna',
                    data: points.map(function (p) { return { x: p.areaAbovePct, y: Math.round(p.elevation * 10) / 10 }; }),
                    fill: true,
                    showLine: true,
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
                        callbacks: {
                            label: function (ctx) {
                                return ctx.parsed.y.toFixed(1) + ' m n.p.m. (' + ctx.parsed.x.toFixed(0) + '% pow.)';
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        type: 'linear',
                        title: { display: true, text: 'Pow. powy\u017cej [%]' },
                        ticks: { stepSize: 20 },
                        grid: { display: false },
                        min: 0,
                        max: 100,
                    },
                    y: {
                        title: { display: true, text: 'Wysoko\u015b\u0107 [m n.p.m.]' },
                        ticks: { maxTicksLimit: 6 },
                        border: { display: false },
                    },
                },
            },
        }, function (target, c) {
            var ds = target.data.datasets[0];
            ds.borderColor = c.green;
            ds.backgroundColor = alpha(c.green, 0.22);
            ds.pointBackgroundColor = c.green;
        });
    }

    /**
     * Render terrain profile chart, with the water surface of analysis
     * results filled between the terrain and the water level where wet.
     *
     * @param {string} canvasId - Canvas element ID
     * @param {Array} distances - Distance values [m]
     * @param {Array} elevations - Elevation values [m]
     * @param {Function} [onHover] - Callback(fraction) when hovering, fraction 0..1
     * @param {Function} [onHoverEnd] - Callback when mouse leaves chart
     * @param {Array} [water] - [{ title, levels }]: water level [m] per sample, null where dry
     */
    function renderProfileChart(canvasId, distances, elevations, onHover, onHoverEnd, water) {
        destroyChart(canvasId);

        var canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined') return;

        var nSamples = distances.length;
        var WATER = 'Zwierciad\u0142o wody';
        water = water || [];
        canvas.setAttribute('aria-label', water.length ? 'Profil terenu i zwierciad\u0142o wody' : 'Profil terenu');

        // Vertical crosshair + hover callback plugin
        var hoverPlugin = {
            id: 'profileHover',
            afterEvent: function (chart, args) {
                var evt = args.event;
                if (evt.type === 'mouseout') {
                    chart._profileHoverIndex = -1;
                    if (onHoverEnd) onHoverEnd();
                    chart.draw();
                    return;
                }
                if (evt.type !== 'mousemove') return;
                var area = chart.chartArea;
                if (!area) return;
                if (evt.x < area.left || evt.x > area.right ||
                    evt.y < area.top || evt.y > area.bottom) {
                    if (chart._profileHoverIndex !== -1) {
                        chart._profileHoverIndex = -1;
                        if (onHoverEnd) onHoverEnd();
                        chart.draw();
                    }
                    return;
                }
                var fraction = (evt.x - area.left) / (area.right - area.left);
                var idx = Math.round(fraction * (nSamples - 1));
                chart._profileHoverIndex = idx;
                if (onHover) onHover(fraction);
                chart.draw();
            },
            afterDraw: function (chart) {
                var idx = chart._profileHoverIndex;
                if (idx == null || idx < 0) return;
                var area = chart.chartArea;
                var meta = chart.getDatasetMeta(0);
                if (!meta || !meta.data || !meta.data[idx]) return;
                var x = meta.data[idx].x;
                var ctx = chart.ctx;
                ctx.save();
                ctx.beginPath();
                ctx.setLineDash([2, 2]);
                ctx.moveTo(x, area.top);
                ctx.lineTo(x, area.bottom);
                ctx.lineWidth = 1;
                ctx.strokeStyle = currentTheme().info;
                ctx.stroke();
                ctx.restore();
            },
        };

        // A wet sample between dry ones has no line to draw: mark it with a dot
        function isolatedPointRadius(ctx) {
            var data = ctx.dataset.data;
            var i = ctx.dataIndex;
            var alone = data[i] !== null && (i === 0 || data[i - 1] === null) &&
                (i === data.length - 1 || data[i + 1] === null);
            return alone ? 2.5 : 0;
        }

        function waterLabel(w) { return WATER + ' \u2014 ' + w.title; }

        if (water.length) lineLegend(canvas, ['Teren'].concat(water.map(waterLabel)));

        createChart(canvas, {
            type: 'line',
            data: {
                labels: distances.map(function (d) { return (d / 1000).toFixed(2); }),
                datasets: [{
                    label: 'Wysoko\u015b\u0107 [m n.p.m.]',
                    data: elevations,
                    fill: true,
                    tension: 0,
                    pointRadius: 0,
                    borderWidth: 1.5,
                }].concat(water.map(function (w) {
                    return {
                        label: waterLabel(w),
                        data: w.levels,
                        tension: 0,
                        pointRadius: isolatedPointRadius,
                        borderWidth: 1.5,
                    };
                })),
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    intersect: false,
                    mode: 'index',
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        intersect: false,
                        mode: 'index',
                        callbacks: {
                            title: function (items) { return items[0].label + ' km'; },
                            label: function (ctx) {
                                if (!water.length) return ctx.parsed.y.toFixed(1) + ' m n.p.m.';
                                if (ctx.datasetIndex === 0) return 'Teren: ' + ctx.parsed.y.toFixed(2) + ' m n.p.m.';
                                // Several results: name the one the line belongs to
                                var name = water.length > 1 ? waterLabel(water[ctx.datasetIndex - 1]) : WATER;
                                var depth = ctx.parsed.y - elevations[ctx.dataIndex];
                                return [
                                    name + ': ' + ctx.parsed.y.toFixed(2) + ' m n.p.m.',
                                    'G\u0142\u0119boko\u015b\u0107: ' + depth.toFixed(2) + ' m',
                                ];
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        title: { display: true, text: 'Odleg\u0142o\u015b\u0107 [km]' },
                        ticks: { maxTicksLimit: 8 },
                        grid: { display: false },
                    },
                    y: {
                        title: { display: true, text: 'H [m n.p.m.]' },
                        ticks: { maxTicksLimit: 6 },
                        border: { display: false },
                    },
                },
            },
            plugins: [hoverPlugin],
        }, function (target, c) {
            var ds = target.data.datasets[0];
            ds.borderColor = c.text2;
            ds.backgroundColor = alpha(mix(c.green, c.warnBg, 0.42), 0.8);
            ds.pointBackgroundColor = c.text2;
            ds.legendColor = c.text2;
            // Water: filled down to the terrain (dataset 0) only where it lies above it
            target.data.datasets.slice(1).forEach(function (w) {
                var fill = alpha(c.info, 0.45);
                w.borderColor = c.info;
                w.backgroundColor = fill;
                w.pointBackgroundColor = c.info;
                w.fill = { target: 0, above: fill, below: 'transparent' };
                w.legendColor = c.info;
            });
        });
    }

    /**
     * Render elevation histogram from hypsometric curve data.
     *
     * Divides elevation range into bands and computes % area per band
     * by differencing the cumulative hypsometric curve.
     *
     * @param {string} canvasId - Canvas element ID
     * @param {Array} curveData - Array of { relative_height, relative_area }
     * @param {number} elevMin - Minimum elevation [m a.s.l.]
     * @param {number} elevMax - Maximum elevation [m a.s.l.]
     */
    function renderElevationHistogram(canvasId, curveData, elevMin, elevMax) {
        destroyChart(canvasId);

        var canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined') return;
        if (!curveData || curveData.length < 2) return;

        var elevRange = elevMax - elevMin;
        if (elevRange <= 0) return;

        // Sort curve by relative_height ascending
        var sorted = curveData.slice().sort(function (a, b) {
            return a.relative_height - b.relative_height;
        });

        // Determine number of bands (10-25, ~5m per band)
        var nBands = Math.max(10, Math.min(25, Math.round(elevRange / 5)));
        var bandSize = elevRange / nBands;

        var labels = [];
        var data = [];

        for (var i = 0; i < nBands; i++) {
            var hLow = elevMin + i * bandSize;
            var hHigh = elevMin + (i + 1) * bandSize;

            // Relative heights for band boundaries
            var rLow = (hLow - elevMin) / elevRange;
            var rHigh = (hHigh - elevMin) / elevRange;

            // Interpolate relative_area at rLow and rHigh from the curve
            // The curve gives "fraction of area ABOVE relative_height"
            var areaAboveLow = interpolateCurve(sorted, rLow);
            var areaAboveHigh = interpolateCurve(sorted, rHigh);

            // Area in band = area above lower boundary - area above upper boundary
            var pct = (areaAboveLow - areaAboveHigh) * 100;
            if (pct < 0) pct = 0;

            labels.push(Math.round(hLow));
            data.push(Math.round(pct * 10) / 10);
        }

        createChart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Powierzchnia [%]',
                    data: data,
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
                            label: function (ctx) { return ctx.parsed.y.toFixed(1) + '% powierzchni'; },
                        },
                    },
                },
                scales: {
                    x: {
                        title: { display: true, text: 'Wysoko\u015b\u0107 [m n.p.m.]' },
                        ticks: { maxRotation: 90, minRotation: 45 },
                        grid: { display: false },
                    },
                    y: {
                        title: { display: true, text: 'Powierzchnia [%]' },
                        border: { display: false },
                        beginAtZero: true,
                    },
                },
            },
        }, function (target, c) {
            var ds = target.data.datasets[0];
            ds.borderColor = c.green;
            ds.backgroundColor = alpha(c.green, 0.6);
        });
    }

    /**
     * Interpolate the hypsometric curve (relative_area as function of relative_height).
     * Returns area_above for a given relative height.
     */
    function interpolateCurve(sorted, relHeight) {
        if (relHeight <= 0) return 1.0;
        if (relHeight >= 1) return 0.0;

        // Find surrounding points
        for (var i = 0; i < sorted.length - 1; i++) {
            var p1 = sorted[i];
            var p2 = sorted[i + 1];
            if (relHeight >= p1.relative_height && relHeight <= p2.relative_height) {
                var t = (relHeight - p1.relative_height) / (p2.relative_height - p1.relative_height);
                return p1.relative_area + t * (p2.relative_area - p1.relative_area);
            }
        }

        // Fallback: return nearest endpoint
        return sorted[sorted.length - 1].relative_area;
    }

    // ── Rainfall-runoff charts ─────────────────────────────────────────

    /**
     * Points of a time series. Steps are stamped at their end, so a series
     * starting after t = 0 gets a zero point at t = 0 to rise from the axis.
     */
    function toPoints(times, values) {
        var points = times.map(function (t, i) { return { x: t, y: values[i] || 0 }; });
        if (times[0] > 0) points.unshift({ x: 0, y: 0 });
        return points;
    }

    /** Line dataset of a time series with an area fill. */
    function seriesDataset(label, data, order) {
        return {
            label: label,
            data: data,
            fill: 'origin',
            cubicInterpolationMode: 'monotone',
            pointRadius: 0,
            pointHoverRadius: 3,
            borderWidth: 2,
            order: order,
        };
    }

    /** Text after the chart title, e.g. the time step. */
    function setChartNote(canvas, text) {
        var box = canvas.closest('.chart');
        var title = box && box.querySelector('.chart-title');
        if (!title) return;
        var note = title.querySelector('span');
        if (!note) {
            note = document.createElement('span');
            title.appendChild(note);
        }
        note.textContent = text;
    }

    /**
     * Render (or update in place, animated) the hietogram: total and
     * effective precipitation per time step as filled lines.
     *
     * @param {string} canvasId - Canvas element ID
     * @param {Array} times - Step times [min]
     * @param {Array} total - Total precipitation per step [mm]
     * @param {Array} effective - Effective precipitation per step [mm]
     * @param {Object} [opts] - { step: time step [min], source: rainfall origin shown in the title }
     */
    function renderHietogramChart(canvasId, times, total, effective, opts) {
        var canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined' || !times.length) return;

        var raw = opts && opts.step != null ? opts.step : (times.length > 1 ? times[1] - times[0] : times[0]);
        var step = String(Number(raw.toFixed(3)));
        var yTitle = 'P [mm / ' + step + ' min]';
        setChartNote(canvas, (opts && opts.source ? opts.source + ' \u00b7 ' : '') + 'krok ' + step + ' min');

        var chart = charts[canvasId];
        if (chart) {
            chart.data.datasets[0].data = toPoints(times, total);
            chart.data.datasets[1].data = toPoints(times, effective);
            chart.options.scales.y.title.text = yTitle;
            chart.update();
            return;
        }

        lineLegend(canvas, ['Opad ca\u0142kowity', 'Opad efektywny']);
        createChart(canvas, {
            type: 'line',
            data: { datasets: [
                seriesDataset('Opad ca\u0142kowity', toPoints(times, total), 2),
                seriesDataset('Opad efektywny', toPoints(times, effective), 1),
            ] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 400, easing: 'easeInOutQuart' },
                interaction: { intersect: false, mode: 'index' },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: function (items) { return 't = ' + items[0].parsed.x + ' min'; },
                            label: function (ctx) { return ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(2) + ' mm'; },
                        },
                    },
                },
                scales: timeScales(yTitle),
            },
            plugins: [peakPlugin(0, function (x, y) {
                return 'Pmax ' + y.toFixed(2) + ' mm \u00b7 ' + x + ' min';
            })],
        }, function (target, c) {
            var tot = target.data.datasets[0];
            var eff = target.data.datasets[1];
            tot.borderColor = mix(c.info, c.surface, 0.55);
            tot.backgroundColor = alpha(c.info, 0.14);
            eff.borderColor = c.info;
            eff.backgroundColor = alpha(c.info, 0.3);
            [tot, eff].forEach(function (ds) {
                ds.pointBackgroundColor = ds.borderColor;
                ds.legendColor = ds.borderColor;
            });
        });
    }

    /**
     * Render (or update in place, animated) the outflow hydrograph.
     *
     * @param {string} canvasId - Canvas element ID
     * @param {Array} times - Times [min]
     * @param {Array} discharge - Discharge [m³/s]
     */
    function renderHydrographChart(canvasId, times, discharge) {
        var canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined' || !times.length) return;

        var chart = charts[canvasId];
        if (chart) {
            chart.data.datasets[0].data = toPoints(times, discharge);
            chart.update();
            return;
        }

        lineLegend(canvas, ['Przep\u0142yw Q']);
        createChart(canvas, {
            type: 'line',
            data: { datasets: [
                seriesDataset('Q [m\u00b3/s]', toPoints(times, discharge), 1),
            ] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 400, easing: 'easeInOutQuart' },
                interaction: { intersect: false, mode: 'index' },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: function (items) { return 't = ' + items[0].parsed.x + ' min'; },
                            label: function (ctx) { return 'Q = ' + ctx.parsed.y.toFixed(3) + ' m\u00b3/s'; },
                        },
                    },
                },
                scales: timeScales('Q [m\u00b3/s]'),
            },
            plugins: [peakPlugin(0, function (x, y) {
                return 'Qmax ' + y.toFixed(2) + ' m\u00b3/s \u00b7 ' + x + ' min';
            })],
        }, function (target, c) {
            var ds = target.data.datasets[0];
            ds.borderColor = c.info;
            ds.backgroundColor = alpha(c.info, 0.18);
            ds.pointBackgroundColor = c.info;
            ds.legendColor = c.info;
        });
    }

    // ── Global listeners ───────────────────────────────────────────────

    // Theme buttons set data-theme; "auto" follows the OS scheme
    new MutationObserver(refreshTheme).observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme'],
    });
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', refreshTheme);

    // Panels resized by the shell, or a section opened: re-measure the charts
    window.addEventListener('hydrograf:layout', resizeAll);
    document.addEventListener('toggle', function (e) {
        if (e.target.tagName !== 'DETAILS' || !e.target.open) return;
        e.target.querySelectorAll('canvas').forEach(function (canvas) {
            resizeChart(canvas.id);
        });
    }, true);

    window.Hydrograf.charts = {
        renderLandCoverChart: renderLandCoverChart,
        renderHsgChart: renderHsgChart,
        renderHypsometricChart: renderHypsometricChart,
        renderElevationHistogram: renderElevationHistogram,
        renderProfileChart: renderProfileChart,
        renderHietogramChart: renderHietogramChart,
        renderHydrographChart: renderHydrographChart,
        destroyChart: destroyChart,
        resizeChart: resizeChart,
        landCoverColor: landCoverColor,
        hsgColor: hsgColor,
    };
})();
