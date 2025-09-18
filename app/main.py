from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timezone, timedelta
from app.config import settings
from app.utils.metrics import metrics, get_metrics_data, get_metrics_content_type
import logging
import time
from typing import Optional
import json
import os

# Setup logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("main")

# Initialize Firebase Admin SDK
firebase_admin = None
firebase_auth = None
firebase_db = None

def initialize_firebase():
    """Initialize Firebase Admin SDK with better error handling"""
    global firebase_admin, firebase_auth, firebase_db
    
    try:
        import firebase_admin
        from firebase_admin import credentials, auth as firebase_auth_module, db as firebase_db_module
        
        if not firebase_admin._apps:
            # Get credentials from environment
            cred_json_str = os.getenv("FIREBASE_CREDENTIALS_JSON")
            database_url = os.getenv("FIREBASE_DATABASE_URL")
            
            if not cred_json_str or not database_url:
                logger.error("Firebase credentials not found in environment")
                return False
            
            try:
                # Clean JSON string for production
                if cred_json_str.startswith('"') and cred_json_str.endswith('"'):
                    cred_json_str = cred_json_str[1:-1]
                
                # Handle escaped characters
                import codecs
                cred_json_str = codecs.decode(cred_json_str, 'unicode_escape')
                
                # Remove problematic control characters but preserve newlines in private key
                import re
                cred_json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', cred_json_str)
                
                # Parse JSON
                cred_dict = json.loads(cred_json_str)
                
                # Validate required fields
                required_fields = ['type', 'project_id', 'private_key', 'client_email']
                missing_fields = [field for field in required_fields if field not in cred_dict]
                
                if missing_fields:
                    logger.error(f"Missing Firebase fields: {missing_fields}")
                    return False
                
                # Initialize Firebase
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred, {
                    'databaseURL': database_url
                })
                
                firebase_auth = firebase_auth_module
                firebase_db = firebase_db_module
                
                logger.info("Firebase Admin SDK initialized successfully")
                return True
                
            except json.JSONDecodeError as e:
                logger.error(f"Firebase JSON parse error: {e}")
                return False
            except Exception as e:
                logger.error(f"Firebase initialization error: {e}")
                return False
        else:
            firebase_auth = firebase_auth_module
            firebase_db = firebase_db_module
            logger.info("Firebase already initialized")
            return True
            
    except ImportError as e:
        logger.error(f"Firebase import error: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected Firebase error: {e}")
        return False

# Initialize Firebase on startup
firebase_initialized = initialize_firebase()

# FastAPI app
app = FastAPI(
    title="EzyagoTrading API",
    description="Professional Crypto Futures Trading Bot",
    version="1.0.0",
    debug=settings.DEBUG
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else [
        "https://www.ezyago.com", 
        "https://ezyago.com",
        "https://ezyagotrading.onrender.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer(auto_error=False)

async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    """Firebase Auth token verification"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication token required")
    
    if not firebase_initialized or not firebase_auth:
        logger.error("Firebase not initialized for authentication")
        raise HTTPException(status_code=500, detail="Authentication service unavailable")
    
    try:
        # Verify Firebase token
        decoded_token = firebase_auth.verify_id_token(credentials.credentials)
        logger.info(f"Token verified for user: {decoded_token['uid']}")
        return decoded_token
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication token")

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    
    # Maintenance mode check
    if settings.MAINTENANCE_MODE and not request.url.path.startswith("/health"):
        return JSONResponse(
            status_code=503,
            content={"error": "Maintenance mode", "message": settings.MAINTENANCE_MESSAGE}
        )
    
    response = await call_next(request)
    
    # Log request
    process_time = time.time() - start_time
    metrics.record_api_request(
        str(request.url.path),
        request.method,
        response.status_code,
        process_time
    )
    
    return response

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
async def startup_event():
    """Application startup"""
    logger.info("EzyagoTrading starting up...")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    
    # Check Firebase connection
    if firebase_initialized:
        logger.info("Firebase connection verified")
    else:
        logger.error("Firebase connection failed")
    
    # Validate settings
    try:
        is_valid = settings.validate_settings()
        if is_valid:
            logger.info("All settings validated successfully")
        else:
            logger.warning("Some configuration issues detected")
    except Exception as e:
        logger.error(f"Settings validation error: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown"""
    logger.info("EzyagoTrading shutting down...")
    
    try:
        from app.bot_manager import bot_manager
        await bot_manager.shutdown_all_bots()
        logger.info("All bots shutdown completed")
    except Exception as e:
        logger.error(f"Error during bot shutdown: {e}")

# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        return {
            "status": "healthy" if firebase_initialized else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "environment": settings.ENVIRONMENT,
            "version": "1.0.0",
            "firebase_connected": firebase_initialized
        }
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

# Firebase config for frontend
@app.get("/api/firebase-config")
async def get_firebase_config():
    """Firebase configuration for frontend"""
    try:
        firebase_config = {
            "apiKey": settings.FIREBASE_WEB_API_KEY,
            "authDomain": settings.FIREBASE_WEB_AUTH_DOMAIN,
            "projectId": settings.FIREBASE_WEB_PROJECT_ID,
            "storageBucket": settings.FIREBASE_WEB_STORAGE_BUCKET,
            "messagingSenderId": settings.FIREBASE_WEB_MESSAGING_SENDER_ID,
            "appId": settings.FIREBASE_WEB_APP_ID,
            "databaseURL": settings.FIREBASE_DATABASE_URL
        }
        
        # Check for missing fields
        missing_fields = [k for k, v in firebase_config.items() if not v]
        if missing_fields:
            logger.error(f"Missing Firebase config fields: {missing_fields}")
            raise HTTPException(
                status_code=500,
                detail=f"Missing Firebase environment variables: {missing_fields}"
            )
        
        return firebase_config
        
    except Exception as e:
        logger.error(f"Firebase config error: {e}")
        raise HTTPException(status_code=500, detail=f"Firebase configuration error: {str(e)}")

# App info
@app.get("/api/app-info")
async def get_app_info():
    """Application information"""
    return {
        "bot_price": settings.BOT_PRICE_USD,
        "trial_days": settings.TRIAL_PERIOD_DAYS,
        "payment_address": settings.PAYMENT_TRC20_ADDRESS,
        "server_ips": settings.SERVER_IPS.split(',') if settings.SERVER_IPS else [],
        "max_bots_per_user": settings.MAX_BOTS_PER_USER,
        "supported_timeframes": ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
        "leverage_range": {"min": settings.MIN_LEVERAGE, "max": settings.MAX_LEVERAGE},
        "order_size_range": {"min": settings.MIN_ORDER_SIZE_USDT, "max": settings.MAX_ORDER_SIZE_USDT}
    }

# Auth routes
@app.post("/api/auth/verify")
async def verify_token(current_user: dict = Depends(get_current_user)):
    """Verify Firebase token and create/update user data"""
    try:
        user_id = current_user['uid']
        email = current_user.get('email')
        
        if not firebase_initialized or not firebase_db:
            raise HTTPException(status_code=500, detail="Database service unavailable")
        
        # Get or create user data
        try:
            user_ref = firebase_db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            
            if not user_data:
                logger.info(f"Creating user data for new user: {user_id}")
                
                # Calculate trial expiry (7 days from now)
                trial_expiry = datetime.now(timezone.utc) + timedelta(days=7)
                
                user_data = {
                    "email": email,
                    "created_at": firebase_db.reference().server_timestamp,
                    "last_login": firebase_db.reference().server_timestamp,
                    "subscription_status": "trial",
                    "subscription_expiry": trial_expiry.isoformat(),
                    "api_keys_set": False,
                    "bot_active": False,
                    "total_trades": 0,
                    "total_pnl": 0.0,
                    "role": "user"
                }
                user_ref.set(user_data)
                logger.info(f"User data created for: {user_id}")
            else:
                # Update last login
                user_ref.update({
                    "last_login": firebase_db.reference().server_timestamp
                })
                logger.info(f"Last login updated for: {user_id}")
        
        except Exception as db_error:
            logger.error(f"Database operation failed: {db_error}")
            # Return basic user info even if database fails
            user_data = {
                "email": email,
                "subscription_status": "trial",
                "api_keys_set": False,
                "bot_active": False
            }
        
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

# User routes
@app.get("/api/user/profile")
async def get_user_profile(current_user: dict = Depends(get_current_user)):
    """Get user profile"""
    try:
        user_id = current_user['uid']
        email = current_user.get('email')
        
        if not firebase_initialized or not firebase_db:
            # Return basic profile if Firebase unavailable
            return {
                "email": email,
                "subscription": {
                    "status": "trial",
                    "plan": "Deneme",
                    "daysRemaining": 7
                },
                "api_keys_set": False,
                "bot_active": False,
                "total_trades": 0,
                "total_pnl": 0.0,
                "account_balance": 0.0
            }
        
        try:
            user_ref = firebase_db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            
            if not user_data:
                # Create basic user data
                trial_expiry = datetime.now(timezone.utc) + timedelta(days=7)
                user_data = {
                    "email": email,
                    "subscription_status": "trial",
                    "subscription_expiry": trial_expiry.isoformat(),
                    "api_keys_set": False,
                    "bot_active": False,
                    "total_trades": 0,
                    "total_pnl": 0.0
                }
                user_ref.set(user_data)
            
            # Check subscription expiry
            subscription_status = "expired"
            days_remaining = 0
            
            if user_data.get('subscription_expiry'):
                try:
                    expiry_date = datetime.fromisoformat(user_data['subscription_expiry'].replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    days_remaining = (expiry_date - now).days
                    
                    if days_remaining > 0:
                        subscription_status = user_data.get('subscription_status', 'trial')
                    else:
                        subscription_status = "expired"
                except Exception as date_error:
                    logger.error(f"Date parsing error: {date_error}")
                    subscription_status = "trial"
                    days_remaining = 7
            
            profile = {
                "email": user_data.get("email", email),
                "full_name": user_data.get("full_name"),
                "subscription": {
                    "status": subscription_status,
                    "plan": "Premium" if subscription_status == "active" else "Deneme",
                    "expiryDate": user_data.get("subscription_expiry"),
                    "daysRemaining": max(0, days_remaining)
                },
                "api_keys_set": user_data.get("api_keys_set", False),
                "bot_active": user_data.get("bot_active", False),
                "total_trades": user_data.get("total_trades", 0),
                "total_pnl": user_data.get("total_pnl", 0.0),
                "account_balance": user_data.get("account_balance", 0.0)
            }
            
            return profile
            
        except Exception as db_error:
            logger.error(f"Database error in profile: {db_error}")
            # Return basic profile if database fails
            return {
                "email": email,
                "subscription": {
                    "status": "trial",
                    "plan": "Deneme",
                    "daysRemaining": 7
                },
                "api_keys_set": False,
                "bot_active": False,
                "total_trades": 0,
                "total_pnl": 0.0,
                "account_balance": 0.0
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Profile fetch error: {e}")
        raise HTTPException(status_code=500, detail="Profile could not be loaded")

@app.get("/api/user/account")
async def get_account_data(current_user: dict = Depends(get_current_user)):
    """Get account data"""
    try:
        user_id = current_user['uid']
        
        # Default values
        account_data = {
            "totalBalance": 0.0,
            "availableBalance": 0.0,
            "unrealizedPnl": 0.0,
            "message": "API keys required"
        }
        
        if not firebase_initialized or not firebase_db:
            return account_data
        
        try:
            user_ref = firebase_db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            
            # If API keys exist, get real Binance data
            if user_data and user_data.get('api_keys_set'):
                try:
                    from app.utils.crypto import decrypt_data
                    from app.binance_client import BinanceClient
                    
                    encrypted_api_key = user_data.get('binance_api_key')
                    encrypted_api_secret = user_data.get('binance_api_secret')
                    
                    if encrypted_api_key and encrypted_api_secret:
                        api_key = decrypt_data(encrypted_api_key)
                        api_secret = decrypt_data(encrypted_api_secret)
                        
                        if api_key and api_secret:
                            client = BinanceClient(api_key, api_secret)
                            await client.initialize()
                            
                            balance = await client.get_account_balance(use_cache=False)
                            
                            account_data = {
                                "totalBalance": balance,
                                "availableBalance": balance,
                                "unrealizedPnl": 0.0,
                                "message": "Real Binance data"
                            }
                            
                            # Update cache
                            user_ref.update({
                                "account_balance": balance,
                                "last_balance_update": firebase_db.reference().server_timestamp
                            })
                            
                            await client.close()
                            
                except Exception as e:
                    logger.error(f"Error getting real account data: {e}")
                    # Use cached data
                    account_data = {
                        "totalBalance": user_data.get("account_balance", 0.0),
                        "availableBalance": user_data.get("account_balance", 0.0),
                        "unrealizedPnl": 0.0,
                        "message": f"Cached data (API error: {str(e)})"
                    }
        except Exception as db_error:
            logger.error(f"Database error in account: {db_error}")
        
        return account_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Account data error: {e}")
        raise HTTPException(status_code=500, detail="Account data could not be loaded")

@app.get("/api/user/positions")
async def get_user_positions(current_user: dict = Depends(get_current_user)):
    """Get user positions"""
    try:
        user_id = current_user['uid']
        positions = []
        
        if not firebase_initialized or not firebase_db:
            return positions
        
        try:
            user_ref = firebase_db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            
            if user_data and user_data.get('api_keys_set'):
                try:
                    from app.utils.crypto import decrypt_data
                    from app.binance_client import BinanceClient
                    
                    encrypted_api_key = user_data.get('binance_api_key')
                    encrypted_api_secret = user_data.get('binance_api_secret')
                    
                    if encrypted_api_key and encrypted_api_secret:
                        api_key = decrypt_data(encrypted_api_key)
                        api_secret = decrypt_data(encrypted_api_secret)
                        
                        if api_key and api_secret:
                            client = BinanceClient(api_key, api_secret)
                            await client.initialize()
                            
                            # Get all positions
                            all_positions = await client.client.futures_position_information()
                            
                            for pos in all_positions:
                                position_amt = float(pos['positionAmt'])
                                if position_amt != 0:
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
                    logger.error(f"Error getting positions: {e}")
        except Exception as db_error:
            logger.error(f"Database error in positions: {db_error}")
        
        return positions
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Positions error: {e}")
        raise HTTPException(status_code=500, detail="Positions could not be loaded")

@app.get("/api/user/recent-trades")
async def get_recent_trades(current_user: dict = Depends(get_current_user), limit: int = 10):
    """Get recent trades"""
    try:
        user_id = current_user['uid']
        trades = []
        
        if not firebase_initialized or not firebase_db:
            return trades
        
        try:
            # Get from Firebase first
            trades_ref = firebase_db.reference('trades')
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
        except Exception as db_error:
            logger.error(f"Database error in trades: {db_error}")
        
        # If no Firebase data, try Binance
        if not trades:
            try:
                user_ref = firebase_db.reference(f'users/{user_id}')
                user_data = user_ref.get()
                
                if user_data and user_data.get('api_keys_set'):
                    from app.utils.crypto import decrypt_data
                    from app.binance_client import BinanceClient
                    
                    encrypted_api_key = user_data.get('binance_api_key')
                    encrypted_api_secret = user_data.get('binance_api_secret')
                    
                    if encrypted_api_key and encrypted_api_secret:
                        api_key = decrypt_data(encrypted_api_key)
                        api_secret = decrypt_data(encrypted_api_secret)
                        
                        if api_key and api_secret:
                            client = BinanceClient(api_key, api_secret)
                            await client.initialize()
                            
                            # Get recent trades for BTCUSDT
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
            except Exception as binance_error:
                logger.error(f"Binance trades fetch failed: {binance_error}")
        
        # Sort by time
        trades.sort(key=lambda x: x.get("time", 0), reverse=True)
        
        return trades
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Recent trades error: {e}")
        raise HTTPException(status_code=500, detail="Recent trades could not be loaded")

@app.post("/api/user/api-keys")
async def save_api_keys(request: dict, current_user: dict = Depends(get_current_user)):
    """Save user API keys"""
    try:
        user_id = current_user['uid']
        api_key = request.get('api_key', '').strip()
        api_secret = request.get('api_secret', '').strip()
        testnet = request.get('testnet', False)
        
        if not api_key or not api_secret:
            raise HTTPException(status_code=400, detail="API key and secret required")
        
        # Test API keys
        try:
            from app.binance_client import BinanceClient
            test_client = BinanceClient(api_key, api_secret)
            await test_client.initialize()
            
            balance = await test_client.get_account_balance(use_cache=False)
            logger.info(f"API test successful for user {user_id}, balance: {balance}")
            
            await test_client.close()
            
        except Exception as e:
            logger.error(f"API test failed: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid API keys: {str(e)}")
        
        if not firebase_initialized or not firebase_db:
            raise HTTPException(status_code=500, detail="Database service unavailable")
        
        # Encrypt and save
        try:
            from app.utils.crypto import encrypt_data
            encrypted_api_key = encrypt_data(api_key)
            encrypted_api_secret = encrypt_data(api_secret)
            
            api_data = {
                "binance_api_key": encrypted_api_key,
                "binance_api_secret": encrypted_api_secret,
                "api_testnet": testnet,
                "api_keys_set": True,
                "api_updated_at": firebase_db.reference().server_timestamp,
                "account_balance": balance
            }
            
            user_ref = firebase_db.reference(f'users/{user_id}')
            user_ref.update(api_data)
            
            logger.info(f"API keys saved for user: {user_id}")
            
        except Exception as save_error:
            logger.error(f"API keys save error: {save_error}")
            raise HTTPException(status_code=500, detail="API keys could not be saved")
        
        return {
            "success": True,
            "message": "API keys saved and tested successfully",
            "balance": balance
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API keys save error: {e}")
        raise HTTPException(status_code=500, detail=f"API keys could not be saved: {str(e)}")

@app.get("/api/user/api-status")
async def get_api_status(current_user: dict = Depends(get_current_user)):
    """Check API status"""
    try:
        user_id = current_user['uid']
        
        if not firebase_initialized or not firebase_db:
            return {
                "hasApiKeys": False,
                "isConnected": False,
                "message": "Database service unavailable"
            }
        
        try:
            user_ref = firebase_db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            
            if not user_data:
                return {
                    "hasApiKeys": False,
                    "isConnected": False,
                    "message": "User data not found"
                }
            
            has_api_keys = user_data.get('api_keys_set', False)
            
            if not has_api_keys:
                return {
                    "hasApiKeys": False,
                    "isConnected": False,
                    "message": "API keys not configured"
                }
            
            # Test API connection
            try:
                from app.utils.crypto import decrypt_data
                from app.binance_client import BinanceClient
                
                encrypted_api_key = user_data.get('binance_api_key')
                encrypted_api_secret = user_data.get('binance_api_secret')
                
                if encrypted_api_key and encrypted_api_secret:
                    api_key = decrypt_data(encrypted_api_key)
                    api_secret = decrypt_data(encrypted_api_secret)
                    
                    if api_key and api_secret:
                        test_client = BinanceClient(api_key, api_secret)
                        await test_client.initialize()
                        balance = await test_client.get_account_balance(use_cache=True)
                        await test_client.close()
                        
                        return {
                            "hasApiKeys": True,
                            "isConnected": True,
                            "message": f"API keys active - Balance: {balance} USDT"
                        }
                    else:
                        return {
                            "hasApiKeys": True,
                            "isConnected": False,
                            "message": "Invalid API key format"
                        }
                else:
                    return {
                        "hasApiKeys": False,
                        "isConnected": False,
                        "message": "API keys not found"
                    }
                    
            except Exception as e:
                logger.error(f"API test error: {e}")
                return {
                    "hasApiKeys": True,
                    "isConnected": False,
                    "message": f"API test error: {str(e)}"
                }
        except Exception as db_error:
            logger.error(f"Database error in API status: {db_error}")
            return {
                "hasApiKeys": False,
                "isConnected": False,
                "message": "Database error"
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API status error: {e}")
        raise HTTPException(status_code=500, detail="API status could not be checked")

@app.get("/api/user/api-info")
async def get_api_info(current_user: dict = Depends(get_current_user)):
    """Get API info (masked)"""
    try:
        user_id = current_user['uid']
        
        if not firebase_initialized or not firebase_db:
            return {
                "hasKeys": False,
                "maskedApiKey": None,
                "useTestnet": False
            }
        
        try:
            user_ref = firebase_db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            
            if not user_data:
                return {
                    "hasKeys": False,
                    "maskedApiKey": None,
                    "useTestnet": False
                }
            
            has_keys = user_data.get('api_keys_set', False)
            
            if has_keys:
                encrypted_api_key = user_data.get('binance_api_key')
                masked_key = None
                
                if encrypted_api_key:
                    try:
                        from app.utils.crypto import decrypt_data
                        api_key = decrypt_data(encrypted_api_key)
                        if api_key and len(api_key) >= 8:
                            masked_key = api_key[:8] + "..." + api_key[-4:]
                    except:
                        masked_key = "Encrypted API Key"
                
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
        except Exception as db_error:
            logger.error(f"Database error in API info: {db_error}")
            return {
                "hasKeys": False,
                "maskedApiKey": None,
                "useTestnet": False
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API info error: {e}")
        raise HTTPException(status_code=500, detail="API info could not be loaded")

# Bot routes
@app.post("/api/bot/start")
async def start_bot(request: dict, current_user: dict = Depends(get_current_user)):
    """Start bot for user"""
    try:
        user_id = current_user['uid']
        logger.info(f"Bot start request from user: {user_id}")
        
        if not firebase_initialized or not firebase_db:
            raise HTTPException(status_code=500, detail="Database service unavailable")
        
        # Check subscription
        try:
            user_ref = firebase_db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            
            if not user_data:
                raise HTTPException(status_code=404, detail="User data not found")
            
            # Check subscription expiry
            subscription_status = user_data.get('subscription_status')
            if user_data.get('subscription_expiry'):
                try:
                    expiry_date = datetime.fromisoformat(user_data['subscription_expiry'].replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    
                    if now > expiry_date:
                        raise HTTPException(status_code=403, detail="Subscription expired")
                except Exception as date_error:
                    logger.error(f"Date parsing error: {date_error}")
                    # Continue with trial if date parsing fails
            
            if subscription_status not in ['trial', 'active']:
                raise HTTPException(status_code=403, detail="Active subscription required")
            
            # Check API keys
            if not user_data.get('api_keys_set'):
                raise HTTPException(status_code=400, detail="Please add your API keys first")
            
            # Start bot (simplified for now)
            from app.bot_manager import bot_manager, StartRequest
            
            bot_settings = StartRequest(
                symbol=request.get('symbol', 'BTCUSDT'),
                timeframe=request.get('timeframe', '15m'),
                leverage=request.get('leverage', 10),
                order_size=request.get('order_size', 35.0),
                stop_loss=request.get('stop_loss', 2.0),
                take_profit=request.get('take_profit', 4.0)
            )
            
            result = await bot_manager.start_bot_for_user(user_id, bot_settings)
            
            if "error" in result:
                raise HTTPException(status_code=400, detail=result["error"])
            
            # Update user data
            user_ref.update({
                "bot_active": True,
                "bot_symbol": request.get('symbol', 'BTCUSDT'),
                "bot_start_time": firebase_db.reference().server_timestamp
            })
            
            return {
                "success": True,
                "message": "Bot started successfully",
                "bot_status": result.get("status", {})
            }
        except Exception as db_error:
            logger.error(f"Database error in bot start: {db_error}")
            raise HTTPException(status_code=500, detail="Bot start failed due to database error")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bot start error: {e}")
        raise HTTPException(status_code=500, detail=f"Bot could not be started: {str(e)}")

@app.post("/api/bot/stop")
async def stop_bot(current_user: dict = Depends(get_current_user)):
    """Stop bot for user"""
    try:
        user_id = current_user['uid']
        logger.info(f"Bot stop request from user: {user_id}")
        
        from app.bot_manager import bot_manager
        result = await bot_manager.stop_bot_for_user(user_id)
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # Update user data
        if firebase_initialized and firebase_db:
            try:
                user_ref = firebase_db.reference(f'users/{user_id}')
                user_ref.update({
                    "bot_active": False,
                    "bot_stop_time": firebase_db.reference().server_timestamp
                })
            except Exception as db_error:
                logger.error(f"Database update error: {db_error}")
        
        return {
            "success": True,
            "message": "Bot stopped successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bot stop error: {e}")
        raise HTTPException(status_code=500, detail=f"Bot could not be stopped: {str(e)}")

@app.get("/api/bot/status")
async def get_bot_status(current_user: dict = Depends(get_current_user)):
    """Get bot status"""
    try:
        user_id = current_user['uid']
        
        from app.bot_manager import bot_manager
        status = bot_manager.get_bot_status(user_id)
        
        return {
            "success": True,
            "status": status
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bot status error: {e}")
        raise HTTPException(status_code=500, detail="Bot status could not be retrieved")

@app.get("/api/bot/api-status")
async def get_bot_api_status(current_user: dict = Depends(get_current_user)):
    """Get API status for bot"""
    try:
        user_id = current_user['uid']
        
        if not firebase_initialized or not firebase_db:
            return {
                "hasApiKeys": False,
                "isConnected": False,
                "message": "Database service unavailable"
            }
        
        try:
            user_ref = firebase_db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            
            if not user_data:
                return {
                    "hasApiKeys": False,
                    "isConnected": False,
                    "message": "User data not found"
                }
            
            has_api_keys = user_data.get('api_keys_set', False)
            
            if not has_api_keys:
                return {
                    "hasApiKeys": False,
                    "isConnected": False,
                    "message": "API keys not configured"
                }
            
            # Test connection
            try:
                from app.utils.crypto import decrypt_data
                from app.binance_client import BinanceClient
                
                encrypted_api_key = user_data.get('binance_api_key')
                encrypted_api_secret = user_data.get('binance_api_secret')
                
                if encrypted_api_key and encrypted_api_secret:
                    api_key = decrypt_data(encrypted_api_key)
                    api_secret = decrypt_data(encrypted_api_secret)
                    
                    if api_key and api_secret:
                        return {
                            "hasApiKeys": True,
                            "isConnected": True,
                            "message": "API keys active"
                        }
                    else:
                        return {
                            "hasApiKeys": True,
                            "isConnected": False,
                            "message": "Invalid API key format"
                        }
                else:
                    return {
                        "hasApiKeys": False,
                        "isConnected": False,
                        "message": "API keys not found"
                    }
                    
            except Exception as e:
                logger.error(f"API test error: {e}")
                return {
                    "hasApiKeys": True,
                    "isConnected": False,
                    "message": f"API test error: {str(e)}"
                }
        except Exception as db_error:
            logger.error(f"Database error in bot API status: {db_error}")
            return {
                "hasApiKeys": False,
                "isConnected": False,
                "message": "Database error"
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API status error: {e}")
        raise HTTPException(status_code=500, detail="API status could not be checked")

@app.get("/api/trading/pairs")
async def get_trading_pairs(current_user: dict = Depends(get_current_user)):
    """Get supported trading pairs"""
    pairs = [
        {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"},
        {"symbol": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT"},
        {"symbol": "BNBUSDT", "baseAsset": "BNB", "quoteAsset": "USDT"},
        {"symbol": "ADAUSDT", "baseAsset": "ADA", "quoteAsset": "USDT"},
        {"symbol": "DOTUSDT", "baseAsset": "DOT", "quoteAsset": "USDT"},
        {"symbol": "LINKUSDT", "baseAsset": "LINK", "quoteAsset": "USDT"}
    ]
    
    return pairs

# Metrics endpoint
@app.get("/metrics")
async def get_metrics():
    """Prometheus metrics"""
    try:
        metrics_data = get_metrics_data()
        return PlainTextResponse(content=metrics_data, media_type=get_metrics_content_type())
    except Exception as e:
        logger.error(f"Metrics error: {e}")
        return PlainTextResponse("# Metrics not available")

# Static routes
@app.get("/")
async def read_root():
    return FileResponse("static/index.html")

@app.get("/login")
async def read_login():
    return FileResponse("static/login.html")

@app.get("/login.html")
async def read_login_html():
    return FileResponse("static/login.html")

@app.get("/register")
async def read_register():
    return FileResponse("static/register.html")

@app.get("/register.html")
async def read_register_html():
    return FileResponse("static/register.html")

@app.get("/dashboard")
async def read_dashboard():
    return FileResponse("static/dashboard.html")

@app.get("/dashboard.html")
async def read_dashboard_html():
    return FileResponse("static/dashboard.html")

@app.get("/admin")
async def read_admin():
    return FileResponse("static/admin.html")

@app.get("/admin.html")
async def read_admin_html():
    return FileResponse("static/admin.html")

# Catch-all for SPA
@app.get("/{full_path:path}")
async def catch_all(full_path: str):
    """Catch-all route"""
    if (full_path.startswith("static/") or 
        full_path.endswith(".html") or
        full_path in ["dashboard", "login", "register", "admin"]):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse("static/index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        reload=settings.DEBUG
    )
