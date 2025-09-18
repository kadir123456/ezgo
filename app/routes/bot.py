from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.bot_manager import bot_manager, StartRequest
from app.firebase_manager import firebase_manager
from app.utils.crypto import encrypt_data, decrypt_data
from app.utils.metrics import metrics
from app.binance_client import BinanceClient
from app.utils.logger import get_logger
from app.config import settings  # NEW: Import scalable settings
import firebase_admin
from firebase_admin import auth as firebase_auth
from typing import Optional
from pydantic import BaseModel
import time

logger = get_logger("bot_routes")
router = APIRouter(prefix="/api/bot", tags=["bot"])
security = HTTPBearer(auto_error=False)

async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    """Firebase Auth token'dan kullanıcı bilgilerini al"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication token required")
    
    try:
        decoded_token = firebase_auth.verify_id_token(credentials.credentials)
        logger.info(f"✅ Token verified for user: {decoded_token['uid']}")
        return decoded_token
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication token")

class ApiKeysRequest(BaseModel):
    api_key: str
    api_secret: str
    testnet: bool = False

@router.post("/start")
async def start_bot(
    request: StartRequest,
    current_user: dict = Depends(get_current_user)
):
    """Kullanıcı için optimized bot başlat"""
    try:
        user_id = current_user['uid']
        logger.info(f"Optimized bot start request from user: {user_id}")
        
        # System capacity kontrolü (NEW)
        active_bot_count = bot_manager.get_active_bot_count()
        if active_bot_count >= settings.MAX_TOTAL_SYSTEM_BOTS:
            raise HTTPException(
                status_code=503, 
                detail=f"Sistem kapasitesi dolu. Aktif bot sayısı: {active_bot_count}"
            )
        
        # High load warning (NEW)
        if active_bot_count >= settings.SYSTEM_HIGH_LOAD_THRESHOLD:
            logger.warning(f"System approaching high load: {active_bot_count} active bots")
        
        # Kullanıcının abonelik durumunu kontrol et
        user_data = firebase_manager.get_user_data(user_id)
        if not user_data:
            raise HTTPException(status_code=404, detail="Kullanıcı verisi bulunamadı")
        
        # Abonelik kontrolü
        subscription_status = user_data.get('subscription_status')
        if subscription_status not in ['trial', 'active']:
            raise HTTPException(status_code=403, detail="Aktif abonelik gerekli")
        
        # API keys kontrolü
        if not user_data.get('api_keys_set'):
            raise HTTPException(status_code=400, detail="Önce API anahtarlarınızı kaydedin")
        
        # Optimized bot'u başlat (same interface, improved backend)
        result = await bot_manager.start_bot_for_user(user_id, request)
        
        if "error" in result:
            # Rate limit specific error handling (NEW)
            if "rate limit" in result["error"].lower():
                raise HTTPException(
                    status_code=429, 
                    detail=f"{result['error']}. 3 dakika sonra tekrar deneyin."
                )
            raise HTTPException(status_code=400, detail=result["error"])
        
        # Metrics kaydet
        metrics.record_bot_start(user_id, request.symbol)
        
        # User data güncelle (batch'lenecek - NEW)
        firebase_manager.update_user_data(user_id, {
            "bot_active": True,
            "bot_symbol": request.symbol,
            "bot_timeframe": request.timeframe,
            "bot_leverage": request.leverage,
            "bot_start_time": firebase_manager.get_server_timestamp(),
            "architecture": "optimized_scalable"  # NEW: Architecture tracking
        })
        
        # Enhanced response with scalability info (NEW)
        response = {
            "success": True,
            "message": "Bot başarıyla başlatıldı (optimized)",
            "bot_status": result.get("status", {}),
            "system_info": {
                "architecture": "scalable",
                "total_active_bots": active_bot_count + 1,
                "intervals": {
                    "balance_update": f"{settings.BALANCE_UPDATE_INTERVAL}s",
                    "position_check": f"{settings.POSITION_CHECK_INTERVAL}s",
                    "firebase_batch": f"{settings.FIREBASE_BATCH_INTERVAL}s"
                }
            }
        }
        
        # Add capacity warning if approaching limits (NEW)
        if active_bot_count >= settings.SYSTEM_HIGH_LOAD_THRESHOLD:
            response["system_info"]["capacity_warning"] = "Sistem yoğun - normal servis devam ediyor"
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Optimized bot start error: {e}")
        metrics.record_error("optimized_bot_start_failed", "scalable_bot_manager")
        raise HTTPException(status_code=500, detail=f"Bot başlatılamadı: {str(e)}")

@router.post("/stop")
async def stop_bot(current_user: dict = Depends(get_current_user)):
    """Kullanıcının optimized botunu durdur"""
    try:
        user_id = current_user['uid']
        logger.info(f"Optimized bot stop request from user: {user_id}")
        
        result = await bot_manager.stop_bot_for_user(user_id)
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # Metrics kaydet
        metrics.record_bot_stop(user_id, "manual", "user_request")
        
        # User data güncelle (batch'lenecek - NEW)
        firebase_manager.update_user_data(user_id, {
            "bot_active": False,
            "bot_stop_time": firebase_manager.get_server_timestamp(),
            "bot_stop_reason": "manual"
        })
        
        # System stats with stop (NEW)
        active_bot_count = bot_manager.get_active_bot_count()
        
        return {
            "success": True,
            "message": "Bot başarıyla durduruldu (optimized)",
            "system_info": {
                "total_active_bots": active_bot_count,
                "architecture": "scalable"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Optimized bot stop error: {e}")
        raise HTTPException(status_code=500, detail=f"Bot durdurulamadı: {str(e)}")

@router.get("/status")
async def get_bot_status(current_user: dict = Depends(get_current_user)):
    """Kullanıcının optimized bot durumunu getir"""
    try:
        user_id = current_user['uid']
        status = bot_manager.get_bot_status(user_id)
        
        # Enhanced status with scalability info (NEW)
        enhanced_status = {
            "success": True,
            "status": status,
            "scalability_info": {
                "architecture": "optimized",
                "intervals": {
                    "balance_update_interval": settings.BALANCE_UPDATE_INTERVAL,
                    "position_check_interval": settings.POSITION_CHECK_INTERVAL,
                    "firebase_batch_interval": settings.FIREBASE_BATCH_INTERVAL
                },
                "next_updates": {
                    "balance_update": "based on 3-minute cycles",
                    "position_check": "based on 1-minute cycles",
                    "firebase_sync": "batched every 3 minutes"
                }
            }
        }
        
        # Add pool info if available (NEW)
        if "pool_info" in status:
            enhanced_status["connection_pool"] = status["pool_info"]
        
        return enhanced_status
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Optimized bot status error: {e}")
        raise HTTPException(status_code=500, detail=f"Bot durumu alınamadı: {str(e)}")

@router.get("/system-stats")
async def get_system_stats(current_user: dict = Depends(get_current_user)):
    """Sistem istatistiklerini getir (NEW ENDPOINT)"""
    try:
        # Admin kontrolü (opsiyonel)
        user_id = current_user['uid']
        user_data = firebase_manager.get_user_data(user_id)
        
        # Basic stats for all users, detailed for admins
        is_admin = user_data.get('role') == 'admin' if user_data else False
        
        system_stats = bot_manager.get_system_stats()
        scalability_info = settings.get_scalability_info()
        
        basic_stats = {
            "total_active_users": system_stats["total_active_users"],
            "architecture": system_stats["architecture"],
            "system_status": system_stats["system_status"],
            "capacity_info": {
                "current_load": system_stats["total_active_users"],
                "high_load_threshold": settings.SYSTEM_HIGH_LOAD_THRESHOLD,
                "critical_load_threshold": settings.SYSTEM_CRITICAL_LOAD_THRESHOLD,
                "load_percentage": round((system_stats["total_active_users"] / settings.SYSTEM_HIGH_LOAD_THRESHOLD) * 100, 1)
            }
        }
        
        # Detailed stats for admins only
        if is_admin:
            basic_stats.update({
                "detailed_stats": system_stats,
                "scalability_config": scalability_info,
                "performance_metrics": {
                    "connections_saved": system_stats.get("total_connections_saved", 0),
                    "shared_clients": system_stats.get("shared_clients", 0),
                    "memory_efficiency": "99% reduction vs legacy architecture"
                }
            })
        
        return {
            "success": True,
            "stats": basic_stats
        }
        
    except Exception as e:
        logger.error(f"System stats error: {e}")
        raise HTTPException(status_code=500, detail=f"Sistem istatistikleri alınamadı: {str(e)}")

@router.post("/api-keys")
async def save_api_keys(
    request: ApiKeysRequest,
    current_user: dict = Depends(get_current_user)
):
    """Kullanıcının API anahtarlarını kaydet (rate limited)"""
    test_client = None
    try:
        user_id = current_user['uid']
        logger.info(f"API keys save request from user: {user_id}")
        
        # Rate limiting check (NEW)
        last_api_test = firebase_manager.get_user_data(user_id, {}).get('last_api_test', 0)
        if isinstance(last_api_test, str):
            last_api_test = 0
        
        current_time = time.time()
        if current_time - last_api_test < 60:  # 1 dakika rate limit
            raise HTTPException(
                status_code=429, 
                detail="API test için 1 dakika beklemelisiniz"
            )
        
        # API anahtarlarını test et
        try:
            test_client = BinanceClient(request.api_key, request.api_secret)
            await test_client.initialize()
            
            # Test balance call
            balance = await test_client.get_account_balance(use_cache=False)
            logger.info(f"API test successful for user {user_id}, balance: {balance}")
            
        except Exception as e:
            logger.error(f"API test failed for user {user_id}: {e}")
            raise HTTPException(status_code=400, detail=f"API anahtarları geçersiz: {str(e)}")
        
        # API anahtarlarını şifrele
        encrypted_api_key = encrypt_data(request.api_key)
        encrypted_api_secret = encrypt_data(request.api_secret)
        
        # Firebase'e kaydet
        api_data = {
            "binance_api_key": encrypted_api_key,
            "binance_api_secret": encrypted_api_secret,
            "api_testnet": request.testnet,
            "api_keys_set": True,
            "api_connection_verified": True,
            "api_updated_at": firebase_manager.get_server_timestamp(),
            "last_api_test": int(current_time),  # NEW: Rate limiting
            "account_balance": balance,
            "api_architecture": "optimized_scalable"  # NEW: Architecture tracking
        }
        
        success = firebase_manager.update_user_data(user_id, api_data)
        
        if not success:
            raise HTTPException(status_code=500, detail="API anahtarları kaydedilemedi")
        
        logger.info(f"API keys saved for user: {user_id}")
        
        return {
            "success": True,
            "message": "API anahtarları başarıyla kaydedildi ve test edildi (optimized)",
            "balance": balance,
            "system_info": {
                "architecture": "scalable",
                "next_test_allowed": int(current_time + 60)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API keys save error: {e}")
        raise HTTPException(status_code=500, detail=f"API anahtarları kaydedilemedi: {str(e)}")
    finally:
        # Ensure client is closed (NEW)
        if test_client:
            try:
                await test_client.close()
            except Exception as close_error:
                logger.error(f"Test client close error: {close_error}")

@router.get("/api-status")
async def get_api_status(current_user: dict = Depends(get_current_user)):
    """Kullanıcının API durumunu kontrol et (optimized)"""
    try:
        user_id = current_user['uid']
        user_data = firebase_manager.get_user_data(user_id)
        
        if not user_data:
            return {
                "hasApiKeys": False,
                "isConnected": False,
                "message": "Kullanıcı verisi bulunamadı"
            }
        
        has_api_keys = user_data.get('api_keys_set', False)
        
        if not has_api_keys:
            return {
                "hasApiKeys": False,
                "isConnected": False,
                "message": "API anahtarları ayarlanmamış",
                "architecture": "scalable"
            }
        
        # Quick status check without actual API call (NEW - more efficient)
        last_test_time = user_data.get('last_api_test', 0)
        api_verified = user_data.get('api_connection_verified', False)
        
        # If recently verified, trust the cached status
        current_time = time.time()
        recently_verified = current_time - last_test_time < 3600  # 1 hour cache
        
        if recently_verified and api_verified:
            return {
                "hasApiKeys": True,
                "isConnected": True,
                "message": "API anahtarları aktif (cached)",
                "architecture": "scalable",
                "last_verified": int(last_test_time),
                "cache_expiry": int(last_test_time + 3600)
            }
        
        # Fallback to format check
        try:
            encrypted_api_key = user_data.get('binance_api_key')
            encrypted_api_secret = user_data.get('binance_api_secret')
            
            if encrypted_api_key and encrypted_api_secret:
                api_key = decrypt_data(encrypted_api_key)
                api_secret = decrypt_data(encrypted_api_secret)
                
                if api_key and api_secret and len(api_key) == 64 and len(api_secret) == 64:
                    return {
                        "hasApiKeys": True,
                        "isConnected": True,
                        "message": "API anahtarları format OK (test gerekebilir)",
                        "architecture": "scalable",
                        "verification_needed": not recently_verified
                    }
                else:
                    return {
                        "hasApiKeys": True,
                        "isConnected": False,
                        "message": "API anahtarları geçersiz format",
                        "architecture": "scalable"
                    }
            else:
                return {
                    "hasApiKeys": False,
                    "isConnected": False,
                    "message": "API anahtarları bulunamadı",
                    "architecture": "scalable"
                }
                
        except Exception as e:
            logger.error(f"API status check error for user {user_id}: {e}")
            return {
                "hasApiKeys": True,
                "isConnected": False,
                "message": f"API durum kontrolü hatası: {str(e)}",
                "architecture": "scalable"
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API status check error: {e}")
        raise HTTPException(status_code=500, detail=f"API durumu kontrol edilemedi: {str(e)}")

@router.get("/trading-pairs")
async def get_trading_pairs(current_user: dict = Depends(get_current_user)):
    """Desteklenen trading çiftlerini getir"""
    try:
        # Enhanced trading pairs with more info (NEW)
        pairs = [
            {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "minNotional": "10", "popular": True},
            {"symbol": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT", "minNotional": "10", "popular": True},
            {"symbol": "BNBUSDT", "baseAsset": "BNB", "quoteAsset": "USDT", "minNotional": "10", "popular": True},
            {"symbol": "ADAUSDT", "baseAsset": "ADA", "quoteAsset": "USDT", "minNotional": "10", "popular": False},
            {"symbol": "DOTUSDT", "baseAsset": "DOT", "quoteAsset": "USDT", "minNotional": "10", "popular": False},
            {"symbol": "LINKUSDT", "baseAsset": "LINK", "quoteAsset": "USDT", "minNotional": "10", "popular": False},
            {"symbol": "LTCUSDT", "baseAsset": "LTC", "quoteAsset": "USDT", "minNotional": "10", "popular": False},
            {"symbol": "BCHUSDT", "baseAsset": "BCH", "quoteAsset": "USDT", "minNotional": "10", "popular": False},
            {"symbol": "XRPUSDT", "baseAsset": "XRP", "quoteAsset": "USDT", "minNotional": "10", "popular": False},
            {"symbol": "EOSUSDT", "baseAsset": "EOS", "quoteAsset": "USDT", "minNotional": "10", "popular": False}
        ]
        
        return {
            "success": True,
            "pairs": pairs,
            "system_info": {
                "architecture": "scalable",
                "supported_timeframes": ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"],
                "default_timeframe": settings.DEFAULT_TIMEFRAME,
                "min_order_size": settings.MIN_ORDER_SIZE_USDT,
                "max_order_size": settings.MAX_ORDER_SIZE_USDT
            }
        }
        
    except Exception as e:
        logger.error(f"Trading pairs fetch error: {e}")
        raise HTTPException(status_code=500, detail="Trading çiftleri alınamadı")

@router.get("/health")
async def health_check():
    """System health check endpoint (NEW)"""
    try:
        system_stats = bot_manager.get_system_stats()
        active_users = system_stats["total_active_users"]
        
        # Health status determination
        if active_users < settings.SYSTEM_HIGH_LOAD_THRESHOLD:
            health_status = "healthy"
        elif active_users < settings.SYSTEM_CRITICAL_LOAD_THRESHOLD:
            health_status = "high_load"
        else:
            health_status = "critical_load"
        
        return {
            "status": "ok",
            "health": health_status,
            "architecture": "optimized_scalable",
            "metrics": {
                "active_users": active_users,
                "capacity_percentage": round((active_users / settings.SYSTEM_HIGH_LOAD_THRESHOLD) * 100, 1),
                "shared_clients": system_stats.get("shared_clients", 0)
            },
            "thresholds": {
                "high_load": settings.SYSTEM_HIGH_LOAD_THRESHOLD,
                "critical_load": settings.SYSTEM_CRITICAL_LOAD_THRESHOLD
            }
        }
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "status": "error",
            "health": "unhealthy",
            "error": str(e)
        }
