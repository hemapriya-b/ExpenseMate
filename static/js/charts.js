// Charts.js - Additional chart functionality for Expensio

// Custom chart plugins
const chartPlugins = {
    id: 'customBackground',
    beforeDraw: (chart) => {
        const ctx = chart.ctx;
        ctx.save();
        ctx.globalCompositeOperation = 'destination-over';
        ctx.fillStyle = 'rgba(255, 255, 255, 0.02)';
        ctx.fillRect(0, 0, chart.width, chart.height);
        ctx.restore();
    }
};

// Register the plugin
Chart.register(chartPlugins);

// Chart utility functions
const ChartUtils = {
    // Format currency
    formatCurrency: (value) => {
        return '₹' + value.toLocaleString('en-IN');
    },
    
    // Generate gradient
    createGradient: (ctx, color1, color2) => {
        const gradient = ctx.createLinearGradient(0, 0, 0, 400);
        gradient.addColorStop(0, color1);
        gradient.addColorStop(1, color2);
        return gradient;
    },
    
    // Animate chart update
    animateChartUpdate: (chart, duration = 500) => {
        chart.options.animation.duration = duration;
        chart.update();
    },
    
    // Export chart as image
    exportChart: (chartId, fileName = 'chart.png') => {
        const chart = document.getElementById(chartId);
        const link = document.createElement('a');
        link.download = fileName;
        link.href = chart.toDataURL('image/png');
        link.click();
        return true;
    },
    
    // Get chart data as JSON
    getChartData: (chartId) => {
        const chart = Chart.getChart(chartId);
        if (chart) {
            return {
                labels: chart.data.labels,
                datasets: chart.data.datasets
            };
        }
        return null;
    }
};

// Additional chart types configuration
const chartConfigs = {
    pie: {
        cutout: '50%',
        borderRadius: 10,
        spacing: 5
    },
    
    bar: {
        borderRadius: 8,
        borderSkipped: false
    },
    
    line: {
        tension: 0.4,
        fill: true,
        pointRadius: 4,
        pointHoverRadius: 6
    }
};

// Initialize all charts on page
function initializeAllCharts() {
    // This function can be called when you have multiple charts
    const charts = document.querySelectorAll('canvas[data-chart-type]');
    
    charts.forEach(canvas => {
        const chartType = canvas.getAttribute('data-chart-type');
        const chartData = JSON.parse(canvas.getAttribute('data-chart-data') || '{}');
        
        switch(chartType) {
            case 'pie':
                createCustomPieChart(canvas.id, chartData);
                break;
            case 'bar':
                createCustomBarChart(canvas.id, chartData);
                break;
            case 'line':
                createCustomLineChart(canvas.id, chartData);
                break;
        }
    });
}

// Create custom pie chart with enhanced options
function createCustomPieChart(canvasId, data) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    
    return new Chart(ctx, {
        type: 'pie',
        data: {
            labels: data.labels || [],
            datasets: [{
                data: data.values || [],
                backgroundColor: data.colors || [],
                borderColor: 'rgba(255, 255, 255, 0.1)',
                borderWidth: 2,
                hoverOffset: 20,
                borderRadius: chartConfigs.pie.borderRadius,
                spacing: chartConfigs.pie.spacing
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: chartConfigs.pie.cutout,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        padding: 20,
                        usePointStyle: true,
                        font: {
                            size: 12
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.parsed;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = Math.round((value / total) * 100);
                            return `${label}: ₹${value.toLocaleString()} (${percentage}%)`;
                        }
                    }
                }
            },
            animation: {
                animateScale: true,
                animateRotate: true,
                duration: 1500,
                easing: 'easeOutQuart'
            }
        }
    });
}

// Create custom bar chart with enhanced options
function createCustomBarChart(canvasId, data) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    
    // Create gradient for bars
    const gradient = ChartUtils.createGradient(ctx, data.color || '#8A2BE2', '#4B0082');
    
    return new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.labels || [],
            datasets: [{
                label: data.label || 'Data',
                data: data.values || [],
                backgroundColor: gradient,
                borderColor: data.color || '#8A2BE2',
                borderWidth: 2,
                borderRadius: chartConfigs.bar.borderRadius,
                borderSkipped: chartConfigs.bar.borderSkipped
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: {
                        color: 'rgba(255, 255, 255, 0.1)'
                    },
                    ticks: {
                        callback: ChartUtils.formatCurrency
                    }
                },
                x: {
                    grid: {
                        display: false
                    }
                }
            },
            animation: {
                duration: 1500,
                easing: 'easeOutQuart'
            }
        }
    });
}

// Create custom line chart
function createCustomLineChart(canvasId, data) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    
    // Create gradient for area under line
    const gradient = ChartUtils.createGradient(ctx, 
        (data.color || '#00D4FF') + '40', 
        (data.color || '#00D4FF') + '10'
    );
    
    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.labels || [],
            datasets: [{
                label: data.label || 'Trend',
                data: data.values || [],
                backgroundColor: gradient,
                borderColor: data.color || '#00D4FF',
                borderWidth: 3,
                tension: chartConfigs.line.tension,
                fill: chartConfigs.line.fill,
                pointRadius: chartConfigs.line.pointRadius,
                pointHoverRadius: chartConfigs.line.pointHoverRadius,
                pointBackgroundColor: '#FFFFFF',
                pointBorderColor: data.color || '#00D4FF',
                pointBorderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: {
                        color: 'rgba(255, 255, 255, 0.1)'
                    },
                    ticks: {
                        callback: ChartUtils.formatCurrency
                    }
                },
                x: {
                    grid: {
                        display: false
                    }
                }
            },
            animation: {
                duration: 2000,
                easing: 'easeOutQuart'
            }
        }
    });
}

// Export the utilities
window.ChartUtils = ChartUtils;
window.initializeAllCharts = initializeAllCharts;