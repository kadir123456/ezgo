import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # --- Environment Ayarları ---
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "LIVE")
    DEBUG: bool = os.getenv("DEBUG", "True").lower() == "true"  # Development için True
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    MAINTENANCE_MODE: bool = os.getenv("MAINTENANCE_MODE", "False").lower() == "true"
    MAINTENANCE_MESSAGE: str = os.getenv("MAINTENANCE_MESSAGE", "Sistem bakımda.")
    
    # --- Firebase Ayarları ---
    FIREBASE_CREDENTIALS_JSON: str = os.getenv("FIREBASE_CREDENTIALS_JSON")
    FIREBASE_DATABASE_URL: str = os.getenv("FIREBASE_DATABASE_URL")
    
    # Firebase Web SDK (Frontend için)
    FIREBASE_WEB_API_KEY: str = os.getenv("FIREBASE_WEB_API_KEY")
    FIREBASE_WEB_AUTH_DOMAIN: str = os.getenv("FIREBASE_WEB_AUTH_DOMAIN")
    FIREBASE_WEB_PROJECT_ID: str = os.getenv("FIREBASE_WEB_PROJECT_ID")
    FIREBASE_WEB_STORAGE_BUCKET: str = os.getenv("FIREBASE_WEB_STORAGE_BUCKET")
    FIREBASE_WEB_MESSAGING_SENDER_ID: str = os.getenv("FIREBASE_WEB_MESSAGING_SENDER_ID")
    FIREBASE_WEB_APP_ID: str = os.getenv("FIREBASE_WEB_APP_ID")
    FIREBASE_WEB_MEASUREMENT_ID: str = os.getenv("FIREBASE_WEB_MEASUREMENT_ID", "")
    
    # --- Güvenlik Ayarları ---
    ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY")
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL")
    SERVER_IPS: str = os.getenv("SERVER_IPS", "")
    
    # --- API Ayarları ---
    API_BASE_URL: str = os.getenv("API_BASE_URL", "https://www.ezyago.com/api")
    API_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("API_RATE_LIMIT_PER_MINUTE", "1200"))
    
    # --- Bot Ayarları ---
    DEFAULT_LEVERAGE: int = int(os.getenv("DEFAULT_LEVERAGE", "10"))
    DEFAULT_ORDER_SIZE_USDT: float = float(os.getenv("DEFAULT_ORDER_SIZE_USDT", "20.0"))
    DEFAULT_TIMEFRAME: str = os.getenv("DEFAULT_TIMEFRAME", "15m")
    DEFAULT_STOP_LOSS_PERCENT: float = float(os.getenv("DEFAULT_STOP_LOSS_PERCENT", "0.3"))
    DEFAULT_TAKE_PROFIT_PERCENT: float = float(os.getenv("DEFAULT_TAKE_PROFIT_PERCENT", "0.5"))
    
    # --- EMA Ayarları ---
    EMA_SHORT_PERIOD: int = int(os.getenv("EMA_SHORT_PERIOD", "9"))
    EMA_LONG_PERIOD: int = int(os.getenv("EMA_LONG_PERIOD", "21"))
    
    # --- Limit Ayarları ---
    MIN_LEVERAGE: int = int(os.getenv("MIN_LEVERAGE", "1"))
    MAX_LEVERAGE: int = int(os.getenv("MAX_LEVERAGE", "125"))
    MIN_ORDER_SIZE_USDT: float = float(os.getenv("MIN_ORDER_SIZE_USDT", "10.0"))
    MAX_ORDER_SIZE_USDT: float = float(os.getenv("MAX_ORDER_SIZE_USDT", "10000.0"))
    MIN_STOP_LOSS_PERCENT: float = float(os.getenv("MIN_STOP_LOSS_PERCENT", "0.5"))
    MAX_STOP_LOSS_PERCENT: float = float(os.getenv("MAX_STOP_LOSS_PERCENT", "25.0"))
    MIN_TAKE_PROFIT_PERCENT: float = float(os.getenv("MIN_TAKE_PROFIT_PERCENT", "0.5"))
    MAX_TAKE_PROFIT_PERCENT: float = float(os.getenv("MAX_TAKE_PROFIT_PERCENT", "50.0"))
    
    # --- Sistem Limitleri (UPDATED - Scalable) ---
    MAX_BOTS_PER_USER: int = int(os.getenv("MAX_BOTS_PER_USER", "4"))
    MAX_TOTAL_SYSTEM_BOTS: int = int(os.getenv("MAX_TOTAL_SYSTEM_BOTS", "10000"))  # Increased from 1000
    
    # --- Demo Mode ---
    DEMO_MODE_ENABLED: bool = os.getenv("DEMO_MODE_ENABLED", "True").lower() == "true"
    DEMO_BALANCE_USDT: float = float(os.getenv("DEMO_BALANCE_USDT", "1000.0"))
    MOCK_BINANCE_API: bool = os.getenv("MOCK_BINANCE_API", "False").lower() == "true"
    
    # --- Abonelik Ayarları ---
    TRIAL_PERIOD_DAYS: int = int(os.getenv("TRIAL_PERIOD_DAYS", "7"))
    MONTHLY_SUBSCRIPTION_PRICE: float = float(os.getenv("MONTHLY_SUBSCRIPTION_PRICE", "15.0"))
    BOT_PRICE_USD: float = float(os.getenv("BOT_PRICE_USD", "15"))
    
    # --- Ödeme Ayarları ---
    PAYMENT_TRC20_ADDRESS: str = os.getenv("PAYMENT_TRC20_ADDRESS")
    
    # ========================================
    # NEW SCALABLE INTERVAL SETTINGS (3-MINUTE APPROACH)
    # ========================================
    
    # --- Core Interval Settings (Scalable Architecture) ---
    # Balance checks - 3 minutes (reduces API calls by 6x)
    BALANCE_UPDATE_INTERVAL: int = int(os.getenv("BALANCE_UPDATE_INTERVAL", "180"))  # 3 minutes
    
    # Position checks - 1 minute (reasonable for crypto trading)
    POSITION_CHECK_INTERVAL: int = int(os.getenv("POSITION_CHECK_INTERVAL", "60"))   # 1 minute
    
    # Firebase batch updates - 3 minutes (reduces Firebase costs by 6x)
    FIREBASE_BATCH_INTERVAL: int = int(os.getenv("FIREBASE_BATCH_INTERVAL", "180"))  # 3 minutes
    
    # Global monitor cycle - 30 seconds (internal loop)
    MONITOR_CYCLE_INTERVAL: int = int(os.getenv("MONITOR_CYCLE_INTERVAL", "30"))     # 30 seconds
    
    # --- Rate Limiting Settings (Connection Pool) ---
    # Max API calls per 3-minute window per shared client
    RATE_LIMIT_MAX_CALLS_PER_WINDOW: int = int(os.getenv("RATE_LIMIT_MAX_CALLS_PER_WINDOW", "20"))
    RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "180"))  # 3 minutes
    
    # --- Connection Pool Settings ---
    # Client cleanup after 10 minutes of inactivity
    CLIENT_CLEANUP_THRESHOLD: int = int(os.getenv("CLIENT_CLEANUP_THRESHOLD", "600"))  # 10 minutes
    
    # Max shared clients before forced cleanup
    MAX_SHARED_CLIENTS: int = int(os.getenv("MAX_SHARED_CLIENTS", "50"))
    
    # --- WebSocket Settings (Shared) ---
    WEBSOCKET_PING_INTERVAL: int = int(os.getenv("WEBSOCKET_PING_INTERVAL", "30"))
    WEBSOCKET_PING_TIMEOUT: int = int(os.getenv("WEBSOCKET_PING_TIMEOUT", "15"))
    WEBSOCKET_CLOSE_TIMEOUT: int = int(os.getenv("WEBSOCKET_CLOSE_TIMEOUT", "10"))
    WEBSOCKET_MAX_RECONNECTS: int = int(os.getenv("WEBSOCKET_MAX_RECONNECTS", "10"))
    WEBSOCKET_RECONNECT_DELAY: int = int(os.getenv("WEBSOCKET_RECONNECT_DELAY", "5"))
    
    # --- Cache Settings (Optimized) ---
    # Balance cache duration (use cached data to reduce API calls)
    CACHE_DURATION_BALANCE: int = int(os.getenv("CACHE_DURATION_BALANCE", "60"))      # 1 minute
    CACHE_DURATION_POSITION: int = int(os.getenv("CACHE_DURATION_POSITION", "30"))   # 30 seconds
    CACHE_DURATION_PNL: int = int(os.getenv("CACHE_DURATION_PNL", "15"))             # 15 seconds
    
    # --- Legacy Monitoring Ayarları (Deprecated but kept for compatibility) ---
    SUBSCRIPTION_CHECK_INTERVAL: int = int(os.getenv("SUBSCRIPTION_CHECK_INTERVAL", "300"))  # 5 minutes
    KLINE_HISTORY_LIMIT: int = int(os.getenv("KLINE_HISTORY_LIMIT", "50"))
    
    # --- Performance Ayarları (Updated) ---
    MAX_REQUESTS_PER_MINUTE: int = API_RATE_LIMIT_PER_MINUTE
    
    # Status update for UI (can be frequent as it's lightweight)
    STATUS_UPDATE_INTERVAL: int = int(os.getenv("STATUS_UPDATE_INTERVAL", "10"))
    
    # ========================================
    # SCALING THRESHOLDS AND ALERTS
    # ========================================
    
    # System health thresholds
    SYSTEM_HIGH_LOAD_THRESHOLD: int = int(os.getenv("SYSTEM_HIGH_LOAD_THRESHOLD", "500"))    # 500+ users = high load
    SYSTEM_CRITICAL_LOAD_THRESHOLD: int = int(os.getenv("SYSTEM_CRITICAL_LOAD_THRESHOLD", "800"))  # 800+ users = critical
    
    # Memory usage alerts (MB)
    MEMORY_WARNING_THRESHOLD: int = int(os.getenv("MEMORY_WARNING_THRESHOLD", "2048"))       # 2GB warning
    MEMORY_CRITICAL_THRESHOLD: int = int(os.getenv("MEMORY_CRITICAL_THRESHOLD", "4096"))     # 4GB critical
    
    # ========================================
    # LEGACY SETTINGS (Backward Compatibility)
    # ========================================
    
    # --- Binance URL'leri ---
    BASE_URL = "https://fapi.binance.com" if ENVIRONMENT == "LIVE" else "https://testnet.binancefuture.com"
    WEBSOCKET_URL = "wss://fstream.binance.com" if ENVIRONMENT == "LIVE" else "wss://stream.binancefuture.com"

    # --- Binance API (Fallback - gerçekte kullanıcıdan alınacak) ---
    BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
    BINANCE_API_SECRET: str = os.getenv("BINANCE_API_SECRET", "")
    
    # --- Backward Compatibility ---
    LEVERAGE: int = DEFAULT_LEVERAGE
    ORDER_SIZE_USDT: float = DEFAULT_ORDER_SIZE_USDT
    TIMEFRAME: str = DEFAULT_TIMEFRAME
    STOP_LOSS_PERCENT: float = DEFAULT_STOP_LOSS_PERCENT / 100.0  # Convert to decimal
    TAKE_PROFIT_PERCENT: float = DEFAULT_TAKE_PROFIT_PERCENT / 100.0  # Convert to decimal
    
    # --- Logging Ayarları ---
    ENABLE_DEBUG_LOGS: bool = os.getenv("ENABLE_DEBUG_LOGS", "False").lower() == "true"
    LOG_TO_FILE: bool = os.getenv("LOG_TO_FILE", "False").lower() == "true"
    LOG_FILE_PATH: str = os.getenv("LOG_FILE_PATH", "logs/trading_bot.log")

    @classmethod
    def get_scalability_info(cls):
        """Scalability ayarları hakkında bilgi döndür"""
        return {
            "architecture": "optimized_scalable",
            "intervals": {
                "balance_update": f"{cls.BALANCE_UPDATE_INTERVAL}s (3 min)",
                "position_check": f"{cls.POSITION_CHECK_INTERVAL}s (1 min)",
                "firebase_batch": f"{cls.FIREBASE_BATCH_INTERVAL}s (3 min)",
                "monitor_cycle": f"{cls.MONITOR_CYCLE_INTERVAL}s"
            },
            "rate_limiting": {
                "max_calls_per_window": cls.RATE_LIMIT_MAX_CALLS_PER_WINDOW,
                "window_duration": f"{cls.RATE_LIMIT_WINDOW_SECONDS}s",
                "estimated_capacity": f"{cls.RATE_LIMIT_MAX_CALLS_PER_WINDOW * 50} API calls/3min"
            },
            "connection_pool": {
                "max_shared_clients": cls.MAX_SHARED_CLIENTS,
                "cleanup_threshold": f"{cls.CLIENT_CLEANUP_THRESHOLD}s",
                "estimated_user_capacity": f"{cls.MAX_SHARED_CLIENTS * 20}+ users"
            },
            "system_limits": {
                "max_total_bots": cls.MAX_TOTAL_SYSTEM_BOTS,
                "high_load_threshold": cls.SYSTEM_HIGH_LOAD_THRESHOLD,
                "critical_load_threshold": cls.SYSTEM_CRITICAL_LOAD_THRESHOLD
            }
        }

    @classmethod
    def validate_settings(cls):
        """Environment variables'ları doğrula"""
        warnings = []
        
        # Firebase kontrolü
        if not cls.FIREBASE_CREDENTIALS_JSON:
            warnings.append("⚠️ FIREBASE_CREDENTIALS_JSON ayarlanmamış!")
        
        if not cls.FIREBASE_DATABASE_URL:
            warnings.append("⚠️ FIREBASE_DATABASE_URL ayarlanmamış!")
        
        if not cls.FIREBASE_WEB_API_KEY:
            warnings.append("⚠️ FIREBASE_WEB_API_KEY ayarlanmamış!")
        
        if not cls.FIREBASE_WEB_PROJECT_ID:
            warnings.append("⚠️ FIREBASE_WEB_PROJECT_ID ayarlanmamış!")
        
        if not cls.FIREBASE_WEB_AUTH_DOMAIN:
            warnings.append("⚠️ FIREBASE_WEB_AUTH_DOMAIN ayarlanmamış!")
        
        # Güvenlik kontrolü
        if not cls.ENCRYPTION_KEY:
            warnings.append("⚠️ ENCRYPTION_KEY ayarlanmamış!")
        
        if not cls.ADMIN_EMAIL:
            warnings.append("⚠️ ADMIN_EMAIL ayarlanmamış!")
        
        # Bot ayarları kontrolü
        if cls.DEFAULT_LEVERAGE < cls.MIN_LEVERAGE or cls.DEFAULT_LEVERAGE > cls.MAX_LEVERAGE:
            warnings.append(f"⚠️ DEFAULT_LEVERAGE geçersiz: {cls.DEFAULT_LEVERAGE}. {cls.MIN_LEVERAGE}-{cls.MAX_LEVERAGE} arası olmalı.")
        
        if cls.DEFAULT_ORDER_SIZE_USDT < cls.MIN_ORDER_SIZE_USDT:
            warnings.append(f"⚠️ DEFAULT_ORDER_SIZE_USDT çok düşük: {cls.DEFAULT_ORDER_SIZE_USDT}. Minimum {cls.MIN_ORDER_SIZE_USDT} USDT.")
        
        # Yüzde kontrolü
        if cls.DEFAULT_STOP_LOSS_PERCENT < cls.MIN_STOP_LOSS_PERCENT or cls.DEFAULT_STOP_LOSS_PERCENT > cls.MAX_STOP_LOSS_PERCENT:
            warnings.append(f"⚠️ DEFAULT_STOP_LOSS_PERCENT geçersiz: {cls.DEFAULT_STOP_LOSS_PERCENT}%")
        
        if cls.DEFAULT_TAKE_PROFIT_PERCENT < cls.MIN_TAKE_PROFIT_PERCENT or cls.DEFAULT_TAKE_PROFIT_PERCENT > cls.MAX_TAKE_PROFIT_PERCENT:
            warnings.append(f"⚠️ DEFAULT_TAKE_PROFIT_PERCENT geçersiz: {cls.DEFAULT_TAKE_PROFIT_PERCENT}%")
        
        # Ödeme kontrolü
        if not cls.PAYMENT_TRC20_ADDRESS:
            warnings.append("⚠️ PAYMENT_TRC20_ADDRESS ayarlanmamış!")
        
        # Scalability validation (NEW)
        if cls.BALANCE_UPDATE_INTERVAL < 60:
            warnings.append(f"⚠️ BALANCE_UPDATE_INTERVAL çok düşük: {cls.BALANCE_UPDATE_INTERVAL}s. Minimum 60s önerilir.")
        
        if cls.RATE_LIMIT_MAX_CALLS_PER_WINDOW > 50:
            warnings.append(f"⚠️ RATE_LIMIT_MAX_CALLS_PER_WINDOW çok yüksek: {cls.RATE_LIMIT_MAX_CALLS_PER_WINDOW}. Maximum 50 önerilir.")
        
        if cls.MAX_SHARED_CLIENTS > 100:
            warnings.append(f"⚠️ MAX_SHARED_CLIENTS çok yüksek: {cls.MAX_SHARED_CLIENTS}. Maximum 100 önerilir.")
        
        for warning in warnings:
            print(warning)
        
        return len(warnings) == 0

    @classmethod
    def print_settings(cls):
        """Environment'dan yüklenen ayarları yazdır"""
        print("=" * 70)
        print("🚀 EZYAGOTRADING BOT AYARLARI (SCALABLE)")
        print("=" * 70)
        print(f"🌐 Ortam: {cls.ENVIRONMENT}")
        print(f"🐛 Debug Mode: {cls.DEBUG}")
        print(f"🔧 Maintenance: {cls.MAINTENANCE_MODE}")
        print(f"💰 Varsayılan İşlem: {cls.DEFAULT_ORDER_SIZE_USDT} USDT")
        print(f"📈 Varsayılan Kaldıraç: {cls.DEFAULT_LEVERAGE}x")
        print(f"⏰ Varsayılan Timeframe: {cls.DEFAULT_TIMEFRAME}")
        print(f"🛑 Stop Loss: %{cls.DEFAULT_STOP_LOSS_PERCENT}")
        print(f"🎯 Take Profit: %{cls.DEFAULT_TAKE_PROFIT_PERCENT}")
        print(f"📊 EMA Periyotları: {cls.EMA_SHORT_PERIOD}/{cls.EMA_LONG_PERIOD}")
        print("-" * 70)
        print("🔄 SCALABLE INTERVALS:")
        print(f"  💰 Balance Update: {cls.BALANCE_UPDATE_INTERVAL}s (3 min)")
        print(f"  📈 Position Check: {cls.POSITION_CHECK_INTERVAL}s (1 min)")
        print(f"  💾 Firebase Batch: {cls.FIREBASE_BATCH_INTERVAL}s (3 min)")
        print(f"  📡 Monitor Cycle: {cls.MONITOR_CYCLE_INTERVAL}s")
        print("-" * 70)
        print("🎯 CONNECTION POOL:")
        print(f"  🔗 Max Shared Clients: {cls.MAX_SHARED_CLIENTS}")
        print(f"  ⏱️ Cleanup Threshold: {cls.CLIENT_CLEANUP_THRESHOLD}s")
        print(f"  🚦 Rate Limit: {cls.RATE_LIMIT_MAX_CALLS_PER_WINDOW} calls/{cls.RATE_LIMIT_WINDOW_SECONDS}s")
        print("-" * 70)
        print("📊 SYSTEM CAPACITY:")
        print(f"  👥 Max Total Bots: {cls.MAX_TOTAL_SYSTEM_BOTS}")
        print(f"  ⚠️ High Load Threshold: {cls.SYSTEM_HIGH_LOAD_THRESHOLD} users")
        print(f"  🚨 Critical Load Threshold: {cls.SYSTEM_CRITICAL_LOAD_THRESHOLD} users")
        print("-" * 70)
        print(f"💳 Bot Fiyatı: ${cls.BOT_PRICE_USD}")
        print(f"🎁 Deneme Süresi: {cls.TRIAL_PERIOD_DAYS} gün")
        print("=" * 70)
        print("💡 Scalable architecture - 1000+ kullanıcı desteği")
        print("🔒 Connection pooling ve batch operations aktif")
        print("📉 %90 daha az API call ve Firebase cost")
        print("=" * 70)

# Global settings instance
settings = Settings()
