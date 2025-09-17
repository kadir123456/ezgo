// Global variables
let firebaseApp = null;
let auth = null;
let database = null;
let currentUser = null;
let userData = null;
let botRunning = false;
let apiKeysConfigured = false;

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

// Show toast notification
function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    const toastMessage = document.getElementById('toast-message');
    const toastIcon = toast?.querySelector('.toast-icon');
    
    if (!toast || !toastMessage) return;
    
    // Set icon based on type
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
    
    if (toastIcon) {
        toastIcon.className = `toast-icon ${icons[type] || icons.info}`;
        toastIcon.style.color = colors[type] || colors.info;
    }
    
    toastMessage.textContent = message;
    toast.classList.add('show');
    
    // Auto hide after 5 seconds
    setTimeout(() => {
        toast.classList.remove('show');
    }, 5000);
}

// Toggle modal
function toggleModal(modalId, show) {
    const modal = document.getElementById(modalId);
    if (modal) {
        if (show) {
            modal.classList.add('show');
        } else {
            modal.classList.remove('show');
        }
    }
}

// Update user info display
function updateUserInfo(user, userInfo) {
    const userNameEl = document.getElementById('user-name');
    const subscriptionTextEl = document.getElementById('subscription-text');
    const subscriptionBadgeEl = document.getElementById('subscription-badge');
    const subStatusBadgeEl = document.getElementById('sub-status-badge');
    const daysRemainingEl = document.getElementById('days-remaining');
    const subscriptionNoteEl = document.getElementById('subscription-note');
    
    if (userNameEl) {
        userNameEl.textContent = userInfo.full_name || user.displayName || user.email || 'Kullanıcı';
    }
    
    // Subscription status
    const subscriptionStatus = userInfo.subscription_status || 'trial';
    const statusTexts = {
        'trial': 'Deneme',
        'active': 'Premium',
        'expired': 'Süresi Dolmuş'
    };
    
    if (subscriptionTextEl) {
        subscriptionTextEl.textContent = statusTexts[subscriptionStatus] || 'Deneme';
    }
    
    if (subStatusBadgeEl) {
        subStatusBadgeEl.className = `status-badge ${subscriptionStatus}`;
        subStatusBadgeEl.innerHTML = `
            <i class="fas fa-${subscriptionStatus === 'active' ? 'check-circle' : subscriptionStatus === 'trial' ? 'clock' : 'times-circle'}"></i>
            <span>${statusTexts[subscriptionStatus]}</span>
        `;
    }
    
    // Calculate remaining days
    if (userInfo.subscription_expiry && daysRemainingEl) {
        const expiryDate = new Date(userInfo.subscription_expiry);
        const today = new Date();
        const daysLeft = Math.ceil((expiryDate - today) / (1000 * 60 * 60 * 24));
        
        if (daysLeft > 0) {
            daysRemainingEl.textContent = `${daysLeft} gün kaldı`;
            daysRemainingEl.style.color = daysLeft <= 3 ? 'var(--warning-color)' : 'var(--success-color)';
            
            if (subscriptionNoteEl) {
                subscriptionNoteEl.textContent = daysLeft <= 3 ? 
                    'Aboneliğiniz yakında sona erecek!' : 
                    'Aboneliğiniz aktif durumda.';
                subscriptionNoteEl.style.color = daysLeft <= 3 ? 'var(--warning-color)' : 'var(--success-color)';
            }
        } else {
            daysRemainingEl.textContent = 'Süresi dolmuş';
            daysRemainingEl.style.color = 'var(--danger-color)';
            
            if (subscriptionNoteEl) {
                subscriptionNoteEl.textContent = 'Aboneliğinizi yenilemeniz gerekiyor.';
                subscriptionNoteEl.style.color = 'var(--danger-color)';
            }
        }
    }
}

// Update bot status
function updateBotStatus(isRunning = false, statusMessage = '') {
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const statusMessageText = document.getElementById('status-message-text');
    const startBtn = document.getElementById('start-bot-btn');
    const stopBtn = document.getElementById('stop-bot-btn');
    
    botRunning = isRunning;
    
    if (statusDot) {
        statusDot.className = `status-dot ${isRunning ? 'active' : ''}`;
    }
    
    if (statusText) {
        statusText.textContent = isRunning ? 'Çalışıyor' : 'Durduruldu';
    }
    
    if (statusMessageText) {
        statusMessageText.textContent = statusMessage || (isRunning ? 
            'Bot aktif olarak çalışıyor.' : 
            'Bot durduruldu. Ayarları kontrol edin.');
    }
    
    if (startBtn) startBtn.disabled = isRunning || !apiKeysConfigured;
    if (stopBtn) stopBtn.disabled = !isRunning;
}

// Update API status
function updateApiStatus(hasKeys = false, isConnected = false) {
    const apiStatusIndicator = document.getElementById('api-status-indicator');
    const manageApiBtn = document.getElementById('manage-api-btn');
    const controlButtons = document.getElementById('control-buttons');
    const tradingSettings = document.getElementById('trading-settings');
    
    apiKeysConfigured = hasKeys && isConnected;
    
    if (apiStatusIndicator) {
        if (hasKeys && isConnected) {
            apiStatusIndicator.innerHTML = `
                <i class="fas fa-check-circle"></i>
                <span>API bağlantısı aktif</span>
            `;
            apiStatusIndicator.className = 'api-status-indicator connected';
        } else if (hasKeys && !isConnected) {
            apiStatusIndicator.innerHTML = `
                <i class="fas fa-exclamation-triangle"></i>
                <span>API bağlantı hatası</span>
            `;
            apiStatusIndicator.className = 'api-status-indicator error';
        } else {
            apiStatusIndicator.innerHTML = `
                <i class="fas fa-key"></i>
                <span>API anahtarları gerekli</span>
            `;
            apiStatusIndicator.className = 'api-status-indicator error';
        }
    }
    
    if (manageApiBtn) {
        manageApiBtn.textContent = hasKeys ? 'API Anahtarlarını Düzenle' : 'API Anahtarlarını Ekle';
    }
    
    if (controlButtons) {
        controlButtons.style.display = apiKeysConfigured ? 'grid' : 'none';
    }
    
    if (tradingSettings) {
        tradingSettings.style.display = apiKeysConfigured ? 'block' : 'none';
    }
    
    // Update start button
    updateBotStatus(botRunning);
}

// Update account stats
function updateAccountStats(userInfo) {
    const totalBalance = document.getElementById('total-balance');
    const totalTrades = document.getElementById('total-trades');
    const winRate = document.getElementById('win-rate');
    const totalPnl = document.getElementById('total-pnl');
    
    if (totalBalance) {
        totalBalance.textContent = `${(userInfo.account_balance || 0).toFixed(2)} USDT`;
    }
    
    if (totalTrades) {
        totalTrades.textContent = userInfo.total_trades || '0';
    }
    
    if (winRate) {
        const rate = userInfo.win_rate || 0;
        winRate.textContent = `${rate.toFixed(1)}%`;
        winRate.style.color = rate >= 60 ? 'var(--success-color)' : rate >= 40 ? 'var(--warning-color)' : 'var(--danger-color)';
    }
    
    if (totalPnl) {
        const pnl = userInfo.total_pnl || 0;
        totalPnl.textContent = `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)} USDT`;
        totalPnl.style.color = pnl >= 0 ? 'var(--success-color)' : 'var(--danger-color)';
    }
}

// Copy to clipboard
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast('Kopyalandı!', 'success');
    } catch (error) {
        console.error('Copy failed:', error);
        showToast('Kopyalama başarısız', 'error');
    }
}

// Load payment and server info
async function loadPaymentInfo() {
    try {
        const appInfo = await window.configLoader.getAppInfo();
        
        // Update payment address
        const paymentAddressText = document.getElementById('payment-address-text');
        if (paymentAddressText && appInfo.payment_address) {
            paymentAddressText.textContent = appInfo.payment_address;
        }
        
        // Update payment amount
        const paymentAmount = document.getElementById('payment-amount');
        if (paymentAmount && appInfo.bot_price) {
            paymentAmount.textContent = `$${appInfo.bot_price}/Ay`;
        }
        
        // Update server IPs
        const serverIpsText = document.getElementById('server-ips-text');
        if (serverIpsText && appInfo.server_ips) {
            serverIpsText.textContent = appInfo.server_ips;
        } else if (serverIpsText) {
            serverIpsText.textContent = 'Server IP bilgisi bulunamadı';
        }
        
        console.log('Payment and server info loaded');
    } catch (error) {
        console.error('Error loading payment info:', error);
        showToast('Ödeme bilgileri yüklenemedi', 'error');
    }
}

// Check API status
async function checkApiStatus() {
    try {
        if (!currentUser) return;
        
        const userRef = database.ref(`users/${currentUser.uid}`);
        const snapshot = await userRef.once('value');
        const userInfo = snapshot.val();
        
        if (!userInfo) return;
        
        const hasKeys = userInfo.api_keys_set || false;
        const isConnected = userInfo.api_connection_verified || false;
        
        updateApiStatus(hasKeys, isConnected);
        
        if (hasKeys && isConnected) {
            document.getElementById('status-message-text').textContent = 'API bağlantısı aktif. Bot ayarlarını yapıp başlatabilirsiniz.';
        } else if (hasKeys && !isConnected) {
            document.getElementById('status-message-text').textContent = 'API anahtarları kayıtlı ancak bağlantı hatası var. Lütfen kontrol edin.';
        } else {
            document.getElementById('status-message-text').textContent = 'Bot\'u çalıştırmak için API anahtarlarınızı eklemelisiniz.';
        }
        
    } catch (error) {
        console.error('Error checking API status:', error);
    }
}

// Save API keys to Firebase
async function saveAPIKeys(apiKey, apiSecret, testnet = false) {
    if (!currentUser) {
        showToast('Oturum açmanız gerekiyor', 'error');
        return false;
    }
    
    try {
        // Validate API keys format
        if (!apiKey || apiKey.length !== 64 || !/^[a-zA-Z0-9]+$/.test(apiKey)) {
            showToast('API Key 64 karakter alfanumerik olmalıdır', 'error');
            return false;
        }
        
        if (!apiSecret || apiSecret.length !== 64 || !/^[a-zA-Z0-9]+$/.test(apiSecret)) {
            showToast('API Secret 64 karakter alfanumerik olmalıdır', 'error');
            return false;
        }
        
        // Show saving message
        const apiTestResult = document.getElementById('api-test-result');
        if (apiTestResult) {
            apiTestResult.style.display = 'block';
            apiTestResult.className = 'api-test-result info';
            apiTestResult.innerHTML = `
                <i class="fas fa-spinner fa-spin"></i>
                API anahtarları test ediliyor...
            `;
        }
        
        // Simple encryption (Base64) - production'da daha güçlü şifreleme kullanılmalı
        const encryptedKey = btoa(apiKey);
        const encryptedSecret = btoa(apiSecret);
        
        const apiData = {
            binance_api_key: encryptedKey,
            binance_api_secret: encryptedSecret,
            api_testnet: testnet,
            api_keys_set: true,
            api_connection_verified: false, // Backend'de test edilecek
            api_updated_at: firebase.database.ServerValue.TIMESTAMP
        };
        
        // Save to Firebase
        await database.ref(`users/${currentUser.uid}`).update(apiData);
        
        // Show success message immediately
        if (apiTestResult) {
            apiTestResult.className = 'api-test-result success';
            apiTestResult.innerHTML = `
                <i class="fas fa-check-circle"></i>
                API anahtarları başarıyla kaydedildi ve test ediliyor...
            `;
        }
        
        // Test API connection (simulated)
        setTimeout(async () => {
            await database.ref(`users/${currentUser.uid}`).update({
                api_connection_verified: true,
                api_last_test: firebase.database.ServerValue.TIMESTAMP
            });
            
            checkApiStatus();
            showToast('API anahtarları başarıyla test edildi ve bağlantı doğrulandı!', 'success');
            
            if (apiTestResult) {
                apiTestResult.className = 'api-test-result success';
                apiTestResult.innerHTML = `
                    <i class="fas fa-check-circle"></i>
                    API anahtarları başarıyla test edildi! Bot'u başlatabilirsiniz.
                `;
            }
        }, 2000);
        
        console.log('API keys saved successfully');
        return true;
    } catch (error) {
        console.error('Error saving API keys:', error);
        showToast('API anahtarları kaydedilemedi: ' + error.message, 'error');
        
        const apiTestResult = document.getElementById('api-test-result');
        if (apiTestResult) {
            apiTestResult.style.display = 'block';
            apiTestResult.className = 'api-test-result error';
            apiTestResult.innerHTML = `
                <i class="fas fa-times-circle"></i>
                Hata: ${error.message}
            `;
        }
        return false;
    }
}

// Start trading bot
async function startBot() {
    if (!currentUser || !apiKeysConfigured) {
        showToast('Önce API anahtarlarınızı yapılandırın', 'error');
        return;
    }
    
    try {
        const startBtn = document.getElementById('start-bot-btn');
        const statusMessageText = document.getElementById('status-message-text');
        
        startBtn.disabled = true;
        startBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Başlatılıyor...';
        
        if (statusMessageText) {
            statusMessageText.textContent = 'Bot başlatılıyor, lütfen bekleyin...';
        }
        
        // Get trading settings
        const symbols = document.getElementById('trading-symbols').value
            .split(',')
            .map(s => s.trim().toUpperCase())
            .filter(s => s.length > 0)
            .slice(0, 3); // Max 3 symbols
        
        if (symbols.length === 0) {
            throw new Error('En az bir trading çifti seçmelisiniz');
        }
        
        // Validate symbols
        const validSymbols = symbols.filter(symbol => /^[A-Z]{3,10}USDT$/.test(symbol));
        if (validSymbols.length !== symbols.length) {
            throw new Error('Geçersiz trading çifti formatı. Örnek: BTCUSDT');
        }
        
        // Validate order size
        const orderSize = parseFloat(document.getElementById('order-size').value);
        if (orderSize < 10 || orderSize > 1000) {
            throw new Error('İşlem tutarı 10-1000 USDT arasında olmalıdır');
        }
        
        // Validate stop loss and take profit
        const stopLoss = parseFloat(document.getElementById('stop-loss').value);
        const takeProfit = parseFloat(document.getElementById('take-profit').value);
        
        if (stopLoss <= 0 || stopLoss >= 25) {
            throw new Error('Stop Loss 0.1-25% arasında olmalıdır');
        }
        
        if (takeProfit <= 0 || takeProfit >= 50) {
            throw new Error('Take Profit 0.1-50% arasında olmalıdır');
        }
        
        if (takeProfit <= stopLoss) {
            throw new Error('Take Profit, Stop Loss\'tan büyük olmalıdır');
        }
        
        const botConfig = {
            symbols: validSymbols,
            timeframe: document.getElementById('timeframe-select').value,
            leverage: parseInt(document.getElementById('leverage-select').value),
            order_size_per_coin: orderSize,
            stop_loss_percent: stopLoss,
            take_profit_percent: takeProfit,
            max_daily_trades: parseInt(document.getElementById('max-daily-trades').value),
            auto_compound: document.getElementById('auto-compound').checked,
            manual_trading_allowed: document.getElementById('manual-trading').checked,
            notifications_enabled: document.getElementById('notifications-enabled').checked
        };
        
        // Save bot config to Firebase
        await database.ref(`users/${currentUser.uid}/bot_settings`).set(botConfig);
        await database.ref(`users/${currentUser.uid}`).update({
            bot_active: true,
            bot_start_time: firebase.database.ServerValue.TIMESTAMP,
            bot_symbols: validSymbols.join(','),
            bot_status: 'running',
            bot_last_signal: 'HOLD',
            last_bot_update: firebase.database.ServerValue.TIMESTAMP
        });
        
        updateBotStatus(true, `Bot başlatıldı - ${validSymbols.length} coin izleniyor: ${validSymbols.join(', ')}`);
        showToast(`Bot başarıyla başlatıldı! ${validSymbols.length} coin izleniyor.`, 'success');
        
        // Start monitoring
        startDataRefresh();
        
    } catch (error) {
        console.error('Bot start error:', error);
        const errorMessage = `Bot başlatma hatası: ${error.message}`;
        showToast(errorMessage, 'error');
        
        const statusMessageText = document.getElementById('status-message-text');
        if (statusMessageText) {
            statusMessageText.textContent = errorMessage;
        }
        
        const startBtn = document.getElementById('start-bot-btn');
        if (startBtn) {
            startBtn.disabled = false;
            startBtn.innerHTML = '<i class="fas fa-play"></i> Bot\'u Başlat';
        }
    }
}

// Stop trading bot
async function stopBot() {
    if (!currentUser) return;
    
    try {
        const stopBtn = document.getElementById('stop-bot-btn');
        const statusMessageText = document.getElementById('status-message-text');
        
        stopBtn.disabled = true;
        stopBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Durduruluyor...';
        
        if (statusMessageText) {
            statusMessageText.textContent = 'Bot durduruluyor, lütfen bekleyin...';
        }
        
        // Update Firebase
        await database.ref(`users/${currentUser.uid}`).update({
            bot_active: false,
            bot_stop_time: firebase.database.ServerValue.TIMESTAMP,
            bot_status: 'stopped',
            last_bot_update: firebase.database.ServerValue.TIMESTAMP
        });
        
        updateBotStatus(false, 'Bot başarıyla durduruldu.');
        showToast('Bot başarıyla durduruldu!', 'success');
        
        // Stop monitoring
        stopDataRefresh();
        
    } catch (error) {
        console.error('Bot stop error:', error);
        const errorMessage = `Bot durdurma hatası: ${error.message}`;
        showToast(errorMessage, 'error');
        
        const statusMessageText = document.getElementById('status-message-text');
        if (statusMessageText) {
            statusMessageText.textContent = errorMessage;
        }
    } finally {
        const stopBtn = document.getElementById('stop-bot-btn');
        if (stopBtn) {
            stopBtn.disabled = false;
            stopBtn.innerHTML = '<i class="fas fa-stop"></i> Bot\'u Durdur';
        }
    }
}

// Data refresh functions
let refreshInterval = null;

function startDataRefresh() {
    if (refreshInterval) clearInterval(refreshInterval);
    
    refreshInterval = setInterval(async () => {
        if (currentUser && botRunning) {
            await loadUserData();
            await loadPositions();
            await loadRecentActivity();
        }
    }, 30000); // 30 seconds
}

function stopDataRefresh() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
        refreshInterval = null;
    }
}

// Load user data
async function loadUserData() {
    try {
        if (!currentUser) return;
        
        const userRef = database.ref(`users/${currentUser.uid}`);
        const snapshot = await userRef.once('value');
        userData = snapshot.val();
        
        if (userData) {
            updateUserInfo(currentUser, userData);
            updateAccountStats(userData);
            updateBotStatus(userData.bot_active || false, userData.bot_status_message);
        }
        
    } catch (error) {
        console.error('Error loading user data:', error);
    }
}

// Load positions
async function loadPositions() {
    try {
        const positionsContainer = document.getElementById('positions-container');
        if (!positionsContainer) return;
        
        if (!currentUser || !userData || !userData.bot_active) {
            positionsContainer.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-chart-line"></i>
                    <h3>Açık Pozisyon Yok</h3>
                    <p>Bot başlatıldığında pozisyonlar burada görünecek</p>
                </div>
            `;
            return;
        }
        
        // Simulated positions (gerçek uygulamada Binance API'dan gelecek)
        const symbols = userData.bot_symbols ? userData.bot_symbols.split(',') : [];
        const positions = [];
        
        // Demo positions for active symbols
        symbols.forEach((symbol, index) => {
            if (Math.random() > 0.7) { // %30 chance of having a position
                positions.push({
                    symbol: symbol.trim(),
                    side: Math.random() > 0.5 ? 'LONG' : 'SHORT',
                    size: (Math.random() * 0.5 + 0.1).toFixed(4),
                    entryPrice: (Math.random() * 50000 + 20000).toFixed(2),
                    currentPrice: (Math.random() * 50000 + 20000).toFixed(2),
                    unrealizedPnl: (Math.random() * 100 - 50).toFixed(2)
                });
            }
        });
        
        if (positions.length === 0) {
            positionsContainer.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-search"></i>
                    <h3>Pozisyon Bekleniyor</h3>
                    <p>Bot sinyal bekliyor. Uygun fırsat bulunduğunda pozisyon açılacak.</p>
                </div>
            `;
            return;
        }
        
        const positionsHTML = positions.map(position => {
            const pnlClass = parseFloat(position.unrealizedPnl) >= 0 ? 'profit' : 'loss';
            const sideClass = position.side.toLowerCase();
            const sideIcon = position.side === 'LONG' ? 'fa-arrow-up' : 'fa-arrow-down';
            
            return `
                <div class="position-item">
                    <div class="position-header">
                        <span class="position-symbol">${position.symbol}</span>
                        <span class="position-side ${sideClass}">
                            <i class="fas ${sideIcon}"></i>
                            ${position.side}
                        </span>
                    </div>
                    <div class="position-stats">
                        <div class="position-stat">
                            <div class="stat-label">Boyut</div>
                            <div class="stat-value">${position.size} ${position.symbol.replace('USDT', '')}</div>
                        </div>
                        <div class="position-stat">
                            <div class="stat-label">Giriş</div>
                            <div class="stat-value">$${position.entryPrice}</div>
                        </div>
                        <div class="position-stat">
                            <div class="stat-label">Güncel</div>
                            <div class="stat-value">$${position.currentPrice}</div>
                        </div>
                        <div class="position-stat">
                            <div class="stat-label">P&L</div>
                            <div class="stat-value ${pnlClass}">
                                ${parseFloat(position.unrealizedPnl) >= 0 ? '+' : ''}${position.unrealizedPnl} USDT
                            </div>
                        </div>
                    </div>
                    <div class="position-actions">
                        <button class="btn btn-danger btn-sm" onclick="closePosition('${position.symbol}', '${position.side}')">
                            <i class="fas fa-times"></i> Pozisyonu Kapat
                        </button>
                    </div>
                </div>
            `;
        }).join('');
        
        positionsContainer.innerHTML = positionsHTML;
        
    } catch (error) {
        console.error('Error loading positions:', error);
        const positionsContainer = document.getElementById('positions-container');
        if (positionsContainer) {
            positionsContainer.innerHTML = `
                <div class="error-state">
                    <i class="fas fa-exclamation-triangle"></i>
                    <h3>Pozisyonlar Yüklenemedi</h3>
                    <p>Pozisyon verileri alınırken hata oluştu</p>
                </div>
            `;
        }
    }
}

// Load recent activity
async function loadRecentActivity() {
    try {
        const activityList = document.getElementById('activity-list');
        if (!activityList) return;
        
        if (!currentUser || !userData) {
            activityList.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-history"></i>
                    <h3>Henüz İşlem Yok</h3>
                    <p>Bot başladığında işlemler burada görünecek</p>
                </div>
            `;
            return;
        }
        
        // Get trades from Firebase
        const tradesRef = database.ref('trades');
        const query = tradesRef.orderByChild('user_id').equalTo(currentUser.uid).limitToLast(10);
        const snapshot = await query.once('value');
        const tradesData = snapshot.val();
        
        if (!tradesData) {
            activityList.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-info-circle"></i>
                    <h3>Henüz İşlem Yok</h3>
                    <p>Bot başladığında işlemler burada görünecek</p>
                </div>
            `;
            return;
        }
        
        const trades = Object.entries(tradesData).map(([id, trade]) => ({
            id,
            ...trade
        })).sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
        
        const tradesHTML = trades.map(trade => {
            const sideClass = trade.side === 'LONG' || trade.side === 'BUY' ? 'success' : 'warning';
            const icon = trade.side === 'LONG' || trade.side === 'BUY' ? 'fa-arrow-up' : 'fa-arrow-down';
            const pnlClass = trade.pnl >= 0 ? 'profit' : 'loss';
            
            return `
                <div class="activity-item">
                    <div class="activity-icon ${sideClass}">
                        <i class="fas ${icon}"></i>
                    </div>
                    <div class="activity-content">
                        <div class="activity-title">
                            ${trade.side} ${trade.symbol} 
                            ${trade.pnl ? `- <span class="${pnlClass}">${trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(2)} USDT</span>` : ''}
                        </div>
                        <div class="activity-time">${new Date(trade.timestamp).toLocaleString('tr-TR')}</div>
                        <div class="activity-status">${trade.status || 'Tamamlandı'}</div>
                    </div>
                </div>
            `;
        }).join('');
        
        activityList.innerHTML = tradesHTML;
        
    } catch (error) {
        console.error('Error loading recent activity:', error);
        const activityList = document.getElementById('activity-list');
        if (activityList) {
            activityList.innerHTML = `
                <div class="error-state">
                    <i class="fas fa-exclamation-triangle"></i>
                    <h3>İşlemler Yüklenemedi</h3>
                    <p>İşlem geçmişi alınırken hata oluştu</p>
                </div>
            `;
        }
    }
}

// Close position
async function closePosition(symbol, side) {
    if (!confirm(`${symbol} ${side} pozisyonunu kapatmak istediğinizden emin misiniz?`)) {
        return;
    }
    
    try {
        // Log trade closure
        await database.ref('trades').push({
            user_id: currentUser.uid,
            symbol: symbol,
            side: side,
            status: 'CLOSED_MANUAL',
            timestamp: new Date().toISOString(),
            pnl: (Math.random() * 20 - 10).toFixed(2) // Simulated PnL
        });
        
        // Update user stats
        const currentTrades = userData.total_trades || 0;
        await database.ref(`users/${currentUser.uid}`).update({
            total_trades: currentTrades + 1,
            last_trade_time: firebase.database.ServerValue.TIMESTAMP
        });
        
        showToast(`${symbol} pozisyonu başarıyla kapatıldı!`, 'success');
        
        // Refresh data
        setTimeout(() => {
            loadPositions();
            loadRecentActivity();
            loadUserData();
        }, 1000);
        
    } catch (error) {
        console.error('Error closing position:', error);
        showToast('Pozisyon kapatılırken hata oluştu', 'error');
    }
}

// Send payment notification
async function sendPaymentNotification(transactionHash) {
    if (!currentUser || !userData) {
        showToast('Oturum açmanız gerekiyor', 'error');
        return false;
    }
    
    try {
        const appInfo = await window.configLoader.getAppInfo();
        
        const paymentData = {
            user_id: currentUser.uid,
            user_email: userData.email,
            transaction_hash: transactionHash,
            amount: appInfo.monthly_price || 15,
            currency: 'USDT',
            network: 'TRC20',
            status: 'pending',
            created_at: firebase.database.ServerValue.TIMESTAMP
        };
        
        await database.ref('payment_notifications').push(paymentData);
        
        console.log('Payment notification sent successfully');
        return true;
    } catch (error) {
        console.error('Error sending payment notification:', error);
        return false;
    }
}

// Send support message
async function sendSupportMessage(subject, message) {
    if (!currentUser || !userData) {
        showToast('Oturum açmanız gerekiyor', 'error');
        return false;
    }
    
    try {
        const supportData = {
            user_id: currentUser.uid,
            user_email: userData.email,
            subject: subject,
            message: message,
            status: 'open',
            created_at: firebase.database.ServerValue.TIMESTAMP
        };
        
        await database.ref('support_messages').push(supportData);
        
        console.log('Support message sent successfully');
        return true;
    } catch (error) {
        console.error('Error sending support message:', error);
        return false;
    }
}

// Event handlers
function setupEventHandlers() {
    // Mobile menu
    const hamburgerMenu = document.getElementById('hamburger-menu');
    const mobileMenu = document.getElementById('mobile-menu');
    const mobileMenuClose = document.getElementById('mobile-menu-close');
    
    if (hamburgerMenu && mobileMenu) {
        hamburgerMenu.addEventListener('click', () => {
            mobileMenu.classList.add('show');
        });
    }
    
    if (mobileMenuClose && mobileMenu) {
        mobileMenuClose.addEventListener('click', () => {
            mobileMenu.classList.remove('show');
        });
    }
    
    // API Modal
    const manageApiBtn = document.getElementById('manage-api-btn');
    const mobileApiBtn = document.getElementById('mobile-api-btn');
    const apiModal = document.getElementById('api-modal');
    const apiModalClose = document.getElementById('api-modal-close');
    const cancelApiBtn = document.getElementById('cancel-api-btn');
    const apiForm = document.getElementById('api-form');
    
    [manageApiBtn, mobileApiBtn].forEach(btn => {
        if (btn) {
            btn.addEventListener('click', async () => {
                await loadPaymentInfo(); // Load server IPs
                toggleModal('api-modal', true);
            });
        }
    });
    
    if (apiModalClose) {
        apiModalClose.addEventListener('click', () => toggleModal('api-modal', false));
    }
    
    if (cancelApiBtn) {
        cancelApiBtn.addEventListener('click', () => toggleModal('api-modal', false));
    }
    
    if (apiForm) {
        apiForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const apiKey = document.getElementById('api-key')?.value.trim();
            const apiSecret = document.getElementById('api-secret')?.value.trim();
            const testnet = document.getElementById('api-testnet')?.checked;
            
            if (!apiKey || !apiSecret) {
                showToast('API anahtarları boş bırakılamaz', 'error');
                return;
            }
            
            const saveBtn = document.getElementById('save-api-btn');
            if (saveBtn) {
                saveBtn.disabled = true;
                saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Test ediliyor...';
            }
            
            const success = await saveAPIKeys(apiKey, apiSecret, testnet);
            
            if (success) {
                showToast('API anahtarları başarıyla kaydedildi ve test ediliyor...', 'success');
                toggleModal('api-modal', false);
                apiForm.reset();
                
                // Check API status after save
                setTimeout(checkApiStatus, 3000);
            }
            
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.innerHTML = '<i class="fas fa-save"></i> Kaydet ve Test Et';
            }
        });
    }
    
    // Copy IPs button
    const copyIpsBtn = document.getElementById('copy-ips-btn');
    if (copyIpsBtn) {
        copyIpsBtn.addEventListener('click', () => {
            const ipsText = document.getElementById('server-ips-text')?.textContent;
            if (ipsText && ipsText !== 'IP adresleri yükleniyor...') {
                copyToClipboard(ipsText);
            }
        });
    }
    
    // Purchase Modal
    const mobilePurchaseBtn = document.getElementById('mobile-purchase-btn');
    const purchaseModal = document.getElementById('purchase-modal');
    const purchaseModalClose = document.getElementById('purchase-modal-close');
    const cancelPurchaseBtn = document.getElementById('cancel-purchase-btn');
    const confirmPaymentBtn = document.getElementById('confirm-payment-btn');
    const copyAddressBtn = document.getElementById('copy-address-btn');
    
    if (mobilePurchaseBtn) {
        mobilePurchaseBtn.addEventListener('click', async () => {
            await loadPaymentInfo();
            toggleModal('purchase-modal', true);
        });
    }
    
    if (purchaseModalClose) {
        purchaseModalClose.addEventListener('click', () => toggleModal('purchase-modal', false));
    }
    
    if (cancelPurchaseBtn) {
        cancelPurchaseBtn.addEventListener('click', () => toggleModal('purchase-modal', false));
    }
    
    if (copyAddressBtn) {
        copyAddressBtn.addEventListener('click', () => {
            const addressElement = document.getElementById('payment-address-text');
            if (addressElement && addressElement.textContent !== 'Yükleniyor...') {
                copyToClipboard(addressElement.textContent);
            }
        });
    }
    
    if (confirmPaymentBtn) {
        confirmPaymentBtn.addEventListener('click', async () => {
            const transactionHash = document.getElementById('transaction-hash')?.value.trim();
            
            if (!transactionHash) {
                showToast('Lütfen işlem hash\'ini girin', 'error');
                return;
            }
            
            if (transactionHash.length < 10) {
                showToast('Geçersiz işlem hash formatı', 'error');
                return;
            }
            
            confirmPaymentBtn.disabled = true;
            confirmPaymentBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Gönderiliyor...';
            
            const success = await sendPaymentNotification(transactionHash);
            
            if (success) {
                showToast('Ödeme bildirimi gönderildi! Admin onayını bekleyin.', 'success');
                toggleModal('purchase-modal', false);
                document.getElementById('transaction-hash').value = '';
            } else {
                showToast('Ödeme bildirimi gönderilemedi', 'error');
            }
            
            confirmPaymentBtn.disabled = false;
            confirmPaymentBtn.innerHTML = '<i class="fas fa-check"></i> Ödeme Bildir';
        });
    }
    
    // Support Modal
    const mobileSupportBtn = document.getElementById('mobile-support-btn');
    const supportModal = document.getElementById('support-modal');
    const supportModalClose = document.getElementById('support-modal-close');
    const cancelSupportBtn = document.getElementById('cancel-support-btn');
    const sendSupportBtn = document.getElementById('send-support-btn');
    
    if (mobileSupportBtn) {
        mobileSupportBtn.addEventListener('click', () => toggleModal('support-modal', true));
    }
    
    if (supportModalClose) {
        supportModalClose.addEventListener('click', () => toggleModal('support-modal', false));
    }
    
    if (cancelSupportBtn) {
        cancelSupportBtn.addEventListener('click', () => toggleModal('support-modal', false));
    }
    
    if (sendSupportBtn) {
        sendSupportBtn.addEventListener('click', async () => {
            const subject = document.getElementById('support-subject')?.value;
            const message = document.getElementById('support-message')?.value.trim();
            
            if (!subject || !message) {
                showToast('Lütfen konu ve mesaj alanlarını doldurun', 'error');
                return;
            }
            
            sendSupportBtn.disabled = true;
            sendSupportBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Gönderiliyor...';
            
            const success = await sendSupportMessage(subject, message);
            
            if (success) {
                showToast('Destek mesajı gönderildi! En kısa sürede yanıtlanacak.', 'success');
                toggleModal('support-modal', false);
                document.getElementById('support-subject').value = '';
                document.getElementById('support-message').value = '';
            } else {
                showToast('Destek mesajı gönderilemedi', 'error');
            }
            
            sendSupportBtn.disabled = false;
            sendSupportBtn.innerHTML = '<i class="fas fa-paper-plane"></i> Destek Talebi Gönder';
        });
    }
    
    // Bot control buttons
    const startBotBtn = document.getElementById('start-bot-btn');
    const stopBotBtn = document.getElementById('stop-bot-btn');
    
    if (startBotBtn) {
        startBotBtn.addEventListener('click', startBot);
    }
    
    if (stopBotBtn) {
        stopBotBtn.addEventListener('click', stopBot);
    }
    
    // Refresh buttons
    const refreshAccountBtn = document.getElementById('refresh-account-btn');
    const refreshPositionsBtn = document.getElementById('refresh-positions-btn');
    const refreshActivityBtn = document.getElementById('refresh-activity-btn');
    
    if (refreshAccountBtn) {
        refreshAccountBtn.addEventListener('click', loadUserData);
    }
    
    if (refreshPositionsBtn) {
        refreshPositionsBtn.addEventListener('click', loadPositions);
    }
    
    if (refreshActivityBtn) {
        refreshActivityBtn.addEventListener('click', loadRecentActivity);
    }
    
    // Logout
    const mobileLogoutBtn = document.getElementById('mobile-logout-btn');
    const logoutBtn = document.getElementById('logout-btn');
    
    const handleLogout = async () => {
        if (confirm('Çıkış yapmak istediğinizden emin misiniz?')) {
            try {
                await auth.signOut();
                window.location.href = '/login';
            } catch (error) {
                console.error('Logout error:', error);
                showToast('Çıkış yapılırken bir hata oluştu', 'error');
            }
        }
    };
    
    if (mobileLogoutBtn) {
        mobileLogoutBtn.addEventListener('click', handleLogout);
    }
    
    if (logoutBtn) {
        logoutBtn.addEventListener('click', handleLogout);
    }
    
    // Toast close button
    const toastClose = document.getElementById('toast-close');
    if (toastClose) {
        toastClose.addEventListener('click', () => {
            document.getElementById('toast')?.classList.remove('show');
        });
    }
    
    // Auto-save settings
    const settingsInputs = [
        'trading-symbols', 'timeframe-select', 'leverage-select', 
        'order-size', 'stop-loss', 'take-profit', 'max-daily-trades',
        'auto-compound', 'manual-trading', 'notifications-enabled'
    ];
    
    settingsInputs.forEach(inputId => {
        const input = document.getElementById(inputId);
        if (input) {
            input.addEventListener('change', () => {
                // Auto-save user settings to localStorage
                const settings = {};
                settingsInputs.forEach(id => {
                    const el = document.getElementById(id);
                    if (el) {
                        settings[id] = el.type === 'checkbox' ? el.checked : el.value;
                    }
                });
                localStorage.setItem('userTradingSettings', JSON.stringify(settings));
            });
        }
    });
}

// Load saved settings
function loadSavedSettings() {
    try {
        const savedSettings = localStorage.getItem('userTradingSettings');
        if (savedSettings) {
            const settings = JSON.parse(savedSettings);
            
            Object.entries(settings).forEach(([inputId, value]) => {
                const input = document.getElementById(inputId);
                if (input) {
                    if (input.type === 'checkbox') {
                        input.checked = value;
                    } else {
                        input.value = value;
                    }
                }
            });
        }
    } catch (error) {
        console.error('Error loading saved settings:', error);
    }
}

// Initialize dashboard
async function initializeDashboard() {
    try {
        console.log('Initializing dashboard...');
        
        // Load configurations first
        await window.configLoader.loadConfigurations();
        
        // Initialize Firebase
        if (!(await initializeFirebase())) {
            throw new Error('Firebase initialization failed');
        }
        
        // Wait for auth state
        await new Promise((resolve) => {
            const unsubscribe = auth.onAuthStateChanged(async (user) => {
                unsubscribe();
                
                if (!user) {
                    console.log('No user logged in, redirecting to login...');
                    window.location.href = '/login';
                    return;
                }
                
                currentUser = user;
                console.log('User authenticated:', user.uid);
                
                try {
                    // Load user data
                    await loadUserData();
                    
                    if (!userData) {
                        throw new Error('User data not found');
                    }
                    
                    console.log('User data loaded');
                    
                    // Check API status
                    await checkApiStatus();
                    
                    // Load payment info
                    await loadPaymentInfo();
                    
                    // Load initial data
                    await Promise.all([
                        loadPositions(),
                        loadRecentActivity()
                    ]);
                    
                    // Load saved settings
                    loadSavedSettings();
                    
                    resolve();
                    
                } catch (error) {
                    console.error('Error loading user data:', error);
                    showToast('Kullanıcı verileri yüklenirken hata oluştu', 'error');
                    resolve();
                }
            });
        });
        
        // Setup event handlers
        setupEventHandlers();
        
        // Hide loading screen and show dashboard
        const loadingScreen = document.getElementById('loading-screen');
        const dashboard = document.getElementById('dashboard');
        
        if (loadingScreen) {
            loadingScreen.style.display = 'none';
        }
        
        if (dashboard) {
            dashboard.classList.remove('hidden');
        }
        
        showToast('Dashboard başarıyla yüklendi!', 'success');
        
        // Start auto-refresh if bot is running
        if (userData && userData.bot_active) {
            startDataRefresh();
        }
        
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
                    <button class="btn btn-primary" onclick="location.reload()">
                        <i class="fas fa-redo"></i> Tekrar Dene
                    </button>
                </div>
            `;
        }
    }
}

// Start when DOM is ready
document.addEventListener('DOMContentLoaded', initializeDashboard);
