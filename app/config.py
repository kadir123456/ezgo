import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # --- Temel Ayarlar ---
    API_KEY: str = os.getenv("BINANCE_API_KEY")
    API_SECRET: str = os.getenv("BINANCE_API_SECRET")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "LIVE")
    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "admin")
    BOT_PASSWORD: str = os.getenv("BOT_PASSWORD", "changeme123")
    
    # --- Firebase Ayarları ---
    FIREBASE_CREDENTIALS_JSON: str = os.getenv("FIREBASE_CREDENTIALS_JSON")
    FIREBASE_DATABASE_URL: str = os.getenv("FIREBASE_DATABASE_URL")
    FIREBASE_WEB_API_KEY: str = os.getenv("FIREBASE_WEB_API_KEY")
    FIREBASE_WEB_AUTH_DOMAIN: str = os.getenv("FIREBASE_WEB_AUTH_DOMAIN")
    FIREBASE_WEB_PROJECT_ID: str = os.getenv("FIREBASE_WEB_PROJECT_ID")
    FIREBASE_WEB_STORAGE_BUCKET: str = os.getenv("FIREBASE_WEB_STORAGE_BUCKET")
    FIREBASE_WEB_MESSAGING_SENDER_ID: str = os.getenv("FIREBASE_WEB_MESSAGING_SENDER_ID")
    FIREBASE_WEB_APP_ID: str = os.getenv("FIREBASE_WEB_APP_ID")
    
    # --- Güvenlik Ayarları ---
    ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY")
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL")
    
    # --- Uygulama Ayarları ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    BASE_URL = "https://fapi.binance.com" if os.getenv("ENVIRONMENT", "TEST") == "LIVE" else "https://testnet.binancefuture.com"
    WEBSOCKET_URL = "wss://fstream.binance.com" if os.getenv("ENVIRONMENT", "TEST") == "LIVE" else "wss://stream.binancefuture.com"

    # --- İşlem Parametreleri ---
    LEVERAGE: int = 10
    ORDER_SIZE_USDT: float = 35.0
    TIMEFRAME: str = "30m"
    
    # --- Kâr/Zarar Ayarları (Stop Loss ve Take Profit) ---
    # CRITICAL: Bu değerler float olmalı, callable değil!
    STOP_LOSS_PERCENT: float = 0.008   # %0.8 Zarar Durdur
    TAKE_PROFIT_PERCENT: float = 0.01 # %1.2 Kar Al (optimize edilmiş)
    
    # --- Rate Limiting ve Performance Ayarları ---
    MAX_REQUESTS_PER_MINUTE: int = 1200
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
        """Ayarları doğrula ve gerekirse uyar"""
        warnings = []
        
        if not cls.API_KEY or not cls.API_SECRET:
            warnings.append("⚠️ BINANCE_API_KEY veya BINANCE_API_SECRET ayarlanmamış!")
        
        if cls.LEVERAGE < 1 or cls.LEVERAGE > 125:
            warnings.append(f"⚠️ Kaldıraç değeri geçersiz: {cls.LEVERAGE}. 1-125 arası olmalı.")
        
        if cls.ORDER_SIZE_USDT < 5:
            warnings.append(f"⚠️ İşlem miktarı çok düşük: {cls.ORDER_SIZE_USDT}. Minimum 5 USDT önerilir.")
        
        # Float kontrolü ekle
        if not isinstance(cls.STOP_LOSS_PERCENT, (int, float)) or cls.STOP_LOSS_PERCENT <= 0 or cls.STOP_LOSS_PERCENT >= 1:
            warnings.append(f"⚠️ Stop Loss yüzdesi geçersiz: {cls.STOP_LOSS_PERCENT}. 0-1 arası float olmalı.")
        
        if not isinstance(cls.TAKE_PROFIT_PERCENT, (int, float)) or cls.TAKE_PROFIT_PERCENT <= 0 or cls.TAKE_PROFIT_PERCENT >= 1:
            warnings.append(f"⚠️ Take Profit yüzdesi geçersiz: {cls.TAKE_PROFIT_PERCENT}. 0-1 arası float olmalı.")
        
        # Rate limit kontrolü
        if cls.MAX_REQUESTS_PER_MINUTE > 2000:
            warnings.append(f"⚠️ Dakikada maksimum istek sayısı yüksek: {cls.MAX_REQUESTS_PER_MINUTE}. Rate limit riski!")
        
        for warning in warnings:
            print(warning)
        
        return len(warnings) == 0

    @classmethod
    def print_settings(cls):
        """Mevcut ayarları yazdır"""
        print("=" * 60)
        print("🚀 OPTIMIZE EDİLMİŞ BOT AYARLARI")
        print("=" * 60)
        print(f"🌐 Ortam: {cls.ENVIRONMENT}")
        print(f"💰 İşlem Miktarı: {cls.ORDER_SIZE_USDT} USDT")
        print(f"📈 Kaldıraç: {cls.LEVERAGE}x")
        print(f"⏰ Zaman Dilimi: {cls.TIMEFRAME} ⭐ (Optimize)")
        print(f"🛑 Stop Loss: %{cls.STOP_LOSS_PERCENT * 100:.1f}")
        print(f"🎯 Take Profit: %{cls.TAKE_PROFIT_PERCENT * 100:.1f}")
        print(f"📈 Risk/Reward Oranı: 1:{cls.TAKE_PROFIT_PERCENT/cls.STOP_LOSS_PERCENT:.1f}")
        print(f"🔄 Maks. İstek/Dakika: {cls.MAX_REQUESTS_PER_MINUTE}")
        print(f"💾 Cache Süreleri: Bakiye={cls.CACHE_DURATION_BALANCE}s, Pozisyon={cls.CACHE_DURATION_POSITION}s")
        print(f"🌐 WebSocket: Ping={cls.WEBSOCKET_PING_INTERVAL}s, Timeout={cls.WEBSOCKET_PING_TIMEOUT}s")
        print("=" * 60)
        print("💡 15m + EMA(9,21) kombinasyonu crypto futures için optimize edilmiştir")
        print("🎯 Risk/Reward oranı 1:1.5 - optimal kar/zarar dengesi")
        print("=" * 60)

settings = Settings()

# Başlangıçta ayarları doğrula
if __name__ == "__main__":
    settings.validate_settings()
    settings.print_settings()
