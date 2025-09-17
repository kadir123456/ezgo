from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer
from app.bot_manager import bot_manager
from app.firebase_manager import firebase_manager
from app.utils.crypto import encrypt_data, decrypt_data
from app.utils.validation import EnhancedStartRequest, EnhancedApiKeysRequest
from app.utils.metrics import metrics
import firebase_admin
from firebase_admin import auth as firebase_auth
import logging

logger = logging.getLogger("bot_routes")
router = APIRouter(prefix="/api/bot", tags=["bot"])
security = HTTPBearer()

async def get_current_user(token: str = Depends(security)):
    """JWT token'dan kullanıcı bilgilerini al"""
    try:
        decoded_token = firebase_auth.verify_id_token(token.credentials)
        return decoded_token
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

@router.post("/start")
async def start_bot(
    request: EnhancedStartRequest,
    current_user: dict = Depends(get_current_user)
):
    """Kullanıcı için bot başlat"""
    try:
        user_id = current_user['uid']
        logger.info(f"Bot start request from user: {user_id}")
        
        # Kullanıcının abonelik durumunu kontrol et
        user_data = firebase_manager.get_user_data(user_id)
        if not user_data:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
        
        # Abonelik kontrolü
        subscription_status = user_data.get('subscription_status')
        if subscription_status not in ['trial', 'active']:
            raise HTTPException(status_code=403, detail="Aktif abonelik gerekli")
        
        # Bot'u başlat
        result = await bot_manager.start_bot_for_user(user_id, request)
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # Metrics kaydet
        metrics.record_bot_start(user_id, request.symbol)
        
        return {
            "success": True,
            "message": "Bot başarıyla başlatıldı",
            "bot_status": result.get("status", {})
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bot start error: {e}")
        metrics.record_error("bot_start_failed", "bot_manager")
        raise HTTPException(status_code=500, detail=f"Bot başlatılamadı: {str(e)}")

@router.post("/stop")
async def stop_bot(current_user: dict = Depends(get_current_user)):
    """Kullanıcının botunu durdur"""
    try:
        user_id = current_user['uid']
        logger.info(f"Bot stop request from user: {user_id}")
        
        result = await bot_manager.stop_bot_for_user(user_id)
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # Metrics kaydet
        metrics.record_bot_stop(user_id, "manual", "user_request")
        
        return {
            "success": True,
            "message": "Bot başarıyla durduruldu"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bot stop error: {e}")
        raise HTTPException(status_code=500, detail=f"Bot durdurulamadı: {str(e)}")

@router.get("/status")
async def get_bot_status(current_user: dict = Depends(get_current_user)):
    """Kullanıcının bot durumunu getir"""
    try:
        user_id = current_user['uid']
        status = bot_manager.get_bot_status(user_id)
        
        return {
            "success": True,
            "status": status
        }
        
    except Exception as e:
        logger.error(f"Bot status error: {e}")
        raise HTTPException(status_code=500, detail=f"Bot durumu alınamadı: {str(e)}")

@router.post("/api-keys")
async def save_api_keys(
    request: EnhancedApiKeysRequest,
    current_user: dict = Depends(get_current_user)
):
    """Kullanıcının API anahtarlarını kaydet"""
    try:
        user_id = current_user['uid']
        logger.info(f"API keys save request from user: {user_id}")
        
        # API anahtarlarını şifrele
        encrypted_api_key = encrypt_data(request.api_key)
        encrypted_api_secret = encrypt_data(request.api_secret)
        
        # Firebase'e kaydet
        api_data = {
            "binance_api_key": encrypted_api_key,
            "binance_api_secret": encrypted_api_secret,
            "api_testnet": request.testnet,
            "api_keys_set": True,
            "api_updated_at": firebase_manager.get_server_timestamp()
        }
        
        success = firebase_manager.update_user_data(user_id, api_data)
        
        if not success:
            raise HTTPException(status_code=500, detail="API anahtarları kaydedilemedi")
        
        logger.info(f"API keys saved for user: {user_id}")
        
        return {
            "success": True,
            "message": "API anahtarları başarıyla kaydedildi"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API keys save error: {e}")
        raise HTTPException(status_code=500, detail=f"API anahtarları kaydedilemedi: {str(e)}")

@router.get("/api-status")
async def get_api_status(current_user: dict = Depends(get_current_user)):
    """Kullanıcının API durumunu kontrol et"""
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
                "message": "API anahtarları ayarlanmamış"
            }
        
        # API bağlantısını test et
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
                        "message": "API anahtarları aktif"
                    }
                else:
                    return {
                        "hasApiKeys": True,
                        "isConnected": False,
                        "message": "API anahtarları geçersiz format"
                    }
            else:
                return {
                    "hasApiKeys": False,
                    "isConnected": False,
                    "message": "API anahtarları bulunamadı"
                }
                
        except Exception as e:
            logger.error(f"API test error for user {user_id}: {e}")
            return {
                "hasApiKeys": True,
                "isConnected": False,
                "message": f"API test hatası: {str(e)}"
            }
        
    except Exception as e:
        logger.error(f"API status check error: {e}")
        raise HTTPException(status_code=500, detail=f"API durumu kontrol edilemedi: {str(e)}")

@router.get("/trading-pairs")
async def get_trading_pairs(current_user: dict = Depends(get_current_user)):
    """Desteklenen trading çiftlerini getir"""
    try:
        # Popüler trading çiftleri
        pairs = [
            {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"},
            {"symbol": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT"},
            {"symbol": "BNBUSDT", "baseAsset": "BNB", "quoteAsset": "USDT"},
            {"symbol": "ADAUSDT", "baseAsset": "ADA", "quoteAsset": "USDT"},
            {"symbol": "DOTUSDT", "baseAsset": "DOT", "quoteAsset": "USDT"},
            {"symbol": "LINKUSDT", "baseAsset": "LINK", "quoteAsset": "USDT"},
            {"symbol": "LTCUSDT", "baseAsset": "LTC", "quoteAsset": "USDT"},
            {"symbol": "BCHUSDT", "baseAsset": "BCH", "quoteAsset": "USDT"},
            {"symbol": "XRPUSDT", "baseAsset": "XRP", "quoteAsset": "USDT"},
            {"symbol": "EOSUSDT", "baseAsset": "EOS", "quoteAsset": "USDT"}
        ]
        
        return {
            "success": True,
            "pairs": pairs
        }
        
    except Exception as e:
        logger.error(f"Trading pairs fetch error: {e}")
        raise HTTPException(status_code=500, detail="Trading çiftleri alınamadı")

@router.get("/system-stats")
async def get_system_stats(current_user: dict = Depends(get_current_user)):
    """Sistem istatistikleri (admin için)"""
    try:
        user_id = current_user['uid']
        user_data = firebase_manager.get_user_data(user_id)
        
        # Admin kontrolü
        if not user_data or user_data.get('role') != 'admin':
            raise HTTPException(status_code=403, detail="Admin yetkisi gerekli")
        
        stats = bot_manager.get_system_stats()
        return {
            "success": True,
            "stats": stats
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"System stats error: {e}")
        raise HTTPException(status_code=500, detail="Sistem istatistikleri alınamadı")
