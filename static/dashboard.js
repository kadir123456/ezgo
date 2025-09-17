// Global variables
let firebaseApp = null;
let auth = null;
let database = null;
let currentUser = null;
let userData = null;

// DOM Elements
const elements = {
    get: (id) => {
        const element = document.getElementById(id);
        if (!element) {
            console.warn(`Element not found: ${id}`);
        }
        return element;
    }
};

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

// Load payment information
async function loadPaymentInfo() {
    try {
        const appInfo = await window.configLoader.getAppInfo();
        
        // Update payment address
        const paymentAddressText = document.getElementById('payment-address-text');
        if (paymentAddressText) {
            paymentAddressText.textContent = appInfo.payment_address || 'Ödeme adresi yapılandırılmamış';
        }
        
        // Update bot price
        const paymentAmount = document.getElementById('payment-amount');
        if (paymentAmount) {
            paymentAmount.textContent = `$${appInfo.bot_price || 15}/Ay`;
        }
        
        console.log('Payment info loaded from environment');
    } catch (error) {
        console.error('Error loading payment info:', error);
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
    
    if (toastIcon) {
        toastIcon.className = `toast-icon ${icons[type] || icons.info}`;
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
        modal.style.display = show ? 'flex' : 'none';
    }
}

// Update user info display
function updateUserInfo(user, userInfo) {
    const userNameEl = document.getElementById('user-name');
    const subscriptionTextEl = document.getElementById('subscription-text');
    const subscriptionBadgeEl = document.getElementById('subscription-badge');
    const daysRemainingEl = document.getElementById('days-remaining');
    const subscriptionNoteEl = document.getElementById('subscription-note');
    
    if (userNameEl) {
        userNameEl.textContent = userInfo.full_name || user.displayName || user.email || 'Kullanıcı';
    }
    
    if (subscriptionTextEl && userInfo.subscription_status) {
        const statusText = {
            'trial': 'Deneme',
            'active': 'Premium',
            'expired': 'Süresi Dolmuş'
        };
        subscriptionTextEl.textContent = statusText[userInfo.subscription_status] || 'Deneme';
    }
    
    // Calculate remaining days
    if (userInfo.subscription_expiry && daysRemainingEl) {
        const expiryDate = new Date(userInfo.subscription_expiry);
        const today = new Date();
        const daysLeft = Math.ceil((expiryDate - today) / (1000 * 60 * 60 * 24));
        
        if (daysLeft > 0) {
            daysRemainingEl.textContent = `${daysLeft} gün kaldı`;
            if (subscriptionNoteEl) {
                subscriptionNoteEl.textContent = daysLeft <= 3 ? 
                    'Aboneliğiniz yakında sona erecek!' : 
                    'Aboneliğiniz aktif durumda.';
            }
        } else {
            daysRemainingEl.textContent = 'Süresi dolmuş';
            if (subscriptionNoteEl) {
                subscriptionNoteEl.textContent = 'Aboneliğinizi yenilemeniz gerekiyor.';
            }
        }
    }
}

// Update bot status
function updateBotStatus(isRunning = false) {
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const statusMessageText = document.getElementById('status-message-text');
    const startBtn = document.getElementById('start-bot-btn');
    const stopBtn = document.getElementById('stop-bot-btn');
    
    if (statusDot) {
        statusDot.className = `status-dot ${isRunning ? 'active' : ''}`;
    }
    
    if (statusText) {
        statusText.textContent = isRunning ? 'Çalışıyor' : 'Durduruldu';
    }
    
    if (statusMessageText) {
        statusMessageText.textContent = isRunning ? 
            'Bot aktif olarak çalışıyor.' : 
            'Bot durduruldu. API anahtarlarınızı kontrol edin.';
    }
    
    if (startBtn) startBtn.disabled = isRunning;
    if (stopBtn) stopBtn.disabled = !isRunning;
}

// Update account stats
function updateAccountStats(userInfo) {
    const totalBalance = document.getElementById('total-balance');
    const totalTrades = document.getElementById('total-trades');
    const winRate = document.getElementById('win-rate');
    const totalPnl = document.getElementById('total-pnl');
    
    if (totalBalance) {
        totalBalance.textContent = `${(userInfo.total_balance || 0).toFixed(2)} USDT`;
    }
    
    if (totalTrades) {
        totalTrades.textContent = userInfo.total_trades || '0';
    }
    
    if (winRate) {
        winRate.textContent = `${(userInfo.win_rate || 0).toFixed(1)}%`;
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
        showToast('Kopyalandı: ' + text.substring(0, 20) + '...', 'success');
    } catch (error) {
        console.error('Copy failed:', error);
        showToast('Kopyalama başarısız', 'error');
    }
}

// Save API keys
async function saveAPIKeys(apiKey, apiSecret, testnet = false) {
    if (!currentUser) {
        showToast('Oturum açmanız gerekiyor', 'error');
        return false;
    }
    
    try {
        // Encrypt API keys (basit örnekleme - gerçek uygulamada daha güvenli şifreleme kullanın)
        const encryptedKey = btoa(apiKey); // Base64 encoding (güvenlik için yeterli değil)
        const encryptedSecret = btoa(apiSecret);
        
        const apiData = {
            api_key: encryptedKey,
            api_secret: encryptedSecret,
            testnet: testnet,
            created_at: firebase.database.ServerValue.TIMESTAMP,
            updated_at: firebase.database.ServerValue.TIMESTAMP
        };
        
        // Save to user's data
        await database.ref(`users/${currentUser.uid}/api_keys`).set(apiData);
        await database.ref(`users/${currentUser.uid}`).update({
            api_keys_set: true,
            updated_at: firebase.database.ServerValue.TIMESTAMP
        });
        
        console.log('API keys saved successfully');
        return true;
    } catch (error) {
        console.error('Error saving API keys:', error);
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
            created_at: firebase.database.ServerValue.TIMESTAMP,
            updated_at: firebase.database.ServerValue.TIMESTAMP
        };
        
        // Save support message
        await database.ref('support_messages').push(supportData);
        
        console.log('Support message sent successfully');
        return true;
    } catch (error) {
        console.error('Error sending support message:', error);
        return false;
    }
}

// Send payment notification
async function sendPaymentNotification(transactionHash, amount = 15) {
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
            amount: appInfo.bot_price || amount,
            currency: 'USDT',
            network: 'TRC20',
            status: 'pending',
            created_at: firebase.database.ServerValue.TIMESTAMP
        };
        
        // Save payment notification
        await database.ref('payment_notifications').push(paymentData);
        
        console.log('Payment notification sent successfully');
        return true;
    } catch (error) {
        console.error('Error sending payment notification:', error);
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
    const apiModal = document.getElementById('api-modal');
    const apiModalClose = document.getElementById('api-modal-close');
    const cancelApiBtn = document.getElementById('cancel-api-btn');
    const apiForm = document.getElementById('api-form');
    
    if (manageApiBtn) {
        manageApiBtn.addEventListener('click', () => {
            toggleModal('api-modal', true);
        });
    }
    
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
                saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Kaydediliyor...';
            }
            
            const success = await saveAPIKeys(apiKey, apiSecret, testnet);
            
            if (success) {
                showToast('API anahtarları başarıyla kaydedildi!', 'success');
                toggleModal('api-modal', false);
                // API form'unu temizle
                apiForm.reset();
            } else {
                showToast('API anahtarları kaydedilemedi', 'error');
            }
            
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.innerHTML = '<i class="fas fa-save"></i> Kaydet ve Test Et';
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
            if (addressElement) {
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
                showToast('Destek mesajı gönderildi!', 'success');
                toggleModal('support-modal', false);
                document.getElementById('support-subject').value = '';
                document.getElementById('support-message').value = '';
            } else {
                showToast('Destek mesajı gönderilemedi', 'error');
            }
            
            sendSupportBtn.disabled = false;
            sendSupportBtn.innerHTML = '<i class="fas fa-paper-plane"></i> Gönder';
        });
    }
    
    // Bot control buttons
    const startBotBtn = document.getElementById('start-bot-btn');
    const stopBotBtn = document.getElementById('stop-bot-btn');
    
    if (startBotBtn) {
        startBotBtn.addEventListener('click', () => {
            showToast('Bot başlatma özelliği yakında aktif olacak!', 'info');
        });
    }
    
    if (stopBotBtn) {
        stopBotBtn.addEventListener('click', () => {
            showToast('Bot durdurma özelliği yakında aktif olacak!', 'info');
        });
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
}

// Initialize dashboard
async function initializeDashboard() {
    try {
        console.log('Initializing dashboard...');
        
        // Load configurations first
        await window.configLoader.loadConfigurations();
        
        // Initialize Firebase with loaded config
        if (!(await initializeFirebase())) {
            throw new Error('Firebase initialization failed');
        }
        
        // Load payment info
        await loadPaymentInfo();
        
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
                    const userRef = database.ref(`users/${user.uid}`);
                    const snapshot = await userRef.once('value');
                    userData = snapshot.val();
                    
                    if (!userData) {
                        throw new Error('User data not found');
                    }
                    
                    console.log('User data loaded:', userData);
                    
                    // Update UI
                    updateUserInfo(user, userData);
                    updateBotStatus(userData.bot_active || false);
                    updateAccountStats(userData);
                    
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
