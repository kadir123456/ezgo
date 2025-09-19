// Dashboard JavaScript for EzyagoTrading (FULLY OPTIMIZED - Rate limit sorunu çözüldü)
let firebaseApp = null;
let auth = null;
let database = null;
let currentUser = null;
let authToken = null;
let tokenRefreshInterval = null;

// ✅ Smart Timeframe Recommendations
const timeframeRecommendations = {
    "5m": {
        name: "🏃‍♂️ Hızlı Scalping",
        stopLoss: 0.3,
        takeProfit: 0.5,
        winRate: 75,
        description: "Günde 10-20 trade, güvenli kazanç",
        riskLevel: "low",
        maxHoldTime: "30 dakika"
    },
    "15m": {
        name: "📈 Dengeli Swing", 
        stopLoss: 0.8,
        takeProfit: 1.2,
        winRate: 70,
        description: "Günde 5-10 trade, istikrarlı kar",
        riskLevel: "low",
        maxHoldTime: "2 saat"
    },
    "30m": {
        name: "🎯 Trend Takip",
        stopLoss: 1.0,
        takeProfit: 2.0,
        winRate: 65,
        description: "Güçlü trend'lerde büyük kazanç",
        riskLevel: "medium",
        maxHoldTime: "5 saat"
    },
    "1h": {
        name: "🏔️ Pozisyon Trading",
        stopLoss: 1.5,
        takeProfit: 3.0,
        winRate: 60,
        description: "Major hareketlerde yüksek kar",
        riskLevel: "medium",
        maxHoldTime: "12 saat"
    },
    "4h": {
        name: "🚀 Major Trend",
        stopLoss: 2.5,
        takeProfit: 5.0,
        winRate: 55,
        description: "Büyük trend'lerde maksimum kazanç",
        riskLevel: "high",
        maxHoldTime: "48 saat"
    }
};

// Manual input tracking
let manualSL = false;
let manualTP = false;

// Initialize Firebase
async function initializeFirebase() {
    try {
        const firebaseConfig = await window.configLoader.getFirebaseConfig();
        
        firebaseApp = firebase.initializeApp(firebaseConfig);
        auth = firebase.auth();
        database = firebase.database();
        console.log('Firebase initialized successfully');
        return true;
    } catch (error) {
        console.error('Firebase initialization error:', error);
        return false;
    }
}

// Get fresh Firebase token
async function getFreshToken() {
    try {
        if (currentUser) {
            const token = await currentUser.getIdToken(true);
            authToken = token;
            console.log('Fresh auth token obtained');
            return token;
        }
        throw new Error('No current user');
    } catch (error) {
        console.error('Error getting fresh token:', error);
        throw error;
    }
}

// Setup token refresh
function setupTokenRefresh() {
    if (tokenRefreshInterval) clearInterval(tokenRefreshInterval);
    
    tokenRefreshInterval = setInterval(async () => {
        try {
            await getFreshToken();
            console.log('Token refreshed automatically');
        } catch (error) {
            console.error('Auto token refresh failed:', error);
        }
    }, 50 * 60 * 1000); // 50 minutes
}

// API call helper with authentication
async function makeAuthenticatedApiCall(endpoint, options = {}) {
    try {
        if (!authToken) {
            console.log('No token available, getting fresh token...');
            await getFreshToken();
        }
        
        if (!authToken) {
            throw new Error('Could not obtain authentication token');
        }

        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            }
        };

        const mergedOptions = {
            ...defaultOptions,
            ...options,
            headers: { ...defaultOptions.headers, ...options.headers }
        };

        console.log(`Making API call to: ${endpoint}`);
        const response = await fetch(endpoint, mergedOptions);
        
        if (!response.ok) {
            if (response.status === 401) {
                console.log('401 error, refreshing token and retrying...');
                try {
                    await getFreshToken();
                    const retryOptions = {
                        ...mergedOptions,
                        headers: {
                            ...mergedOptions.headers,
                            'Authorization': `Bearer ${authToken}`
                        }
                    };
                    const retryResponse = await fetch(endpoint, retryOptions);
                    if (retryResponse.ok) {
                        const contentType = retryResponse.headers.get('content-type');
                        if (contentType && contentType.includes('application/json')) {
                            return await retryResponse.json();
                        }
                        return await retryResponse.text();
                    } else {
                        throw new Error(`HTTP ${retryResponse.status} after retry`);
                    }
                } catch (refreshError) {
                    console.error('Token refresh and retry failed:', refreshError);
                    throw new Error('Authentication failed - please login again');
                }
            } else {
                throw new Error(`HTTP ${response.status}`);
            }
        }

        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
            return await response.json();
        }
        
        return await response.text();
    } catch (error) {
        console.error('API call failed:', error);
        throw error;
    }
}

// Show notification
function showNotification(message, type = 'info', duration = 5000) {
    const toast = document.getElementById('toast');
    const icon = toast.querySelector('.toast-icon');
    const messageEl = toast.querySelector('.toast-message');
    
    const icons = {
        success: 'fas fa-check-circle',
        error: 'fas fa-exclamation-circle',
        warning: 'fas fa-exclamation-triangle',
        info: 'fas fa-info-circle'
    };
    
    const colors = {
        success: 'var(--success-color)',
        error: 'var(--danger-color)',
        warning: 'var(--warning-color)',
        info: 'var(--info-color)'
    };
    
    icon.className = `toast-icon ${icons[type] || icons.info}`;
    icon.style.color = colors[type] || colors.info;
    messageEl.textContent = message;
    
    toast.classList.add('show');
    
    setTimeout(() => {
        toast.classList.remove('show');
    }, duration);
}

// Format currency
function formatCurrency(amount, currency = 'USDT') {
    const num = parseFloat(amount) || 0;
    return `${num.toLocaleString('tr-TR', { 
        minimumFractionDigits: 2, 
        maximumFractionDigits: 2 
    })} ${currency}`;
}

// Format percentage
function formatPercentage(value) {
    const num = parseFloat(value) || 0;
    const sign = num >= 0 ? '+' : '';
    return `${sign}${num.toFixed(2)}%`;
}

// ✅ Advanced settings toggle
function toggleAdvancedSettings() {
    const content = document.getElementById('advanced-settings-content');
    const toggle = document.getElementById('advanced-toggle');
    
    if (content && toggle) {
        const isShowing = content.classList.contains('show');
        
        if (isShowing) {
            content.classList.remove('show');
            toggle.innerHTML = '<i class="fas fa-chevron-down"></i>';
        } else {
            content.classList.add('show');
            toggle.innerHTML = '<i class="fas fa-chevron-up"></i>';
        }
    }
}

// ✅ Smart Recommendations Logic
function updateStrategyInfo(timeframe) {
    const rec = timeframeRecommendations[timeframe];
    if (!rec) return;

    // Update strategy info card
    const strategyName = document.getElementById('strategy-name');
    const strategyDescription = document.getElementById('strategy-description');
    const expectedWinRate = document.getElementById('expected-win-rate');
    const maxHoldTime = document.getElementById('max-hold-time');
    
    if (strategyName) strategyName.textContent = rec.name;
    if (strategyDescription) strategyDescription.textContent = rec.description;
    if (expectedWinRate) expectedWinRate.textContent = `🎯 ${rec.winRate}% Win Rate`;
    if (maxHoldTime) maxHoldTime.textContent = `⏱️ Max: ${rec.maxHoldTime}`;
    
    // Update risk badge
    const riskBadge = document.getElementById('risk-badge');
    if (riskBadge) {
        riskBadge.className = `risk-badge ${rec.riskLevel}`;
        riskBadge.textContent = rec.riskLevel === 'low' ? 'DÜŞÜK RİSK' : rec.riskLevel === 'medium' ? 'ORTA RİSK' : 'YÜKSEK RİSK';
    }
    
    // Update recommended values
    const slRecommendedValue = document.getElementById('sl-recommended-value');
    const tpRecommendedValue = document.getElementById('tp-recommended-value');
    
    if (slRecommendedValue) slRecommendedValue.textContent = rec.stopLoss;
    if (tpRecommendedValue) tpRecommendedValue.textContent = rec.takeProfit;
    
    // Auto-update if not manual
    const stopLossInput = document.getElementById('stop-loss');
    const takeProfitInput = document.getElementById('take-profit');
    const slRecommendationBtn = document.getElementById('sl-recommendation-btn');
    const tpRecommendationBtn = document.getElementById('tp-recommendation-btn');
    
    if (!manualSL && stopLossInput && slRecommendationBtn) {
        stopLossInput.value = rec.stopLoss;
        stopLossInput.classList.add('recommended-input');
        stopLossInput.classList.remove('manual-input');
        slRecommendationBtn.classList.add('active');
        slRecommendationBtn.classList.remove('inactive');
    }
    
    if (!manualTP && takeProfitInput && tpRecommendationBtn) {
        takeProfitInput.value = rec.takeProfit;
        takeProfitInput.classList.add('recommended-input');
        takeProfitInput.classList.remove('manual-input');
        tpRecommendationBtn.classList.add('active');
        tpRecommendationBtn.classList.remove('inactive');
    }
}

// ✅ Setup smart recommendations event listeners
function setupSmartRecommendations() {
    // Initial strategy update
    updateStrategyInfo('15m');
    
    // Timeframe change listener
    const timeframeSelect = document.getElementById('timeframe-select');
    if (timeframeSelect) {
        timeframeSelect.addEventListener('change', function() {
            updateStrategyInfo(this.value);
        });
    }
    
    // SL input change listener
    const slInput = document.getElementById('stop-loss');
    if (slInput) {
        slInput.addEventListener('input', function() {
            manualSL = true;
            this.classList.add('manual-input');
            this.classList.remove('recommended-input');
            const slRecommendationBtn = document.getElementById('sl-recommendation-btn');
            const slHint = document.getElementById('sl-hint');
            if (slRecommendationBtn) {
                slRecommendationBtn.classList.add('inactive');
                slRecommendationBtn.classList.remove('active');
            }
            if (slHint) slHint.style.display = 'block';
        });
    }
    
    // TP input change listener
    const tpInput = document.getElementById('take-profit');
    if (tpInput) {
        tpInput.addEventListener('input', function() {
            manualTP = true;
            this.classList.add('manual-input');
            this.classList.remove('recommended-input');
            const tpRecommendationBtn = document.getElementById('tp-recommendation-btn');
            const tpHint = document.getElementById('tp-hint');
            if (tpRecommendationBtn) {
                tpRecommendationBtn.classList.add('inactive');
                tpRecommendationBtn.classList.remove('active');
            }
            if (tpHint) tpHint.style.display = 'block';
        });
    }
    
    // SL recommendation button
    const slRecBtn = document.getElementById('sl-recommendation-btn');
    if (slRecBtn) {
        slRecBtn.addEventListener('click', function() {
            const timeframe = document.getElementById('timeframe-select').value;
            const rec = timeframeRecommendations[timeframe];
            if (rec) {
                manualSL = false;
                const stopLossInput = document.getElementById('stop-loss');
                const slHint = document.getElementById('sl-hint');
                if (stopLossInput) {
                    stopLossInput.value = rec.stopLoss;
                    stopLossInput.classList.add('recommended-input');
                    stopLossInput.classList.remove('manual-input');
                }
                this.classList.add('active');
                this.classList.remove('inactive');
                if (slHint) slHint.style.display = 'none';
            }
        });
    }
    
    // TP recommendation button
    const tpRecBtn = document.getElementById('tp-recommendation-btn');
    if (tpRecBtn) {
        tpRecBtn.addEventListener('click', function() {
            const timeframe = document.getElementById('timeframe-select').value;
            const rec = timeframeRecommendations[timeframe];
            if (rec) {
                manualTP = false;
                const takeProfitInput = document.getElementById('take-profit');
                const tpHint = document.getElementById('tp-hint');
                if (takeProfitInput) {
                    takeProfitInput.value = rec.takeProfit;
                    takeProfitInput.classList.add('recommended-input');
                    takeProfitInput.classList.remove('manual-input');
                }
                this.classList.add('active');
                this.classList.remove('inactive');
                if (tpHint) tpHint.style.display = 'none';
            }
        });
    }
    
    // Use recommended buttons
    const useSLBtn = document.getElementById('use-sl-recommended');
    if (useSLBtn) {
        useSLBtn.addEventListener('click', function() {
            const slRecommendationBtn = document.getElementById('sl-recommendation-btn');
            if (slRecommendationBtn) slRecommendationBtn.click();
        });
    }
    
    const useTPBtn = document.getElementById('use-tp-recommended');
    if (useTPBtn) {
        useTPBtn.addEventListener('click', function() {
            const tpRecommendationBtn = document.getElementById('tp-recommendation-btn');
            if (tpRecommendationBtn) tpRecommendationBtn.click();
        });
    }
}

// ✅ OPTIMIZED: Tek seferde tüm dashboard verilerini yükle (Rate limit çözümü)
async function loadAllDashboardData() {
    try {
        console.log('Loading dashboard data with optimized single API call...');
        
        // ✅ TEK API ÇAĞRISI - 8 yerine 1 çağrı
        const data = await makeAuthenticatedApiCall('/api/user/dashboard-data');
        
        // Update all UI elements
        updateProfile(data.profile);
        updateAccount(data.account);
        updatePositions(data.positions);
        updateStats(data.stats);
        updateApiStatus(data.api_status);
        
        console.log('✅ Dashboard data loaded successfully with single API call');
        showNotification('Dashboard başarıyla yüklendi!', 'success', 2000);
        
    } catch (error) {
        console.error('Dashboard data load failed:', error);
        showNotification('Dashboard verileri yüklenirken hata oluştu', 'error');
        
        // Fallback: Load basic data
        try {
            await loadFallbackData();
        } catch (fallbackError) {
            console.error('Fallback data load also failed:', fallbackError);
        }
    }
}

// ✅ Fallback data loading
async function loadFallbackData() {
    console.log('Loading fallback data...');
    
    try {
        // Load only essential data individually if main endpoint fails
        const profile = await makeAuthenticatedApiCall('/api/user/profile');
        updateProfile(profile);
        
        const stats = await makeAuthenticatedApiCall('/api/user/stats');
        updateStats(stats);
        
        showNotification('Temel veriler yüklendi (sınırlı mod)', 'warning');
        
    } catch (error) {
        console.error('Fallback data load failed:', error);
        // Show empty state
        updateProfile({ email: 'Kullanıcı', subscription: { status: 'trial' } });
        updateStats({ totalTrades: 0, totalPnl: 0, winRate: 0 });
    }
}

// Update profile UI
function updateProfile(profile) {
    const userName = document.getElementById('user-name');
    const subscriptionText = document.getElementById('subscription-text');
    const subStatusBadge = document.getElementById('sub-status-badge');
    const daysRemaining = document.getElementById('days-remaining');
    const subscriptionNote = document.getElementById('subscription-note');
    
    if (userName) userName.textContent = profile.email || 'Kullanıcı';
    
    if (profile.subscription) {
        if (subscriptionText) subscriptionText.textContent = profile.subscription.plan || 'Premium';
        if (subStatusBadge) {
            const statusSpan = subStatusBadge.querySelector('span');
            if (statusSpan) statusSpan.textContent = profile.subscription.status === 'active' ? 'Aktif' : 'Deneme';
        }
        
        if (daysRemaining) {
            const daysLeft = profile.subscription.daysRemaining || 0;
            daysRemaining.textContent = daysLeft > 0 ? `${daysLeft} gün kaldı` : 'Süresi dolmuş';
            
            if (subscriptionNote) {
                if (daysLeft <= 7 && daysLeft > 0) {
                    subscriptionNote.textContent = 'Aboneliğiniz yakında sona erecek. Yenilemeyi unutmayın!';
                    subscriptionNote.style.color = 'var(--warning-color)';
                } else if (daysLeft <= 0) {
                    subscriptionNote.textContent = 'Abonelik süresi dolmuş. Lütfen yenileyin.';
                    subscriptionNote.style.color = 'var(--danger-color)';
                } else {
                    subscriptionNote.textContent = 'Aboneliğiniz aktif durumda.';
                    subscriptionNote.style.color = 'var(--success-color)';
                }
            }
        }
    }
}

// Update account UI
function updateAccount(account) {
    const totalBalance = document.getElementById('total-balance');
    const totalPnl = document.getElementById('total-pnl');
    
    if (totalBalance) totalBalance.textContent = formatCurrency(account.totalBalance || 0);
    
    if (totalPnl) {
        totalPnl.textContent = formatCurrency(account.unrealizedPnl || 0);
        const pnlValue = parseFloat(account.unrealizedPnl || 0);
        if (pnlValue > 0) {
            totalPnl.style.color = 'var(--success-color)';
        } else if (pnlValue < 0) {
            totalPnl.style.color = 'var(--danger-color)';
        } else {
            totalPnl.style.color = 'var(--text-primary)';
        }
    }
}

// Update positions UI
function updatePositions(positions) {
    const positionsContainer = document.getElementById('positions-container');
    if (!positionsContainer) return;
    
    if (!positions || positions.length === 0) {
        positionsContainer.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-chart-line"></i>
                <h3>Açık Pozisyon Yok</h3>
                <p>Bot başlatıldığında pozisyonlar burada görünecek</p>
            </div>
        `;
        return;
    }

    const positionsHTML = positions.map(position => {
        const pnlClass = position.unrealizedPnl >= 0 ? 'profit' : 'loss';
        const sideClass = position.positionSide.toLowerCase();
        
        return `
            <div class="position-item">
                <div class="position-header">
                    <span class="position-symbol">${position.symbol}</span>
                    <span class="position-side ${sideClass}">${position.positionSide}</span>
                </div>
                <div class="position-stats">
                    <div class="position-stat">
                        <div class="stat-label">Boyut</div>
                        <div class="stat-value">${Math.abs(position.positionAmt)} ${position.symbol.replace('USDT', '')}</div>
                    </div>
                    <div class="position-stat">
                        <div class="stat-label">Giriş Fiyatı</div>
                        <div class="stat-value">$${parseFloat(position.entryPrice).toFixed(2)}</div>
                    </div>
                    <div class="position-stat">
                        <div class="stat-label">Güncel Fiyat</div>
                        <div class="stat-value">$${parseFloat(position.markPrice).toFixed(2)}</div>
                    </div>
                    <div class="position-stat">
                        <div class="stat-label">P&L</div>
                        <div class="stat-value ${pnlClass}">${formatCurrency(position.unrealizedPnl)}</div>
                    </div>
                </div>
                <div class="position-actions">
                    <button class="btn btn-danger btn-sm" onclick="closePosition('${position.symbol}', '${position.positionSide}')">
                        <i class="fas fa-times"></i> Pozisyonu Kapat
                    </button>
                </div>
            </div>
        `;
    }).join('');

    positionsContainer.innerHTML = positionsHTML;
}

// Update stats UI
function updateStats(stats) {
    const totalTrades = document.getElementById('total-trades');
    const winRate = document.getElementById('win-rate');
    const totalPnl = document.getElementById('total-pnl');
    
    if (totalTrades) totalTrades.textContent = stats.totalTrades || '0';
    if (winRate) winRate.textContent = formatPercentage(stats.winRate || 0);
    if (totalPnl) {
        totalPnl.textContent = formatCurrency(stats.totalPnl || 0);
        const pnlValue = parseFloat(stats.totalPnl || 0);
        if (pnlValue > 0) {
            totalPnl.style.color = 'var(--success-color)';
        } else if (pnlValue < 0) {
            totalPnl.style.color = 'var(--danger-color)';
        } else {
            totalPnl.style.color = 'var(--text-primary)';
        }
    }
}

// Update API status UI
function updateApiStatus(apiStatus) {
    const apiStatusIndicator = document.getElementById('api-status-indicator');
    const manageApiBtn = document.getElementById('manage-api-btn');
    const tradingSettings = document.getElementById('trading-settings');
    const controlButtons = document.getElementById('control-buttons');
    const statusMessageText = document.getElementById('status-message-text');
    
    if (apiStatus.hasApiKeys && apiStatus.isConnected) {
        // API connected
        if (apiStatusIndicator) {
            apiStatusIndicator.innerHTML = `
                <i class="fas fa-check-circle"></i>
                <span>API bağlantısı aktif</span>
            `;
            apiStatusIndicator.className = 'api-status-indicator connected';
        }
        
        if (manageApiBtn) {
            manageApiBtn.style.display = 'inline-flex';
            manageApiBtn.textContent = 'API Ayarlarını Düzenle';
        }
        
        if (tradingSettings) tradingSettings.style.display = 'block';
        if (controlButtons) controlButtons.style.display = 'grid';
        if (statusMessageText) statusMessageText.textContent = 'Bot hazır. Ayarları yapılandırıp başlatabilirsiniz.';
        
        // Load trading pairs
        loadTradingPairs();
        
    } else if (apiStatus.hasApiKeys && !apiStatus.isConnected) {
        // API error
        if (apiStatusIndicator) {
            apiStatusIndicator.innerHTML = `
                <i class="fas fa-times-circle"></i>
                <span>API bağlantı hatası</span>
            `;
            apiStatusIndicator.className = 'api-status-indicator error';
        }
        
        if (manageApiBtn) {
            manageApiBtn.style.display = 'inline-flex';
            manageApiBtn.textContent = 'API Anahtarlarını Düzenle';
        }
        
        if (statusMessageText) statusMessageText.textContent = apiStatus.message || 'API bağlantı hatası';
        
    } else {
        // No API keys
        if (apiStatusIndicator) {
            apiStatusIndicator.innerHTML = `
                <i class="fas fa-exclamation-triangle"></i>
                <span>API anahtarları gerekli</span>
            `;
            apiStatusIndicator.className = 'api-status-indicator error';
        }
        
        if (manageApiBtn) {
            manageApiBtn.style.display = 'inline-flex';
            manageApiBtn.textContent = 'API Anahtarlarını Ekle';
        }
        
        if (statusMessageText) statusMessageText.textContent = 'Bot\'u çalıştırmak için API anahtarlarınızı eklemelisiniz.';
    }
}

// Load trading pairs
async function loadTradingPairs() {
    try {
        const response = await makeAuthenticatedApiCall('/api/bot/trading-pairs');
        
        const symbolSelect = document.getElementById('symbol-select');
        if (symbolSelect && response) {
            symbolSelect.innerHTML = '';
            response.forEach(pair => {
                const option = document.createElement('option');
                option.value = pair.symbol;
                option.textContent = `${pair.baseAsset}/${pair.quoteAsset}`;
                symbolSelect.appendChild(option);
            });
            
            // Set default to BTCUSDT
            symbolSelect.value = 'BTCUSDT';
        }
        
    } catch (error) {
        console.error('Error loading trading pairs:', error);
    }
}

// Load payment and server info
async function loadPaymentAndServerInfo() {
    try {
        const appInfo = await window.configLoader.getAppInfo();
        
        // Update payment address
        const paymentAddressText = document.getElementById('payment-address-text');
        if (paymentAddressText) {
            paymentAddressText.textContent = appInfo.payment_address || 'Ödeme adresi yüklenemedi';
        }
        
        // Update payment amount
        const paymentAmount = document.getElementById('payment-amount');
        if (paymentAmount) {
            paymentAmount.textContent = `$${appInfo.bot_price || 15}/Ay`;
        }
        
        // Update server IPs
        const serverIpsText = document.getElementById('server-ips-text');
        if (serverIpsText && appInfo.server_ips) {
            serverIpsText.textContent = appInfo.server_ips.join(', ');
        }
        
        console.log('Payment and server info loaded');
        
    } catch (error) {
        console.error('Error loading payment info:', error);
    }
}

// Get bot status
async function getBotStatus() {
    try {
        console.log('Getting bot status...');
        
        const response = await makeAuthenticatedApiCall('/api/bot/status');
        
        const statusDot = document.getElementById('status-dot');
        const statusText = document.getElementById('status-text');
        const statusMessageText = document.getElementById('status-message-text');
        const startBotBtn = document.getElementById('start-bot-btn');
        const stopBotBtn = document.getElementById('stop-bot-btn');
        
        if (response.status && response.status.is_running) {
            // Bot running
            if (statusDot) statusDot.className = 'status-dot active';
            if (statusText) statusText.textContent = 'Çalışıyor';
            if (statusMessageText) statusMessageText.textContent = response.status.status_message || 'Bot aktif olarak çalışıyor';
            if (startBotBtn) startBotBtn.disabled = true;
            if (stopBotBtn) stopBotBtn.disabled = false;
        } else {
            // Bot stopped
            if (statusDot) statusDot.className = 'status-dot';
            if (statusText) statusText.textContent = 'Durduruldu';
            if (statusMessageText) statusMessageText.textContent = response.status?.status_message || 'Bot durduruldu';
            if (startBotBtn) startBotBtn.disabled = false;
            if (stopBotBtn) stopBotBtn.disabled = true;
        }
        
        console.log('Bot status loaded successfully');
        
    } catch (error) {
        console.error('Error getting bot status:', error);
    }
}

// Start bot
async function startBot() {
    try {
        const startBotBtn = document.getElementById('start-bot-btn');
        const statusMessageText = document.getElementById('status-message-text');
        
        if (startBotBtn) {
            startBotBtn.disabled = true;
            startBotBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Başlatılıyor...';
        }
        
        if (statusMessageText) statusMessageText.textContent = 'Bot başlatılıyor...';
        
        // Get form values
        const symbolSelect = document.getElementById('symbol-select');
        const timeframeSelect = document.getElementById('timeframe-select');
        const leverageSelect = document.getElementById('leverage-select');
        const orderSize = document.getElementById('order-size');
        const stopLoss = document.getElementById('stop-loss');
        const takeProfit = document.getElementById('take-profit');
        const maxDailyTrades = document.getElementById('max-daily-trades');
        const autoCompound = document.getElementById('auto-compound');
        const manualTrading = document.getElementById('manual-trading');
        const notificationsEnabled = document.getElementById('notifications-enabled');
        
        const botConfig = {
            symbol: symbolSelect?.value || 'BTCUSDT',
            timeframe: timeframeSelect?.value || '15m',
            leverage: parseInt(leverageSelect?.value || '10'),
            order_size: parseFloat(orderSize?.value || '35'),
            stop_loss: parseFloat(stopLoss?.value || '0.8'),
            take_profit: parseFloat(takeProfit?.value || '1.2'),
            max_daily_trades: parseInt(maxDailyTrades?.value || '10'),
            auto_compound: autoCompound?.checked || false,
            manual_trading: manualTrading?.checked || false,
            notifications_enabled: notificationsEnabled?.checked || true
        };
        
        console.log('Starting bot with config:', botConfig);
        
        const response = await makeAuthenticatedApiCall('/api/bot/start', {
            method: 'POST',
            body: JSON.stringify(botConfig)
        });
        
        if (response.success) {
            showNotification('Bot başarıyla başlatıldı!', 'success');
            await getBotStatus();
            startPeriodicUpdates();
        } else {
            throw new Error(response.message || 'Bot başlatılamadı');
        }
        
    } catch (error) {
        console.error('Bot start error:', error);
        showNotification(`Bot başlatma hatası: ${error.message}`, 'error');
        
        const startBotBtn = document.getElementById('start-bot-btn');
        if (startBotBtn) {
            startBotBtn.disabled = false;
            startBotBtn.innerHTML = '<i class="fas fa-play"></i> Bot\'u Başlat';
        }
    }
}

// Stop bot
async function stopBot() {
    try {
        const stopBotBtn = document.getElementById('stop-bot-btn');
        const statusMessageText = document.getElementById('status-message-text');
        
        if (stopBotBtn) {
            stopBotBtn.disabled = true;
            stopBotBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Durduruluyor...';
        }
        
        if (statusMessageText) statusMessageText.textContent = 'Bot durduruluyor...';
        
        console.log('Stopping bot...');
        
        const response = await makeAuthenticatedApiCall('/api/bot/stop', {
            method: 'POST'
        });
        
        if (response.success) {
            showNotification('Bot başarıyla durduruldu!', 'success');
            await getBotStatus();
            stopPeriodicUpdates();
        } else {
            throw new Error(response.message || 'Bot durdurulamadı');
        }
        
    } catch (error) {
        console.error('Bot stop error:', error);
        showNotification(`Bot durdurma hatası: ${error.message}`, 'error');
        
        const stopBotBtn = document.getElementById('stop-bot-btn');
        if (stopBotBtn) {
            stopBotBtn.disabled = false;
            stopBotBtn.innerHTML = '<i class="fas fa-stop"></i> Bot\'u Durdur';
        }
    }
}

// Close position
async function closePosition(symbol, positionSide) {
    if (!confirm(`${symbol} ${positionSide} pozisyonunu kapatmak istediğinizden emin misiniz?`)) {
        return;
    }

    try {
        console.log(`Closing position: ${symbol} ${positionSide}`);
        
        const response = await makeAuthenticatedApiCall('/api/user/close-position', {
            method: 'POST',
            body: JSON.stringify({ symbol, positionSide })
        });

        if (response.success) {
            showNotification('Pozisyon başarıyla kapatıldı!', 'success');
            // Refresh data
            await loadAllDashboardData();
            await getBotStatus();
        } else {
            throw new Error(response.message || 'Pozisyon kapatılamadı');
        }
    } catch (error) {
        console.error('Position close error:', error);
        showNotification(`Pozisyon kapatma hatası: ${error.message}`, 'error');
    }
}

// API Management
async function openApiModal() {
    const apiModal = document.getElementById('api-modal');
    if (apiModal) {
        apiModal.classList.add('show');

        // Clear inputs
        const apiKeyInput = document.getElementById('api-key');
        const apiSecretInput = document.getElementById('api-secret');
        const apiTestnetCheckbox = document.getElementById('api-testnet');

        if (apiKeyInput) apiKeyInput.value = '';
        if (apiSecretInput) apiSecretInput.placeholder = 'API Secret';
        if (apiTestnetCheckbox) apiTestnetCheckbox.checked = false;

        try {
            // Load existing API info
            const apiInfo = await makeAuthenticatedApiCall('/api/user/api-info');

            if (apiInfo.hasKeys) {
                if (apiKeyInput) apiKeyInput.value = apiInfo.maskedApiKey || '';
                if (apiTestnetCheckbox) apiTestnetCheckbox.checked = apiInfo.is_testnet || false;
                if (apiSecretInput) apiSecretInput.placeholder = 'Mevcut secret korunuyor (değiştirmek için yeni girin)';
            }

        } catch (error) {
            console.error('API keys load error:', error);
            showNotification('API key bilgileri yüklenirken hata oluştu. Lütfen tekrar deneyin.', 'error');
        }
    }
}

function closeApiModal() {
    const apiModal = document.getElementById('api-modal');
    if (apiModal) {
        apiModal.classList.remove('show');
        
        const apiForm = document.getElementById('api-form');
        if (apiForm) apiForm.reset();
        
        const apiTestResult = document.getElementById('api-test-result');
        if (apiTestResult) apiTestResult.style.display = 'none';
    }
}

// Save API keys
async function saveApiKeys(event) {
    event.preventDefault();
    
    const apiKey = document.getElementById('api-key');
    const apiSecret = document.getElementById('api-secret');
    const apiTestnet = document.getElementById('api-testnet');
    const saveApiBtn = document.getElementById('save-api-btn');
    const apiTestResult = document.getElementById('api-test-result');
    
    if (!apiKey?.value.trim() || !apiSecret?.value.trim()) {
        showNotification('API Key ve Secret alanları gerekli', 'error');
        return;
    }
    
    try {
        if (saveApiBtn) {
            saveApiBtn.disabled = true;
            saveApiBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Test ediliyor...';
        }
        
        const response = await makeAuthenticatedApiCall('/api/user/api-keys', {
            method: 'POST',
            body: JSON.stringify({
                api_key: apiKey.value.trim(),
                api_secret: apiSecret.value.trim(),
                testnet: apiTestnet?.checked || false
            })
        });
        
        if (response.success) {
            if (apiTestResult) {
                apiTestResult.style.display = 'block';
                apiTestResult.className = 'api-test-result success';
                apiTestResult.innerHTML = `
                    <i class="fas fa-check-circle"></i>
                    API anahtarları başarıyla kaydedildi! Balance: ${formatCurrency(response.balance)}
                `;
            }
            
            showNotification('API anahtarları başarıyla kaydedildi!', 'success');
            
            setTimeout(() => {
                closeApiModal();
                // Refresh dashboard data
                loadAllDashboardData();
            }, 2000);
            
        } else {
            throw new Error(response.message || 'API anahtarları kaydedilemedi');
        }
        
    } catch (error) {
        console.error('API keys save error:', error);
        
        if (apiTestResult) {
            apiTestResult.style.display = 'block';
            apiTestResult.className = 'api-test-result error';
            apiTestResult.innerHTML = `
                <i class="fas fa-times-circle"></i>
                Hata: ${error.message}
            `;
        }
        
        showNotification(`API kaydı başarısız: ${error.message}`, 'error');
        
    } finally {
        if (saveApiBtn) {
            saveApiBtn.disabled = false;
            saveApiBtn.innerHTML = '<i class="fas fa-save"></i> Kaydet ve Test Et';
        }
    }
}

// Copy to clipboard
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showNotification('Kopyalandı!', 'success', 2000);
    } catch (error) {
        console.error('Copy failed:', error);
        showNotification('Kopyalama başarısız', 'error');
    }
}

// Purchase modal
function openPurchaseModal() {
    const purchaseModal = document.getElementById('purchase-modal');
    if (purchaseModal) purchaseModal.classList.add('show');
}

function closePurchaseModal() {
    const purchaseModal = document.getElementById('purchase-modal');
    if (purchaseModal) {
        purchaseModal.classList.remove('show');
        const transactionHash = document.getElementById('transaction-hash');
        if (transactionHash) transactionHash.value = '';
    }
}

// Support modal
function openSupportModal() {
    const supportModal = document.getElementById('support-modal');
    if (supportModal) supportModal.classList.add('show');
}

function closeSupportModal() {
    const supportModal = document.getElementById('support-modal');
    if (supportModal) {
        supportModal.classList.remove('show');
        const supportForm = document.getElementById('support-form');
        if (supportForm) supportForm.reset();
    }
}

// Send support message
async function sendSupportMessage() {
    const supportSubject = document.getElementById('support-subject');
    const supportMessage = document.getElementById('support-message');
    const sendSupportBtn = document.getElementById('send-support-btn');
    
    if (!supportSubject?.value || !supportMessage?.value.trim()) {
        showNotification('Lütfen konu ve mesaj alanlarını doldurun', 'error');
        return;
    }
    
    try {
        if (sendSupportBtn) {
            sendSupportBtn.disabled = true;
            sendSupportBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Gönderiliyor...';
        }
        
        const messageData = {
            user_id: currentUser.uid,
            user_email: currentUser.email,
            subject: supportSubject.value,
            message: supportMessage.value.trim(),
            created_at: firebase.database.ServerValue.TIMESTAMP,
            status: 'open'
        };
        
        // Send to Firebase
        const supportRef = database.ref('support_messages');
        await supportRef.push(messageData);
        
        showNotification('Destek talebiniz gönderildi!', 'success');
        closeSupportModal();
        
    } catch (error) {
        console.error('Support message error:', error);
        showNotification('Destek talebi gönderilemedi', 'error');
    } finally {
        if (sendSupportBtn) {
            sendSupportBtn.disabled = false;
            sendSupportBtn.innerHTML = '<i class="fas fa-paper-plane"></i> Destek Talebi Gönder';
        }
    }
}

// Confirm payment
async function confirmPayment() {
    const transactionHash = document.getElementById('transaction-hash');
    const confirmPaymentBtn = document.getElementById('confirm-payment-btn');
    
    if (!transactionHash?.value.trim()) {
        showNotification('Lütfen işlem hash\'ini girin', 'error');
        return;
    }
    
    try {
        if (confirmPaymentBtn) {
            confirmPaymentBtn.disabled = true;
            confirmPaymentBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Bildiriliyor...';
        }
        
        const paymentData = {
            user_id: currentUser.uid,
            user_email: currentUser.email,
            transaction_hash: transactionHash.value.trim(),
            amount: 15,
            currency: 'USDT',
            created_at: firebase.database.ServerValue.TIMESTAMP,
            status: 'pending'
        };
        
        // Send to Firebase
        const paymentsRef = database.ref('payment_notifications');
        await paymentsRef.push(paymentData);
        
        showNotification('Ödeme bildirimi gönderildi! Admin onayından sonra aboneliğiniz aktif olacak.', 'success');
        closePurchaseModal();
        
    } catch (error) {
        console.error('Payment notification error:', error);
        showNotification('Ödeme talebi gönderilemedi', 'error');
    } finally {
        if (confirmPaymentBtn) {
            confirmPaymentBtn.disabled = false;
            confirmPaymentBtn.innerHTML = '<i class="fas fa-check"></i> Ödeme Bildir';
        }
    }
}

// Periodic updates
let updateInterval = null;

function startPeriodicUpdates() {
    if (updateInterval) clearInterval(updateInterval);
    
    updateInterval = setInterval(async () => {
        try {
            // ✅ Optimized: Sadece bot status al, dashboard verilerini tekrar yükleme
            await getBotStatus();
            
            // 5 dakikada bir dashboard verilerini yenile
            const now = new Date().getMinutes();
            if (now % 5 === 0) {
                await loadAllDashboardData();
            }
        } catch (error) {
            console.error('Periodic update error:', error);
        }
    }, 30000); // 30 seconds
}

function stopPeriodicUpdates() {
    if (updateInterval) {
        clearInterval(updateInterval);
        updateInterval = null;
    }
}

// Mobile menu
function toggleMobileMenu() {
    const mobileMenu = document.getElementById('mobile-menu');
    if (mobileMenu) {
        mobileMenu.classList.toggle('show');
    }
}

function closeMobileMenu() {
    const mobileMenu = document.getElementById('mobile-menu');
    if (mobileMenu) {
        mobileMenu.classList.remove('show');
    }
}

// Logout
async function logout() {
    if (!confirm('Çıkış yapmak istediğinizden emin misiniz?')) return;
    
    try {
        // Clear intervals
        if (tokenRefreshInterval) {
            clearInterval(tokenRefreshInterval);
            tokenRefreshInterval = null;
        }
        
        await auth.signOut();
        stopPeriodicUpdates();
        authToken = null;
        currentUser = null;
        window.location.href = '/login.html';
    } catch (error) {
        console.error('Logout error:', error);
        showNotification('Çıkış yapılırken hata oluştu', 'error');
    }
}

// Event listeners
function setupEventListeners() {
    // Mobile menu
    const hamburgerMenu = document.getElementById('hamburger-menu');
    const mobileMenuClose = document.getElementById('mobile-menu-close');
    
    if (hamburgerMenu) hamburgerMenu.addEventListener('click', toggleMobileMenu);
    if (mobileMenuClose) mobileMenuClose.addEventListener('click', closeMobileMenu);
    
    // API modal
    const manageApiBtn = document.getElementById('manage-api-btn');
    const mobileApiBtn = document.getElementById('mobile-api-btn');
    const apiModalClose = document.getElementById('api-modal-close');
    const cancelApiBtn = document.getElementById('cancel-api-btn');
    const apiForm = document.getElementById('api-form');
    
    if (manageApiBtn) manageApiBtn.addEventListener('click', openApiModal);
    if (mobileApiBtn) mobileApiBtn.addEventListener('click', () => { openApiModal(); closeMobileMenu(); });
    if (apiModalClose) apiModalClose.addEventListener('click', closeApiModal);
    if (cancelApiBtn) cancelApiBtn.addEventListener('click', closeApiModal);
    if (apiForm) apiForm.addEventListener('submit', saveApiKeys);
    
    // Bot controls
    const startBotBtn = document.getElementById('start-bot-btn');
    const stopBotBtn = document.getElementById('stop-bot-btn');
    
    if (startBotBtn) startBotBtn.addEventListener('click', startBot);
    if (stopBotBtn) stopBotBtn.addEventListener('click', stopBot);
    
    // Purchase modal
    const mobilePurchaseBtn = document.getElementById('mobile-purchase-btn');
    const purchaseModalClose = document.getElementById('purchase-modal-close');
    const cancelPurchaseBtn = document.getElementById('cancel-purchase-btn');
    const confirmPaymentBtn = document.getElementById('confirm-payment-btn');
    
    if (mobilePurchaseBtn) mobilePurchaseBtn.addEventListener('click', () => { openPurchaseModal(); closeMobileMenu(); });
    if (purchaseModalClose) purchaseModalClose.addEventListener('click', closePurchaseModal);
    if (cancelPurchaseBtn) cancelPurchaseBtn.addEventListener('click', closePurchaseModal);
    if (confirmPaymentBtn) confirmPaymentBtn.addEventListener('click', confirmPayment);
    
    // Support modal
    const mobileSupportBtn = document.getElementById('mobile-support-btn');
    const supportModalClose = document.getElementById('support-modal-close');
    const cancelSupportBtn = document.getElementById('cancel-support-btn');
    const sendSupportBtn = document.getElementById('send-support-btn');
    
    if (mobileSupportBtn) mobileSupportBtn.addEventListener('click', () => { openSupportModal(); closeMobileMenu(); });
    if (supportModalClose) supportModalClose.addEventListener('click', closeSupportModal);
    if (cancelSupportBtn) cancelSupportBtn.addEventListener('click', closeSupportModal);
    if (sendSupportBtn) sendSupportBtn.addEventListener('click', sendSupportMessage);
    
    // Copy buttons
    const copyIpsBtn = document.getElementById('copy-ips-btn');
    const copyAddressBtn = document.getElementById('copy-address-btn');
    
    if (copyIpsBtn) {
        copyIpsBtn.addEventListener('click', () => {
            const serverIpsText = document.getElementById('server-ips-text');
            if (serverIpsText) copyToClipboard(serverIpsText.textContent);
        });
    }
    
    if (copyAddressBtn) {
        copyAddressBtn.addEventListener('click', () => {
            const paymentAddressText = document.getElementById('payment-address-text');
            if (paymentAddressText) copyToClipboard(paymentAddressText.textContent);
        });
    }
    
    // Refresh buttons - Optimized
    const refreshAccountBtn = document.getElementById('refresh-account-btn');
    const refreshPositionsBtn = document.getElementById('refresh-positions-btn');
    const refreshActivityBtn = document.getElementById('refresh-activity-btn');
    
    // ✅ Tüm refresh butonları tek dashboard data çağrısı yapar
    if (refreshAccountBtn) refreshAccountBtn.addEventListener('click', loadAllDashboardData);
    if (refreshPositionsBtn) refreshPositionsBtn.addEventListener('click', loadAllDashboardData);
    if (refreshActivityBtn) refreshActivityBtn.addEventListener('click', loadAllDashboardData);
    
    // Logout buttons
    const logoutBtn = document.getElementById('logout-btn');
    const mobileLogoutBtn = document.getElementById('mobile-logout-btn');
    
    if (logoutBtn) logoutBtn.addEventListener('click', logout);
    if (mobileLogoutBtn) mobileLogoutBtn.addEventListener('click', () => { logout(); closeMobileMenu(); });
    
    // Settings button
    const settingsBtn = document.getElementById('settings-btn');
    if (settingsBtn) {
        settingsBtn.addEventListener('click', () => {
            showNotification('Ayarlar sayfası geliştirilmekte...', 'info');
        });
    }
    
    // Toast close
    const toastClose = document.getElementById('toast-close');
    if (toastClose) {
        toastClose.addEventListener('click', () => {
            const toast = document.getElementById('toast');
            if (toast) toast.classList.remove('show');
        });
    }
    
    // Modal backdrop close
    const modals = document.querySelectorAll('.modal');
    modals.forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.classList.remove('show');
            }
        });
    });
    
    // ✅ Setup smart recommendations
    setupSmartRecommendations();
}

// Initialize dashboard
async function initializeDashboard() {
    try {
        console.log('Initializing dashboard...');
        
        // Initialize Firebase
        if (!(await initializeFirebase())) {
            throw new Error('Firebase initialization failed');
        }
        
        // Check authentication
        auth.onAuthStateChanged(async (user) => {
            if (user) {
                currentUser = user;
                console.log('User authenticated:', user.uid);
                
                try {
                    // Get Firebase ID token for backend authentication
                    authToken = await user.getIdToken(true);
                    console.log('Auth token obtained');
                    
                    // Setup automatic token refresh
                    setupTokenRefresh();
                    
                    // ✅ OPTIMIZED: Tek API çağrısı ile tüm veriler
                    await loadAllDashboardData();
                    
                    // Bot status ve payment info
                    await getBotStatus();
                    await loadPaymentAndServerInfo();
                    
                    // Setup event listeners
                    setupEventListeners();
                    
                    // Hide loading and show dashboard
                    const loadingScreen = document.getElementById('loading-screen');
                    const dashboard = document.getElementById('dashboard');
                    
                    if (loadingScreen) loadingScreen.style.display = 'none';
                    if (dashboard) dashboard.classList.remove('hidden');
                    
                    console.log('✅ Dashboard fully initialized with optimized loading');
                    
                } catch (error) {
                    console.error('Dashboard data loading failed:', error);
                    showNotification('Dashboard verileri yüklenemedi', 'error');
                }
            } else {
                console.log('User not authenticated, redirecting to login...');
                if (tokenRefreshInterval) {
                    clearInterval(tokenRefreshInterval);
                    tokenRefreshInterval = null;
                }
                window.location.href = '/login.html';
            }
        });
        
    } catch (error) {
        console.error('Dashboard initialization failed:', error);
        
        const loadingScreen = document.getElementById('loading-screen');
        if (loadingScreen) {
            loadingScreen.innerHTML = `
                <div class="loading-content">
                    <div class="loading-logo">
                        <i class="fas fa-exclamation-triangle" style="color: var(--danger-color);"></i>
                        <span>Hata</span>
                    </div>
                    <p>Dashboard başlatılırken hata oluştu</p>
                    <button class="btn btn-primary" onclick="location.reload()">Tekrar Dene</button>
                </div>
            `;
        }
    }
}

// Start the application
document.addEventListener('DOMContentLoaded', initializeDashboard);

// Global functions for HTML onclick events
window.startBot = startBot;
window.stopBot = stopBot;
window.closePosition = closePosition;
window.openApiModal = openApiModal;
window.closeApiModal = closeApiModal;
window.openPurchaseModal = openPurchaseModal;
window.closePurchaseModal = closePurchaseModal;
window.openSupportModal = openSupportModal;
window.closeSupportModal = closeSupportModal;
window.copyToClipboard = copyToClipboard;
window.loadAllDashboardData = loadAllDashboardData;  // ✅ Yeni optimized function
window.toggleAdvancedSettings = toggleAdvancedSettings;
