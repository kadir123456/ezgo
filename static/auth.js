// Auth page JavaScript for EzyagoTrading
let firebaseApp = null;
let auth = null;
let database = null;

// Get Firebase configuration from backend
async function getFirebaseConfig() {
    try {
        return await window.configLoader.getFirebaseConfig();
    } catch (error) {
        console.error('Error getting Firebase config:', error);
        throw new Error('Firebase configuration could not be loaded');
    }
}

// Initialize auth page
async function initAuthPage(pageType) {
    try {
        // Get Firebase configuration
        const firebaseConfig = await getFirebaseConfig();
        
        // Initialize Firebase
        if (!firebaseApp) {
            firebaseApp = firebase.initializeApp(firebaseConfig);
            auth = firebase.auth();
            database = firebase.database();
        }
        
        // Initialize page-specific functionality
        if (pageType === 'login') {
            initLoginPage();
        } else if (pageType === 'register') {
            initRegisterPage();
        }
        
        // Common functionality
        initPasswordToggle();
        checkAuthState();
        
    } catch (error) {
        console.error('Firebase initialization failed:', error);
        showError('Sistem başlatılamadı. Lütfen sayfayı yenileyin.');
    }
}

// Initialize login page
function initLoginPage() {
    const loginForm = document.getElementById('login-form');
    if (loginForm) {
        loginForm.addEventListener('submit', handleLogin);
    }
}

// Initialize register page
function initRegisterPage() {
    const registerForm = document.getElementById('register-form');
    if (registerForm) {
        registerForm.addEventListener('submit', handleRegister);
    }
}

// Handle login form submission
async function handleLogin(event) {
    event.preventDefault();
    
    const email = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;
    
    // Validation
    if (!email || !password) {
        showError('Lütfen tüm alanları doldurun.');
        return;
    }
    
    if (!isValidEmail(email)) {
        showError('Geçerli bir e-posta adresi girin.');
        return;
    }
    
    // Start loading
    setLoading('login', true);
    hideMessages();
    
    try {
        // Sign in with Firebase Auth
        const userCredential = await auth.signInWithEmailAndPassword(email, password);
        const user = userCredential.user;
        
        // Update last login in Realtime Database
        await database.ref(`users/${user.uid}`).update({
            last_login: firebase.database.ServerValue.TIMESTAMP,
            last_login_ip: await getUserIP()
        });
        
        showSuccess('Giriş başarılı! Yönlendiriliyorsunuz...');
        
        // Redirect to dashboard after 1 second
        setTimeout(() => {
            window.location.href = '/dashboard.html';
        }, 1000);
        
    } catch (error) {
        console.error('Login error:', error);
        showError(getAuthErrorMessage(error.code));
    } finally {
        setLoading('login', false);
    }
}

// Handle register form submission
async function handleRegister(event) {
    event.preventDefault();
    
    const fullName = document.getElementById('full_name').value.trim();
    const email = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;
    const termsAccepted = document.getElementById('terms').checked;
    
    // Validation
    if (!fullName || !email || !password) {
        showError('Lütfen tüm alanları doldurun.');
        return;
    }
    
    if (fullName.length < 2) {
        showError('Ad soyad en az 2 karakter olmalıdır.');
        return;
    }
    
    if (!isValidEmail(email)) {
        showError('Geçerli bir e-posta adresi girin.');
        return;
    }
    
    if (password.length < 6) {
        showError('Şifre en az 6 karakter olmalıdır.');
        return;
    }
    
    if (!termsAccepted) {
        showError('Kullanım şartlarını kabul etmelisiniz.');
        return;
    }
    
    // Start loading
    setLoading('register', true);
    hideMessages();
    
    try {
        // Create user with Firebase Auth
        const userCredential = await auth.createUserWithEmailAndPassword(email, password);
        const user = userCredential.user;
        
        // Update user profile
        await user.updateProfile({
            displayName: fullName
        });
        
        // Create user record in Realtime Database
        const userData = {
            email: email,
            full_name: fullName,
            created_at: firebase.database.ServerValue.TIMESTAMP,
            last_login: firebase.database.ServerValue.TIMESTAMP,
            subscription_status: 'trial',
            subscription_start: firebase.database.ServerValue.TIMESTAMP,
            subscription_expiry: Date.now() + (7 * 24 * 60 * 60 * 1000), // 7 days from now
            api_keys_set: false,
            bot_active: false,
            total_trades: 0,
            total_pnl: 0,
            settings: {
                language: 'tr',
                timezone: 'Europe/Istanbul',
                notifications: true
            },
            registration_ip: await getUserIP()
        };
        
        await database.ref(`users/${user.uid}`).set(userData);
        
        showSuccess('Hesabınız başarıyla oluşturuldu! Yönlendiriliyorsunuz...');
        
        // Redirect to dashboard after 1 second
        setTimeout(() => {
            window.location.href = '/dashboard.html';
        }, 1000);
        
    } catch (error) {
        console.error('Registration error:', error);
        showError(getAuthErrorMessage(error.code));
    } finally {
        setLoading('register', false);
    }
}

// Check if user is already authenticated
function checkAuthState() {
    auth.onAuthStateChanged((user) => {
        if (user) {
            // User is signed in, redirect to dashboard
            console.log('User already authenticated, redirecting...');
            window.location.href = '/dashboard.html';
        }
    });
}

// Initialize password toggle functionality
function initPasswordToggle() {
    const passwordToggle = document.getElementById('password-toggle');
    const passwordInput = document.getElementById('password');
    
    if (passwordToggle && passwordInput) {
        passwordToggle.addEventListener('click', () => {
            const type = passwordInput.getAttribute('type') === 'password' ? 'text' : 'password';
            passwordInput.setAttribute('type', type);
            
            const icon = passwordToggle.querySelector('i');
            icon.className = type === 'password' ? 'fas fa-eye' : 'fas fa-eye-slash';
        });
    }
}

// Utility functions
function isValidEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}

function setLoading(formType, loading) {
    const btnId = formType === 'login' ? 'login-btn' : 'register-btn';
    const textId = formType === 'login' ? 'login-btn-text' : 'register-btn-text';
    const spinnerId = formType === 'login' ? 'login-spinner' : 'register-spinner';
    
    const btn = document.getElementById(btnId);
    const btnText = document.getElementById(textId);
    const spinner = document.getElementById(spinnerId);
    
    if (btn && btnText && spinner) {
        btn.disabled = loading;
        if (loading) {
            btnText.style.opacity = '0';
            spinner.classList.remove('hidden');
        } else {
            btnText.style.opacity = '1';
            spinner.classList.add('hidden');
        }
    }
}

function showError(message) {
    const errorDiv = document.getElementById('error-message');
    const errorText = document.getElementById('error-text');
    const successDiv = document.getElementById('success-message');
    
    if (errorDiv && errorText) {
        errorText.textContent = message;
        errorDiv.classList.remove('hidden');
    }
    
    if (successDiv) {
        successDiv.classList.add('hidden');
    }
    
    // Auto hide after 5 seconds
    setTimeout(hideMessages, 5000);
}

function showSuccess(message) {
    const successDiv = document.getElementById('success-message');
    const successText = document.getElementById('success-text');
    const errorDiv = document.getElementById('error-message');
    
    if (successDiv && successText) {
        successText.textContent = message;
        successDiv.classList.remove('hidden');
    }
    
    if (errorDiv) {
        errorDiv.classList.add('hidden');
    }
}

function hideMessages() {
    const errorDiv = document.getElementById('error-message');
    const successDiv = document.getElementById('success-message');
    
    if (errorDiv) errorDiv.classList.add('hidden');
    if (successDiv) successDiv.classList.add('hidden');
}

function getAuthErrorMessage(errorCode) {
    const errorMessages = {
        'auth/user-not-found': 'Bu e-posta adresi ile kayıtlı bir kullanıcı bulunamadı.',
        'auth/wrong-password': 'Şifre hatalı. Lütfen tekrar deneyin.',
        'auth/email-already-in-use': 'Bu e-posta adresi zaten kullanımda.',
        'auth/weak-password': 'Şifre çok zayıf. En az 6 karakter olmalıdır.',
        'auth/invalid-email': 'Geçersiz e-posta adresi.',
        'auth/user-disabled': 'Bu hesap devre dışı bırakılmış.',
        'auth/too-many-requests': 'Çok fazla başarısız giriş denemesi. Lütfen daha sonra tekrar deneyin.',
        'auth/network-request-failed': 'Ağ bağlantısı hatası. İnternet bağlantınızı kontrol edin.',
        'auth/internal-error': 'Bir sistem hatası oluştu. Lütfen daha sonra tekrar deneyin.'
    };
    
    return errorMessages[errorCode] || 'Bir hata oluştu. Lütfen tekrar deneyin.';
}

async function getUserIP() {
    try {
        const response = await fetch('https://api.ipify.org?format=json');
        const data = await response.json();
        return data.ip;
    } catch (error) {
        console.error('Error getting user IP:', error);
        return 'unknown';
    }
}

// Export functions for use in HTML pages
window.initAuthPage = initAuthPage;
