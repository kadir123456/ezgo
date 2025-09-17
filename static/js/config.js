// Configuration loader for EzyagoTrading frontend
class ConfigLoader {
    constructor() {
        this.firebaseConfig = null;
        this.appInfo = null;
        this.isLoaded = false;
    }

    async loadConfigurations() {
        if (this.isLoaded) {
            return {
                firebase: this.firebaseConfig,
                app: this.appInfo
            };
        }

        try {
            // Firebase config'i backend'den al
            const firebaseResponse = await fetch('/api/firebase-config');
            if (!firebaseResponse.ok) {
                throw new Error(`Firebase config HTTP ${firebaseResponse.status}`);
            }
            this.firebaseConfig = await firebaseResponse.json();
            
            // Firebase config'in geçerli olduğunu kontrol et
            const requiredFields = ['apiKey', 'authDomain', 'projectId', 'appId'];
            const missingFields = requiredFields.filter(field => !this.firebaseConfig[field]);
            
            if (missingFields.length > 0) {
                throw new Error(`Missing Firebase config fields: ${missingFields.join(', ')}`);
            }

            // App info'yu backend'den al
            const appResponse = await fetch('/api/app-info');
            if (!appResponse.ok) {
                throw new Error(`App info HTTP ${appResponse.status}`);
            }
            this.appInfo = await appResponse.json();

            this.isLoaded = true;
            
            console.log('✅ Configurations loaded from backend environment variables');
            console.log('Firebase Project ID:', this.firebaseConfig.projectId);
            console.log('Payment Address:', this.appInfo.payment_address);
            
            return {
                firebase: this.firebaseConfig,
                app: this.appInfo
            };
            
        } catch (error) {
            console.error('❌ Failed to load configurations from backend:', error);
            
            // Hata durumunda kullanıcıya bilgi ver
            alert(`Konfigürasyon yüklenemedi: ${error.message}\n\nLütfen sayfayı yenileyin veya destek ile iletişime geçin.`);
            
            // Fallback config KALDIRILDI - sadece backend'den alınacak
            throw error;
        }
    }

    async getFirebaseConfig() {
        if (!this.firebaseConfig) {
            await this.loadConfigurations();
        }
        return this.firebaseConfig;
    }

    async getAppInfo() {
        if (!this.appInfo) {
            await this.loadConfigurations();
        }
        return this.appInfo;
    }

    isConfigLoaded() {
        return this.isLoaded && this.firebaseConfig !== null && this.appInfo !== null;
    }

    // Utility methods
    getPaymentAddress() {
        return this.appInfo?.payment_address || 'Ödeme adresi yüklenemedi';
    }

    getBotPrice() {
        return this.appInfo?.bot_price || 15;
    }

    getTrialDays() {
        return this.appInfo?.trial_days || 7;
    }

    isDemoMode() {
        return this.appInfo?.demo_mode || false;
    }

    isMaintenanceMode() {
        return this.appInfo?.maintenance_mode || false;
    }

    // Debug method
    logCurrentConfig() {
        console.log('🔧 Current Configuration:');
        console.log('Firebase Config:', this.firebaseConfig);
        console.log('App Info:', this.appInfo);
        console.log('Is Loaded:', this.isLoaded);
    }
}

// Global instance
window.configLoader = new ConfigLoader();

// Helper functions for backward compatibility
window.getFirebaseConfig = async function() {
    return await window.configLoader.getFirebaseConfig();
};

window.getAppInfo = async function() {
    return await window.configLoader.getAppInfo();
};

// Initialize configurations on page load
document.addEventListener('DOMContentLoaded', async () => {
    try {
        console.log('🔄 Loading configurations from environment variables...');
        await window.configLoader.loadConfigurations();
        console.log('✅ All configurations loaded successfully from backend');
        
        // Debug için config'i logla
        if (window.location.search.includes('debug=true')) {
            window.configLoader.logCurrentConfig();
        }
    } catch (error) {
        console.error('❌ Configuration loading failed:', error);
        
        // Kullanıcıya hata mesajı göster
        const errorDiv = document.createElement('div');
        errorDiv.style.cssText = `
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: #dc2626;
            color: white;
            padding: 1rem 2rem;
            border-radius: 0.5rem;
            z-index: 10000;
            font-family: Inter, sans-serif;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        `;
        errorDiv.innerHTML = `
            <div style="display: flex; align-items: center; gap: 0.5rem;">
                <i class="fas fa-exclamation-triangle"></i>
                <span>Sistem yapılandırması yüklenemedi. Lütfen sayfayı yenileyin.</span>
            </div>
        `;
        document.body.appendChild(errorDiv);
        
        // 5 saniye sonra otomatik yenile
        setTimeout(() => {
            window.location.reload();
        }, 5000);
    }
});
