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
     * @param {string} canvasId - Canvas element ID
     * @param {Array} curveData - Array of { relative_height, relative_area }
     */
    function renderHypsometricChart(canvasId, curveData) {
        destroyChart(canvasId);

        var canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined') return;

        // Sort by relative_area ascending
        var sorted = curveData.slice().sort(function (a, b) {
            return a.relative_area - b.relative_area;
        });

        charts[canvasId] = new Chart(canvas, {
            type: 'line',
            data: {
                labels: sorted.map(function (p) { return (p.relative_area * 100).toFixed(0); }),
                datasets: [{
                    label: 'Krzywa hipsometryczna',
                    data: sorted.map(function (p) { return (p.relative_height * 100).toFixed(1); }),
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
                        callbacks: {
                            title: function (items) { return 'a/A = ' + items[0].label + '%'; },
                            label: function (ctx) { return 'h/H = ' + ctx.parsed.y + '%'; },
                        },
                    },
                },
                scales: {
                    x: {
                        title: { display: true, text: 'a/A [%]', font: { size: 10 } },
                        ticks: { font: { size: 9 }, maxTicksLimit: 6 },
                    },
                    y: {
                        title: { display: true, text: 'h/H [%]', font: { size: 10 } },
                        ticks: { font: { size: 9 }, maxTicksLimit: 6 },
                        min: 0,
                        max: 100,
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
     */
    function renderProfileChart(canvasId, distances, elevations) {
        destroyChart(canvasId);

        var canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined') return;

        charts[canvasId] = new Chart(canvas, {
            type: 'line',
            data: {
                labels: distances.map(function (d) { return (d / 1000).toFixed(2); }),
                datasets: [{
                    label: 'Wysokość [m n.p.m.]',
                    data: elevations,
                    borderColor: '#8B4513',
                    backgroundColor: 'rgba(139, 69, 19, 0.15)',
                    fill: true,
                    tension: 0.2,
                    pointRadius: 0,
                    borderWidth: 1.5,
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
        });
    }

    window.Hydrograf.charts = {
        renderLandCoverChart: renderLandCoverChart,
        renderHypsometricChart: renderHypsometricChart,
        renderProfileChart: renderProfileChart,
        destroyChart: destroyChart,
    };
})();
