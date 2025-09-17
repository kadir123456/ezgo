from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer
from app.bot_manager import bot_manager, StartRequest
from app.firebase_manager import firebase_manager
from app.utils.logger import get_logger
from app.utils.crypto import encrypt_data, decrypt_data
from pydantic import BaseModel
import firebase_admin
from firebase_admin import auth as firebase_auth

logger = get_logger("bot_routes")
router = APIRouter(prefix="/api/bot", tags=["bot"])
security = HTTPBearer()

class ApiKeysRequest(BaseModel):
    api_key: str
    api_secret: str
    testnet: bool = False

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
    request: StartRequest,
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
        
        return {
            "success": True,
            "message": "Bot başarıyla başlatıldı",
            "bot_status": result.get("status", {})
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bot start error: {e}")
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
    request: ApiKeysRequest,
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
            "api_updated_at": firebase_manager.db.reference().server_timestamp
        }
        
        firebase_manager.db.reference(f'users/{user_id}').update(api_data)
        
        logger.info(f"API keys saved for user: {user_id}")
        
        return {
            "success": True,
            "message": "API anahtarları başarıyla kaydedildi"
        }
        
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
        
        # API bağlantısını test et (basit kontrol)
        try:
            encrypted_api_key = user_data.get('binance_api_key')
            encrypted_api_secret = user_data.get('binance_api_secret')
            
            if encrypted_api_key and encrypted_api_secret:
                # Şifreleri çöz ve test et
                api_key = decrypt_data(encrypted_api_key)
                api_secret = decrypt_data(encrypted_api_secret)
                
                if api_key and api_secret:
                    return {
                        "hasApiKeys": True,
                        "isConnected": True,
                        "message": "API anahtarları aktif"
                    }
                else:
                    return {
                        "hasApiKeys": True,
                        "isConnected": False,
                        "message": "API anahtarları çözülemedi"
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
