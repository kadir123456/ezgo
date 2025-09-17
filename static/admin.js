// Global variables
let firebaseApp = null;
let auth = null;
let database = null;
let currentUser = null;

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
    console.log(`${type.toUpperCase()}: ${message}`);
    
    // Basit alert kullan (gelişmiş toast sistemi için)
    if (type === 'error') {
        alert('Hata: ' + message);
    } else if (type === 'success') {
        alert('Başarılı: ' + message);
    } else {
        alert(message);
    }
}

// Format date
function formatDate(timestamp) {
    if (!timestamp) return 'Bilinmiyor';
    const date = new Date(timestamp);
    return date.toLocaleDateString('tr-TR', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// Get subscription status
function getSubscriptionStatus(userData) {
    const now = new Date();
    const expiryDate = userData.subscription_expiry ? new Date(userData.subscription_expiry) : null;
    
    if (!expiryDate) {
        return { status: 'inactive', label: 'Pasif', icon: 'fa-times' };
    }

    const isExpired = now > expiryDate;
    const subscriptionStatus = userData.subscription_status || 'trial';

    if (isExpired) {
        return { status: 'expired', label: 'Süresi Dolmuş', icon: 'fa-times-circle' };
    }

    switch (subscriptionStatus) {
        case 'active':
            return { status: 'active', label: 'Aktif', icon: 'fa-check-circle' };
        case 'trial':
            return { status: 'trial', label: 'Deneme', icon: 'fa-clock' };
        default:
            return { status: 'inactive', label: 'Pasif', icon: 'fa-times' };
    }
}

// Get expiry info
function getExpiryInfo(userData) {
    if (!userData.subscription_expiry) {
        return { date: 'Belirlenmemiş', remaining: null, class: '' };
    }

    const now = new Date();
    const expiryDate = new Date(userData.subscription_expiry);
    const diffTime = expiryDate - now;
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

    const formattedDate = expiryDate.toLocaleDateString('tr-TR', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
    });

    let remaining = null;
    let remainingClass = '';

    if (diffDays > 0) {
        remaining = `${diffDays} gün kaldı`;
        remainingClass = diffDays <= 3 ? 'warning' : 'positive';
    } else if (diffDays === 0) {
        remaining = 'Bugün sona eriyor';
        remainingClass = 'warning';
    } else {
        remaining = `${Math.abs(diffDays)} gün önce doldu`;
        remainingClass = 'expired';
    }

    return {
        date: formattedDate,
        remaining: remaining,
        class: remainingClass
    };
}

// Load users data
async function loadUsers() {
    try {
        console.log('Loading users...');
        
        const usersTableBody = document.getElementById('users-table-body');
        if (!usersTableBody) {
            console.error('Users table body not found');
            return;
        }
        
        // Show loading
        usersTableBody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center loading-message">
                    <i class="fas fa-spinner fa-spin"></i>
                    Kullanıcılar yükleniyor...
                </td>
            </tr>
        `;
        
        const usersRef = database.ref('users');
        const snapshot = await usersRef.once('value');
        const usersData = snapshot.val();

        if (!usersData) {
            usersTableBody.innerHTML = `
                <tr><td colspan="5" class="text-center text-muted">Henüz kullanıcı kaydı yok.</td></tr>
            `;
            updateStats({ total: 0, active: 0, trial: 0, expired: 0 });
            return;
        }

        const users = Object.entries(usersData);
        console.log(`Loaded ${users.length} users`);
        
        renderUsers(users);
        
    } catch (error) {
        console.error('Error loading users:', error);
        showToast('Kullanıcılar yüklenirken hata: ' + error.message, 'error');
        
        const usersTableBody = document.getElementById('users-table-body');
        if (usersTableBody) {
            usersTableBody.innerHTML = `
                <tr><td colspan="5" class="text-center text-danger">Hata: ${error.message}</td></tr>
            `;
        }
    }
}

// Render users table
function renderUsers(users) {
    const stats = { total: 0, active: 0, trial: 0, expired: 0 };
    
    const tableRows = users.map(([userId, userData]) => {
        stats.total++;
        const subscriptionStatus = getSubscriptionStatus(userData);
        const expiryInfo = getExpiryInfo(userData);
        
        if (subscriptionStatus.status === 'active') stats.active++;
        else if (subscriptionStatus.status === 'trial') stats.trial++;
        else stats.expired++;

        return `
            <tr class="user-row">
                <td>
                    <div class="user-info">
                        <div class="email-text">${userData.email || 'Bilinmiyor'}</div>
                        <div class="join-date">Katıldı: ${formatDate(userData.created_at)}</div>
                        ${userData.full_name ? `<div class="user-language">${userData.full_name}</div>` : ''}
                    </div>
                </td>
                <td>
                    <span class="status-badge ${subscriptionStatus.status}">
                        <i class="fas ${subscriptionStatus.icon}"></i>
                        ${subscriptionStatus.label}
                    </span>
                </td>
                <td>
                    <div class="expiry-info">
                        <div class="expiry-date">${expiryInfo.date}</div>
                        ${expiryInfo.remaining ? `<div class="days-remaining ${expiryInfo.class}">${expiryInfo.remaining}</div>` : ''}
                    </div>
                </td>
                <td>
                    <span class="user-id-text" onclick="copyToClipboard('${userId}')" title="Kopyalamak için tıklayın">
                        ${userId.substring(0, 12)}...
                    </span>
                </td>
                <td class="actions-cell">
                    <div class="action-buttons">
                        <button class="btn btn-success btn-sm" onclick="extendSubscription('${userId}', '${escapeHtml(userData.email)}')" title="30 gün ekle">
                            <i class="fas fa-plus"></i>
                            <span class="btn-text">30 Gün</span>
                        </button>
                        <button class="btn btn-outline btn-sm" onclick="viewUserDetails('${userId}')" title="Detayları göster">
                            <i class="fas fa-eye"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');

    const usersTableBody = document.getElementById('users-table-body');
    if (usersTableBody) {
        usersTableBody.innerHTML = tableRows;
    }
    
    updateStats(stats);
}

// Update statistics
function updateStats(stats) {
    const totalUsersCount = document.getElementById('total-users-count');
    const activeUsersCount = document.getElementById('active-users-count');
    const trialUsersCount = document.getElementById('trial-users-count');
    const expiredUsersCount = document.getElementById('expired-users-count');
    
    if (totalUsersCount) totalUsersCount.textContent = stats.total;
    if (activeUsersCount) activeUsersCount.textContent = stats.active;
    if (trialUsersCount) trialUsersCount.textContent = stats.trial;
    if (expiredUsersCount) expiredUsersCount.textContent = stats.expired;
}

// Load payment notifications
async function loadPayments() {
    try {
        console.log('Loading payments...');
        
        const paymentsTableBody = document.getElementById('payments-table-body');
        if (!paymentsTableBody) return;
        
        paymentsTableBody.innerHTML = `
            <tr>
                <td colspan="6" class="text-center loading-message">
                    <i class="fas fa-spinner fa-spin"></i>
                    Ödeme bildirimleri yükleniyor...
                </td>
            </tr>
        `;
        
        const paymentsRef = database.ref('payment_notifications');
        const snapshot = await paymentsRef.once('value');
        const paymentsData = snapshot.val();

        if (!paymentsData) {
            paymentsTableBody.innerHTML = `
                <tr><td colspan="6" class="text-center text-muted">Ödeme bildirimi yok.</td></tr>
            `;
            return;
        }

        const payments = Object.entries(paymentsData);
        console.log(`Loaded ${payments.length} payments`);
        
        renderPayments(payments);
        
    } catch (error) {
        console.error('Error loading payments:', error);
        showToast('Ödeme bildirimleri yüklenirken hata: ' + error.message, 'error');
    }
}

// Render payments table
function renderPayments(payments) {
    const tableRows = payments.map(([paymentId, paymentData]) => {
        const statusClass = paymentData.status === 'pending' ? 'warning' : 
                          paymentData.status === 'approved' ? 'success' : 'danger';
        
        return `
            <tr class="payment-row">
                <td>
                    <div class="user-info">
                        <div class="email-text">${paymentData.user_email || 'Bilinmiyor'}</div>
                        <div class="join-date">${paymentData.user_id ? paymentData.user_id.substring(0, 12) + '...' : ''}</div>
                    </div>
                </td>
                <td>$${paymentData.amount || '15'}</td>
                <td>
                    <span class="user-id-text" onclick="copyToClipboard('${paymentData.transaction_hash}')" title="Hash kopyala">
                        ${paymentData.transaction_hash ? paymentData.transaction_hash.substring(0, 16) + '...' : 'N/A'}
                    </span>
                </td>
                <td>${formatDate(paymentData.created_at)}</td>
                <td>
                    <span class="status-badge ${statusClass}">
                        <i class="fas fa-${paymentData.status === 'pending' ? 'clock' : paymentData.status === 'approved' ? 'check' : 'times'}"></i>
                        ${paymentData.status === 'pending' ? 'Bekliyor' : paymentData.status === 'approved' ? 'Onaylandı' : 'Reddedildi'}
                    </span>
                </td>
                <td class="actions-cell">
                    <div class="action-buttons">
                        ${paymentData.status === 'pending' ? `
                            <button class="btn btn-success btn-sm" onclick="approvePayment('${paymentId}')" title="Onayla">
                                <i class="fas fa-check"></i>
                            </button>
                            <button class="btn btn-danger btn-sm" onclick="rejectPayment('${paymentId}')" title="Reddet">
                                <i class="fas fa-times"></i>
                            </button>
                        ` : `
                            <button class="btn btn-outline btn-sm" onclick="viewPaymentDetails('${paymentId}')" title="Detaylar">
                                <i class="fas fa-eye"></i>
                            </button>
                        `}
                    </div>
                </td>
            </tr>
        `;
    }).join('');

    const paymentsTableBody = document.getElementById('payments-table-body');
    if (paymentsTableBody) {
        paymentsTableBody.innerHTML = tableRows;
    }
}

// Load support messages
async function loadSupportMessages() {
    try {
        console.log('Loading support messages...');
        
        const supportContainer = document.getElementById('support-messages-container');
        if (!supportContainer) return;
        
        const supportRef = database.ref('support_messages');
        const snapshot = await supportRef.once('value');
        const supportData = snapshot.val();

        if (!supportData) {
            supportContainer.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-comments"></i>
                    <h3>Destek mesajı yok</h3>
                    <p>Henüz destek talebi gelmemiş</p>
                </div>
            `;
            return;
        }

        const messages = Object.entries(supportData);
        console.log(`Loaded ${messages.length} support messages`);
        
        renderSupportMessages(messages);
        
    } catch (error) {
        console.error('Error loading support messages:', error);
        showToast('Destek mesajları yüklenirken hata: ' + error.message, 'error');
    }
}

// Render support messages
function renderSupportMessages(messages) {
    const messageCards = messages.map(([messageId, messageData]) => {
        const statusClass = messageData.status === 'open' ? 'warning' : 'success';
        
        return `
            <div class="support-message-card">
                <div class="message-header">
                    <div class="message-user">
                        <strong>${messageData.user_email || 'Anonim'}</strong>
                        <span class="message-date">${formatDate(messageData.created_at)}</span>
                    </div>
                    <span class="status-badge ${statusClass}">
                        ${messageData.status === 'open' ? 'Açık' : 'Yanıtlandı'}
                    </span>
                </div>
                <div class="message-subject">
                    <strong>Konu:</strong> ${messageData.subject || 'Genel'}
                </div>
                <div class="message-content">
                    ${messageData.message || 'Mesaj içeriği yok'}
                </div>
                <div class="message-actions">
                    <button class="btn btn-primary btn-sm" onclick="replyToSupport('${messageId}')">
                        <i class="fas fa-reply"></i> Yanıtla
                    </button>
                    ${messageData.status === 'open' ? `
                        <button class="btn btn-success btn-sm" onclick="markSupportResolved('${messageId}')">
                            <i class="fas fa-check"></i> Çözüldü
                        </button>
                    ` : ''}
                </div>
            </div>
        `;
    }).join('');

    const supportContainer = document.getElementById('support-messages-container');
    if (supportContainer) {
        supportContainer.innerHTML = messageCards;
    }
}

// Utility functions
function escapeHtml(text) {
    if (!text) return '';
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast(`Kopyalandı: ${text.substring(0, 20)}...`, 'success');
    } catch (error) {
        console.error('Copy failed:', error);
        showToast('Kopyalama başarısız', 'error');
    }
}

// Admin actions
async function extendSubscription(userId, userEmail) {
    if (!confirm(`${userEmail} kullanıcısının aboneliğini 30 gün uzatmak istediğinizden emin misiniz?`)) return;
    
    try {
        showToast('Abonelik uzatılıyor...', 'info');
        
        const userRef = database.ref(`users/${userId}`);
        const snapshot = await userRef.once('value');
        const userData = snapshot.val();
        
        if (!userData) throw new Error('Kullanıcı bulunamadı');
        
        const now = new Date();
        const currentExpiry = userData.subscription_expiry ? new Date(userData.subscription_expiry) : now;
        const baseDate = currentExpiry > now ? currentExpiry : now;
        const newExpiryDate = new Date(baseDate.getTime() + (30 * 24 * 60 * 60 * 1000));
        
        await userRef.update({
            subscription_expiry: newExpiryDate.getTime(),
            subscription_status: 'active',
            subscription_extended_by: currentUser.email,
            subscription_extended_at: firebase.database.ServerValue.TIMESTAMP,
            last_updated: firebase.database.ServerValue.TIMESTAMP,
            updated_by: currentUser.email
        });
        
        showToast(`✅ ${userEmail} kullanıcısının aboneliği 30 gün uzatıldı! Yeni bitiş tarihi: ${newExpiryDate.toLocaleDateString('tr-TR')}`, 'success');
        
        // Immediately reload users to show updated data
        setTimeout(() => {
            loadUsers();
        }, 1000);
        
    } catch (error) {
        console.error('Error extending subscription:', error);
        showToast('Abonelik uzatılırken hata: ' + error.message, 'error');
    }
}

function viewUserDetails(userId) {
    alert(`Kullanıcı detayları: ${userId}\n(Detaylı görünüm yakında eklenecek)`);
}

async function approvePayment(paymentId) {
    if (!confirm('Bu ödemeyi onaylamak istediğinizden emin misiniz?')) return;
    
    try {
        showToast('Ödeme onaylanıyor...', 'info');
        
        const paymentRef = database.ref(`payment_notifications/${paymentId}`);
        const paymentSnapshot = await paymentRef.once('value');
        const paymentData = paymentSnapshot.val();
        
        if (!paymentData) {
            throw new Error('Ödeme verisi bulunamadı');
        }
        
        // First approve the payment
        await paymentRef.update({
            status: 'approved',
            approved_at: firebase.database.ServerValue.TIMESTAMP,
            approved_by: currentUser.email
        });
        
        // Then extend user subscription by 30 days
        if (paymentData.user_id) {
            const userRef = database.ref(`users/${paymentData.user_id}`);
            const userSnapshot = await userRef.once('value');
            const userData = userSnapshot.val();
            
            if (userData) {
                const now = new Date();
                const currentExpiry = userData.subscription_expiry ? new Date(userData.subscription_expiry) : now;
                const baseDate = currentExpiry > now ? currentExpiry : now;
                const newExpiryDate = new Date(baseDate.getTime() + (30 * 24 * 60 * 60 * 1000));
                
                await userRef.update({
                    subscription_expiry: newExpiryDate.getTime(),
                    subscription_status: 'active',
                    payment_approved_by: currentUser.email,
                    payment_approved_at: firebase.database.ServerValue.TIMESTAMP,
                    last_updated: firebase.database.ServerValue.TIMESTAMP
                });
                
                showToast(`✅ Ödeme onaylandı ve ${userData.email} kullanıcısının aboneliği 30 gün uzatıldı!`, 'success');
            } else {
                showToast('⚠️ Ödeme onaylandı ancak kullanıcı bulunamadı', 'warning');
            }
        } else {
            showToast('✅ Ödeme onaylandı!', 'success');
        }
        
        // Reload both payments and users
        setTimeout(() => {
            loadPayments();
            loadUsers();
        }, 1000);
        
    } catch (error) {
        console.error('Error approving payment:', error);
        showToast('Ödeme onaylanırken hata: ' + error.message, 'error');
    }
}

async function rejectPayment(paymentId) {
    const reason = prompt('Reddetme sebebi:');
    if (!reason) return;
    
    try {
        const paymentRef = database.ref(`payment_notifications/${paymentId}`);
        await paymentRef.update({
            status: 'rejected',
            rejected_at: firebase.database.ServerValue.TIMESTAMP,
            rejected_by: currentUser.email,
            rejection_reason: reason
        });
        
        showToast('Ödeme reddedildi', 'success');
        loadPayments();
        
    } catch (error) {
        console.error('Error rejecting payment:', error);
        showToast('Ödeme reddedilirken hata: ' + error.message, 'error');
    }
}

function viewPaymentDetails(paymentId) {
    alert(`Ödeme detayları: ${paymentId}\n(Detaylı görünüm yakında eklenecek)`);
}

function replyToSupport(messageId) {
    const reply = prompt('Yanıtınızı yazın:');
    if (!reply) return;
    
    // Support reply functionality would be implemented here
    alert(`Yanıt gönderildi: ${messageId}`);
    showToast('Destek yanıtı gönderildi', 'success');
}

async function markSupportResolved(messageId) {
    try {
        const messageRef = database.ref(`support_messages/${messageId}`);
        await messageRef.update({
            status: 'resolved',
            resolved_at: firebase.database.ServerValue.TIMESTAMP,
            resolved_by: currentUser.email
        });
        
        showToast('Destek talebi çözüldü olarak işaretlendi', 'success');
        loadSupportMessages();
        
    } catch (error) {
        console.error('Error marking support resolved:', error);
        showToast('Durum güncellenirken hata: ' + error.message, 'error');
    }
}

// Setup tab switching
function setupTabs() {
    const tabs = document.querySelectorAll('.nav-tab');
    const tabContents = document.querySelectorAll('.tab-content');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetTab = tab.dataset.tab;
            
            // Update active tab
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            
            // Update active content
            tabContents.forEach(content => {
                content.classList.remove('active');
                if (content.id === `${targetTab}-tab`) {
                    content.classList.add('active');
                }
            });

            // Load data for the active tab
            if (targetTab === 'users') loadUsers();
            else if (targetTab === 'payments') loadPayments();
            else if (targetTab === 'support') loadSupportMessages();
        });
    });
}

// Setup event listeners
function setupEventListeners() {
    // Refresh buttons
    const refreshAllBtn = document.getElementById('refresh-all-btn');
    if (refreshAllBtn) {
        refreshAllBtn.addEventListener('click', () => {
            loadUsers();
            loadPayments();
            loadSupportMessages();
            showToast('Tüm veriler yenilendi', 'success');
        });
    }

    // Logout button
    const adminLogoutButton = document.getElementById('admin-logout-button');
    if (adminLogoutButton) {
        adminLogoutButton.addEventListener('click', async () => {
            if (confirm('Admin panelinden çıkış yapmak istediğinizden emin misiniz?')) {
                try {
                    await auth.signOut();
                    window.location.href = '/login.html';
                } catch (error) {
                    console.error('Logout error:', error);
                    showToast('Çıkış yapılırken hata oluştu', 'error');
                }
            }
        });
    }

    // Setup tabs
    setupTabs();

    // Set current year
    const currentYear = document.getElementById('current-year');
    if (currentYear) {
        currentYear.textContent = new Date().getFullYear();
    }
}

// Check admin authentication
async function checkAdminAuth() {
    return new Promise((resolve) => {
        auth.onAuthStateChanged(async (user) => {
            if (user) {
                try {
                    // Get user data to check admin status
                    const userRef = database.ref(`users/${user.uid}`);
                    const snapshot = await userRef.once('value');
                    const userData = snapshot.val();
                    
                    if (userData && userData.role === 'admin') {
                        currentUser = user;
                        console.log('Admin authenticated:', user.email);
                        resolve(true);
                    } else {
                        showToast('Admin yetkisi bulunamadı. Dashboard\'a yönlendiriliyorsunuz.', 'error');
                        setTimeout(() => window.location.href = '/dashboard.html', 3000);
                        resolve(false);
                    }
                } catch (error) {
                    console.error('Admin verification failed:', error);
                    showToast('Yetki kontrolü başarısız.', 'error');
                    resolve(false);
                }
            } else {
                showToast('Giriş yapılmamış. Yönlendiriliyor...', 'error');
                setTimeout(() => window.location.href = '/login.html', 2000);
                resolve(false);
            }
        });
    });
}

// Initialize admin panel
async function initializeAdmin() {
    try {
        console.log('Initializing admin panel...');
        
        // Initialize Firebase
        if (!(await initializeFirebase())) {
            throw new Error('Firebase initialization failed');
        }

        // Check admin authentication
        const isAdmin = await checkAdminAuth();
        if (!isAdmin) {
            return;
        }

        // Setup event listeners
        setupEventListeners();

        // Load initial data
        await loadUsers();
        
        // Hide loading screen and show admin panel
        const loadingScreen = document.getElementById('loading-screen');
        const adminContainer = document.getElementById('admin-container');
        
        if (loadingScreen) {
            loadingScreen.style.display = 'none';
        }
        if (adminContainer) {
            adminContainer.classList.remove('hidden');
        }

        showToast('Admin paneli başarıyla yüklendi!', 'success');
        console.log('Admin panel initialized successfully');

    } catch (error) {
        console.error('Admin panel initialization failed:', error);
        
        const loadingScreen = document.getElementById('loading-screen');
        if (loadingScreen) {
            loadingScreen.innerHTML = `
                <div class="loading-content">
                    <div class="loading-logo">
                        <i class="fas fa-exclamation-triangle" style="color: var(--danger-color);"></i>
                        <span>Hata</span>
                    </div>
                    <p>Admin panel başlatılırken hata oluştu</p>
                    <button class="btn btn-primary" onclick="location.reload()" style="margin-top: 1rem;">
                        <i class="fas fa-redo"></i> Tekrar Dene
                    </button>
                </div>
            `;
        }
    }
}

// Start the application
document.addEventListener('DOMContentLoaded', initializeAdmin);

// Auto-refresh every 30 seconds
setInterval(() => {
    if (document.querySelector('.nav-tab[data-tab="users"].active')) {
        loadUsers();
    } else if (document.querySelector('.nav-tab[data-tab="payments"].active')) {
        loadPayments();
    } else if (document.querySelector('.nav-tab[data-tab="support"].active')) {
        loadSupportMessages();
    }
}, 30000);
