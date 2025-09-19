# app/core/client_manager.py
"""
Singleton BinanceClient Manager
Her kullanıcı için tek client instance - Rate limit sorununu çözer
"""

import asyncio
import time
from typing import Dict, Optional
from ..binance_client import BinanceClient
from ..utils.logger import get_logger

logger = get_logger("client_manager")

class BinanceClientManager:
    """
    Kullanıcı başına tek BinanceClient instance
    Rate limit sorununu çözer
    """
    
    _instances: Dict[str, BinanceClient] = {}
    _last_cleanup = 0
    _cleanup_interval = 3600  # 1 hour
    
    @classmethod
    async def get_client(cls, user_id: str, api_key: str, api_secret: str) -> BinanceClient:
        """
        Kullanıcı için BinanceClient al - varsa mevcut, yoksa yeni oluştur
        """
        try:
            # Temizlik kontrolü (1 saatte bir)
            current_time = time.time()
            if current_time - cls._last_cleanup > cls._cleanup_interval:
                await cls._cleanup_inactive_clients()
                cls._last_cleanup = current_time
            
            # Mevcut client var mı kontrol et
            if user_id in cls._instances:
                client = cls._instances[user_id]
                
                # Client hala aktif mi kontrol et
                if client.client is not None:
                    logger.debug(f"Reusing existing client for user: {user_id}")
                    return client
                else:
                    # Client kapanmış, yeniden başlat
                    logger.info(f"Reinitializing client for user: {user_id}")
                    success = await client.initialize()
                    if success:
                        return client
                    else:
                        # Başlatma başarısız, client'ı kaldır
                        del cls._instances[user_id]
            
            # Yeni client oluştur
            logger.info(f"Creating new BinanceClient for user: {user_id}")
            client = BinanceClient(api_key, api_secret, user_id)
            
            # Client'ı başlat
            success = await client.initialize()
            if not success:
                raise Exception("Client initialization failed")
            
            # Cache'e ekle
            cls._instances[user_id] = client
            
            logger.info(f"✅ BinanceClient ready for user: {user_id}")
            return client
            
        except Exception as e:
            logger.error(f"❌ Failed to get client for user {user_id}: {e}")
            # Hatalı client'ı temizle
            if user_id in cls._instances:
                await cls.remove_client(user_id)
            raise
    
    @classmethod
    async def remove_client(cls, user_id: str):
        """
        Kullanıcının client'ını kaldır ve kapat
        """
        if user_id in cls._instances:
            try:
                client = cls._instances[user_id]
                await client.close()
                del cls._instances[user_id]
                logger.info(f"Client removed for user: {user_id}")
            except Exception as e:
                logger.error(f"Error removing client for user {user_id}: {e}")
    
    @classmethod
    async def get_client_status(cls, user_id: str) -> dict:
        """
        Kullanıcının client durumunu kontrol et
        """
        if user_id not in cls._instances:
            return {
                "exists": False,
                "is_connected": False,
                "message": "Client not initialized"
            }
        
        client = cls._instances[user_id]
        
        try:
            # Hızlı bağlantı testi (cache kullan)
            balance = await client.get_account_balance(use_cache=True)
            
            return {
                "exists": True,
                "is_connected": True,
                "balance": balance,
                "message": "Client active and connected"
            }
        except Exception as e:
            return {
                "exists": True,
                "is_connected": False,
                "message": f"Connection error: {str(e)}"
            }
    
    @classmethod
    async def _cleanup_inactive_clients(cls):
        """
        Kullanılmayan client'ları temizle
        """
        try:
            inactive_users = []
            
            for user_id, client in cls._instances.items():
                try:
                    # Client'ın son kullanım zamanını kontrol et
                    if client.client is None:
                        inactive_users.append(user_id)
                    else:
                        # Test çağrısı yap (cache kullan, API çağrısı yapmaz)
                        await client.get_account_balance(use_cache=True)
                except Exception:
                    inactive_users.append(user_id)
            
            # Inactive client'ları kaldır
            for user_id in inactive_users:
                await cls.remove_client(user_id)
            
            if inactive_users:
                logger.info(f"Cleaned up {len(inactive_users)} inactive clients")
            
        except Exception as e:
            logger.error(f"Client cleanup error: {e}")
    
    @classmethod
    def get_stats(cls) -> dict:
        """
        Client manager istatistiklerini getir
        """
        return {
            "total_active_clients": len(cls._instances),
            "active_user_ids": list(cls._instances.keys()),
            "last_cleanup": cls._last_cleanup,
            "next_cleanup": cls._last_cleanup + cls._cleanup_interval
        }
    
    @classmethod
    async def shutdown_all(cls):
        """
        Tüm client'ları kapat (uygulama kapatılırken)
        """
        logger.info(f"Shutting down {len(cls._instances)} clients...")
        
        for user_id in list(cls._instances.keys()):
            await cls.remove_client(user_id)
        
        logger.info("All clients shut down")

# Global instance
client_manager = BinanceClientManager()
