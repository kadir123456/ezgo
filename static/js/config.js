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

            // App info'yu backend'den al
            const appResponse = await fetch('/api/app-info');
            if (!appResponse.ok) {
                throw new Error(`App info HTTP ${appResponse.status}`);
            }
            this.appInfo = await appResponse.json();

            this.isLoaded = true;
            
            console.log('Configurations loaded from backend');
            return {
                firebase: this.firebaseConfig,
                app: this.appInfo
            };
            
        } catch (error) {
            console.error('Failed to load configurations:', error);
            throw new Error('System configuration could not be loaded');
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
        await window.configLoader.loadConfigurations();
        console.log('✅ All configurations loaded successfully');
    } catch (error) {
        console.error('❌ Configuration loading failed:', error);
    }
});
