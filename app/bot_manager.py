# app/bot_manager.py - UPDATED: %90 Bakiye Validation
import asyncio
import time
from typing import Dict, Optional
from collections import defaultdict
from app.bot_core import BotCore
from app.utils.logger import get_logger
from app.utils.crypto import decrypt_data
from pydantic import BaseModel, Field, validator

logger = get_logger("bot_manager")

class StartRequest(BaseModel):
    """
    🔥 UPDATED: order_size artık 0 olabilir
    - order_size = 0 → %90 bakiye kullan
    - order_size > 0 → Belirli tutar kullan
    """
    symbol: str = Field(..., min_length=6, max_length=12)
    timeframe: str = Field(..., pattern=r'^(1m|3m|5m|15m|30m|1h|2h|4h|6h|8h|12h|1d)$')
    leverage: int = Field(..., ge=1, le=125)
    order_size: float = Field(..., ge=0.0, le=10000.0)  # ✅ 0 artık kabul edilir
    stop_loss: float = Field(..., ge=0.01, le=50.0)
    take_profit: float = Field(..., ge=0.01, le=100.0)

    @validator('order_size')
    def validate_order_size(cls, v):
        """
        Order size validation:
        - 0 = %90 bakiye modu
        - 10-10000 = Sabit tutar modu
        - 0.01-9.99 = Geçersiz (çok düşük)
        """
        if v == 0.0:
            # %90 bakiye modu - OK
            return v
        elif v < 10.0:
            raise ValueError("Order size must be 0 (for 90% balance mode) or >= 10 USDT (for fixed mode)")
        return v

    class Config:
        schema_extra = {
            "example": {
                "symbol": "BTCUSDT",
                "timeframe": "15m",
                "leverage": 10,
                "order_size": 0,  # ✅ 0 = %90 bakiye kullan
                "stop_loss": 0.8,
                "take_profit": 1.0
            }
        }

class BatchFirebaseUpdater:
    """Firebase batch updates - Performance için"""
    def __init__(self):
        self.pending_updates: Dict[str, dict] = {}
        self.last_batch_time = 0
        self.batch_interval = 180

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
                updates = {}
                for user_id, user_data in self.pending_updates.items():
                    for key, value in user_data.items():
                        updates[f'users/{user_id}/{key}'] = value

                if updates:
                    firebase_db.reference().update(updates)
                    logger.info(f"Batch Firebase update: {len(self.pending_updates)} users updated")

                self.pending_updates.clear()
                self.last_batch_time = time.time()

        except Exception as e:
            logger.error(f"Batch Firebase update error: {e}")

class RateLimitTracker:
    """Rate limiting tracking"""
    def __init__(self):
        self.user_api_calls: Dict[str, list] = defaultdict(list)
        
    def can_start_bot(self, user_id: str, max_calls: int = 10) -> bool:
        """Kullanıcı bot başlatabilir mi?"""
        now = time.time()
        window = 300  # 5 dakika
        
        self.user_api_calls[user_id] = [
            timestamp for timestamp in self.user_api_calls[user_id] 
            if now - timestamp < window
        ]
        
        if len(self.user_api_calls[user_id]) >= max_calls:
            logger.warning(f"Rate limit reached for user: {user_id}")
            return False
        
        self.user_api_calls[user_id].append(now)
        return True

class SimpleBotManager:
    """
    💰 %90 BAKİYE + KULLANICI TUTARI DESTEĞİ Bot Manager
    - order_size = 0 → Bakiyenin %90'ını kullan
    - order_size > 0 → Kullanıcının belirlediği tutarı kullan
    - EMA9 x EMA21 kesişimi stratejisi
    """
    
    def __init__(self):
        self.bot_instances: Dict[str, BotCore] = {}
        self.active_users: Dict[str, dict] = {}
        self.user_statuses: Dict[str, dict] = {}
        
        self.firebase_batcher = BatchFirebaseUpdater()
        self.rate_limiter = RateLimitTracker()
        
        self._monitor_task = None
        self._running = False
        
        logger.info("💰 SimpleBotManager initialized with %90 balance support")

    async def start_bot_for_user(self, uid: str, bot_settings: StartRequest) -> Dict:
        """
        💰 %90 BAKİYE + KULLANICI TUTARI bot başlatma
        """
        try:
            # 🔥 Order size mode belirleme
            if bot_settings.order_size == 0:
                mode_text = "90% Balance Mode"
                logger.info(f"💰 Starting bot for user {uid} in %90 BALANCE MODE")
            else:
                mode_text = f"Fixed {bot_settings.order_size} USDT Mode"
                logger.info(f"💰 Starting bot for user {uid} in FIXED {bot_settings.order_size} USDT MODE")
            
            logger.info(f"🔧 Settings: Symbol={bot_settings.symbol}, TF={bot_settings.timeframe}")
            logger.info(f"📊 TP/SL: {bot_settings.take_profit}%/{bot_settings.stop_loss}%")
            
            # Rate limit kontrolü
            if not self.rate_limiter.can_start_bot(uid, max_calls=5):
                return {"error": "Çok sık bot başlatma girişimi. 5 dakika bekleyin."}
            
            # Mevcut bot varsa durdur
            if uid in self.active_users:
                await self.stop_bot_for_user(uid)
                await asyncio.sleep(1)

            # Firebase'den kullanıcı verilerini al
            try:
                from app.main import firebase_db, firebase_initialized
                
                if not firebase_initialized or not firebase_db:
                    return {"error": "Database service unavailable"}
                
                user_ref = firebase_db.reference(f'users/{uid}')
                user_data = user_ref.get()
                
                if not user_data:
                    return {"error": "Kullanıcı verisi bulunamadı."}
                
                # API keys kontrolü
                encrypted_api_key = user_data.get('binance_api_key')
                encrypted_api_secret = user_data.get('binance_api_secret')
                
                if not encrypted_api_key or not encrypted_api_secret:
                    return {"error": "Lütfen önce Binance API anahtarlarınızı kaydedin."}

                api_key = decrypt_data(encrypted_api_key)
                api_secret = decrypt_data(encrypted_api_secret)
                
                if not api_key or not api_secret:
                    return {"error": "API anahtarları çözülemedi."}

                # ✅ UPDATED: StartRequest'i dict'e çevir
                bot_settings_dict = {
                    "symbol": bot_settings.symbol,
                    "timeframe": bot_settings.timeframe,
                    "leverage": bot_settings.leverage,
                    "order_size": bot_settings.order_size,  # ✅ 0 veya pozitif değer
                    "stop_loss": bot_settings.stop_loss,
                    "take_profit": bot_settings.take_profit
                }
                
                # 💰 BAKIYE ÖN KONTROLÜ
                try:
                    from app.binance_client import BinanceClient
                    
                    # Geçici client ile bakiye kontrolü
                    temp_client = BinanceClient(api_key, api_secret, f"{uid}_balance_check")
                    await temp_client.initialize()
                    
                    balance_info = await temp_client.get_balance_with_status()
                    current_balance = balance_info["balance"]
                    
                    await temp_client.close()
                    
                    logger.info(f"💰 Pre-start balance check: {current_balance:.2f} USDT")
                    
                    # Minimum bakiye kontrolü
                    min_required = 20.0  # Minimum 20 USDT
                    
                    if bot_settings.order_size == 0:
                        # %90 bakiye modu - bakiyenin %90'ı en az 10 USDT olmalı
                        usable_balance = current_balance * 0.90
                        if usable_balance < 10.0:
                            return {
                                "error": f"Yetersiz bakiye: {current_balance:.2f} USDT × 90% = {usable_balance:.2f} USDT. "
                                       f"%90 bakiye modu için en az {10/0.90:.2f} USDT bakiye gerekli."
                            }
                        logger.info(f"✅ %90 Balance mode: {usable_balance:.2f} USDT will be used")
                    else:
                        # Sabit tutar modu - bakiye order_size'dan fazla olmalı
                        if current_balance < bot_settings.order_size:
                            return {
                                "error": f"Yetersiz bakiye: {current_balance:.2f} USDT < {bot_settings.order_size} USDT"
                            }
                        logger.info(f"✅ Fixed mode: {bot_settings.order_size} USDT will be used")
                    
                    if current_balance < min_required:
                        return {
                            "error": f"Yetersiz bakiye: {current_balance:.2f} USDT < {min_required} USDT minimum gerekli."
                        }
                    
                    logger.info(f"✅ Balance check passed: {current_balance:.2f} USDT >= {min_required} USDT")
                    
                except Exception as balance_error:
                    logger.error(f"💰 Balance pre-check failed: {balance_error}")
                    return {"error": f"Bakiye kontrolü başarısız: {str(balance_error)}"}
                
                logger.info(f"🎯 Bot settings dict: {bot_settings_dict}")
                
                # ✅ BotCore'u başlat
                bot_core = BotCore(uid, api_key, api_secret, bot_settings_dict)
                
                # BotCore'u başlat
                await bot_core.start()
                
                # BotCore instance'ını kaydet
                self.bot_instances[uid] = bot_core
                
                # User config kaydet
                user_config = {
                    "uid": uid,
                    "settings": bot_settings_dict,
                    "start_time": time.time(),
                    "balance_at_start": current_balance,
                    "min_balance_required": min_required,
                    "order_mode": "percentage_90" if bot_settings.order_size == 0 else "fixed"
                }
                
                self.active_users[uid] = user_config
                
                # BotCore'dan initial status al
                bot_status = bot_core.get_status()
                self.user_statuses[uid] = {
                    "user_id": uid,
                    "is_running": True,
                    "symbol": bot_settings.symbol,
                    "timeframe": bot_settings.timeframe,
                    "strategy_type": "Simple EMA Crossover",
                    "leverage": bot_settings.leverage,
                    "order_size": bot_settings.order_size,
                    "order_size_mode": user_config["order_mode"],
                    "stop_loss": bot_settings.stop_loss,
                    "take_profit": bot_settings.take_profit,
                    "position_side": bot_status.get("position_side"),
                    "status_message": f"💰 Simple EMA Bot aktif - {bot_settings.symbol} ({bot_settings.timeframe}) - {mode_text}",
                    "account_balance": bot_status.get("account_balance", 0),
                    "balance_sufficient": bot_status.get("balance_sufficient", True),
                    "min_balance_required": min_required,
                    "position_pnl": bot_status.get("position_pnl", 0),
                    "total_trades": bot_status.get("total_trades", 0),
                    "total_pnl": bot_status.get("total_pnl", 0),
                    "last_check_time": time.time(),
                    "current_price": bot_status.get("current_price"),
                    "data_candles": bot_status.get("data_candles", 0),
                    "last_signal": bot_status.get("last_signal", "HOLD")
                }

                # Background monitor başlat
                if not self._running:
                    self._running = True
                    self._monitor_task = asyncio.create_task(self._global_monitor_loop())
                    logger.info("✅ Global monitor started")

                logger.info(f"💰 Simple EMA trading bot started for user: {uid}")
                
                return {
                    "success": True,
                    "message": f"💰 Simple EMA trading bot başarıyla başlatıldı ({mode_text})",
                    "settings": {
                        "timeframe": bot_settings.timeframe,
                        "symbol": bot_settings.symbol,
                        "strategy": "EMA9 x EMA21 Crossover",
                        "stop_loss": bot_settings.stop_loss,
                        "take_profit": bot_settings.take_profit,
                        "leverage": bot_settings.leverage,
                        "order_size": bot_settings.order_size,
                        "order_mode": user_config["order_mode"],
                        "balance_monitoring": True,
                        "min_balance_required": min_required
                    },
                    "balance_info": {
                        "current_balance": current_balance,
                        "min_required": min_required,
                        "balance_sufficient": True,
                        "monitoring_enabled": True,
                        "order_mode": user_config["order_mode"],
                        "usable_amount": current_balance * 0.90 if bot_settings.order_size == 0 else bot_settings.order_size
                    },
                    "status": self.user_statuses[uid]
                }
                
            except Exception as e:
                logger.error(f"❌ Error in start_bot_for_user: {e}")
                return {"error": f"Bot başlatılamadı: {str(e)}"}

        except Exception as e:
            logger.error(f"❌ Unexpected error starting bot for user {uid}: {e}")
            return {"error": f"Beklenmeyen hata: {str(e)}"}

    async def stop_bot_for_user(self, uid: str) -> Dict:
        """Bot durdurma"""
        try:
            if uid not in self.active_users:
                return {"error": "Durdurulacak aktif bir bot bulunamadı."}

            # BotCore'u durdur
            if uid in self.bot_instances:
                bot_core = self.bot_instances[uid]
                await bot_core.stop()
                del self.bot_instances[uid]
                logger.info(f"✅ BotCore stopped for user: {uid}")

            # User'ı temizle
            del self.active_users[uid]
            if uid in self.user_statuses:
                del self.user_statuses[uid]

            logger.info(f"💰 Simple EMA Bot stopped for user: {uid}")
            
            return {"success": True, "message": "💰 Simple EMA Bot başarıyla durduruldu."}

        except Exception as e:
            logger.error(f"❌ Error stopping bot for user {uid}: {e}")
            return {"error": f"Bot durdurulamadı: {str(e)}"}

    def get_bot_status(self, uid: str) -> Dict:
        """BotCore'dan gerçek status al"""
        if uid in self.bot_instances:
            bot_core = self.bot_instances[uid]
            real_status = bot_core.get_status()
            
            # System stats ekle
            real_status["system_info"] = {
                "total_active_bots": len(self.bot_instances),
                "shared_websocket": True,
                "architecture": "simple_ema_balance_90_controlled",
                "timeframe_support": ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"],
                "strategy": "EMA9 x EMA21 Crossover",
                "balance_monitoring": True,
                "order_modes": ["percentage_90", "fixed"]
            }
            
            return real_status
        
        return {
            "user_id": uid,
            "is_running": False,
            "symbol": None,
            "timeframe": None,
            "strategy_type": "Simple EMA Crossover",
            "position_side": None,
            "status_message": "Bot başlatılmadı.",
            "account_balance": 0.0,
            "balance_sufficient": True,
            "min_balance_required": 20.0,
            "position_pnl": 0.0,
            "total_trades": 0,
            "total_pnl": 0.0,
            "last_check_time": None,
            "last_signal": "HOLD",
            "order_size": 0,
            "order_size_mode": "percentage_90",
            "stop_loss": 0.0,
            "take_profit": 0.0
        }

    async def _global_monitor_loop(self):
        """Global monitor loop"""
        logger.info("💰 Global monitor loop started with %90 balance support")
        
        while self._running:
            try:
                # Her kullanıcı için BotCore sync
                for uid in list(self.bot_instances.keys()):
                    try:
                        await self._sync_botcore_status(uid)
                        self._queue_firebase_update(uid)
                    except Exception as e:
                        logger.error(f"❌ Monitor error for user {uid}: {e}")

                # Firebase batch flush
                await self.firebase_batcher.flush_if_needed()

                await asyncio.sleep(30)

            except Exception as e:
                logger.error(f"❌ Global monitor error: {e}")
                await asyncio.sleep(10)

    async def _sync_botcore_status(self, uid: str):
        """BotCore status sync"""
        if uid in self.bot_instances and uid in self.user_statuses:
            try:
                bot_core = self.bot_instances[uid]
                real_status = bot_core.get_status()
                
                # Key field'ları güncelle
                self.user_statuses[uid].update({
                    "is_running": real_status.get("is_running", True),
                    "position_side": real_status.get("position_side"),
                    "account_balance": real_status.get("account_balance", 0),
                    "balance_sufficient": real_status.get("balance_sufficient", True),
                    "min_balance_required": real_status.get("min_balance_required", 20.0),
                    "position_pnl": real_status.get("position_pnl", 0),
                    "unrealized_pnl": real_status.get("unrealized_pnl", 0),
                    "total_trades": real_status.get("total_trades", 0),
                    "total_pnl": real_status.get("total_pnl", 0),
                    "current_price": real_status.get("current_price"),
                    "entry_price": real_status.get("entry_price", 0),
                    "last_signal": real_status.get("last_signal", "HOLD"),
                    "status_message": real_status.get("status_message", ""),
                    "data_candles": real_status.get("data_candles", 0),
                    "consecutive_losses": real_status.get("consecutive_losses", 0),
                    "stop_loss": real_status.get("stop_loss", 0),
                    "take_profit": real_status.get("take_profit", 0),
                    "order_size": real_status.get("order_size", 0),
                    "order_size_mode": real_status.get("order_size_mode", "percentage_90"),
                    "strategy_type": "Simple EMA Crossover",
                    "timeframe": real_status.get("timeframe", "15m"),
                    "last_check_time": time.time()
                })
                
                # Bakiye yetersizliği nedeniyle bot durmuşsa temizle
                if not real_status.get("is_running", True):
                    balance_sufficient = real_status.get("balance_sufficient", True)
                    if not balance_sufficient:
                        logger.warning(f"💰 Bot stopped due to insufficient balance for user {uid}")
                        await self.stop_bot_for_user(uid)
                    else:
                        logger.warning(f"⚠️ BotCore stopped for other reason for user {uid}")
                        await self.stop_bot_for_user(uid)
                
            except Exception as e:
                logger.error(f"❌ BotCore sync error for user {uid}: {e}")

    def _queue_firebase_update(self, uid: str):
        """Firebase update queue"""
        if uid in self.user_statuses:
            status = self.user_statuses[uid]
            update_data = {
                "bot_active": status.get("is_running", False),
                "bot_symbol": status.get("symbol"),
                "bot_timeframe": status.get("timeframe"),
                "bot_strategy": "Simple EMA Crossover",
                "bot_position": status.get("position_side"),
                "account_balance": status.get("account_balance", 0),
                "balance_sufficient": status.get("balance_sufficient", True),
                "min_balance_required": status.get("min_balance_required", 20.0),
                "position_pnl": status.get("position_pnl", 0),
                "unrealized_pnl": status.get("unrealized_pnl", 0),
                "total_trades": status.get("total_trades", 0),
                "total_pnl": status.get("total_pnl", 0),
                "current_price": status.get("current_price"),
                "entry_price": status.get("entry_price", 0),
                "last_signal": status.get("last_signal", "HOLD"),
                "data_candles": status.get("data_candles", 0),
                "consecutive_losses": status.get("consecutive_losses", 0),
                "user_stop_loss": status.get("stop_loss", 0),
                "user_take_profit": status.get("take_profit", 0),
                "order_size": status.get("order_size", 0),
                "order_size_mode": status.get("order_size_mode", "percentage_90"),
                "strategy_indicators": "EMA9 x EMA21",
                "balance_monitoring_active": True,
                "last_bot_update": int(time.time() * 1000)
            }
            self.firebase_batcher.queue_update(uid, update_data)

    async def shutdown_all_bots(self):
        """Tüm botları durdur"""
        try:
            logger.info("💰 Shutting down all bots...")
            self._running = False
            
            if self._monitor_task and not self._monitor_task.done():
                self._monitor_task.cancel()

            for uid, bot_core in list(self.bot_instances.items()):
                try:
                    await bot_core.stop()
                    logger.info(f"✅ BotCore stopped for user: {uid}")
                except Exception as e:
                    logger.error(f"❌ Error stopping BotCore for user {uid}: {e}")
            
            self.bot_instances.clear()
            await self.firebase_batcher.flush_all()
            self.active_users.clear()
            self.user_statuses.clear()
            
            logger.info("✅ All BotCore instances shutdown completed")
            
        except Exception as e:
            logger.error(f"❌ Shutdown error: {e}")

    def get_active_bot_count(self) -> int:
        """Aktif bot sayısı"""
        return len(self.bot_instances)

    def get_system_stats(self) -> dict:
        """System istatistikleri"""
        trading_bots = len(self.bot_instances)
        active_traders = sum(1 for uid in self.bot_instances 
                           if self.user_statuses.get(uid, {}).get("position_side"))
        
        total_trades = sum(status.get("total_trades", 0) for status in self.user_statuses.values())
        total_pnl = sum(status.get("total_pnl", 0) for status in self.user_statuses.values())
        
        # Order mode stats
        percentage_mode_users = sum(1 for status in self.user_statuses.values() 
                                   if status.get("order_size_mode") == "percentage_90")
        fixed_mode_users = trading_bots - percentage_mode_users
        
        return {
            "total_active_users": len(self.active_users),
            "trading_bots_running": trading_bots,
            "bots_with_positions": active_traders,
            "total_trades_executed": total_trades,
            "total_system_pnl": round(total_pnl, 2),
            "order_mode_distribution": {
                "percentage_90_users": percentage_mode_users,
                "fixed_mode_users": fixed_mode_users
            },
            "strategy_info": {
                "type": "Simple EMA Crossover",
                "indicators": "EMA9 x EMA21",
                "order_modes": "90% Balance or Fixed Amount"
            },
            "system_status": "SIMPLE_EMA_BALANCE_90_CONTROLLED",
            "architecture": "simple_ema_with_90_percent_balance_support"
        }

# Global bot manager instance
bot_manager = SimpleBotManager()
