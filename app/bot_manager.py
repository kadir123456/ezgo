import asyncio
import hashlib
import time
from typing import Dict, Optional, Set
from collections import defaultdict
from app.bot_core import BotCore
from app.binance_client import BinanceClient
from app.utils.logger import get_logger
from app.utils.crypto import decrypt_data
from pydantic import BaseModel, Field
import logging

logger = get_logger("bot_manager")

class StartRequest(BaseModel):
    symbol: str = Field(..., min_length=6, max_length=12)
    timeframe: str = Field(..., pattern=r'^(1m|3m|5m|15m|30m|1h|2h|4h|6h|8h|12h|1d)$')
    leverage: int = Field(..., ge=1, le=125)
    order_size: float = Field(..., ge=10.0, le=10000.0)
    stop_loss: float = Field(..., ge=0.1, le=50.0)
    take_profit: float = Field(..., ge=0.1, le=100.0)

class ConnectionPool:
    """Binance Client Connection Pool - Scalability için"""
    def __init__(self):
        self.clients: Dict[str, BinanceClient] = {}  # api_hash -> shared_client
        self.client_users: Dict[str, Set[str]] = defaultdict(set)  # api_hash -> user_ids
        self.last_used: Dict[str, float] = {}  # api_hash -> timestamp
        self.rate_limits: Dict[str, list] = defaultdict(list)  # api_hash -> call_timestamps

    def _hash_api_keys(self, api_key: str, api_secret: str) -> str:
        """API keys için unique hash oluştur"""
        combined = f"{api_key}:{api_secret}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    async def get_client(self, user_id: str, api_key: str, api_secret: str) -> BinanceClient:
        """Shared client al veya oluştur"""
        api_hash = self._hash_api_keys(api_key, api_secret)
        
        # Client yoksa oluştur
        if api_hash not in self.clients:
            client = BinanceClient(api_key, api_secret)
            await client.initialize()
            self.clients[api_hash] = client
            logger.info(f"New shared client created: {api_hash[:8]}... for user: {user_id}")
        
        # User'ı bu client'a ata
        self.client_users[api_hash].add(user_id)
        self.last_used[api_hash] = time.time()
        
        return self.clients[api_hash]

    async def release_client(self, user_id: str, api_key: str, api_secret: str):
        """Client'tan user'ı çıkar"""
        api_hash = self._hash_api_keys(api_key, api_secret)
        self.client_users[api_hash].discard(user_id)
        
        # Kimse kullanmıyorsa client'ı kapat
        if not self.client_users[api_hash] and api_hash in self.clients:
            await self.clients[api_hash].close()
            del self.clients[api_hash]
            del self.client_users[api_hash]
            if api_hash in self.last_used:
                del self.last_used[api_hash]
            logger.info(f"Shared client closed: {api_hash[:8]}... (no users)")

    async def rate_limit_check(self, api_key: str, api_secret: str, max_calls: int = 50) -> bool:
        """Rate limiting kontrolü - 3 dakikada max_calls"""
        api_hash = self._hash_api_keys(api_key, api_secret)
        now = time.time()
        window = 180  # 3 dakika = 180 saniye
        
        # Eski kayıtları temizle
        self.rate_limits[api_hash] = [
            timestamp for timestamp in self.rate_limits[api_hash] 
            if now - timestamp < window
        ]
        
        # Limit kontrolü
        if len(self.rate_limits[api_hash]) >= max_calls:
            logger.warning(f"Rate limit reached for client: {api_hash[:8]}...")
            return False
        
        self.rate_limits[api_hash].append(now)
        return True

    def get_stats(self) -> dict:
        """Connection pool istatistikleri"""
        total_users = sum(len(users) for users in self.client_users.values())
        return {
            "total_shared_clients": len(self.clients),
            "total_users_served": total_users,
            "clients_info": {
                api_hash[:8]: len(users) 
                for api_hash, users in self.client_users.items()
            }
        }

class BatchFirebaseUpdater:
    """Firebase batch updates - Performance için"""
    def __init__(self):
        self.pending_updates: Dict[str, dict] = {}  # user_id -> update_data
        self.last_batch_time = 0
        self.batch_interval = 180  # 3 dakika

    def queue_update(self, user_id: str, update_data: dict):
        """Update'i queue'ya ekle"""
        if user_id not in self.pending_updates:
            self.pending_updates[user_id] = {}
        self.pending_updates[user_id].update(update_data)

    async def flush_if_needed(self):
        """Gerekirse batch'i flush et"""
        current_time = time.time()
        if current_time - self.last_batch_time > self.batch_interval:
            await self.flush_all()

    async def flush_all(self):
        """Tüm pending updates'i batch olarak gönder"""
        if not self.pending_updates:
            return

        try:
            from app.main import firebase_db, firebase_initialized
            
            if firebase_initialized and firebase_db:
                # Batch update hazırla
                updates = {}
                for user_id, user_data in self.pending_updates.items():
                    for key, value in user_data.items():
                        updates[f'users/{user_id}/{key}'] = value

                # Batch write
                if updates:
                    firebase_db.reference().update(updates)
                    logger.info(f"Batch Firebase update: {len(self.pending_updates)} users updated")

                self.pending_updates.clear()
                self.last_batch_time = time.time()

        except Exception as e:
            logger.error(f"Batch Firebase update error: {e}")

class OptimizedBotManager:
    """
    Scalable Multi-user Bot Manager
    - Connection pooling
    - Batch Firebase updates  
    - Rate limiting
    - 3 dakika intervals
    """
    
    def __init__(self):
        # Lightweight user tracking (no heavy BotCore instances)
        self.active_users: Dict[str, dict] = {}  # user_id -> user_config
        self.user_statuses: Dict[str, dict] = {}  # user_id -> bot_status
        
        # Shared resources
        self.connection_pool = ConnectionPool()
        self.firebase_batcher = BatchFirebaseUpdater()
        
        # Timing controls - 3 dakika intervals
        self.last_balance_check: Dict[str, float] = {}
        self.last_position_check: Dict[str, float] = {}
        self.last_firebase_update: Dict[str, float] = {}
        
        # Background tasks
        self._monitor_task = None
        self._running = False
        
        logger.info("OptimizedBotManager initialized with scalable architecture")

    async def start_bot_for_user(self, uid: str, bot_settings: StartRequest) -> Dict:
        """
        Kullanıcı için lightweight bot başlat
        """
        try:
            logger.info(f"Starting optimized bot for user: {uid}")
            
            # Kullanıcı zaten aktifse durdur
            if uid in self.active_users:
                await self.stop_bot_for_user(uid)
                await asyncio.sleep(0.5)

            # Firebase'den kullanıcı verilerini al
            try:
                from app.main import firebase_db, firebase_initialized
                
                if not firebase_initialized or not firebase_db:
                    return {"error": "Database service unavailable"}
                
                user_ref = firebase_db.reference(f'users/{uid}')
                user_data = user_ref.get()
                
                if not user_data:
                    return {"error": "Kullanıcı verisi bulunamadı."}
                
                # API keys çöz
                encrypted_api_key = user_data.get('binance_api_key')
                encrypted_api_secret = user_data.get('binance_api_secret')
                
                if not encrypted_api_key or not encrypted_api_secret:
                    return {"error": "Lütfen önce Binance API anahtarlarınızı kaydedin."}

                api_key = decrypt_data(encrypted_api_key)
                api_secret = decrypt_data(encrypted_api_secret)
                
                if not api_key or not api_secret:
                    return {"error": "API anahtarları çözülemedi."}

                # Shared client al
                shared_client = await self.connection_pool.get_client(uid, api_key, api_secret)
                
                # Rate limit kontrolü
                can_proceed = await self.connection_pool.rate_limit_check(api_key, api_secret, max_calls=20)
                if not can_proceed:
                    return {"error": "API rate limit aşıldı. 3 dakika sonra tekrar deneyin."}

                # Test connection
                try:
                    test_balance = await shared_client.get_account_balance(use_cache=True)
                    logger.info(f"Shared client tested for user: {uid}, balance: {test_balance}")
                except Exception as e:
                    return {"error": f"Binance bağlantısı kurulamadı: {str(e)}"}

                # Lightweight user config kaydet
                user_config = {
                    "uid": uid,
                    "api_key": api_key,
                    "api_secret": api_secret,
                    "settings": bot_settings.model_dump(),
                    "start_time": time.time()
                }
                
                self.active_users[uid] = user_config
                
                # Initial status
                self.user_statuses[uid] = {
                    "user_id": uid,
                    "is_running": True,
                    "symbol": bot_settings.symbol,
                    "timeframe": bot_settings.timeframe,
                    "leverage": bot_settings.leverage,
                    "position_side": None,
                    "status_message": f"Bot aktif - {bot_settings.symbol} (optimized)",
                    "account_balance": test_balance,
                    "position_pnl": 0.0,
                    "total_trades": 0,
                    "total_pnl": 0.0,
                    "last_check_time": time.time()
                }

                # Background monitor başlat (eğer ilk user ise)
                if not self._running:
                    self._running = True
                    self._monitor_task = asyncio.create_task(self._global_monitor_loop())
                    logger.info("Global monitor started")

                logger.info(f"Optimized bot started for user: {uid}")
                
                return {
                    "success": True,
                    "message": "Bot başarıyla başlatıldı (optimized)",
                    "status": self.user_statuses[uid]
                }
                
            except Exception as e:
                logger.error(f"Error in start_bot_for_user: {e}")
                return {"error": f"Bot başlatılamadı: {str(e)}"}

        except Exception as e:
            logger.error(f"Unexpected error starting bot for user {uid}: {e}")
            return {"error": f"Beklenmeyen hata: {str(e)}"}

    async def stop_bot_for_user(self, uid: str) -> Dict:
        """
        Kullanıcı botunu durdur
        """
        try:
            if uid not in self.active_users:
                return {"error": "Durdurulacak aktif bir bot bulunamadı."}

            user_config = self.active_users[uid]
            api_key = user_config.get("api_key")
            api_secret = user_config.get("api_secret")

            # Shared client'tan user'ı çıkar
            if api_key and api_secret:
                await self.connection_pool.release_client(uid, api_key, api_secret)

            # User'ı temizle
            del self.active_users[uid]
            if uid in self.user_statuses:
                del self.user_statuses[uid]

            # Timing cache'lerini temizle
            self.last_balance_check.pop(uid, None)
            self.last_position_check.pop(uid, None)
            self.last_firebase_update.pop(uid, None)

            logger.info(f"Optimized bot stopped for user: {uid}")
            
            return {"success": True, "message": "Bot başarıyla durduruldu."}

        except Exception as e:
            logger.error(f"Error stopping bot for user {uid}: {e}")
            return {"error": f"Bot durdurulamadı: {str(e)}"}

    def get_bot_status(self, uid: str) -> Dict:
        """
        Kullanıcının bot durumunu döndür
        """
        if uid in self.user_statuses:
            status = self.user_statuses[uid].copy()
            
            # Pool stats ekle
            pool_stats = self.connection_pool.get_stats()
            status["pool_info"] = {
                "shared_clients": pool_stats["total_shared_clients"],
                "total_users": pool_stats["total_users_served"]
            }
            
            return status
        
        return {
            "user_id": uid,
            "is_running": False,
            "symbol": None,
            "position_side": None,
            "status_message": "Bot başlatılmadı.",
            "account_balance": 0.0,
            "position_pnl": 0.0,
            "total_trades": 0,
            "total_pnl": 0.0,
            "last_check_time": None
        }

    async def _global_monitor_loop(self):
        """
        Global monitoring - tüm kullanıcılar için batch operations
        3 dakika intervals ile
        """
        logger.info("Global monitor loop started with 3-minute intervals")
        
        while self._running:
            try:
                current_time = time.time()
                
                # Her kullanıcı için 3 dakikada bir kontroller
                for uid, user_config in list(self.active_users.items()):
                    try:
                        await self._monitor_user(uid, user_config, current_time)
                    except Exception as e:
                        logger.error(f"Monitor error for user {uid}: {e}")

                # Firebase batch flush
                await self.firebase_batcher.flush_if_needed()

                # Pool cleanup (kullanılmayan client'ları temizle)
                await self._cleanup_unused_clients(current_time)

                await asyncio.sleep(30)  # 30 saniye cycle time

            except Exception as e:
                logger.error(f"Global monitor error: {e}")
                await asyncio.sleep(10)

    async def _monitor_user(self, uid: str, user_config: dict, current_time: float):
        """
        Einzelnen kullanıcıyı monitor et - 3 dakika intervals
        """
        api_key = user_config.get("api_key")
        api_secret = user_config.get("api_secret")
        
        if not api_key or not api_secret:
            return

        # 3 dakika interval kontrolü
        balance_interval = 180  # 3 dakika
        position_interval = 60   # 1 dakika
        firebase_interval = 180  # 3 dakika

        # Balance check (3 dakikada bir)
        if current_time - self.last_balance_check.get(uid, 0) > balance_interval:
            await self._update_user_balance(uid, api_key, api_secret)
            self.last_balance_check[uid] = current_time

        # Position check (1 dakikada bir)  
        if current_time - self.last_position_check.get(uid, 0) > position_interval:
            await self._check_user_positions(uid, user_config)
            self.last_position_check[uid] = current_time

        # Firebase update (3 dakikada bir)
        if current_time - self.last_firebase_update.get(uid, 0) > firebase_interval:
            self._queue_firebase_update(uid)
            self.last_firebase_update[uid] = current_time

    async def _update_user_balance(self, uid: str, api_key: str, api_secret: str):
        """Balance güncelle (rate limited)"""
        try:
            # Rate limit check
            can_call = await self.connection_pool.rate_limit_check(api_key, api_secret)
            if not can_call:
                logger.warning(f"Balance update skipped for user {uid} - rate limited")
                return

            client = await self.connection_pool.get_client(uid, api_key, api_secret)
            balance = await client.get_account_balance(use_cache=True)
            
            if uid in self.user_statuses:
                self.user_statuses[uid]["account_balance"] = balance
                self.user_statuses[uid]["last_check_time"] = time.time()
                
        except Exception as e:
            logger.error(f"Balance update error for user {uid}: {e}")

    async def _check_user_positions(self, uid: str, user_config: dict):
        """Position kontrolü"""
        try:
            api_key = user_config.get("api_key")
            api_secret = user_config.get("api_secret")
            symbol = user_config["settings"]["symbol"]
            
            # Rate limit check
            can_call = await self.connection_pool.rate_limit_check(api_key, api_secret)
            if not can_call:
                return

            client = await self.connection_pool.get_client(uid, api_key, api_secret)
            positions = await client.get_open_positions(symbol, use_cache=True)
            
            if uid in self.user_statuses:
                if positions:
                    position = positions[0]
                    position_amt = float(position['positionAmt'])
                    self.user_statuses[uid]["position_side"] = "LONG" if position_amt > 0 else "SHORT"
                    self.user_statuses[uid]["position_pnl"] = float(position.get('unRealizedProfit', 0))
                else:
                    self.user_statuses[uid]["position_side"] = None
                    self.user_statuses[uid]["position_pnl"] = 0.0
                    
        except Exception as e:
            logger.error(f"Position check error for user {uid}: {e}")

    def _queue_firebase_update(self, uid: str):
        """Firebase update'i queue'ya ekle"""
        if uid in self.user_statuses:
            update_data = {
                "bot_active": True,
                "account_balance": self.user_statuses[uid].get("account_balance", 0),
                "position_side": self.user_statuses[uid].get("position_side"),
                "last_bot_update": int(time.time() * 1000)
            }
            self.firebase_batcher.queue_update(uid, update_data)

    async def _cleanup_unused_clients(self, current_time: float):
        """Kullanılmayan client'ları temizle"""
        cleanup_threshold = 600  # 10 dakika
        
        for api_hash, last_used in list(self.connection_pool.last_used.items()):
            if current_time - last_used > cleanup_threshold:
                if not self.connection_pool.client_users[api_hash]:
                    if api_hash in self.connection_pool.clients:
                        await self.connection_pool.clients[api_hash].close()
                        del self.connection_pool.clients[api_hash]
                        del self.connection_pool.last_used[api_hash]
                        logger.info(f"Cleaned up unused client: {api_hash[:8]}...")

    async def shutdown_all_bots(self):
        """
        Tüm botları güvenli şekilde durdur
        """
        try:
            self._running = False
            
            if self._monitor_task and not self._monitor_task.done():
                self._monitor_task.cancel()

            # Tüm shared client'ları kapat
            for client in self.connection_pool.clients.values():
                await client.close()

            # Final Firebase batch
            await self.firebase_batcher.flush_all()

            self.active_users.clear()
            self.user_statuses.clear()
            self.connection_pool = ConnectionPool()
            
            logger.info("All optimized bots shutdown completed")
            
        except Exception as e:
            logger.error(f"Shutdown error: {e}")

    def get_active_bot_count(self) -> int:
        """Aktif bot sayısı"""
        return len(self.active_users)

    def get_system_stats(self) -> dict:
        """Sistem istatistikleri"""
        pool_stats = self.connection_pool.get_stats()
        
        return {
            "total_active_users": len(self.active_users),
            "active_user_ids": list(self.active_users.keys()),
            "shared_clients": pool_stats["total_shared_clients"],
            "total_connections_saved": pool_stats["total_users_served"] - pool_stats["total_shared_clients"],
            "system_status": "optimized",
            "architecture": "scalable_lightweight",
            "intervals": {
                "balance_check": "3 minutes",
                "position_check": "1 minute", 
                "firebase_batch": "3 minutes"
            }
        }

# Global optimized bot manager instance
bot_manager = OptimizedBotManager()
