import asyncio
from typing import Dict, Optional
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

class BotManager:
    """
    Multi-user bot yönetici sınıfı
    Her kullanıcı için ayrı BotCore ve BinanceClient instance'ı oluşturur
    """
    def __init__(self):
        self.active_bots: Dict[str, BotCore] = {}  # user_id -> BotCore
        self.user_clients: Dict[str, BinanceClient] = {}  # user_id -> BinanceClient
        logger.info("BotManager initialized for multi-user system")

    async def start_bot_for_user(self, uid: str, bot_settings: StartRequest) -> Dict:
        """
        Belirtilen kullanıcı için botu başlatır
        """
        try:
            logger.info(f"Starting bot for user: {uid}")
            
            # Eğer kullanıcının zaten aktif botu varsa durdur
            if uid in self.active_bots:
                logger.info(f"Stopping existing bot for user: {uid}")
                await self.stop_bot_for_user(uid)
                await asyncio.sleep(1)  # Temizlik için bekle

            # Firebase'den kullanıcı verilerini al
            try:
                from app.main import firebase_db, firebase_initialized
                
                if not firebase_initialized or not firebase_db:
                    return {"error": "Database service unavailable"}
                
                user_ref = firebase_db.reference(f'users/{uid}')
                user_data = user_ref.get()
                
                if not user_data:
                    logger.error(f"User data not found for: {uid}")
                    return {"error": "Kullanıcı verisi bulunamadı."}
                
                # Şifrelenmiş API anahtarlarını çöz
                encrypted_api_key = user_data.get('binance_api_key')
                encrypted_api_secret = user_data.get('binance_api_secret')
                
                if not encrypted_api_key or not encrypted_api_secret:
                    logger.error(f"API keys not found for user: {uid}")
                    return {"error": "Lütfen önce Binance API anahtarlarınızı kaydedin."}

                try:
                    api_key = decrypt_data(encrypted_api_key)
                    api_secret = decrypt_data(encrypted_api_secret)
                    
                    if not api_key or not api_secret:
                        raise Exception("API anahtarları çözülemedi")
                        
                except Exception as e:
                    logger.error(f"Failed to decrypt API keys for user {uid}: {e}")
                    return {"error": "API anahtarları çözülemedi. Lütfen tekrar kaydedin."}

                # Kullanıcıya özel Binance client oluştur
                try:
                    user_client = BinanceClient(api_key, api_secret)
                    
                    # Client'ı test et
                    await user_client.initialize()
                    test_balance = await user_client.get_account_balance(use_cache=False)
                    logger.info(f"Binance client created and tested for user: {uid}, balance: {test_balance}")
                    
                    # Client'ı kaydet
                    self.user_clients[uid] = user_client
                    
                except Exception as e:
                    logger.error(f"Failed to create/test Binance client for user {uid}: {e}")
                    return {"error": f"Binance bağlantısı kurulamadı: {str(e)}"}
                
                # Bot ayarlarını hazırla
                bot_settings_dict = bot_settings.model_dump()
                bot_settings_dict['user_id'] = uid
                
                # BotCore oluştur
                try:
                    bot = BotCore(
                        user_id=uid,
                        binance_client=user_client,
                        bot_settings=bot_settings_dict
                    )
                    
                    # Botu aktif listesine ekle
                    self.active_bots[uid] = bot
                    
                    # Bot'u arka planda başlat
                    asyncio.create_task(bot.start())
                    
                    # Kısa bekleme sonrası durum döndür
                    await asyncio.sleep(1)
                    
                    logger.info(f"Bot started successfully for user: {uid}")
                    
                    return {
                        "success": True,
                        "message": "Bot başarıyla başlatıldı",
                        "status": bot.get_status()
                    }
                    
                except Exception as e:
                    logger.error(f"Failed to create BotCore for user {uid}: {e}")
                    # Hatalı client'ı temizle
                    if uid in self.user_clients:
                        await self.user_clients[uid].close()
                        del self.user_clients[uid]
                    return {"error": f"Bot oluşturulamadı: {str(e)}"}
                    
            except Exception as db_error:
                logger.error(f"Database error for user {uid}: {db_error}")
                return {"error": "Veritabanı hatası"}

        except Exception as e:
            logger.error(f"Unexpected error starting bot for user {uid}: {e}")
            # Temizlik
            if uid in self.active_bots:
                del self.active_bots[uid]
            if uid in self.user_clients:
                try:
                    await self.user_clients[uid].close()
                except:
                    pass
                del self.user_clients[uid]
            return {"error": f"Beklenmeyen hata: {str(e)}"}

    async def stop_bot_for_user(self, uid: str) -> Dict:
        """
        Belirtilen kullanıcı için botu durdurur
        """
        try:
            logger.info(f"Stopping bot for user: {uid}")
            
            if uid in self.active_bots:
                bot = self.active_bots[uid]
                
                # Bot'u durdur
                await bot.stop()
                
                # Bot'u listeden kaldır
                del self.active_bots[uid]
                
                # Kullanıcıya özel client'ı kapat
                if uid in self.user_clients:
                    await self.user_clients[uid].close()
                    del self.user_clients[uid]
                
                logger.info(f"Bot stopped and cleaned up for user: {uid}")
                
                return {"success": True, "message": "Bot başarıyla durduruldu."}
            else:
                logger.warning(f"No active bot found for user: {uid}")
                return {"error": "Durdurulacak aktif bir bot bulunamadı."}
                
        except Exception as e:
            logger.error(f"Error stopping bot for user {uid}: {e}")
            # Hata durumunda da temizlik yap
            if uid in self.active_bots:
                del self.active_bots[uid]
            if uid in self.user_clients:
                try:
                    await self.user_clients[uid].close()
                except:
                    pass
                del self.user_clients[uid]
            return {"error": f"Bot durdurulamadı: {str(e)}"}

    def get_bot_status(self, uid: str) -> Dict:
        """
        Kullanıcının bot durumunu döndürür
        """
        try:
            if uid in self.active_bots:
                bot = self.active_bots[uid]
                return bot.get_status()
            
            # Bot çalışmıyorsa varsayılan durum
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
            
        except Exception as e:
            logger.error(f"Error getting bot status for user {uid}: {e}")
            return {
                "user_id": uid,
                "is_running": False,
                "symbol": None,
                "position_side": None,
                "status_message": f"Durum alınamadı: {str(e)}",
                "account_balance": 0.0,
                "position_pnl": 0.0,
                "total_trades": 0,
                "total_pnl": 0.0,
                "last_check_time": None
            }

    async def shutdown_all_bots(self):
        """
        Tüm aktif botları güvenli şekilde durdur
        """
        try:
            logger.info("Shutting down all active bots...")
            
            if not self.active_bots:
                logger.info("No active bots to shutdown")
                return
            
            # Tüm botları paralel olarak durdur
            tasks = []
            for uid, bot in self.active_bots.items():
                tasks.append(bot.stop())
                logger.info(f"Added shutdown task for user: {uid}")
            
            # Tüm shutdown işlemlerini bekle
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                logger.info(f"Shutdown completed for {len(tasks)} bots")
            
            # Tüm client'ları kapat
            for uid, client in self.user_clients.items():
                try:
                    await client.close()
                except Exception as e:
                    logger.error(f"Error closing client for user {uid}: {e}")
            
            # Temizlik
            self.active_bots.clear()
            self.user_clients.clear()
            
            logger.info("All bots shutdown completed successfully")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {str(e)}")
            # Hata olsa bile temizle
            self.active_bots.clear()
            self.user_clients.clear()

    def get_active_bot_count(self) -> int:
        """Aktif bot sayısını döndür"""
        return len(self.active_bots)

    def get_all_active_users(self) -> list:
        """Aktif bot'u olan kullanıcıların listesini döndür"""
        return list(self.active_bots.keys())

    def get_system_stats(self) -> dict:
        """Sistem istatistiklerini döndür"""
        return {
            "total_active_bots": len(self.active_bots),
            "active_users": list(self.active_bots.keys()),
            "total_clients": len(self.user_clients),
            "system_status": "healthy" if len(self.active_bots) < 1000 else "high_load"
        }

# Global bot manager instance
bot_manager = BotManager()
