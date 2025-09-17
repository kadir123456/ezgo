# main.py - API ve Firebase Realtime Database Entegrasyonu ile Multi-User Bot Backend

import asyncio
import time
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from fastapi.security import HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict
import logging
import firebase_admin
from firebase_admin import credentials, db, auth
import os
import json
from dataclasses import dataclass
from datetime import datetime, timezone
import math

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Firebase ve Bot Ayarları
__firebase_config = os.getenv("FIREBASE_CONFIG")
__app_id = os.getenv("APP_ID", "default-app-id")

class Settings:
    # --- Temel Ayarlar ---
    API_KEY: str = os.getenv("BINANCE_API_KEY")
    API_SECRET: str = os.getenv("BINANCE_API_SECRET")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "TEST")
    BASE_URL = "https://fapi.binance.com" if ENVIRONMENT == "LIVE" else "https://testnet.binancefuture.com"

    # --- İşlem Parametreleri (Kullanıcı Tarafından Ayarlanır) ---
    LEVERAGE: int = 10
    ORDER_SIZE_USDT: float = 35.0
    TIMEFRAME: str = "30m"
    STOP_LOSS_PERCENT: float = 0.008
    TAKE_PROFIT_PERCENT: float = 0.01

settings = Settings()

# Firebase Realtime Database Manager
class FirebaseManager:
    def __init__(self):
        self.db = None
        self.is_initialized = False

    async def initialize_firebase(self):
        if not self.is_initialized:
            try:
                # app_id ve firebase config global değişkenlerini kullan
                firebase_config = json.loads(__firebase_config)
                
                # Realtime Database için servis hesabı kimlik bilgileri ve databaseURL gerekli
                cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
                database_url = firebase_config.get("databaseURL")

                if cred_path and os.path.exists(cred_path) and database_url:
                    cred = credentials.Certificate(cred_path)
                    firebase_admin.initialize_app(cred, {'databaseURL': database_url})
                    self.db = db.reference('/')
                    self.is_initialized = True
                    print("Firebase (Admin SDK & Realtime DB) başarıyla başlatıldı.")
                else:
                    print("UYARI: Firebase kimlik bilgileri veya databaseURL bulunamadı.")

            except Exception as e:
                print(f"Firebase başlatılırken hata oluştu: {e}")
                
    async def get_user_settings(self, user_id: str) -> dict:
        try:
            settings_ref = self.db.child('artifacts').child(__app_id).child('users').child(user_id).child('settings')
            snapshot = settings_ref.get()
            return snapshot or {}
        except Exception as e:
            logger.error(f"Kullanıcı ayarları alınamadı: {e}")
            return {}

    async def update_user_settings(self, user_id: str, settings_data: dict):
        try:
            settings_ref = self.db.child('artifacts').child(__app_id).child('users').child(user_id).child('settings')
            settings_ref.update(settings_data)
            logger.info(f"Kullanıcı {user_id} için ayarlar güncellendi.")
        except Exception as e:
            logger.error(f"Kullanıcı ayarları kaydedilemedi: {e}")

    async def log_trade(self, user_id: str, trade_data: dict):
        try:
            trade_data['timestamp'] = datetime.utcnow().isoformat()
            trades_ref = self.db.child('artifacts').child(__app_id).child('users').child(user_id).child('trades')
            trades_ref.push(trade_data)
            logger.info(f"Kullanıcı {user_id} için işlem kaydedildi.")
        except Exception as e:
            logger.error(f"İşlem kaydedilemedi: {e}")

    async def get_bot_status(self, user_id: str) -> dict:
        try:
            status_ref = self.db.child('artifacts').child(__app_id).child('users').child(user_id).child('bot_status')
            snapshot = status_ref.get()
            return snapshot or {"is_running": False, "message": "Bot başlatılmadı."}
        except Exception as e:
            logger.error(f"Bot durumu alınamadı: {e}")
            return {"is_running": False, "message": "Durum alınamadı."}

    async def update_bot_status(self, user_id: str, status_data: dict):
        try:
            status_data['last_updated'] = datetime.utcnow().isoformat()
            status_ref = self.db.child('artifacts').child(__app_id).child('users').child(user_id).child('bot_status')
            status_ref.update(status_data)
        except Exception as e:
            logger.error(f"Bot durumu güncellenemedi: {e}")

firebase_manager = FirebaseManager()

# Bot Core Sınıfı
@dataclass
class BotStatus:
    is_running: bool = False
    symbols: List[str] = None
    status_message: str = "Bot başlatılmadı."
    account_balance: float = 0.0
    position_pnl: float = 0.0

class BotCore:
    def __init__(self, user_id: str, api_key: str, api_secret: str, settings: Dict):
        self.user_id = user_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.settings = settings
        self._stop_requested = False
        self.status = BotStatus()
        self.main_task = None
        self.logger = logging.getLogger(f"BotCore_{user_id}")
    
    async def start(self):
        self._stop_requested = False
        self.status.is_running = True
        self.status.status_message = "Bot başlatılıyor..."
        await firebase_manager.update_bot_status(self.user_id, {"is_running": True, "status_message": "Bot başlatılıyor..."})
        
        # Bu kısım botun ana döngüsünü içerecek
        self.main_task = asyncio.create_task(self._main_loop())
        self.logger.info(f"Bot başarıyla başlatıldı: {self.user_id}")
        return {"success": True, "message": "Bot başlatıldı."}

    async def stop(self):
        if not self.status.is_running:
            return {"success": False, "message": "Bot zaten durdurulmuş."}

        self.status.status_message = "Durduruluyor..."
        await firebase_manager.update_bot_status(self.user_id, {"status_message": "Durduruluyor..."})
        self._stop_requested = True
        
        # Ana döngünün tamamlanmasını bekle
        if self.main_task:
            try:
                await asyncio.wait_for(self.main_task, timeout=5)
            except asyncio.TimeoutError:
                self.main_task.cancel()
                self.logger.warning("Bot ana görevi zaman aşımına uğradı ve iptal edildi.")
        
        self.status.is_running = False
        self.status.status_message = "Bot durduruldu."
        await firebase_manager.update_bot_status(self.user_id, {"is_running": False, "status_message": "Bot durduruldu."})
        self.logger.info(f"Bot başarıyla durduruldu: {self.user_id}")
        return {"success": True, "message": "Bot durduruldu."}

    async def _main_loop(self):
        try:
            while not self._stop_requested:
                # Gerçek bot mantığı buraya gelecek
                
                # Örnek olarak, her 10 saniyede bir durumu güncelle
                balance = 10000.0  # BinanceClient'dan alınacak
                pnl = 50.0 # PositionManager'dan alınacak
                self.status.account_balance = balance
                self.status.position_pnl = pnl
                
                await firebase_manager.update_bot_status(self.user_id, {
                    "account_balance": balance,
                    "position_pnl": pnl,
                    "last_active": datetime.utcnow().isoformat()
                })
                
                await asyncio.sleep(10) # 10 saniye bekle
        
        except asyncio.CancelledError:
            self.logger.info(f"Bot ana görevi iptal edildi: {self.user_id}")
        except Exception as e:
            self.logger.error(f"Bot ana döngü hatası: {e}")
            self.status.status_message = f"Hata: {e}"
            await firebase_manager.update_bot_status(self.user_id, {"status_message": f"Hata: {e}"})

class BotManager:
    def __init__(self):
        self.active_bots: Dict[str, BotCore] = {}

    async def start_bot(self, user_id: str, start_req: dict):
        if user_id in self.active_bots and self.active_bots[user_id].status.is_running:
            return {"success": False, "message": "Bot zaten çalışıyor."}
        
        # Kullanıcının API anahtarlarını Firebase'den al
        user_data = await firebase_manager.get_user_settings(user_id)
        api_key = user_data.get('apiKey')
        api_secret = user_data.get('apiSecret')

        if not api_key or not api_secret:
            raise HTTPException(status_code=400, detail="API anahtarları bulunamadı. Lütfen önce API ayarlarınızı kaydedin.")

        bot = BotCore(user_id, api_key, api_secret, start_req)
        self.active_bots[user_id] = bot
        result = await bot.start()
        return result

    async def stop_bot(self, user_id: str):
        if user_id not in self.active_bots:
            return {"success": False, "message": "Aktif bot bulunamadı."}
        
        result = await self.active_bots[user_id].stop()
        if result.get("success"):
            del self.active_bots[user_id]
        return result

# FastAPI uygulama başlatma
app = FastAPI()

# CORS middleware ekle
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Production'da specific domains kullanın
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bot_manager = BotManager()

@app.on_event("startup")
async def startup_event():
    await firebase_manager.initialize_firebase()

# Health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "environment": settings.ENVIRONMENT
    }

# Firebase config endpoint for frontend
@app.get("/api/firebase-config")
async def get_firebase_config():
    try:
        firebase_web_config = {
            "apiKey": os.getenv("FIREBASE_WEB_API_KEY"),
            "authDomain": os.getenv("FIREBASE_WEB_AUTH_DOMAIN"),
            "databaseURL": os.getenv("FIREBASE_DATABASE_URL"),
            "projectId": os.getenv("FIREBASE_WEB_PROJECT_ID"),
            "storageBucket": os.getenv("FIREBASE_WEB_STORAGE_BUCKET"),
            "messagingSenderId": os.getenv("FIREBASE_WEB_MESSAGING_SENDER_ID"),
            "appId": os.getenv("FIREBASE_WEB_APP_ID")
        }
        return firebase_web_config
    except Exception as e:
        logger.error(f"Firebase config error: {e}")
        raise HTTPException(status_code=500, detail="Firebase configuration error")

@app.post("/api/start-bot")
async def start_bot_endpoint(start_req: dict, user_id: str = "example_user_id"): # TODO: Gerçek kullanıcı kimliği doğrulama
    print(f"👤 Kullanıcı {user_id} için bot başlatılıyor...")
    result = await bot_manager.start_bot(user_id, start_req)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result

@app.post("/api/stop-bot")
async def stop_bot_endpoint(user_id: str = "example_user_id"): # TODO: Gerçek kullanıcı kimliği doğrulama
    print(f"👤 Kullanıcı {user_id} için bot durduruluyor...")
    result = await bot_manager.stop_bot(user_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result

@app.get("/api/bot-status")
async def get_bot_status_endpoint(user_id: str = "example_user_id"): # TODO: Gerçek kullanıcı kimliği doğrulama
    print(f"👤 Kullanıcı {user_id} için bot durumu alınıyor...")
    status = await firebase_manager.get_bot_status(user_id)
    return status

@app.post("/api/save-settings")
async def save_settings_endpoint(settings_data: dict, user_id: str = "example_user_id"):
    print(f"👤 Kullanıcı {user_id} için ayarlar kaydediliyor...")
    await firebase_manager.update_user_settings(user_id, settings_data)
    return {"message": "Ayarlar başarıyla kaydedildi."}

@app.get("/api/load-settings")
async def load_settings_endpoint(user_id: str = "example_user_id"):
    print(f"👤 Kullanıcı {user_id} için ayarlar yükleniyor...")
    settings = await firebase_manager.get_user_settings(user_id)
    return settings

# ============ STATIC FILES ===========
# Static dosyaları mount et
app.mount("/static", StaticFiles(directory="static"), name="static")

# Root route - ana sayfa
@app.get("/")
async def read_root():
    return FileResponse("static/index.html")

# Login sayfası
@app.get("/login")
async def read_login():
    return FileResponse("static/login.html")
    
# Dashboard sayfası
@app.get("/dashboard")
async def read_dashboard():
    return FileResponse("static/dashboard.html")

# Register sayfası
@app.get("/register")
async def read_register():
    return FileResponse("static/register.html")

# Admin sayfası
@app.get("/admin")
async def read_admin():
    return FileResponse("static/admin.html")

# Catch-all route for SPA routing
@app.get("/{full_path:path}")
async def catch_all(full_path: str):
    # Eğer dosya static klasöründe varsa onu döndür
    static_file_path = f"static/{full_path}"
    if os.path.exists(static_file_path) and os.path.isfile(static_file_path):
        return FileResponse(static_file_path)
    
    # Aksi halde ana sayfayı döndür (SPA routing için)
    return FileResponse("static/index.html")
