from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.firebase_manager import firebase_manager
from app.utils.logger import get_logger
from app.utils.crypto import decrypt_data, encrypt_data
from app.binance_client import BinanceClient
from app.bot_manager import bot_manager
from pydantic import BaseModel
import firebase_admin
from firebase_admin import auth as firebase_auth
from datetime import datetime, timezone
from typing import Optional

logger = get_logger("user_routes")
router = APIRouter(prefix="/api/user", tags=["user"])
security = HTTPBearer(auto_error=False)

async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    """Firebase Auth token'dan kullanıcı bilgilerini al"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication token required")
    
    try:
        decoded_token = firebase_auth.verify_id_token(credentials.credentials)
        logger.info(f"User authenticated: {decoded_token['uid']}")
        return decoded_token
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication token")

class ApiKeysRequest(BaseModel):
    api_key: str
    api_secret: str
    testnet: bool = False

@router.get("/profile")
async def get_user_profile(current_user: dict = Depends(get_current_user)):
    """Kullanıcı profil bilgilerini getir"""
    try:
        user_id = current_user['uid']
        user_data = firebase_manager.get_user_data(user_id)
        
        if not user_data:
            # Yeni kullanıcı için varsayılan veri oluştur
            logger.info(f"Creating default user data for: {user_id}")
            user_data = {
                "email": current_user.get('email'),
                "created_at": firebase_manager.get_server_timestamp(),
                "subscription_status": "trial",
                "api_keys_set": False,
                "bot_active": False,
                "total_trades": 0,
                "total_pnl": 0.0,
                "role": "user"
            }
            firebase_manager.update_user_data(user_id, user_data)
        
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
        
        # Varsayılan değerler
        account_data = {
            "totalBalance": 0.0,
            "availableBalance": 0.0,
            "unrealizedPnl": 0.0,
            "message": "API anahtarları gerekli"
        }
        
        # Eğer API keys varsa gerçek Binance verilerini al
        if user_data and user_data.get('api_keys_set'):
            try:
                encrypted_api_key = user_data.get('binance_api_key')
                encrypted_api_secret = user_data.get('binance_api_secret')
                
                if encrypted_api_key and encrypted_api_secret:
                    api_key = decrypt_data(encrypted_api_key)
                    api_secret = decrypt_data(encrypted_api_secret)
                    
                    if api_key and api_secret:
                        # Binance client oluştur
                        client = BinanceClient(api_key, api_secret)
                        await client.initialize()
                        
                        # Gerçek balance al
                        balance = await client.get_account_balance(use_cache=False)
                        
                        # Gerçek PnL al
                        pnl = 0.0
                        if user_data.get('bot_active'):
                            bot_status = bot_manager.get_bot_status(user_id)
                            if bot_status.get('is_running'):
                                pnl = bot_status.get('position_pnl', 0.0)
                        
                        account_data = {
                            "totalBalance": balance,
                            "availableBalance": balance,
                            "unrealizedPnl": pnl,
                            "message": "Gerçek Binance verileri"
                        }
                        
                        # Cache'e kaydet
                        firebase_manager.update_user_data(user_id, {
                            "account_balance": balance,
                            "last_balance_update": firebase_manager.get_server_timestamp()
                        })
                        
                        await client.close()
                        logger.info(f"Real account data loaded for user: {user_id}")
                        
            except Exception as e:
                logger.error(f"Error getting real account data for {user_id}: {e}")
                # Fallback to cached data
                account_data = {
                    "totalBalance": user_data.get("account_balance", 0.0),
                    "availableBalance": user_data.get("account_balance", 0.0),
                    "unrealizedPnl": 0.0,
                    "message": f"Cache verisi (API hatası: {str(e)})"
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
            # Varsayılan stats
            return {
                "totalTrades": 0,
                "totalPnl": 0.0,
                "winRate": 0.0,
                "botStartTime": None,
                "lastTradeTime": None
            }
        
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
        user_data = firebase_manager.get_user_data(user_id)
        
        positions = []
        
        # Gerçek pozisyonları Binance'dan al
        if user_data and user_data.get('api_keys_set'):
            try:
                encrypted_api_key = user_data.get('binance_api_key')
                encrypted_api_secret = user_data.get('binance_api_secret')
                
                if encrypted_api_key and encrypted_api_secret:
                    api_key = decrypt_data(encrypted_api_key)
                    api_secret = decrypt_data(encrypted_api_secret)
                    
                    if api_key and api_secret:
                        # Binance client oluştur
                        client = BinanceClient(api_key, api_secret)
                        await client.initialize()
                        
                        # Tüm açık pozisyonları al
                        all_positions = await client.client.futures_position_information()
                        
                        for pos in all_positions:
                            position_amt = float(pos['positionAmt'])
                            if position_amt != 0:  # Sadece açık pozisyonlar
                                positions.append({
                                    "symbol": pos['symbol'],
                                    "positionSide": "LONG" if position_amt > 0 else "SHORT",
                                    "positionAmt": str(abs(position_amt)),
                                    "entryPrice": pos['entryPrice'],
                                    "markPrice": pos['markPrice'],
                                    "unrealizedPnl": float(pos['unRealizedProfit']),
                                    "percentage": float(pos['percentage'])
                                })
                        
                        await client.close()
                        logger.info(f"Real positions loaded for user: {user_id}")
                        
            except Exception as e:
                logger.error(f"Error getting real positions for {user_id}: {e}")
        
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
        user_data = firebase_manager.get_user_data(user_id)
        
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
        
        # Eğer Firebase'den veri yoksa ve API keys varsa, Binance'dan al
        if not trades and user_data and user_data.get('api_keys_set'):
            try:
                encrypted_api_key = user_data.get('binance_api_key')
                encrypted_api_secret = user_data.get('binance_api_secret')
                
                if encrypted_api_key and encrypted_api_secret:
                    api_key = decrypt_data(encrypted_api_key)
                    api_secret = decrypt_data(encrypted_api_secret)
                    
                    if api_key and api_secret:
                        client = BinanceClient(api_key, api_secret)
                        await client.initialize()
                        
                        # Son işlemleri al (BTCUSDT örneği)
                        recent_trades = await client.client.futures_account_trades(symbol="BTCUSDT", limit=limit)
                        
                        for trade in recent_trades[-limit:]:
                            trades.append({
                                "id": str(trade['id']),
                                "symbol": trade['symbol'],
                                "side": trade['side'],
                                "quantity": float(trade['qty']),
                                "price": float(trade['price']),
                                "quoteQty": float(trade['quoteQty']),
                                "pnl": float(trade['realizedPnl']),
                                "status": "FILLED",
                                "time": trade['time']
                            })
                        
                        await client.close()
                        logger.info(f"Binance trades loaded for user: {user_id}")
                        
            except Exception as e:
                logger.error(f"Binance trades fetch failed: {e}")
        
        # Tarihe göre sırala (en yeni önce)
        trades.sort(key=lambda x: x.get("time", 0), reverse=True)
        
        return trades
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Recent trades fetch error: {e}")
        raise HTTPException(status_code=500, detail="Son işlemler alınamadı")

@router.post("/api-keys")
async def save_api_keys(
    request: ApiKeysRequest,
    current_user: dict = Depends(get_current_user)
):
    """Kullanıcının API anahtarlarını kaydet"""
    try:
        user_id = current_user['uid']
        logger.info(f"API keys save request from user: {user_id}")
        
        # API anahtarlarını test et
        try:
            test_client = BinanceClient(request.api_key, request.api_secret)
            await test_client.initialize()
            
            # Test balance call
            balance = await test_client.get_account_balance(use_cache=False)
            logger.info(f"API test successful for user {user_id}, balance: {balance}")
            
            await test_client.close()
            
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
            "account_balance": balance
        }
        
        success = firebase_manager.update_user_data(user_id, api_data)
        
        if not success:
            raise HTTPException(status_code=500, detail="API anahtarları kaydedilemedi")
        
        logger.info(f"API keys saved for user: {user_id}")
        
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
                    # Quick test
                    test_client = BinanceClient(api_key, api_secret)
                    await test_client.initialize()
                    balance = await test_client.get_account_balance(use_cache=True)
                    await test_client.close()
                    
                    return {
                        "hasApiKeys": True,
                        "isConnected": True,
                        "message": f"API anahtarları aktif - Balance: {balance} USDT"
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API status check error: {e}")
        raise HTTPException(status_code=500, detail=f"API durumu kontrol edilemedi: {str(e)}")

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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API info fetch error: {e}")
        raise HTTPException(status_code=500, detail="API bilgileri alınamadı")

@router.post("/close-position")
async def close_position(
    request: dict,
    current_user: dict = Depends(get_current_user)
):
    """Pozisyon kapatma"""
    try:
        user_id = current_user['uid']
        symbol = request.get('symbol')
        position_side = request.get('positionSide')
        
        if not symbol or not position_side:
            raise HTTPException(status_code=400, detail="Symbol ve position side gerekli")
        
        user_data = firebase_manager.get_user_data(user_id)
        
        if not user_data or not user_data.get('api_keys_set'):
            raise HTTPException(status_code=400, detail="API anahtarları gerekli")
        
        # Gerçek pozisyon kapatma
        try:
            encrypted_api_key = user_data.get('binance_api_key')
            encrypted_api_secret = user_data.get('binance_api_secret')
            
            api_key = decrypt_data(encrypted_api_key)
            api_secret = decrypt_data(encrypted_api_secret)
            
            client = BinanceClient(api_key, api_secret)
            await client.initialize()
            
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
                # PnL hesapla
                pnl = await client.get_last_trade_pnl(symbol)
                
                # Trade'i Firebase'e kaydet
                trade_data = {
                    "user_id": user_id,
                    "symbol": symbol,
                    "side": position_side,
                    "status": "CLOSED_MANUAL",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "pnl": pnl,
                    "close_reason": "manual"
                }
                
                firebase_manager.log_trade(trade_data)
                
                # User stats güncelle
                current_trades = user_data.get('total_trades', 0)
                current_pnl = user_data.get('total_pnl', 0.0)
                
                firebase_manager.update_user_data(user_id, {
                    'total_trades': current_trades + 1,
                    'total_pnl': current_pnl + pnl,
                    'last_trade_time': firebase_manager.get_server_timestamp()
                })
                
                await client.close()
                
                return {
                    "success": True,
                    "message": "Pozisyon başarıyla kapatıldı",
                    "pnl": pnl
                }
            else:
                raise Exception("Pozisyon kapatma işlemi başarısız")
                
        except Exception as e:
            logger.error(f"Position close error for {user_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Pozisyon kapatılamadı: {str(e)}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Position close error: {e}")
        raise HTTPException(status_code=500, detail="Pozisyon kapatılamadı")
