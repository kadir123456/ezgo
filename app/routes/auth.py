from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer
from app.firebase_manager import firebase_manager
from app.utils.validation import LoginRequest, RegisterRequest
import firebase_admin
from firebase_admin import auth as firebase_auth
import logging

logger = logging.getLogger("auth_routes")
router = APIRouter(prefix="/api/auth", tags=["authentication"])
security = HTTPBearer()

async def get_current_user(token: str = Depends(security)):
    """JWT token'dan kullanıcı bilgilerini al"""
    try:
        decoded_token = firebase_auth.verify_id_token(token.credentials)
        return decoded_token
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

@router.post("/verify-token")
async def verify_token(token: str = Depends(security)):
    """Firebase token doğrulama"""
    try:
        decoded_token = firebase_auth.verify_id_token(token.credentials)
        return {
            "success": True,
            "user_id": decoded_token['uid'],
            "email": decoded_token.get('email')
        }
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

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
            "role": user_data.get("role", "user")
        }
        
        return safe_user_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user info")
