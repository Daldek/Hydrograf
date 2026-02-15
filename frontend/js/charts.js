/**
 * Hydrograf Charts module.
 *
 * Chart.js wrappers for land cover donut, hypsometric curve, and terrain profile.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    // Track chart instances by canvas ID
    var charts = {};

    // Polish land cover color palette
    var LAND_COVER_COLORS = {
        'las': '#228B22',
        'łąka': '#90EE90',
        'grunt_orny': '#DAA520',
        'zabudowa_mieszkaniowa': '#CD5C5C',
        'zabudowa_przemysłowa': '#8B4513',
        'droga': '#696969',
        'woda': '#4169E1',
        'inny': '#A9A9A9',
    };

    // Polish labels for categories
    var LAND_COVER_LABELS = {
        'las': 'Las',
        'łąka': 'Łąka',
        'grunt_orny': 'Grunt orny',
        'zabudowa_mieszkaniowa': 'Zabudowa mieszk.',
        'zabudowa_przemysłowa': 'Zabudowa przem.',
        'droga': 'Droga',
        'woda': 'Woda',
        'inny': 'Inne',
    };

    /**
     * Destroy an existing chart on a canvas.
     */
    function destroyChart(canvasId) {
        if (charts[canvasId]) {
            charts[canvasId].destroy();
            delete charts[canvasId];
        }
    }

    /**
     * Render a donut chart of land cover categories.
     *
     * @param {string} canvasId - Canvas element ID
     * @param {Array} categories - Array of { category, percentage, area_m2, cn_value }
     */
    function renderLandCoverChart(canvasId, categories) {
        destroyChart(canvasId);

        var canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined') return;

        var labels = categories.map(function (c) {
            return LAND_COVER_LABELS[c.category] || c.category;
        });
        var data = categories.map(function (c) { return c.percentage; });
        var colors = categories.map(function (c) {
            return LAND_COVER_COLORS[c.category] || '#A9A9A9';
        });

        charts[canvasId] = new Chart(canvas, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: colors,
                    borderWidth: 1,
                    borderColor: '#fff',
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'right',
                        labels: {
                            font: { size: 10 },
                            boxWidth: 12,
                            padding: 6,
                            color: '#000',
                        },
                    },
                    tooltip: {
                        callbacks: {
                            label: function (ctx) {
                                var cat = categories[ctx.dataIndex];
                                return ctx.label + ': ' + cat.percentage.toFixed(1) + '% (CN=' + cat.cn_value + ')';
                            },
                        },
                    },
                },
                cutout: '55%',
            },
        });
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

        charts[canvasId] = new Chart(canvas, {
            type: 'scatter',
            data: {
                datasets: [{
                    label: 'Krzywa hipsometryczna',
                    data: points.map(function (p) { return { x: p.areaAbovePct, y: Math.round(p.elevation * 10) / 10 }; }),
                    borderColor: '#0A84FF',
                    backgroundColor: 'rgba(10, 132, 255, 0.1)',
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
                        title: { display: true, text: 'Pow. powyżej [%]', font: { size: 10 }, color: '#000' },
                        ticks: { font: { size: 9 }, stepSize: 20, color: '#000' },
                        grid: { color: 'rgba(0,0,0,0.1)' },
                        min: 0,
                        max: 100,
                    },
                    y: {
                        title: { display: true, text: 'Wysokość [m n.p.m.]', font: { size: 10 }, color: '#000' },
                        ticks: { font: { size: 9 }, maxTicksLimit: 6, color: '#000' },
                        grid: { color: 'rgba(0,0,0,0.1)' },
                    },
                },
            },
        });
    }

    /**
     * Render terrain profile chart.
     *
     * @param {string} canvasId - Canvas element ID
     * @param {Array} distances - Distance values [m]
     * @param {Array} elevations - Elevation values [m]
     * @param {Function} [onHover] - Callback(fraction) when hovering, fraction 0..1
     * @param {Function} [onHoverEnd] - Callback when mouse leaves chart
     */
    function renderProfileChart(canvasId, distances, elevations, onHover, onHoverEnd) {
        destroyChart(canvasId);

        var canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined') return;

        var nSamples = distances.length;

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
                ctx.moveTo(x, area.top);
                ctx.lineTo(x, area.bottom);
                ctx.lineWidth = 1;
                ctx.strokeStyle = 'rgba(220, 53, 69, 0.7)';
                ctx.stroke();
                ctx.restore();
            },
        };

        charts[canvasId] = new Chart(canvas, {
            type: 'line',
            data: {
                labels: distances.map(function (d) { return (d / 1000).toFixed(2); }),
                datasets: [{
                    label: 'Wysokość [m n.p.m.]',
                    data: elevations,
                    borderColor: '#DC3545',
                    backgroundColor: 'rgba(220, 53, 69, 0.12)',
                    fill: true,
                    tension: 0.2,
                    pointRadius: 0,
                    borderWidth: 1.5,
                }],
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
                            label: function (ctx) { return ctx.parsed.y.toFixed(1) + ' m n.p.m.'; },
                        },
                    },
                },
                scales: {
                    x: {
                        title: { display: true, text: 'Odległość [km]', font: { size: 10 } },
                        ticks: { font: { size: 9 }, maxTicksLimit: 8 },
                    },
                    y: {
                        title: { display: true, text: 'H [m n.p.m.]', font: { size: 10 } },
                        ticks: { font: { size: 9 } },
                    },
                },
            },
            plugins: [hoverPlugin],
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

        charts[canvasId] = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Powierzchnia [%]',
                    data: data,
                    backgroundColor: 'rgba(10, 132, 255, 0.6)',
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
                            label: function (ctx) { return ctx.parsed.y.toFixed(1) + '% powierzchni'; },
                        },
                    },
                },
                scales: {
                    x: {
                        title: { display: true, text: 'Wysokość [m n.p.m.]', font: { size: 9 }, color: '#000' },
                        ticks: { font: { size: 7 }, maxRotation: 90, minRotation: 45, color: '#000' },
                        grid: { color: 'rgba(0,0,0,0.1)' },
                    },
                    y: {
                        title: { display: true, text: 'Powierzchnia [%]', font: { size: 10 }, color: '#000' },
                        ticks: { font: { size: 9 }, color: '#000' },
                        grid: { color: 'rgba(0,0,0,0.1)' },
                        beginAtZero: true,
                    },
                },
            },
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

    window.Hydrograf.charts = {
        renderLandCoverChart: renderLandCoverChart,
        renderHypsometricChart: renderHypsometricChart,
        renderElevationHistogram: renderElevationHistogram,
        renderProfileChart: renderProfileChart,
        destroyChart: destroyChart,
    };
})();
