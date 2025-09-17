import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # --- Environment Ayarları ---
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "LIVE")
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
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
    DEFAULT_STOP_LOSS_PERCENT: float = float(os.getenv("DEFAULT_STOP_LOSS_PERCENT", "2.0"))
    DEFAULT_TAKE_PROFIT_PERCENT: float = float(os.getenv("DEFAULT_TAKE_PROFIT_PERCENT", "4.0"))
    
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
    
    # --- Sistem Limitleri ---
    MAX_BOTS_PER_USER: int = int(os.getenv("MAX_BOTS_PER_USER", "4"))
    MAX_TOTAL_SYSTEM_BOTS: int = int(os.getenv("MAX_TOTAL_SYSTEM_BOTS", "1000"))
    
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
    
    # --- Monitoring Ayarları ---
    POSITION_CHECK_INTERVAL: int = int(os.getenv("POSITION_CHECK_INTERVAL", "30"))
    SUBSCRIPTION_CHECK_INTERVAL: int = int(os.getenv("SUBSCRIPTION_CHECK_INTERVAL", "60"))
    KLINE_HISTORY_LIMIT: int = int(os.getenv("KLINE_HISTORY_LIMIT", "50"))
    WEBSOCKET_RECONNECT_DELAY: int = int(os.getenv("WEBSOCKET_RECONNECT_DELAY", "5"))
    
    # --- Logging Ayarları ---
    ENABLE_DEBUG_LOGS: bool = os.getenv("ENABLE_DEBUG_LOGS", "False").lower() == "true"
    LOG_TO_FILE: bool = os.getenv("LOG_TO_FILE", "False").lower() == "true"
    LOG_FILE_PATH: str = os.getenv("LOG_FILE_PATH", "logs/trading_bot.log")
    
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
    
    # --- Performance Ayarları ---
    MAX_REQUESTS_PER_MINUTE: int = API_RATE_LIMIT_PER_MINUTE
    CACHE_DURATION_BALANCE: int = 10
    CACHE_DURATION_POSITION: int = 5
    CACHE_DURATION_PNL: int = 3
    
    # --- WebSocket Ayarları ---
    WEBSOCKET_PING_INTERVAL: int = 30
    WEBSOCKET_PING_TIMEOUT: int = 15
    WEBSOCKET_CLOSE_TIMEOUT: int = 10
    WEBSOCKET_MAX_RECONNECTS: int = 10
    
    # --- Status Update Intervals ---
    STATUS_UPDATE_INTERVAL: int = 10
    BALANCE_UPDATE_INTERVAL: int = 30

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
        
        for warning in warnings:
            print(warning)
        
        return len(warnings) == 0

    @classmethod
    def get_firebase_web_config(cls):
        """Frontend için Firebase web config döndür"""
        return {
            "apiKey": cls.FIREBASE_WEB_API_KEY,
            "authDomain": cls.FIREBASE_WEB_AUTH_DOMAIN,
            "databaseURL": cls.FIREBASE_DATABASE_URL,
            "projectId": cls.FIREBASE_WEB_PROJECT_ID,
            "storageBucket": cls.FIREBASE_WEB_STORAGE_BUCKET,
            "messagingSenderId": cls.FIREBASE_WEB_MESSAGING_SENDER_ID,
            "appId": cls.FIREBASE_WEB_APP_ID
        }
    @classmethod
    def print_settings(cls):
        """Environment'dan yüklenen ayarları yazdır"""
        print("=" * 60)
        print("🚀 EZYAGOTRADING BOT AYARLARI")
        print("=" * 60)
        print(f"🌐 Ortam: {cls.ENVIRONMENT}")
        print(f"🐛 Debug Mode: {cls.DEBUG}")
        print(f"🔧 Maintenance: {cls.MAINTENANCE_MODE}")
        print(f"💰 Varsayılan İşlem: {cls.DEFAULT_ORDER_SIZE_USDT} USDT")
        print(f"📈 Varsayılan Kaldıraç: {cls.DEFAULT_LEVERAGE}x")
        print(f"⏰ Varsayılan Timeframe: {cls.DEFAULT_TIMEFRAME}")
        print(f"🛑 Stop Loss: %{cls.DEFAULT_STOP_LOSS_PERCENT}")
        print(f"🎯 Take Profit: %{cls.DEFAULT_TAKE_PROFIT_PERCENT}")
        print(f"📊 EMA Periyotları: {cls.EMA_SHORT_PERIOD}/{cls.EMA_LONG_PERIOD}")
        print(f"🔄 Rate Limit: {cls.API_RATE_LIMIT_PER_MINUTE}/dakika")
        print(f"💳 Bot Fiyatı: ${cls.BOT_PRICE_USD}")
        print(f"🎁 Deneme Süresi: {cls.TRIAL_PERIOD_DAYS} gün")
        print("=" * 60)
        print("💡 Tüm ayarlar environment variables'dan yüklendi")
        print("🔒 Firebase ve API bilgileri güvenli şekilde saklanıyor")
        print("=" * 60)

settings = Settings()

    @classmethod
    def get_firebase_web_config(cls):
        """Frontend için Firebase web config döndür"""
        return {
            "apiKey": cls.FIREBASE_WEB_API_KEY,
            "authDomain": cls.FIREBASE_WEB_AUTH_DOMAIN,
            "databaseURL": cls.FIREBASE_DATABASE_URL,
            "projectId": cls.FIREBASE_WEB_PROJECT_ID,
            "storageBucket": cls.FIREBASE_WEB_STORAGE_BUCKET,
            "messagingSenderId": cls.FIREBASE_WEB_MESSAGING_SENDER_ID,
            "appId": cls.FIREBASE_WEB_APP_ID
        }
