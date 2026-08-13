/**
 * Chart.js host helpers for the Stats tab.
 *
 * Owns create/update of doughnut and bar charts, including center-text
 * plugins used by Avg Signal Quality (dBm) and other donuts.
 * Credit: javastraat/meshpoint fc92680 (centerLabel wire-up).
 */

const STATS_CHART_COLORS = [
    '#06b6d4', '#a855f7', '#f59e0b', '#3b82f6', '#10b981',
    '#ef4444', '#ec4899', '#8b5cf6', '#14b8a6', '#f97316',
    '#eab308', '#6366f1', '#84cc16', '#e11d48',
];

/** Return obj when it has at least one key; otherwise null (falsy for ||). */
function nonemptyStatsMap(obj) {
    if (!obj || typeof obj !== 'object') return null;
    return Object.keys(obj).length > 0 ? obj : null;
}

class StatsChartHost {
    constructor() {
        this._charts = {};
    }

    destroyAll() {
        Object.values(this._charts).forEach((c) => c.destroy());
        this._charts = {};
    }

    renderDoughnut(canvasId, labels, values, colors, centerText) {
        const centerPlugin = centerText != null ? {
            id: `center-${canvasId}`,
            afterDraw(chart) {
                const text = chart.options.meshpointCenterText;
                if (text == null) return;
                const { ctx, chartArea } = chart;
                if (!chartArea) return;
                const cx = (chartArea.left + chartArea.right) / 2;
                const cy = (chartArea.top + chartArea.bottom) / 2;
                ctx.save();
                ctx.font = 'bold 16px "JetBrains Mono", monospace';
                ctx.fillStyle = '#f1f5f9';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(String(text), cx, cy);
                ctx.restore();
            },
        } : null;

        this.renderChart(canvasId, 'doughnut', {
            labels,
            datasets: [{
                data: values,
                backgroundColor: colors.slice(0, labels.length),
                borderWidth: 0,
            }],
        }, {
            cutout: '65%',
            meshpointCenterText: centerText,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#94a3b8',
                        font: { size: 11 },
                        padding: 8,
                        usePointStyle: true,
                        pointStyleWidth: 8,
                    },
                },
            },
        }, null, [centerPlugin].filter(Boolean));
    }

    renderHorizontalBar(canvasId, labels, values, color) {
        const barColor = color || '#06b6d4';
        this.renderChart(canvasId, 'bar', {
            labels,
            datasets: [{
                data: values,
                backgroundColor: barColor + '99',
                borderColor: barColor,
                borderWidth: 1,
            }],
        }, {
            indexAxis: 'y',
            plugins: { legend: { display: false } },
            scales: {
                x: { ticks: { color: '#64748b' }, grid: { color: 'rgba(30,41,59,0.5)' } },
                y: { ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { display: false } },
            },
        });
    }

    renderChart(canvasId, type, data, extraOpts, centerLabel, extraPlugins) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;

        if (this._charts[canvasId]) {
            const chart = this._charts[canvasId];
            chart.data.labels = data.labels;
            chart.data.datasets = data.datasets;
            if (extraOpts && Object.prototype.hasOwnProperty.call(extraOpts, 'meshpointCenterText')) {
                chart.options.meshpointCenterText = extraOpts.meshpointCenterText;
            }
            if (centerLabel != null) {
                chart.options.meshpointCenterText = centerLabel;
            }
            chart.update('none');
            return;
        }

        const baseOpts = {
            responsive: true,
            maintainAspectRatio: false,
            scales: type === 'bar' && !(extraOpts && extraOpts.indexAxis) ? {
                x: { ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: 'rgba(30,41,59,0.5)' } },
                y: { ticks: { color: '#64748b' }, grid: { color: 'rgba(30,41,59,0.5)' } },
            } : undefined,
        };

        const opts = { ...baseOpts, ...(extraOpts || {}) };
        if (centerLabel != null) {
            opts.meshpointCenterText = centerLabel;
        }
        const plugins = [...(extraPlugins || [])];
        if (centerLabel != null) {
            plugins.push({
                id: `center-${canvasId}`,
                afterDraw(chart) {
                    const text = chart.options.meshpointCenterText;
                    if (text == null) return;
                    const { ctx, chartArea } = chart;
                    if (!chartArea) return;
                    const cx = (chartArea.left + chartArea.right) / 2;
                    const cy = (chartArea.top + chartArea.bottom) / 2;
                    ctx.save();
                    ctx.font = 'bold 16px "JetBrains Mono", monospace';
                    ctx.fillStyle = '#f1f5f9';
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(String(text), cx, cy);
                    ctx.restore();
                },
            });
        }

        this._charts[canvasId] = new Chart(canvas, { type, data, options: opts, plugins });
    }
}

window.StatsChartHost = StatsChartHost;
window.STATS_CHART_COLORS = STATS_CHART_COLORS;
window.nonemptyStatsMap = nonemptyStatsMap;
