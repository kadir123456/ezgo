from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer
from app.firebase_manager import firebase_manager
from app.utils.crypto import decrypt_data
from pydantic import BaseModel
import firebase_admin
from firebase_admin import auth as firebase_auth
from datetime import datetime, timezone
import logging

logger = logging.getLogger("user_routes")
router = APIRouter(prefix="/api/user", tags=["user"])
security = HTTPBearer()

async def get_current_user(token: str = Depends(security)):
    """JWT token'dan kullanıcı bilgilerini al"""
    try:
        decoded_token = firebase_auth.verify_id_token(token.credentials)
        return decoded_token
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

@router.get("/profile")
async def get_user_profile(current_user: dict = Depends(get_current_user)):
    """Kullanıcı profil bilgilerini getir"""
    try:
        user_id = current_user['uid']
        user_data = firebase_manager.get_user_data(user_id)
        
        if not user_data:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
        
        # Güvenli kullanıcı bilgileri döndür
        profile = {
            "email": user_data.get("email"),
            "full_name": user_data.get("full_name"),
            "subscription": {
                "status": user_data.get("subscription_status", "trial"),
                "plan": "Premium" if user_data.get("subscription_status") == "active" else "Deneme",
                "expiryDate": user_data.get("subscription_expiry")
            },
            "api_keys_set": user_data.get("api_keys_set", False),
            "bot_active": user_data.get("bot_active", False),
            "total_trades": user_data.get("total_trades", 0),
            "total_pnl": user_data.get("total_pnl", 0.0),
            "account_balance": user_data.get("account_balance", 0.0),
            "created_at": user_data.get("created_at"),
            "last_login": user_data.get("last_login")
        }
        
        return profile
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Profile fetch error: {e}")
        raise HTTPException(status_code=500, detail="Profil bilgileri alınamadı")

@router.get("/account")
async def get_account_data(current_user: dict = Depends(get_current_user)):
    """Kullanıcının hesap verilerini getir"""
    try:
        user_id = current_user['uid']
        user_data = firebase_manager.get_user_data(user_id)
        
        if not user_data:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
        
        # Binance hesap bilgilerini al (eğer API anahtarları varsa)
        account_data = {
            "totalBalance": user_data.get("account_balance", 0.0),
            "availableBalance": user_data.get("account_balance", 0.0),
            "unrealizedPnl": user_data.get("position_pnl", 0.0)
        }
        
        return account_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Account data fetch error: {e}")
        raise HTTPException(status_code=500, detail="Hesap verileri alınamadı")

@router.get("/stats")
async def get_user_stats(current_user: dict = Depends(get_current_user)):
    """Kullanıcının trading istatistiklerini getir"""
    try:
        user_id = current_user['uid']
        user_data = firebase_manager.get_user_data(user_id)
        
        if not user_data:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
        
        # Trading istatistikleri
        stats = {
            "totalTrades": user_data.get("total_trades", 0),
            "totalPnl": user_data.get("total_pnl", 0.0),
            "winRate": user_data.get("win_rate", 0.0),
            "botStartTime": user_data.get("bot_start_time"),
            "lastTradeTime": user_data.get("last_trade_time")
        }
        
        return stats
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stats fetch error: {e}")
        raise HTTPException(status_code=500, detail="İstatistikler alınamadı")

@router.get("/positions")
async def get_user_positions(current_user: dict = Depends(get_current_user)):
    """Kullanıcının açık pozisyonlarını getir"""
    try:
        user_id = current_user['uid']
        
        # Bot manager'dan kullanıcının bot durumunu al
        bot_status = bot_manager.get_bot_status(user_id)
        
        positions = []
        if bot_status.get("is_running") and bot_status.get("position_side"):
            # Aktif pozisyon varsa bilgilerini döndür
            positions.append({
                "symbol": bot_status.get("symbol"),
                "positionSide": bot_status.get("position_side"),
                "positionAmt": "1.0",  # Gerçek miktar Binance'dan alınmalı
                "entryPrice": "0.0",   # Gerçek giriş fiyatı
                "markPrice": "0.0",    # Güncel fiyat
                "unrealizedPnl": bot_status.get("position_pnl", 0.0)
            })
        
        return positions
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Positions fetch error: {e}")
        raise HTTPException(status_code=500, detail="Pozisyonlar alınamadı")

@router.get("/recent-trades")
async def get_recent_trades(
    current_user: dict = Depends(get_current_user),
    limit: int = 10
):
    """Kullanıcının son işlemlerini getir"""
    try:
        user_id = current_user['uid']
        
        # Firebase'den kullanıcının son işlemlerini al
        trades_ref = firebase_manager.db.reference('trades')
        query = trades_ref.order_by_child('user_id').equal_to(user_id).limit_to_last(limit)
        snapshot = query.get()
        
        trades = []
        if snapshot:
            for trade_id, trade_data in snapshot.items():
                trades.append({
                    "id": trade_id,
                    "symbol": trade_data.get("symbol"),
                    "side": trade_data.get("side"),
                    "quantity": trade_data.get("quantity", 0),
                    "price": trade_data.get("price", 0),
                    "quoteQty": trade_data.get("quote_qty", 0),
                    "pnl": trade_data.get("pnl", 0),
                    "status": trade_data.get("status"),
                    "time": trade_data.get("timestamp")
                })
        
        # Tarihe göre sırala (en yeni önce)
        trades.sort(key=lambda x: x.get("time", ""), reverse=True)
        
        return trades
        
    except Exception as e:
        logger.error(f"Recent trades fetch error: {e}")
        raise HTTPException(status_code=500, detail="Son işlemler alınamadı")

@router.get("/api-info")
async def get_api_info(current_user: dict = Depends(get_current_user)):
    """Kullanıcının API bilgilerini getir (masked)"""
    try:
        user_id = current_user['uid']
        user_data = firebase_manager.get_user_data(user_id)
        
        if not user_data:
            return {
                "hasKeys": False,
                "maskedApiKey": None,
                "useTestnet": False
            }
        
        has_keys = user_data.get('api_keys_set', False)
        
        if has_keys:
            # API key'in ilk 8 karakterini göster
            encrypted_api_key = user_data.get('binance_api_key')
            masked_key = None
            
            if encrypted_api_key:
                try:
                    api_key = decrypt_data(encrypted_api_key)
                    if api_key and len(api_key) >= 8:
                        masked_key = api_key[:8] + "..." + api_key[-4:]
                except:
                    masked_key = "Şifreli API Key"
            
            return {
                "hasKeys": True,
                "maskedApiKey": masked_key,
                "useTestnet": user_data.get('api_testnet', False)
            }
        else:
            return {
                "hasKeys": False,
                "maskedApiKey": None,
                "useTestnet": False
            }
        
    except Exception as e:
        logger.error(f"API info fetch error: {e}")
        raise HTTPException(status_code=500, detail="API bilgileri alınamadı")
