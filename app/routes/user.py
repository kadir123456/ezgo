from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer
from app.firebase_manager import firebase_manager
from app.utils.logger import get_logger
from app.utils.crypto import decrypt_data
from app.binance_client import BinanceClient
from app.bot_manager import bot_manager
from pydantic import BaseModel
import firebase_admin
from firebase_admin import auth as firebase_auth
from datetime import datetime, timezone
import random

logger = get_logger("user_routes")
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
        
        # Gerçek Binance hesap bilgilerini al
        account_data = {"totalBalance": 0.0, "availableBalance": 0.0, "unrealizedPnl": 0.0}
        
        if user_data.get('api_keys_set') and user_data.get('api_connection_verified'):
            try:
                # API anahtarlarını çöz
                encrypted_api_key = user_data.get('binance_api_key')
                encrypted_api_secret = user_data.get('binance_api_secret')
                
                if encrypted_api_key and encrypted_api_secret:
                    api_key = decrypt_data(encrypted_api_key)
                    api_secret = decrypt_data(encrypted_api_secret)
                    
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
                        "unrealizedPnl": pnl
                    }
                    
                    await client.close()
                    
            except Exception as e:
                logger.error(f"Error getting real account data for {user_id}: {e}")
                # Fallback to cached data
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
        user_data = firebase_manager.get_user_data(user_id)
        
        positions = []
        
        # Gerçek pozisyonları Binance'dan al
        if user_data and user_data.get('api_keys_set') and user_data.get('api_connection_verified'):
            try:
                # API anahtarlarını çöz
                encrypted_api_key = user_data.get('binance_api_key')
                encrypted_api_secret = user_data.get('binance_api_secret')
                
                if encrypted_api_key and encrypted_api_secret:
                    api_key = decrypt_data(encrypted_api_key)
                    api_secret = decrypt_data(encrypted_api_secret)
                    
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
                    
            except Exception as e:
                logger.error(f"Binance trades fetch failed: {e}")
        
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

@router.get("/trading-pairs")
async def get_trading_pairs(current_user: dict = Depends(get_current_user)):
    """Gerçek trading çiftlerini Binance'dan getir"""
    try:
        user_id = current_user['uid']
        user_data = firebase_manager.get_user_data(user_id)
        
        # Varsayılan popüler çiftler
        default_pairs = [
            {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"},
            {"symbol": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT"},
            {"symbol": "BNBUSDT", "baseAsset": "BNB", "quoteAsset": "USDT"},
            {"symbol": "ADAUSDT", "baseAsset": "ADA", "quoteAsset": "USDT"},
            {"symbol": "DOTUSDT", "baseAsset": "DOT", "quoteAsset": "USDT"},
            {"symbol": "LINKUSDT", "baseAsset": "LINK", "quoteAsset": "USDT"},
            {"symbol": "LTCUSDT", "baseAsset": "LTC", "quoteAsset": "USDT"},
            {"symbol": "XRPUSDT", "baseAsset": "XRP", "quoteAsset": "USDT"}
        ]
        
        # Eğer API keys varsa gerçek exchange info al
        if user_data and user_data.get('api_keys_set'):
            try:
                encrypted_api_key = user_data.get('binance_api_key')
                encrypted_api_secret = user_data.get('binance_api_secret')
                
                if encrypted_api_key and encrypted_api_secret:
                    api_key = decrypt_data(encrypted_api_key)
                    api_secret = decrypt_data(encrypted_api_secret)
                    
                    client = BinanceClient(api_key, api_secret)
                    await client.initialize()
                    
                    # Exchange info al
                    exchange_info = await client.client.futures_exchange_info()
                    
                    # Aktif USDT çiftlerini filtrele
                    active_pairs = []
                    for symbol_info in exchange_info['symbols']:
                        if (symbol_info['status'] == 'TRADING' and 
                            symbol_info['quoteAsset'] == 'USDT' and
                            symbol_info['symbol'] in [p['symbol'] for p in default_pairs]):
                            active_pairs.append({
                                "symbol": symbol_info['symbol'],
                                "baseAsset": symbol_info['baseAsset'],
                                "quoteAsset": symbol_info['quoteAsset']
                            })
                    
                    await client.close()
                    
                    if active_pairs:
                        return {"success": True, "pairs": active_pairs}
                        
            except Exception as e:
                logger.error(f"Error getting real trading pairs: {e}")
        
        return {"success": True, "pairs": default_pairs}
        
    except Exception as e:
        logger.error(f"Trading pairs fetch error: {e}")
        raise HTTPException(status_code=500, detail="Trading çiftleri alınamadı")

@router.post("/close-position")
async def close_position(
    request: dict,
    current_user: dict = Depends(get_current_user)
):
    """Pozisyon kapatma (simulated)"""
    try:
        user_id = current_user['uid']
        symbol = request.get('symbol')
        position_side = request.get('positionSide')
        
        if not symbol or not position_side:
            raise HTTPException(status_code=400, detail="Symbol ve position side gerekli")
        
        # Simulated position close - gerçek uygulamada Binance API kullanılacak
        trade_data = {
            "user_id": user_id,
            "symbol": symbol,
            "side": position_side,
            "status": "CLOSED_MANUAL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pnl": round((random.random() * 40 - 20), 2)  # Random PnL for demo
        }
        
        # Log trade to Firebase
        firebase_manager.log_trade(trade_data)
        
        # Update user stats
        user_data = firebase_manager.get_user_data(user_id)
        if user_data:
            current_trades = user_data.get('total_trades', 0)
            current_pnl = user_data.get('total_pnl', 0.0)
            
            firebase_manager.update_user_data(user_id, {
                'total_trades': current_trades + 1,
                'total_pnl': current_pnl + trade_data['pnl'],
                'last_trade_time': firebase_manager.get_server_timestamp()
            })
        
        return {
            "success": True,
            "message": "Pozisyon başarıyla kapatıldı",
            "pnl": trade_data['pnl']
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Position close error: {e}")
        raise HTTPException(status_code=500, detail="Pozisyon kapatılamadı")
