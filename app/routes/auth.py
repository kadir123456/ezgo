from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.firebase_manager import firebase_manager
from app.utils.validation import LoginRequest, RegisterRequest
from app.utils.logger import get_logger
import firebase_admin
from firebase_admin import auth as firebase_auth
from typing import Optional

logger = get_logger("auth_routes")
router = APIRouter(prefix="/api/auth", tags=["authentication"])
security = HTTPBearer(auto_error=False)

async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    """Firebase Auth token'dan kullanıcı bilgilerini al"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication token required")
    
    try:
        # Firebase token'ı verify et
        decoded_token = firebase_auth.verify_id_token(credentials.credentials)
        logger.info(f"Token verified for user: {decoded_token['uid']}")
        return decoded_token
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication token")

@router.post("/verify")
async def verify_token(current_user: dict = Depends(get_current_user)):
    """Firebase token doğrulama"""
    try:
        user_id = current_user['uid']
        email = current_user.get('email')
        
        # Kullanıcı verilerini Firebase'den al
        user_data = firebase_manager.get_user_data(user_id)
        
        # Eğer kullanıcı verisi yoksa oluştur
        if not user_data:
            logger.info(f"Creating user data for new user: {user_id}")
            user_data = {
                "email": email,
                "created_at": firebase_manager.get_server_timestamp(),
                "last_login": firebase_manager.get_server_timestamp(),
                "subscription_status": "trial",
                "api_keys_set": False,
                "bot_active": False,
                "total_trades": 0,
                "total_pnl": 0.0,
                "role": "user"
            }
            firebase_manager.update_user_data(user_id, user_data)
        else:
            # Son giriş zamanını güncelle
            firebase_manager.update_user_data(user_id, {
                "last_login": firebase_manager.get_server_timestamp()
            })
        
        return {
            "success": True,
            "user_id": user_id,
            "email": email,
            "user_data": user_data
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token verification error: {e}")
        raise HTTPException(status_code=500, detail="Token verification failed")

@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    """Kullanıcı çıkışı"""
    try:
        user_id = current_user['uid']
        
        # Son çıkış zamanını kaydet
        firebase_manager.update_user_data(user_id, {
            "last_logout": firebase_manager.get_server_timestamp()
        })
        
        logger.info(f"User logged out: {user_id}")
        
        return {
            "success": True,
            "message": "Başarıyla çıkış yapıldı"
        }
    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HTTPException(status_code=500, detail="Çıkış işlemi başarısız")

@router.get("/user-info")
async def get_user_info(current_user: dict = Depends(get_current_user)):
    """Kullanıcı bilgilerini getir"""
    try:
        user_id = current_user['uid']
        
        user_data = firebase_manager.get_user_data(user_id)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Hassas bilgileri çıkar
        safe_user_data = {
            "email": user_data.get("email"),
            "full_name": user_data.get("full_name"),
            "subscription_status": user_data.get("subscription_status"),
            "subscription_expiry": user_data.get("subscription_expiry"),
            "api_keys_set": user_data.get("api_keys_set", False),
            "total_trades": user_data.get("total_trades", 0),
            "total_pnl": user_data.get("total_pnl", 0.0),
            "role": user_data.get("role", "user"),
            "created_at": user_data.get("created_at"),
            "last_login": user_data.get("last_login")
        }
        
        return safe_user_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user info")
