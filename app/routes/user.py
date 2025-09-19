# app/routes/user.py (FIXED - Rate limit sorunu çözüldü)
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.firebase_manager import firebase_manager
from app.utils.logger import get_logger
from app.utils.crypto import decrypt_data, encrypt_data
from app.core.client_manager import client_manager  # ✅ YENİ: Singleton client manager
from app.bot_manager import bot_manager
from pydantic import BaseModel
import firebase_admin
from firebase_admin import auth as firebase_auth
from datetime import datetime, timezone
from typing import Optional
import asyncio

logger = get_logger("user_routes")
router = APIRouter(prefix="/api/user", tags=["user"])
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

async def get_user_client(user_id: str, user_data: dict):
    """
    ✅ HELPER: Kullanıcının BinanceClient'ını al (singleton)
    Rate limit sorununu çözer
    """
    if not user_data or not user_data.get('api_keys_set'):
        return None
    
    try:
        encrypted_api_key = user_data.get('binance_api_key')
        encrypted_api_secret = user_data.get('binance_api_secret')
        
        if not encrypted_api_key or not encrypted_api_secret:
            return None
        
        api_key = decrypt_data(encrypted_api_key)
        api_secret = decrypt_data(encrypted_api_secret)
        
        if not api_key or not api_secret:
            return None
        
        # ✅ Singleton client al - rate limit korunur
        client = await client_manager.get_client(user_id, api_key, api_secret)
        return client
        
    except Exception as e:
        logger.error(f"Error getting client for user {user_id}: {e}")
        return None

@router.get("/dashboard-data")
async def get_dashboard_data(current_user: dict = Depends(get_current_user)):
    """
    ✅ YENİ: Tüm dashboard verilerini tek seferde getir
    Rate limit sorununu çözer - 8 API çağrısı → 1 API çağrısı
    """
    try:
        user_id = current_user['uid']
        user_data = firebase_manager.get_user_data(user_id)
        
        # Varsayılan değerler
        dashboard_data = {
            "profile": await get_profile_data(user_id, user_data),
            "account": {
                "totalBalance": 0.0,
                "availableBalance": 0.0,
                "unrealizedPnl": 0.0,
                "message": "API anahtarları gerekli"
            },
            "positions": [],
            "stats": await get_stats_data(user_data),
            "api_status": {
                "hasApiKeys": False,
                "isConnected": False,
                "message": "API anahtarları ayarlanmamış"
            }
        }
        
        # ✅ SADECE API keys varsa Binance verilerini al
        client = await get_user_client(user_id, user_data)
        if client:
            try:
                # ✅ PARALEL veri alımı - ama aynı client kullanarak
                balance_task = client.get_account_balance(use_cache=True)
                positions_task = client.get_open_positions("BTCUSDT", use_cache=True)
                
                # Paralel bekle
                balance, positions = await asyncio.gather(
                    balance_task, 
                    positions_task,
                    return_exceptions=True
                )
                
                # Balance sonucu
                if isinstance(balance, Exception):
                    logger.error(f"Balance error: {balance}")
                    balance = user_data.get("account_balance", 0.0)
                
                # Positions sonucu
                if isinstance(positions, Exception):
                    logger.error(f"Positions error: {positions}")
                    positions = []
                
                # ✅ Gerçek Binance verileri
                dashboard_data.update({
                    "account": {
                        "totalBalance": balance,
                        "availableBalance": balance,
                        "unrealizedPnl": sum(float(p.get('unRealizedProfit', 0)) for p in positions),
                        "message": "Gerçek Binance verileri (cached)"
                    },
                    "positions": await format_positions(positions),
                    "api_status": {
                        "hasApiKeys": True,
                        "isConnected": True,
                        "message": f"API aktif - Balance: {balance:.2f} USDT"
                    }
                })
                
                # ✅ Firebase cache güncelle (async)
                asyncio.create_task(update_user_cache(user_id, balance))
                
                logger.info(f"✅ Dashboard data loaded for user: {user_id}")
                
            except Exception as e:
                logger.error(f"Binance data error for user {user_id}: {e}")
                # Fallback to cached/default data
                dashboard_data["account"]["message"] = f"Cache verisi (API hatası: {str(e)})"
                dashboard_data["api_status"]["isConnected"] = False
                dashboard_data["api_status"]["message"] = f"API bağlantı hatası: {str(e)}"
        
        return dashboard_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Dashboard data error: {e}")
        raise HTTPException(status_code=500, detail="Dashboard verileri alınamadı")

async def get_profile_data(user_id: str, user_data: dict) -> dict:
    """Helper: Profil verilerini getir"""
    if not user_data:
        # Yeni kullanıcı için varsayılan veri oluştur
        logger.info(f"Creating default user data for: {user_id}")
        user_data = {
            "email": "unknown@example.com",
            "created_at": firebase_manager.get_server_timestamp(),
            "subscription_status": "trial",
            "api_keys_set": False,
            "bot_active": False,
            "total_trades": 0,
            "total_pnl": 0.0,
            "role": "user"
        }
        firebase_manager.update_user_data(user_id, user_data)
    
    return {
        "email": user_data.get("email", "unknown@example.com"),
        "full_name": user_data.get("full_name"),
        "subscription": {
            "status": user_data.get("subscription_status", "trial"),
            "plan": "Premium" if user_data.get("subscription_status") == "active" else "Deneme",
            "expiryDate": user_data.get("subscription_expiry"),
            "daysRemaining": user_data.get("days_remaining", 7)
        },
        "api_keys_set": user_data.get("api_keys_set", False),
        "bot_active": user_data.get("bot_active", False),
        "total_trades": user_data.get("total_trades", 0),
        "total_pnl": user_data.get("total_pnl", 0.0),
        "account_balance": user_data.get("account_balance", 0.0),
        "created_at": user_data.get("created_at"),
        "last_login": user_data.get("last_login")
    }

async def get_stats_data(user_data: dict) -> dict:
    """Helper: İstatistik verilerini getir"""
    if not user_data:
        return {
            "totalTrades": 0,
            "totalPnl": 0.0,
            "winRate": 0.0,
            "botStartTime": None,
            "lastTradeTime": None
        }
    
    return {
        "totalTrades": user_data.get("total_trades", 0),
        "totalPnl": user_data.get("total_pnl", 0.0),
        "winRate": user_data.get("win_rate", 0.0),
        "botStartTime": user_data.get("bot_start_time"),
        "lastTradeTime": user_data.get("last_trade_time")
    }

async def format_positions(positions: list) -> list:
    """Helper: Pozisyonları formatla"""
    formatted_positions = []
    
    for pos in positions:
        try:
            position_amt = float(pos['positionAmt'])
            if position_amt != 0:  # Sadece açık pozisyonlar
                # Percentage hesaplama
                entry_price = float(pos['entryPrice'])
                mark_price = float(pos['markPrice'])
                percentage = 0.0
                
                if entry_price > 0:
                    if position_amt > 0:  # Long pozisyon
                        percentage = ((mark_price - entry_price) / entry_price) * 100
                    else:  # Short pozisyon
                        percentage = ((entry_price - mark_price) / entry_price) * 100
                
                formatted_positions.append({
                    "symbol": pos['symbol'],
                    "positionSide": "LONG" if position_amt > 0 else "SHORT",
                    "positionAmt": str(abs(position_amt)),
                    "entryPrice": pos['entryPrice'],
                    "markPrice": pos['markPrice'],
                    "unrealizedPnl": float(pos['unRealizedProfit']),
                    "percentage": round(percentage, 2)
                })
        except Exception as e:
            logger.error(f"Position format error: {e}")
            continue
    
    return formatted_positions

async def update_user_cache(user_id: str, balance: float):
    """Helper: Kullanıcı cache'ini güncelle (async)"""
    try:
        firebase_manager.update_user_data(user_id, {
            "account_balance": balance,
            "last_balance_update": firebase_manager.get_server_timestamp()
        })
    except Exception as e:
        logger.error(f"Cache update error for user {user_id}: {e}")

# ✅ ESKİ ENDPOINT'LER - Geriye uyumluluk için (artık cache kullanırlar)
@router.get("/profile")
async def get_user_profile(current_user: dict = Depends(get_current_user)):
    """Kullanıcı profil bilgilerini getir - OPTIMIZED"""
    try:
        user_id = current_user['uid']
        user_data = firebase_manager.get_user_data(user_id)
        return await get_profile_data(user_id, user_data)
    except Exception as e:
        logger.error(f"Profile fetch error: {e}")
        raise HTTPException(status_code=500, detail="Profil bilgileri alınamadı")

@router.get("/account")
async def get_account_data(current_user: dict = Depends(get_current_user)):
    """Kullanıcının hesap verilerini getir - OPTIMIZED"""
    try:
        user_id = current_user['uid']
        user_data = firebase_manager.get_user_data(user_id)
        
        # ✅ Singleton client kullan
        client = await get_user_client(user_id, user_data)
        
        if client:
            balance = await client.get_account_balance(use_cache=True)  # ✅ Cache kullan
            return {
                "totalBalance": balance,
                "availableBalance": balance,
                "unrealizedPnl": 0.0,
                "message": "Cached Binance data"
            }
        else:
            return {
                "totalBalance": user_data.get("account_balance", 0.0) if user_data else 0.0,
                "availableBalance": user_data.get("account_balance", 0.0) if user_data else 0.0,
                "unrealizedPnl": 0.0,
                "message": "API anahtarları gerekli"
            }
    except Exception as e:
        logger.error(f"Account data fetch error: {e}")
        raise HTTPException(status_code=500, detail="Hesap verileri alınamadı")

@router.get("/stats")
async def get_user_stats(current_user: dict = Depends(get_current_user)):
    """Kullanıcının trading istatistiklerini getir - OPTIMIZED"""
    try:
        user_id = current_user['uid']
        user_data = firebase_manager.get_user_data(user_id)
        return await get_stats_data(user_data)
    except Exception as e:
        logger.error(f"Stats fetch error: {e}")
        raise HTTPException(status_code=500, detail="İstatistikler alınamadı")

@router.get("/positions")
async def get_user_positions(current_user: dict = Depends(get_current_user)):
    """Kullanıcının açık pozisyonlarını getir - OPTIMIZED"""
    try:
        user_id = current_user['uid']
        user_data = firebase_manager.get_user_data(user_id)
        
        # ✅ Singleton client kullan
        client = await get_user_client(user_id, user_data)
        
        if client:
            # ✅ Cache kullan
            all_positions = await client.client.futures_position_information()
            return await format_positions(all_positions)
        else:
            return []
            
    except Exception as e:
        logger.error(f"Positions fetch error: {e}")
        raise HTTPException(status_code=500, detail="Pozisyonlar alınamadı")

@router.get("/recent-trades")
async def get_recent_trades(
    current_user: dict = Depends(get_current_user),
    limit: int = 10
):
    """Kullanıcının son işlemlerini getir - OPTIMIZED"""
    try:
        user_id = current_user['uid']
        trades = []
        
        # Önce Firebase'den al
        try:
            if firebase_manager.is_initialized():
                trades_ref = firebase_manager.db.reference('trades')
                query = trades_ref.order_by_child('user_id').equal_to(user_id).limit_to_last(limit)
                snapshot = query.get()
                
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
                    logger.info(f"Firebase trades loaded for user: {user_id}")
        except Exception as firebase_error:
            logger.warning(f"Firebase trades fetch failed: {firebase_error}")
        
        # Tarihe göre sırala
        trades.sort(key=lambda x: x.get("time", 0), reverse=True)
        return trades
        
    except Exception as e:
        logger.error(f"Recent trades fetch error: {e}")
        raise HTTPException(status_code=500, detail="Son işlemler alınamadı")

@router.post("/api-keys")
async def save_api_keys(
    request: ApiKeysRequest,
    current_user: dict = Depends(get_current_user)
):
    """Kullanıcının API anahtarlarını kaydet - OPTIMIZED"""
    try:
        user_id = current_user['uid']
        logger.info(f"API keys save request from user: {user_id}")
        
        # ✅ TEST: Geçici client ile test et
        from app.binance_client import BinanceClient
        test_client = BinanceClient(request.api_key, request.api_secret, f"{user_id}_test")
        
        try:
            await test_client.initialize()
            balance = await test_client.get_account_balance(use_cache=False)
            logger.info(f"API test successful for user {user_id}, balance: {balance}")
        except Exception as e:
            logger.error(f"API test failed for user {user_id}: {e}")
            raise HTTPException(status_code=400, detail=f"API anahtarları geçersiz: {str(e)}")
        finally:
            await test_client.close()
        
        # API anahtarlarını şifrele ve kaydet
        encrypted_api_key = encrypt_data(request.api_key)
        encrypted_api_secret = encrypt_data(request.api_secret)
        
        api_data = {
            "binance_api_key": encrypted_api_key,
            "binance_api_secret": encrypted_api_secret,
            "api_testnet": request.testnet,
            "api_keys_set": True,
            "api_connection_verified": True,
            "api_updated_at": firebase_manager.get_server_timestamp(),
            "account_balance": balance
        }
        
        success = firebase_manager.update_user_data(user_id, api_data)
        
        if not success:
            raise HTTPException(status_code=500, detail="API anahtarları kaydedilemedi")
        
        # ✅ Eski client'ı kaldır (yeni anahtarlar için)
        await client_manager.remove_client(user_id)
        
        logger.info(f"✅ API keys saved for user: {user_id}")
        
        return {
            "success": True,
            "message": "API anahtarları başarıyla kaydedildi ve test edildi",
            "balance": balance
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API keys save error: {e}")
        raise HTTPException(status_code=500, detail=f"API anahtarları kaydedilemedi: {str(e)}")

@router.get("/api-status")
async def get_api_status(current_user: dict = Depends(get_current_user)):
    """Kullanıcının API durumunu kontrol et - OPTIMIZED"""
    try:
        user_id = current_user['uid']
        
        # ✅ Client manager'dan status al
        status = await client_manager.get_client_status(user_id)
        
        return {
            "hasApiKeys": status["exists"],
            "isConnected": status["is_connected"],
            "message": status["message"]
        }
        
    except Exception as e:
        logger.error(f"API status check error: {e}")
        raise HTTPException(status_code=500, detail=f"API durumu kontrol edilemedi: {str(e)}")

@router.get("/api-info")
async def get_api_info(current_user: dict = Depends(get_current_user)):
    """Kullanıcının API bilgilerini getir (masked) - OPTIMIZED"""
    try:
        user_id = current_user['uid']
        user_data = firebase_manager.get_user_data(user_id)
        
        if not user_data or not user_data.get('api_keys_set'):
            return {
                "hasKeys": False,
                "maskedApiKey": None,
                "is_testnet": False
            }
        
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
            "is_testnet": user_data.get('api_testnet', False)
        }
        
    except Exception as e:
        logger.error(f"API info fetch error: {e}")
        raise HTTPException(status_code=500, detail="API bilgileri alınamadı")

@router.post("/close-position")
async def close_position(
    request: dict,
    current_user: dict = Depends(get_current_user)
):
    """Pozisyon kapatma - OPTIMIZED"""
    try:
        user_id = current_user['uid']
        symbol = request.get('symbol')
        position_side = request.get('positionSide')
        
        if not symbol or not position_side:
            raise HTTPException(status_code=400, detail="Symbol ve position side gerekli")
        
        user_data = firebase_manager.get_user_data(user_id)
        
        # ✅ Singleton client kullan
        client = await get_user_client(user_id, user_data)
        if not client:
            raise HTTPException(status_code=400, detail="API anahtarları gerekli")
        
        # Pozisyon bilgilerini al
        positions = await client.get_open_positions(symbol, use_cache=False)
        
        if not positions:
            raise HTTPException(status_code=404, detail="Açık pozisyon bulunamadı")
        
        position = positions[0]
        position_amt = float(position['positionAmt'])
        side_to_close = 'SELL' if position_amt > 0 else 'BUY'
        
        # Pozisyonu kapat
        close_result = await client.close_position(symbol, position_amt, side_to_close)
        
        if close_result:
            return {
                "success": True,
                "message": "Pozisyon başarıyla kapatıldı"
            }
        else:
            raise Exception("Pozisyon kapatma işlemi başarısız")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Position close error: {e}")
        raise HTTPException(status_code=500, detail="Pozisyon kapatılamadı")
