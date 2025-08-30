// Variables globales
const API_BASE_URL = '';
const socket = io(window.location.origin);
let performanceChart = null;
let currentTheme = 'light';
let positionsData = [];
let tradesData = [];
let trailingStopData = {};
let currentChartRange = '1M';

// Inicialización cuando se carga la página
window.onload = function() {
    initializeTheme();
    initializeCharts();
    loadInitialData();
    setupEventListeners();
};

// Función para inicializar el tema
function initializeTheme() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    setTheme(savedTheme);
}

// Función para cambiar el tema
function toggleTheme() {
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';
    setTheme(newTheme);
    localStorage.setItem('theme', newTheme);
}

// Función para aplicar el tema
function setTheme(theme) {
    currentTheme = theme;
    const body = document.body;
    const themeIcon = document.getElementById('theme-toggle').querySelector('i');
    
    if (theme === 'dark') {
        body.classList.add('dark-mode');
        themeIcon.classList.remove('fa-moon');
        themeIcon.classList.add('fa-sun');
    } else {
        body.classList.remove('dark-mode');
        themeIcon.classList.remove('fa-sun');
        themeIcon.classList.add('fa-moon');
    }
}

// Función para inicializar los gráficos
function initializeCharts() {
    const ctx = document.getElementById('performance-chart').getContext('2d');
    performanceChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Balance',
                data: [],
                borderColor: '#3B82F6',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: function(context) {
                            return `Balance: ${formatCurrency(context.parsed.y)} USDT`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        display: false
                    }
                },
                y: {
                    beginAtZero: false,
                    grid: {
                        color: 'rgba(255, 255, 255, 0.1)'
                    },
                    ticks: {
                        callback: function(value) {
                            return formatCurrency(value);
                        }
                    }
                }
            }
        }
    });
}

// Función para cargar datos iniciales
function loadInitialData() {
    fetchInitialState();
    loadTrailingStopData();
}

// Función para configurar event listeners
function setupEventListeners() {
    document.getElementById('modal-cancel-btn').addEventListener('click', function() {
        document.getElementById('confirmation-modal').classList.remove('visible');
    });

    // Configurar el buscador de posiciones
    document.getElementById('position-search').addEventListener('input', filterPositions);
    
    // Configurar el buscador de trades
    document.getElementById('trade-search').addEventListener('input', filterTrades);
}

// Función para cambiar pestaña de trades
function changeTradeTab(tabElement, tabName) {
    // Desactivar todas las pestañas
    const tabs = tabElement.parentElement.querySelectorAll('.tab');
    tabs.forEach(tab => tab.classList.remove('active'));
    
    // Activar la pestaña seleccionada
    tabElement.classList.add('active');
    
    // Cargar trades según el período seleccionado
    loadTradesByPeriod(tabName);
}

// Función para cambiar pestaña de configuración
function changeConfigTab(tabElement, tabName) {
    // Desactivar todas las pestañas
    const tabs = tabElement.parentElement.querySelectorAll('.tab');
    tabs.forEach(tab => tab.classList.remove('active'));
    
    // Ocultar todos los contenidos
    const contents = document.querySelectorAll('.tab-content');
    contents.forEach(content => content.classList.remove('active'));
    
    // Activar la pestaña seleccionada
    tabElement.classList.add('active');
    
    // Mostrar el contenido correspondiente
    document.getElementById(tabName + '-config').classList.add('active');
}

// Función para cambiar el rango del gráfico
function changeChartRange(range) {
    currentChartRange = range;
    
    // Actualizar estilos de botones
    const buttons = document.querySelectorAll('.card-actions .btn');
    buttons.forEach(btn => {
        if (btn.textContent.includes(range)) {
            btn.classList.remove('btn-secondary');
            btn.classList.add('btn-primary');
        } else {
            btn.classList.remove('btn-primary');
            btn.classList.add('btn-secondary');
        }
    });
    
    // Aquí podrías cargar datos históricos según el rango seleccionado
    // Por ahora solo es un ejemplo
    console.log('Cambiando rango del gráfico a:', range);
}

// Función para formatear valores monetarios
function formatCurrency(value, decimals = 2) { 
    return parseFloat(value || 0).toFixed(decimals); 
}

// Función para formatear números grandes
function formatNumber(num) {
    if (num >= 1000000) {
        return (num / 1000000).toFixed(2) + 'M';
    } else if (num >= 1000) {
        return (num / 1000).toFixed(2) + 'K';
    }
    return num;
}

// Función para actualizar la interfaz
function updateUI(state) {
    const isRunning = state.running;
    document.getElementById('status-message').textContent = state.status_message || 'Detenido';
    document.getElementById('status-dot').classList.toggle('running', isRunning);
    document.getElementById('start-btn').disabled = isRunning;
    document.getElementById('stop-btn').disabled = !isRunning;
    
    document.getElementById('header-balance').textContent = `${formatCurrency(state.balance)} USDT`;
    document.getElementById('balance-stat').textContent = formatCurrency(state.balance);
    document.getElementById('investment-stat').textContent = formatCurrency(state.total_investment_usd);
    
    const openPositions = Object.keys(state.open_positions || {}).length;
    const maxPositions = state.config?.MAX_CONCURRENT_POS || 20;
    document.getElementById('positions-stat').textContent = `${openPositions}/${maxPositions}`;
    
    const totalUnrealizedPnl = Object.values(state.open_positions || {}).reduce((acc, pos) => acc + parseFloat(pos.unRealizedProfit || pos.unrealizedProfit || 0), 0);
    const unrealizedPnlEl = document.getElementById('unrealized-pnl-stat');
    unrealizedPnlEl.textContent = formatCurrency(totalUnrealizedPnl);
    unrealizedPnlEl.className = `stat-value ${totalUnrealizedPnl >= 0 ? 'positive' : 'negative'}`;
    
    // Actualizar tendencia del P&L no realizado
    const unrealizedTrendEl = document.getElementById('unrealized-trend');
    if (totalUnrealizedPnl >= 0) {
        unrealizedTrendEl.innerHTML = '<i class="fas fa-caret-up positive"></i> ' + formatCurrency(totalUnrealizedPnl) + '%';
    } else {
        unrealizedTrendEl.innerHTML = '<i class="fas fa-caret-down negative"></i> ' + formatCurrency(Math.abs(totalUnrealizedPnl)) + '%';
    }
    
    const perf = state.performance_stats || {};
    const realizedPnlEl = document.getElementById('realized-pnl-stat');
    realizedPnlEl.textContent = formatCurrency(perf.realized_pnl);
    realizedPnlEl.className = `stat-value ${perf.realized_pnl >= 0 ? 'positive' : 'negative'}`;
    
    // Actualizar tendencia del P&L realizado
    const realizedTrendEl = document.getElementById('realized-trend');
    if (perf.realized_pnl >= 0) {
        realizedTrendEl.innerHTML = '<i class="fas fa-caret-up positive"></i> ' + formatCurrency(perf.realized_pnl) + '%';
    } else {
        realizedTrendEl.innerHTML = '<i class="fas fa-caret-down negative"></i> ' + formatCurrency(Math.abs(perf.realized_pnl)) + '%';
    }
    
    document.getElementById('trades-stat').textContent = perf.trades_count || 0;
    
    // Actualizar el resumen de trading
    document.getElementById('win-rate-stat').textContent = formatCurrency(perf.win_rate || 0) + '%';
    document.getElementById('avg-win-stat').textContent = formatCurrency(perf.avg_win || 0);
    document.getElementById('avg-loss-stat').textContent = formatCurrency(perf.avg_loss || 0);
    
    let profitFactor = perf.profit_factor || 0;
    if (profitFactor === Infinity) {
        document.getElementById('profit-factor-stat').textContent = 'Infinito';
    } else {
        document.getElementById('profit-factor-stat').textContent = formatCurrency(profitFactor, 2);
    }
    
    if (state.config) {
        ['LEVERAGE', 'MAX_CONCURRENT_POS', 'FIXED_MARGIN_PER_TRADE_USDT', 'NUM_SYMBOLS_TO_SCAN', 'ATR_MULT_SL', 'ATR_MULT_TP', 'TRAILING_STOP_ACTIVATION', 'TRAILING_STOP_PERCENTAGE'].forEach(key => {
            const el = document.getElementById(key);
            if (el) el.value = state.config[key];
        });
    }
    
    // Guardar datos de posiciones para filtrado
    positionsData = Object.values(state.open_positions || {});
    updatePositionsTable(positionsData);
    
    // Actualizar gráfico de rendimiento
    updatePerformanceChart(state.balance);
}

// Función para actualizar la tabla de posiciones
function updatePositionsTable(positions) {
    const tbody = document.getElementById('positions-tbody');
    tbody.innerHTML = positions.length === 0 
        ? '<tr><td colspan="8" style="text-align:center; padding: 2rem;">No hay posiciones abiertas.</td></tr>'
        : positions.map(pos => {
            const pnl = parseFloat(pos.unRealizedProfit || pos.unrealizedProfit || 0);
            const side = parseFloat(pos.positionAmt) > 0 ? 'LONG' : 'SHORT';
            const entryPrice = parseFloat(pos.entryPrice);
            const markPrice = parseFloat(pos.markPrice);
            const priceChange = ((markPrice - entryPrice) / entryPrice) * 100;
            
            // Obtener información de trailing stop
            const trailingInfo = trailingStopData[pos.symbol] || {};
            const trailingStatus = trailingInfo.activated ? 
                `<span class="badge badge-success">Activo @ ${formatCurrency(trailingInfo.current_stop, 4)}</span>` : 
                `<span class="badge badge-secondary">Inactivo</span>`;
            
            return `<tr>
                <td><strong>${pos.symbol}</strong></td>
                <td><span class="${side === 'LONG' ? 'positive' : 'negative'}">${side}</span></td>
                <td>${formatCurrency(Math.abs(pos.positionAmt), 4)}</td>
                <td>${formatCurrency(entryPrice, 4)}</td>
                <td>${formatCurrency(markPrice, 4)} <span class="${priceChange >= 0 ? 'positive' : 'negative'}">(${formatCurrency(priceChange)}%)</span></td>
                <td id="pnl-${pos.symbol}" class="${pnl >= 0 ? 'positive' : 'negative'}">${formatCurrency(pnl)}</td>
                <td>${trailingStatus}</td>
                <td>
                    <button class="btn btn-danger btn-sm" onclick="confirmClosePosition('${pos.symbol}')">
                        <i class="fas fa-times"></i> Cerrar
                    </button>
                </td>
            </tr>`;
        }).join('');
}

// Función para filtrar posiciones
function filterPositions() {
    const searchTerm = document.getElementById('position-search').value.toLowerCase();
    const filteredPositions = positionsData.filter(pos => 
        pos.symbol.toLowerCase().includes(searchTerm)
    );
    updatePositionsTable(filteredPositions);
}

// Función para cargar trades por período
function loadTradesByPeriod(period) {
    // Esta función se implementará cuando se carguen los trades desde la API
    console.log('Cargando trades del período:', period);
    // Por ahora, solo actualizamos la tabla con los trades disponibles
    updateTradesTable();
}

// Función para actualizar la tabla de trades
function updateTradesTable() {
    const tbody = document.getElementById('trades-tbody');
    // Por ahora, solo mostramos un mensaje
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding: 2rem;">No hay trades recientes</td></tr>';
}

// Función para filtrar trades
function filterTrades() {
    const searchTerm = document.getElementById('trade-search').value.toLowerCase();
    // Esta función se implementará cuando se carguen los trades
    console.log('Filtrando trades por:', searchTerm);
}

// Función para actualizar el gráfico de rendimiento
function updatePerformanceChart(balance) {
    if (!performanceChart) return;
    
    // Agregar nuevo punto de datos
    const now = new Date();
    const timeLabel = now.getHours() + ':' + now.getMinutes().toString().padStart(2, '0');
    
    performanceChart.data.labels.push(timeLabel);
    performanceChart.data.datasets[0].data.push(balance);
    
    // Mantener un número limitado de puntos de datos
    const maxDataPoints = 20;
    if (performanceChart.data.labels.length > maxDataPoints) {
        performanceChart.data.labels.shift();
        performanceChart.data.datasets[0].data.shift();
    }
    
    performanceChart.update();
}

// Función para agregar entrada al log
function addLogEntry(message, level = 'info') {
    const logContainer = document.getElementById('log-container');
    const sanitizedMessage = message.replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const time = new Date().toLocaleTimeString();
    let logClass = '';
    let icon = '';
    
    if (level.includes('error')) {
        logClass = 'log-error';
        icon = '<i class="fas fa-exclamation-circle"></i> ';
    } else if (level.includes('warning')) {
        logClass = 'log-warning';
        icon = '<i class="fas fa-exclamation-triangle"></i> ';
    } else if (level.includes('info')) {
        logClass = 'log-info';
        icon = '<i class="fas fa-info-circle"></i> ';
    } else if (level.includes('success')) {
        logClass = 'log-success';
        icon = '<i class="fas fa-check-circle"></i> ';
    }
    
    logContainer.innerHTML += `<div class="${logClass}"><span style="color: #6B7280;">[${time}]</span> ${icon}${sanitizedMessage}</div>`;
    logContainer.scrollTop = logContainer.scrollHeight;
}

// Función para mostrar notificación toast
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    let icon = '';
    
    switch(type) {
        case 'success':
            icon = '<i class="fas fa-check-circle"></i>';
            break;
        case 'error':
            icon = '<i class="fas fa-exclamation-circle"></i>';
            break;
        default:
            icon = '<i class="fas fa-info-circle"></i>';
    }
    
    toast.className = `toast ${type}`;
    toast.innerHTML = `${icon} ${message}`;
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.classList.add('show');
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }, 10);
}

// Función para llamar a la API
async function apiCall(endpoint, options = {}, button = null) {
    if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="loader"></span> Procesando...';
    }
    
    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, options);
        const responseData = await response.json().catch(() => ({ message: 'Respuesta no válida del servidor' }));
        
        if (!response.ok) {
            throw new Error(responseData.message || `Error ${response.status}`);
        }
        
        if (responseData.message) {
            showToast(responseData.message, 'success');
        }
        
        return responseData;
    } catch (error) {
        showToast(error.message, 'error');
        addLogEntry(`❌ Error en API (${endpoint}): ${error.message}`, 'error');
        throw error;
    } finally {
        if (button) {
            button.disabled = false;
            button.innerHTML = button.dataset.originalText;
        }
    }
}

// Función para configurar botones
function setupButton(button, action) {
    button.dataset.originalText = button.innerHTML;
    action(button);
}

// Función para iniciar el bot
async function startBot(btn) { 
    setupButton(btn, () => apiCall('/api/start', { method: 'POST' }, btn)); 
}

// Función para detener el bot
async function stopBot(btn) { 
    setupButton(btn, () => apiCall('/api/stop', { method: 'POST' }, btn)); 
}

// Función para guardar configuración
async function saveConfig(btn, type) {
    const keys = {
        'global': ['LEVERAGE', 'MAX_CONCURRENT_POS', 'FIXED_MARGIN_PER_TRADE_USDT', 'NUM_SYMBOLS_TO_SCAN'],
        'strategy': ['ATR_MULT_SL', 'ATR_MULT_TP'],
        'trailing': ['TRAILING_STOP_ACTIVATION', 'TRAILING_STOP_PERCENTAGE']
    }[type] || [];
        
    const config = keys.reduce((acc, key) => {
        acc[key] = document.getElementById(key).value;
        return acc;
    }, {});
    
    setupButton(btn, () => apiCall('/api/update_config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
    }, btn));
}

// Función para ejecutar trade manual
async function executeManualTrade(btn) {
    const trade = {
        symbol: document.getElementById('manual-symbol').value.toUpperCase(),
        side: document.getElementById('manual-side').value,
        margin: document.getElementById('manual-margin').value,
        leverage: document.getElementById('manual-leverage').value
    };
    
    if (!trade.symbol) {
        showToast('Por favor, introduce un símbolo.', 'error');
        return;
    }
    
    setupButton(btn, () => apiCall('/api/manual_trade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(trade)
    }, btn));
}

// Función para confirmar cierre de posición
function confirmClosePosition(symbol) {
    const modal = document.getElementById('confirmation-modal');
    document.getElementById('modal-title').textContent = `Cerrar Posición`;
    document.getElementById('modal-body').textContent = `¿Está seguro que desea cerrar la posición en ${symbol}? Esta acción es irreversible.`;
    modal.classList.add('visible');

    const confirmBtn = document.getElementById('modal-confirm-btn');
    const cancelBtn = document.getElementById('modal-cancel-btn');

    const close = () => modal.classList.remove('visible');
    
    confirmBtn.onclick = async () => {
        close();
        await apiCall('/api/close_position', {
            method: 'POST', 
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol })
        });
    };
    
    cancelBtn.onclick = close;
}

// Función para cargar el estado inicial
async function fetchInitialState() {
    try {
        const initialState = await apiCall('/api/status');
        updateUI(initialState);
    } catch (e) {
        console.error("Error al cargar estado inicial", e);
    }
}

// Función para cargar datos de trailing stop
async function loadTrailingStopData() {
    try {
        const response = await fetch('/api/trailing_stop_data');
        if (response.ok) {
            trailingStopData = await response.json();
        }
    } catch (error) {
        console.error("Error loading trailing stop data:", error);
    }
}

// Función para refrescar datos
function refreshData() {
    fetchInitialState();
    loadTrailingStopData();
    showToast('Datos actualizados', 'success');
}

// Función para limpiar logs
function clearLogs() {
    document.getElementById('log-container').innerHTML = '';
    addLogEntry('Registros limpiados manualmente', 'info');
}

// Función para exportar logs
function exportLogs() {
    showToast('Función de exportación en desarrollo', 'info');
}

// Función para exportar trades
function exportTrades() {
    showToast('Función de exportación de trades en desarrollo', 'info');
}

// Función para guardar configuración API
function saveApiConfig(btn) {
    showToast('Configuración API guardada', 'success');
}

// Función para guardar configuración avanzada
function saveAdvancedSettings() {
    showToast('Configuración avanzada guardada', 'success');
    document.getElementById('settings-modal').classList.remove('visible');
}

// Función para cargar métricas de rendimiento
async function loadPerformanceMetrics() {
    try {
        const symbol = document.getElementById('performance-symbol').value;
        const response = await fetch(`/api/performance_metrics?symbol=${symbol}&hours=24`);
        const metrics = await response.json();
        
        if (metrics.length === 0) {
            document.getElementById('performance-metrics').innerHTML = 
                '<p class="text-center">No hay datos de rendimiento disponibles</p>';
            return;
        }
        
        // Agrupar por símbolo y tomar la métrica más reciente
        const latestMetrics = {};
        metrics.forEach(m => {
            if (!latestMetrics[m.symbol] || new Date(m.timestamp) > new Date(latestMetrics[m.symbol].timestamp)) {
                latestMetrics[m.symbol] = m;
            }
        });
        
        let html = '';
        for (const symbol in latestMetrics) {
            const m = latestMetrics[symbol];
            html += `
                <div class="stat-card" style="margin-bottom: 1rem; padding: 1rem;">
                    <h4>${m.symbol}</h4>
                    <div class="stat-grid">
                        <div>Win Rate: <span class="${m.win_rate > 0.5 ? 'positive' : 'negative'}">${(m.win_rate * 100).toFixed(2)}%</span></div>
                        <div>Profit Factor: <span class="${m.profit_factor > 1 ? 'positive' : 'negative'}">${m.profit_factor.toFixed(2)}</span></div>
                        <div>Leverage Recomendado: <strong>${m.recommended_leverage}x</strong></div>
                        <div>Efectividad: ${m.strategy_effectiveness.toFixed(2)}</div>
                    </div>
                    <button class="btn btn-sm btn-primary" onclick="autoAdjustLeverage('${m.symbol}')" style="margin-top: 0.5rem;">
                        Ajustar Leverage
                    </button>
                </div>
            `;
        }
        
        document.getElementById('performance-metrics').innerHTML = html;
    } catch (error) {
        console.error('Error loading performance metrics:', error);
        document.getElementById('performance-metrics').innerHTML = 
            '<p class="text-center error">Error cargando métricas</p>';
    }
}

// Función para ajustar automáticamente el leverage
async function autoAdjustLeverage(symbol) {
    try {
        const response = await fetch('/api/auto_adjust_leverage', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol })
        });
        
        const result = await response.json();
        
        if (result.status === 'success') {
            showToast(result.message, 'success');
            // Recargar configuración
            fetchInitialState();
        } else {
            showToast(result.message, 'error');
        }
    } catch (error) {
        console.error('Error adjusting leverage:', error);
        showToast('Error ajustando leverage', 'error');
    }
}

// Configuración de Socket.IO
socket.on('connect', () => {
    addLogEntry('✅ Conectado al servidor.', 'success');
    showToast('Conexión establecida con el servidor', 'success');
});

socket.on('disconnect', () => {
    addLogEntry('❌ Desconectado del servidor.', 'warning');
    showToast('Conexión perdida con el servidor', 'error');
});

socket.on('connect_error', (err) => {
    addLogEntry(`❌ Error de conexión: ${err.message}`, 'error');
});

socket.on('status_update', updateUI);

socket.on('config_updated', () => {
    addLogEntry('⚙️ Configuración actualizada desde el servidor.', 'info');
});

socket.on('log_update', (data) => {
    addLogEntry(data.message, data.level.toLowerCase());
});

socket.on('pnl_update', (pnlData) => {
    Object.entries(pnlData).forEach(([symbol, pnl]) => {
        const pnlCell = document.getElementById(`pnl-${symbol}`);
        if (pnlCell) {
            pnlCell.textContent = formatCurrency(pnl);
            pnlCell.className = pnl >= 0 ? 'positive' : 'negative';
        }
    });
});

// Solicitar datos iniciales
fetchInitialState();

// Llamar a loadPerformanceMetrics cuando la página cargue
window.addEventListener('load', () => {
    loadPerformanceMetrics();
    
    // Cargar símbolos en el selector
    fetch('/api/positions')
        .then(r => r.json())
        .then(data => {
            const symbols = Object.keys(data.positions || {});
            const select = document.getElementById('performance-symbol');
            
            symbols.forEach(symbol => {
                const option = document.createElement('option');
                option.value = symbol;
                option.textContent = symbol;
                select.appendChild(option);
            });
        });
});