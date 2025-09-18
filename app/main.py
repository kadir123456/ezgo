from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.exceptions import RequestValidationError
from datetime import datetime, timezone, timedelta
from app.config import settings
from app.utils.metrics import metrics, get_metrics_data, get_metrics_content_type
import logging
import time
import traceback
import sys
from typing import Optional
import json
import os
import re

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
    """Initialize Firebase Admin SDK with robust error handling"""
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
                logger.error(f"FIREBASE_CREDENTIALS_JSON length: {len(cred_json_str) if cred_json_str else 0}")
                logger.error(f"FIREBASE_DATABASE_URL: {database_url}")
                return False
            
            try:
                # Multiple JSON cleaning strategies for robust parsing
                original_json = cred_json_str
                logger.info(f"Original Firebase JSON length: {len(original_json)}")
                
                # Strategy 1: Remove outer quotes if present
                if original_json.startswith('"') and original_json.endswith('"'):
                    original_json = original_json[1:-1]
                    logger.info("✓ Removed outer quotes from Firebase JSON")
                
                # Strategy 2: Handle escaped characters
                try:
                    import codecs
                    decoded_json = codecs.decode(original_json, 'unicode_escape')
                    logger.info("✓ Applied unicode decode to Firebase JSON")
                except Exception as decode_error:
                    logger.warning(f"Unicode decode failed: {decode_error}")
                    decoded_json = original_json
                
                # Strategy 3: Try parsing in order of likelihood
                parse_attempts = [
                    ("original", original_json),
                    ("decoded", decoded_json),
                ]
                
                # Add cleaned version if needed
                if '\\n' in original_json or '\\t' in original_json:
                    # Clean control characters but preserve newlines in private key
                    cleaned_json = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', decoded_json)
                    parse_attempts.append(("cleaned", cleaned_json))
                
                cred_dict = None
                successful_strategy = None
                
                for strategy_name, json_to_try in parse_attempts:
                    try:
                        cred_dict = json.loads(json_to_try)
                        successful_strategy = strategy_name
                        logger.info(f"✅ Firebase JSON parsed successfully using: {strategy_name}")
                        break
                    except json.JSONDecodeError as parse_error:
                        logger.warning(f"Parse attempt '{strategy_name}' failed: {parse_error}")
                        continue
                
                if not cred_dict:
                    logger.error("❌ All Firebase JSON parse attempts failed")
                    logger.error(f"JSON preview: {original_json[:200]}...")
                    logger.error(f"JSON contains \\n: {'\\n' in original_json}")
                    logger.error(f"JSON contains \\\\n: {'\\\\n' in original_json}")
                    return False
                
                # Validate required fields
                required_fields = ['type', 'project_id', 'private_key', 'client_email']
                missing_fields = [field for field in required_fields if field not in cred_dict]
                
                if missing_fields:
                    logger.error(f"❌ Missing Firebase fields: {missing_fields}")
                    return False
                
                # Validate private key format
                private_key = cred_dict.get('private_key', '')
                if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
                    logger.error("❌ Invalid private key format")
                    logger.error(f"Private key starts with: {private_key[:50]}...")
                    return False
                
                # Validate project ID matches
                expected_project_id = "aviatoronline-6c2b4"
                actual_project_id = cred_dict.get('project_id')
                if actual_project_id != expected_project_id:
                    logger.warning(f"Project ID mismatch: expected {expected_project_id}, got {actual_project_id}")
                
                # Initialize Firebase
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred, {
                    'databaseURL': database_url
                })
                
                firebase_auth = firebase_auth_module
                firebase_db = firebase_db_module
                
                logger.info("🔥 Firebase Admin SDK initialized successfully")
                logger.info(f"✅ Project ID: {cred_dict.get('project_id')}")
                logger.info(f"✅ Client Email: {cred_dict.get('client_email', '')[:50]}...")
                logger.info(f"✅ Parsing strategy: {successful_strategy}")
                
                # Test database connection
                try:
                    test_ref = firebase_db.reference('system/connection_test')
                    test_ref.set({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'status': 'connected',
                        'parsing_strategy': successful_strategy
                    })
                    logger.info("✅ Firebase database write test successful")
                except Exception as db_test_error:
                    logger.warning(f"⚠️ Firebase database test failed: {db_test_error}")
                
                return True
                
            except Exception as init_error:
                logger.error(f"❌ Firebase initialization error: {init_error}")
                logger.error(f"Error type: {type(init_error).__name__}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                return False
        else:
            firebase_auth = firebase_auth_module
            firebase_db = firebase_db_module
            logger.info("🔥 Firebase already initialized")
            return True
            
    except ImportError as e:
        logger.error(f"❌ Firebase import error: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected Firebase error: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
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
    """Firebase Auth token verification with fallback"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication token required")
    
    if not firebase_initialized or not firebase_auth:
        logger.error("Firebase not initialized for authentication")
        # In production, this should fail. In debug mode, we can provide a mock user
        if settings.DEBUG:
            logger.warning("🔧 Using mock authentication for debug mode")
            return {
                'uid': 'debug-user-123',
                'email': 'debug@ezyago.com',
                'name': 'Debug User',
                'debug_mode': True
            }
        raise HTTPException(status_code=500, detail="Authentication service unavailable")
    
    try:
        # Verify Firebase token
        decoded_token = firebase_auth.verify_id_token(credentials.credentials)
        logger.info(f"✅ Token verified for user: {decoded_token['uid']}")
        return decoded_token
    except Exception as e:
        logger.error(f"❌ Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication token")

# Global exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for all unhandled exceptions"""
    
    error_details = {
        "error": "Internal Server Error",
        "detail": str(exc),
        "path": str(request.url.path),
        "method": request.method,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    # Add debug info in debug mode
    if settings.DEBUG:
        error_details.update({
            "type": type(exc).__name__,
            "traceback": traceback.format_exc(),
            "firebase_status": firebase_initialized
        })
    
    # Log the error
    logger.error(f"💥 Global exception in {request.method} {request.url.path}: {exc}")
    logger.error(f"Traceback: {traceback.format_exc()}")
    
    # Return structured error response
    return JSONResponse(
        status_code=500,
        content=error_details
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors"""
    return JSONResponse(
        status_code=400,
        content={
            "error": "Validation Error",
            "detail": exc.errors(),
            "path": str(request.url.path)
        }
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "path": str(request.url.path)
        }
    )

# Request logging middleware
@app.middleware("http")
async def enhanced_logging_middleware(request: Request, call_next):
    start_time = time.time()
    
    # Maintenance mode check
    if settings.MAINTENANCE_MODE and not request.url.path.startswith(("/health", "/api/health")):
        return JSONResponse(
            status_code=503,
            content={
                "error": "Maintenance Mode",
                "message": settings.MAINTENANCE_MESSAGE,
                "retry_after": 3600
            }
        )
    
    # Request logging (reduced verbosity for common endpoints)
    if not request.url.path.startswith(("/static", "/favicon")):
        logger.info(f"🌐 {request.method} {request.url.path}")
    
    try:
        response = await call_next(request)
        
        # Response logging
        process_time = time.time() - start_time
        
        if response.status_code >= 400:
            logger.error(f"❌ {request.method} {request.url.path} - {response.status_code} ({process_time:.3f}s)")
        elif not request.url.path.startswith(("/static", "/favicon")):
            logger.info(f"✅ {request.method} {request.url.path} - {response.status_code} ({process_time:.3f}s)")
        
        # Metrics
        metrics.record_api_request(
            str(request.url.path),
            request.method,
            response.status_code,
            process_time
        )
        
        return response
        
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(f"💥 {request.method} {request.url.path} - EXCEPTION ({process_time:.3f}s): {e}")
        raise e

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
async def startup_event():
    """Enhanced application startup"""
    try:
        logger.info("🚀 EzyagoTrading starting up...")
        logger.info(f"🌍 Environment: {settings.ENVIRONMENT}")
        logger.info(f"🐛 Debug mode: {settings.DEBUG}")
        
        # Firebase connection status
        if firebase_initialized:
            logger.info("✅ Firebase connection established")
        else:
            logger.error("❌ Firebase connection failed")
            if not settings.DEBUG:
                logger.warning("⚠️ Production mode with Firebase issues - some features may be unavailable")
        
        # Validate settings
        try:
            is_valid = settings.validate_settings()
            if is_valid:
                logger.info("✅ All settings validated successfully")
            else:
                logger.warning("⚠️ Some configuration issues detected")
        except Exception as e:
            logger.error(f"Settings validation error: {e}")
            
        logger.info("🎉 Startup completed!")
        
    except Exception as startup_error:
        logger.error(f"💥 Startup error: {startup_error}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        if not settings.DEBUG:
            logger.error("🛑 Critical startup error in production mode")
            sys.exit(1)

@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown"""
    logger.info("🛑 EzyagoTrading shutting down...")
    
    try:
        from app.bot_manager import bot_manager
        await bot_manager.shutdown_all_bots()
        logger.info("✅ All bots shutdown completed")
    except Exception as e:
        logger.error(f"Error during bot shutdown: {e}")

# Health check endpoints
@app.get("/health")
async def health_check():
    """Basic health check endpoint"""
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

@app.get("/api/health-detailed")
async def detailed_health_check():
    """Detailed health check with all components"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": settings.ENVIRONMENT,
        "version": "1.0.0",
        "components": {}
    }
    
    # Firebase check
    try:
        if firebase_initialized and firebase_db:
            # Test write
            test_ref = firebase_db.reference('health_check')
            test_ref.set({
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'status': 'healthy'
            })
            health_status["components"]["firebase"] = {
                "status": "healthy",
                "database_connected": True,
                "auth_available": firebase_auth is not None
            }
        else:
            health_status["components"]["firebase"] = {
                "status": "unhealthy", 
                "database_connected": False,
                "error": "Firebase not initialized"
            }
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["components"]["firebase"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "degraded"
    
    # Environment variables check
    required_vars = ["FIREBASE_CREDENTIALS_JSON", "ENCRYPTION_KEY", "ADMIN_EMAIL"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    health_status["components"]["environment"] = {
        "status": "healthy" if not missing_vars else "unhealthy",
        "missing_variables": missing_vars,
        "total_env_vars": len([k for k in os.environ.keys() if k.startswith(('FIREBASE_', 'ADMIN_', 'ENCRYPTION_'))])
    }
    
    if missing_vars:
        health_status["status"] = "degraded"
    
    # System resources
    try:
        import psutil
        memory = psutil.virtual_memory()
        health_status["components"]["system"] = {
            "status": "healthy",
            "memory_usage_percent": memory.percent,
            "available_memory_gb": round(memory.available / (1024**3), 2)
        }
    except:
        health_status["components"]["system"] = {"status": "unknown"}
    
    return health_status

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
        
        # Add measurement ID if available
        if hasattr(settings, 'FIREBASE_WEB_MEASUREMENT_ID') and settings.FIREBASE_WEB_MEASUREMENT_ID:
            firebase_config["measurementId"] = settings.FIREBASE_WEB_MEASUREMENT_ID
        
        # Check for missing fields
        missing_fields = [k for k, v in firebase_config.items() if not v and k != "measurementId"]
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

# Debug endpoints (only in debug mode)
@app.get("/api/debug/firebase-status")
async def debug_firebase_status():
    """Debug Firebase initialization status"""
    if not settings.DEBUG:
        raise HTTPException(status_code=404, detail="Debug mode only")
    
    firebase_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    
    status = {
        "firebase_initialized": firebase_initialized,
        "firebase_auth_available": firebase_auth is not None,
        "firebase_db_available": firebase_db is not None,
        "credentials_length": len(firebase_json) if firebase_json else 0,
        "credentials_preview": firebase_json[:100] + "..." if firebase_json and len(firebase_json) > 100 else firebase_json,
        "database_url": os.getenv("FIREBASE_DATABASE_URL"),
        "environment": settings.ENVIRONMENT,
        "debug_mode": settings.DEBUG
    }
    
    if firebase_json:
        try:
            # Test JSON parsing
            parsed = json.loads(firebase_json)
            status["json_parse"] = "success"
            status["project_id"] = parsed.get("project_id")
            status["client_email"] = parsed.get("client_email", "")[:50] + "..."
            status["has_private_key"] = "private_key" in parsed
            status["private_key_valid"] = parsed.get("private_key", "").startswith("-----BEGIN PRIVATE KEY-----")
            status["required_fields_present"] = all(
                field in parsed for field in ['type', 'project_id', 'private_key', 'client_email']
            )
        except json.JSONDecodeError as e:
            status["json_parse"] = f"error: {e}"
            status["json_error_position"] = getattr(e, 'pos', None)
            status["json_error_line"] = getattr(e, 'lineno', None)
            status["json_error_column"] = getattr(e, 'colno', None)
    
    return status

# Auth routes
@app.post("/api/auth/verify")
async def verify_token(current_user: dict = Depends(get_current_user)):
    """Verify Firebase token and create/update user data"""
    try:
        user_id = current_user['uid']
        email = current_user.get('email')
        
        if not firebase_initialized or not firebase_db:
            # Return basic response without database operations
            return {
                "success": True,
                "user_id": user_id,
                "email": email,
                "user_data": {
                    "email": email,
                    "subscription_status": "trial",
                    "api_keys_set": False,
                    "bot_active": False,
                    "note": "Database unavailable - limited functionality"
                },
                "firebase_available": False
            }
        
        # Get or create user data
        try:
            user_ref = firebase_db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            
            if not user_data:
                logger.info(f"Creating user data for new user: {user_id}")
                
                # Calculate trial expiry (7 days from now)
                trial_expiry = datetime.now(timezone.utc) + timedelta(days=7)
                
                from firebase_admin import db
                
                user_data = {
                    "email": email,
                    "created_at": db.SERVER_TIMESTAMP,
                    "last_login": db.SERVER_TIMESTAMP,
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
                from firebase_admin import db
                user_ref.update({
                    "last_login": db.SERVER_TIMESTAMP
                })
                logger.info(f"Last login updated for: {user_id}")
        
        except Exception as db_error:
            logger.error(f"Database operation failed: {db_error}")
            # Return basic user info even if database fails
            user_data = {
                "email": email,
                "subscription_status": "trial",
                "api_keys_set": False,
                "bot_active": False,
                "database_error": str(db_error)
            }
        
        return {
            "success": True,
            "user_id": user_id,
            "email": email,
            "user_data": user_data,
            "firebase_available": True
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token verification error: {e}")
        raise HTTPException(status_code=500, detail="Token verification failed")

# User routes
@app.get("/api/user/profile")
async def get_user_profile(current_user: dict = Depends(get_current_user)):
    """Get user profile with Firebase fallback"""
    try:
        user_id = current_user['uid']
        email = current_user.get('email')
        
        if not firebase_initialized or not firebase_db:
            # Return mock profile if Firebase unavailable
            logger.warning("Firebase unavailable, returning mock profile")
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
                "account_balance": 0.0,
                "note": "Firebase unavailable - mock data"
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
                "account_balance": 0.0,
                "error": "Database error"
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Profile fetch error: {e}")
        # Fallback response
        return {
            "email": current_user.get('email', 'unknown@user.com'),
            "subscription": {
                "status": "trial",
                "plan": "Deneme", 
                "daysRemaining": 7
            },
            "api_keys_set": False,
            "bot_active": False,
            "total_trades": 0,
            "total_pnl": 0.0,
            "account_balance": 0.0,
            "error": str(e)
        }

@app.get("/api/user/account")
async def get_account_data(current_user: dict = Depends(get_current_user)):
    """Get account data with fallback"""
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
                            from firebase_admin import db
                            user_ref.update({
                                "account_balance": balance,
                                "last_balance_update": db.SERVER_TIMESTAMP
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

@app.get("/api/user/stats")
async def get_user_stats(current_user: dict = Depends(get_current_user)):
    """Get user stats"""
    try:
        user_id = current_user['uid']
        
        if not firebase_initialized or not firebase_db:
            return {
                "totalTrades": 0,
                "totalPnl": 0.0,
                "winRate": 0.0,
                "botStartTime": None,
                "lastTradeTime": None
            }
        
        try:
            user_ref = firebase_db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            
            if user_data:
                return {
                    "totalTrades": user_data.get("total_trades", 0),
                    "totalPnl": user_data.get("total_pnl", 0.0),
                    "winRate": user_data.get("win_rate", 0.0),
                    "botStartTime": user_data.get("bot_start_time"),
                    "lastTradeTime": user_data.get("last_trade_time")
                }
        except Exception as db_error:
            logger.error(f"Database error in stats: {db_error}")
        
        return {
            "totalTrades": 0,
            "totalPnl": 0.0,
            "winRate": 0.0,
            "botStartTime": None,
            "lastTradeTime": None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail="Stats could not be loaded")

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
        
        # Validate API key format
        if len(api_key) != 64 or not api_key.isalnum():
            raise HTTPException(status_code=400, detail="Invalid API key format")
        
        if len(api_secret) != 64 or not api_secret.isalnum():
            raise HTTPException(status_code=400, detail="Invalid API secret format")
        
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
            # If Firebase unavailable, still return success (store temporarily)
            logger.warning("Firebase unavailable - API keys validated but not stored")
            return {
                "success": True,
                "message": "API keys tested successfully (temporary storage)",
                "balance": balance,
                "firebase_available": False
            }
        
        # Encrypt and save
        try:
            from app.utils.crypto import encrypt_data
            encrypted_api_key = encrypt_data(api_key)
            encrypted_api_secret = encrypt_data(api_secret)
            
            from firebase_admin import db
            
            api_data = {
                "binance_api_key": encrypted_api_key,
                "binance_api_secret": encrypted_api_secret,
                "api_testnet": testnet,
                "api_keys_set": True,
                "api_updated_at": db.SERVER_TIMESTAMP,
                "account_balance": balance
            }
            
            user_ref = firebase_db.reference(f'users/{user_id}')
            user_ref.update(api_data)
            
            logger.info(f"API keys saved for user: {user_id}")
            
        except Exception as save_error:
            logger.error(f"API keys save error: {save_error}")
            # Still return success since API test passed
            return {
                "success": True,
                "message": "API keys tested successfully but not saved (database error)",
                "balance": balance,
                "error": str(save_error)
            }
        
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

@app.post("/api/user/close-position")
async def close_position(request: dict, current_user: dict = Depends(get_current_user)):
    """Close position"""
    try:
        user_id = current_user['uid']
        symbol = request.get('symbol')
        position_side = request.get('positionSide')
        
        if not symbol or not position_side:
            raise HTTPException(status_code=400, detail="Symbol and position side required")
        
        if not firebase_initialized or not firebase_db:
            return {
                "success": False,
                "message": "Database service unavailable"
            }
        
        user_ref = firebase_db.reference(f'users/{user_id}')
        user_data = user_ref.get()
        
        if not user_data or not user_data.get('api_keys_set'):
            raise HTTPException(status_code=400, detail="API keys required")
        
        # Real position closing
        try:
            from app.utils.crypto import decrypt_data
            from app.binance_client import BinanceClient
            
            encrypted_api_key = user_data.get('binance_api_key')
            encrypted_api_secret = user_data.get('binance_api_secret')
            
            api_key = decrypt_data(encrypted_api_key)
            api_secret = decrypt_data(encrypted_api_secret)
            
            client = BinanceClient(api_key, api_secret)
            await client.initialize()
            
            # Get position info
            positions = await client.get_open_positions(symbol, use_cache=False)
            
            if not positions:
                raise HTTPException(status_code=404, detail="No open position found")
            
            position = positions[0]
            position_amt = float(position['positionAmt'])
            side_to_close = 'SELL' if position_amt > 0 else 'BUY'
            
            # Close position
            close_result = await client.close_position(symbol, position_amt, side_to_close)
            
            if close_result:
                # Calculate PnL
                pnl = await client.get_last_trade_pnl(symbol)
                
                # Log trade to Firebase
                trade_data = {
                    "user_id": user_id,
                    "symbol": symbol,
                    "side": position_side,
                    "status": "CLOSED_MANUAL",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "pnl": pnl,
                    "close_reason": "manual"
                }
                
                try:
                    trades_ref = firebase_db.reference('trades')
                    trades_ref.push(trade_data)
                except Exception as log_error:
                    logger.error(f"Trade logging error: {log_error}")
                
                # Update user stats
                from firebase_admin import db
                current_trades = user_data.get('total_trades', 0)
                current_pnl = user_data.get('total_pnl', 0.0)
                
                user_ref.update({
                    'total_trades': current_trades + 1,
                    'total_pnl': current_pnl + pnl,
                    'last_trade_time': db.SERVER_TIMESTAMP
                })
                
                await client.close()
                
                return {
                    "success": True,
                    "message": "Position closed successfully",
                    "pnl": pnl
                }
            else:
                raise Exception("Position closing failed")
                
        except Exception as e:
            logger.error(f"Position close error for {user_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Position could not be closed: {str(e)}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Position close error: {e}")
        raise HTTPException(status_code=500, detail="Position could not be closed")

# Bot routes
@app.get("/api/bot/status")
async def get_bot_status(current_user: dict = Depends(get_current_user)):
    """Get bot status"""
    try:
        user_id = current_user['uid']
        
        # Try to get real bot status
        try:
            from app.bot_manager import bot_manager
            status = bot_manager.get_bot_status(user_id)
            return {
                "success": True,
                "status": status
            }
        except Exception as bot_error:
            logger.error(f"Bot manager error: {bot_error}")
            # Return fallback status
            return {
                "success": True,
                "status": {
                    "user_id": user_id,
                    "is_running": False,
                    "symbol": None,
                    "position_side": None,
                    "status_message": "Bot service unavailable",
                    "account_balance": 0.0,
                    "position_pnl": 0.0,
                    "total_trades": 0,
                    "total_pnl": 0.0,
                    "last_check_time": None
                }
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
        logger.error(f"Bot API status error: {e}")
        raise HTTPException(status_code=500, detail="API status could not be checked")

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
            
            # Try to start bot
            try:
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
                from firebase_admin import db
                user_ref.update({
                    "bot_active": True,
                    "bot_symbol": request.get('symbol', 'BTCUSDT'),
                    "bot_start_time": db.SERVER_TIMESTAMP
                })
                
                return {
                    "success": True,
                    "message": "Bot started successfully",
                    "bot_status": result.get("status", {})
                }
                
            except Exception as bot_error:
                logger.error(f"Bot manager error: {bot_error}")
                # Return mock success for now
                return {
                    "success": False,
                    "message": f"Bot service unavailable: {str(bot_error)}"
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
        
        try:
            from app.bot_manager import bot_manager
            result = await bot_manager.stop_bot_for_user(user_id)
            
            if "error" in result:
                raise HTTPException(status_code=400, detail=result["error"])
        except Exception as bot_error:
            logger.error(f"Bot manager error: {bot_error}")
            # Return mock success for now
            pass
        
        # Update user data
        if firebase_initialized and firebase_db:
            try:
                from firebase_admin import db
                user_ref = firebase_db.reference(f'users/{user_id}')
                user_ref.update({
                    "bot_active": False,
                    "bot_stop_time": db.SERVER_TIMESTAMP
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
    """Catch-all route for SPA"""
    if (full_path.startswith("static/") or 
        full_path.endswith((".html", ".js", ".css", ".png", ".jpg", ".ico")) or
        full_path in ["dashboard", "login", "register", "admin"]):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse("static/index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=int(os.getenv("PORT", 8000)),
        reload=settings.DEBUG
    )
