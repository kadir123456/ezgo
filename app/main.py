# =================================================================
# CSS MIME Type Fix - Dosyanın en başında
# =================================================================
import mimetypes
mimetypes.add_type('text/css', '.css')
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('application/json', '.json')

import logging
import time
import traceback
import sys
import json
import os
import re
from typing import Optional, Dict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from contextlib import asynccontextmanager

# ------------------------------
# Üçüncü Parti Kütüphaneler
# ------------------------------
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.exceptions import RequestValidationError

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# ------------------------------
# Lokal Modüller
# ------------------------------
from app.config import settings
from app.utils.metrics import metrics, get_metrics_data, get_metrics_content_type
from app.binance_client import BinanceClient

# =================================================================
# GLOBAL SINGLETONS - Performance Optimization
# =================================================================
class GlobalClients:
    """Global singleton pattern for expensive resources"""
    
    def __init__(self):
        self.binance_clients: Dict[str, BinanceClient] = {}  # user_id -> BinanceClient
        self.default_client: Optional[BinanceClient] = None  # Public data client
        self.firebase_admin = None
        self.firebase_auth = None
        self.firebase_db = None
        self.firebase_initialized = False

    async def get_binance_client(self, user_id: str = None, api_key: str = None, api_secret: str = None) -> BinanceClient:
        """
        Get BinanceClient instance - optimized singleton pattern
        """
        # Public client (for market data only - no private endpoints)
        if not user_id and not api_key:
            if not self.default_client:
                # Create public-only client without API credentials
                self.default_client = BinanceClient(api_key=None, api_secret=None, user_id="public")
                try:
                    await self.default_client.initialize()
                except Exception as e:
                    logging.warning(f"Public client initialization failed: {e}")
                    # Create minimal client for public data only
                    self.default_client = BinanceClient()
                    self.default_client.client = None  # Will use REST fallback
            return self.default_client
        
        # User-specific client
        if user_id:
            # Check if we already have a client for this user
            if user_id in self.binance_clients:
                client = self.binance_clients[user_id]
                # Check if client is still valid
                if client.client and not client.client.session.closed:
                    return client
                else:
                    # Remove invalid client
                    del self.binance_clients[user_id]
            
            # Create new client for user
            if api_key and api_secret:
                new_client = BinanceClient(api_key, api_secret, user_id)
                success = await new_client.initialize()
                if success:
                    self.binance_clients[user_id] = new_client
                    return new_client
                else:
                    raise HTTPException(status_code=400, detail="Invalid API credentials")
            else:
                # Get API keys from database
                if self.firebase_initialized and self.firebase_db:
                    try:
                        from app.utils.crypto import decrypt_data
                        
                        user_ref = self.firebase_db.reference(f'users/{user_id}')
                        user_data = user_ref.get()
                        
                        if user_data and user_data.get('api_keys_set'):
                            encrypted_api_key = user_data.get('binance_api_key')
                            encrypted_api_secret = user_data.get('binance_api_secret')
                            
                            if encrypted_api_key and encrypted_api_secret:
                                api_key = decrypt_data(encrypted_api_key)
                                api_secret = decrypt_data(encrypted_api_secret)
                                
                                new_client = BinanceClient(api_key, api_secret, user_id)
                                success = await new_client.initialize()
                                if success:
                                    self.binance_clients[user_id] = new_client
                                    return new_client
                    except Exception as e:
                        logging.error(f"Error creating client for user {user_id}: {e}")
                
                # Fallback to default client
                return await self.get_binance_client()
        
        # Create temporary client with provided credentials (for testing)
        temp_client = BinanceClient(api_key, api_secret)
        await temp_client.initialize()
        return temp_client

    async def cleanup_client(self, user_id: str):
        """Clean up client for specific user"""
        if user_id in self.binance_clients:
            client = self.binance_clients[user_id]
            try:
                await client.close_connection()
            except Exception as e:
                logging.error(f"Error closing client for {user_id}: {e}")
            finally:
                del self.binance_clients[user_id]

    async def cleanup_all_clients(self):
        """Clean up all clients"""
        for user_id in list(self.binance_clients.keys()):
            await self.cleanup_client(user_id)
        
        if self.default_client:
            try:
                await self.default_client.close_connection()
            except Exception as e:
                logging.error(f"Error closing default client: {e}")
            finally:
                self.default_client = None

# Global instance
global_clients = GlobalClients()

# =================================================================
# Custom StaticFiles Class - CSS MIME Type Fix
# =================================================================
class FixedStaticFiles(StaticFiles):
    """CSS ve JS dosyaları için MIME type'ları düzelten custom StaticFiles"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
            
            # MIME type düzeltmeleri
            if path.endswith('.css'):
                response.headers['content-type'] = 'text/css; charset=utf-8'
                response.headers['cache-control'] = 'public, max-age=31536000'
            elif path.endswith('.js'):
                response.headers['content-type'] = 'application/javascript; charset=utf-8'
                response.headers['cache-control'] = 'public, max-age=31536000'
            elif path.endswith('.json'):
                response.headers['content-type'] = 'application/json; charset=utf-8'
            elif path.endswith('.html'):
                response.headers['content-type'] = 'text/html; charset=utf-8'
                response.headers['cache-control'] = 'no-cache'
                
            return response
        except Exception as e:
            logging.error(f"Static file error for {path}: {e}")
            raise

# ------------------------------
# Logging Ayarları
# ------------------------------
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("main")

def initialize_firebase():
    """Initialize Firebase Admin SDK with robust error handling"""
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
                return False, None, None
            
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
                    return False, None, None
                
                # Validate required fields
                required_fields = ['type', 'project_id', 'private_key', 'client_email']
                missing_fields = [field for field in required_fields if field not in cred_dict]
                
                if missing_fields:
                    logger.error(f"❌ Missing Firebase fields: {missing_fields}")
                    return False, None, None
                
                # Validate private key format
                private_key = cred_dict.get('private_key', '')
                if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
                    logger.error("❌ Invalid private key format")
                    logger.error(f"Private key starts with: {private_key[:50]}...")
                    return False, None, None
                
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
                
                logger.info("🔥 Firebase Admin SDK initialized successfully")
                logger.info(f"✅ Project ID: {cred_dict.get('project_id')}")
                logger.info(f"✅ Client Email: {cred_dict.get('client_email', '')[:50]}...")
                logger.info(f"✅ Parsing strategy: {successful_strategy}")
                
                # Test database connection
                try:
                    test_ref = firebase_db_module.reference('system/connection_test')
                    test_ref.set({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'status': 'connected',
                        'parsing_strategy': successful_strategy
                    })
                    logger.info("✅ Firebase database write test successful")
                except Exception as db_test_error:
                    logger.warning(f"⚠️ Firebase database test failed: {db_test_error}")
                
                return True, firebase_auth_module, firebase_db_module
                
            except Exception as init_error:
                logger.error(f"❌ Firebase initialization error: {init_error}")
                logger.error(f"Error type: {type(init_error).__name__}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                return False, None, None
        else:
            logger.info("🔥 Firebase already initialized")
            return True, firebase_auth_module, firebase_db_module
            
    except ImportError as e:
        logger.error(f"❌ Firebase import error: {e}")
        return False, None, None
    except Exception as e:
        logger.error(f"❌ Unexpected Firebase error: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False, None, None

# =================================================================
# LIFESPAN EVENT HANDLER - Optimized Resource Management
# =================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan event handler for efficient resource management
    """
    # STARTUP
    logger.info("🚀 EzyagoTrading starting up...")
    logger.info(f"🌍 Environment: {settings.ENVIRONMENT}")
    logger.info(f"🐛 Debug mode: {settings.DEBUG}")
    
    try:
        # Initialize Firebase
        firebase_init_result = initialize_firebase()
        global_clients.firebase_initialized, global_clients.firebase_auth, global_clients.firebase_db = firebase_init_result
        
        if global_clients.firebase_initialized:
            logger.info("✅ Firebase connection established")
        else:
            logger.error("❌ Firebase connection failed")
            if not settings.DEBUG:
                logger.warning("⚠️ Production mode with Firebase issues - some features may be unavailable")
        
        # Initialize default BinanceClient for public data
        try:
            logger.info("🔄 Initializing default BinanceClient...")
            default_client = await global_clients.get_binance_client()
            logger.info("✅ Default BinanceClient initialized successfully")
        except Exception as client_error:
            logger.error(f"❌ Default BinanceClient initialization failed: {client_error}")
        
        # CSS dosyası kontrolü
        css_path = Path("static/dashboard.css")
        if css_path.exists():
            logger.info("✅ dashboard.css file found")
        else:
            logger.error("❌ dashboard.css file not found!")
        
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
    
    yield  # Application runs here
    
    # SHUTDOWN
    logger.info("🛑 EzyagoTrading shutting down...")
    
    try:
        # Cleanup BinanceClients
        await global_clients.cleanup_all_clients()
        logger.info("✅ All BinanceClients closed")
        
        # Cleanup bot manager
        try:
            from app.bot_manager import bot_manager
            await bot_manager.shutdown_all_bots()
            logger.info("✅ All bots shutdown completed")
        except Exception as e:
            logger.error(f"Error during bot shutdown: {e}")
            
    except Exception as shutdown_error:
        logger.error(f"💥 Shutdown error: {shutdown_error}")
    
    logger.info("✅ Shutdown completed")

# FastAPI app with lifespan
app = FastAPI(
    title="EzyagoTrading API",
    description="Professional Crypto Futures Trading Bot",
    version="1.0.0",
    debug=settings.DEBUG,
    lifespan=lifespan
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
    
    if not global_clients.firebase_initialized or not global_clients.firebase_auth:
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
        decoded_token = global_clients.firebase_auth.verify_id_token(credentials.credentials)
        logger.info(f"✅ Token verified for user: {decoded_token['uid']}")
        return decoded_token
    except Exception as e:
        logger.error(f"❌ Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication token")

# =================================================================
# HELPER FUNCTIONS - Optimized
# =================================================================
async def get_binance_client_for_user(user_id: str) -> BinanceClient:
    """
    Optimized function to get BinanceClient for specific user
    """
    try:
        return await global_clients.get_binance_client(user_id=user_id)
    except Exception as e:
        logger.error(f"Error getting client for user {user_id}: {e}")
        # Return default client as fallback
        return await global_clients.get_binance_client()

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
            "firebase_status": global_clients.firebase_initialized
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

# =================================================================
# CSS ve JS için özel route'lar - MIME type garantisi
# =================================================================
@app.get("/static/dashboard.css")
async def serve_dashboard_css():
    """Dashboard CSS dosyası için özel route"""
    css_path = Path("static/dashboard.css")
    if css_path.exists():
        return FileResponse(
            css_path, 
            media_type="text/css", 
            headers={
                "Cache-Control": "public, max-age=31536000",
                "Content-Type": "text/css; charset=utf-8"
            }
        )
    else:
        logger.error("dashboard.css file not found")
        raise HTTPException(status_code=404, detail="CSS file not found")

@app.get("/static/dashboard.js")
async def serve_dashboard_js():
    """Dashboard JS dosyası için özel route"""
    js_path = Path("static/dashboard.js")
    if js_path.exists():
        return FileResponse(
            js_path, 
            media_type="application/javascript",
            headers={
                "Cache-Control": "public, max-age=31536000", 
                "Content-Type": "application/javascript; charset=utf-8"
            }
        )
    else:
        logger.error("dashboard.js file not found")
        raise HTTPException(status_code=404, detail="JS file not found")

@app.get("/static/config.js")
async def serve_config_js():
    """Config JS dosyası için özel route"""
    js_path = Path("static/config.js")
    if js_path.exists():
        return FileResponse(
            js_path, 
            media_type="application/javascript",
            headers={
                "Cache-Control": "public, max-age=31536000", 
                "Content-Type": "application/javascript; charset=utf-8"
            }
        )
    else:
        logger.error("config.js file not found")
        raise HTTPException(status_code=404, detail="Config JS file not found")

# Static files - İkinci mount (fallback)
app.mount("/static", FixedStaticFiles(directory="static"), name="static")

# Health check endpoints
@app.get("/health")
async def health_check():
    """Basic health check endpoint"""
    try:
        return {
            "status": "healthy" if global_clients.firebase_initialized else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "environment": settings.ENVIRONMENT,
            "version": "1.0.0",
            "firebase_connected": global_clients.firebase_initialized,
            "binance_clients_active": len(global_clients.binance_clients),
            "default_client_active": global_clients.default_client is not None
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
        "firebase_initialized": global_clients.firebase_initialized,
        "firebase_auth_available": global_clients.firebase_auth is not None,
        "firebase_db_available": global_clients.firebase_db is not None,
        "credentials_length": len(firebase_json) if firebase_json else 0,
        "credentials_preview": firebase_json[:100] + "..." if firebase_json and len(firebase_json) > 100 else firebase_json,
        "database_url": os.getenv("FIREBASE_DATABASE_URL"),
        "environment": settings.ENVIRONMENT,
        "debug_mode": settings.DEBUG,
        "binance_clients_count": len(global_clients.binance_clients),
        "default_client_status": "active" if global_clients.default_client else "inactive"
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

# =================================================================
# AUTH ENDPOINTS
# =================================================================
@app.post("/api/auth/verify")
async def verify_token(current_user: dict = Depends(get_current_user)):
    """Verify Firebase token and create/update user data"""
    try:
        user_id = current_user['uid']
        email = current_user.get('email')
        
        if not global_clients.firebase_initialized or not global_clients.firebase_db:
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
            user_ref = global_clients.firebase_db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            
            if not user_data:
                logger.info(f"Creating user data for new user: {user_id}")
                
                # Calculate trial expiry (7 days from now)
                trial_expiry = datetime.now(timezone.utc) + timedelta(days=7)
                
                user_data = {
                    "email": email,
                    "created_at": int(datetime.utcnow().timestamp() * 1000),
                    "last_login": int(datetime.utcnow().timestamp() * 1000),
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
                    "last_login": int(datetime.utcnow().timestamp() * 1000)
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

# =================================================================
# USER ENDPOINTS - FIXED API KEYS SAVE
# =================================================================
@app.post("/api/user/api-keys")
async def save_api_keys(request: dict, current_user: dict = Depends(get_current_user)):
    """Save user API keys - FIXED VERSION using old working method"""
    try:
        user_id = current_user['uid']
        api_key = request.get('api_key', '').strip()
        api_secret = request.get('api_secret', '').strip()
        testnet = request.get('testnet', False)
        
        logger.info(f"API keys save request from user: {user_id}")
        
        if not api_key or not api_secret:
            raise HTTPException(status_code=400, detail="API key and secret required")
        
        # Daha esnek API key format validation
        if len(api_key) < 32 or len(api_key) > 100:
            raise HTTPException(status_code=400, detail="Invalid API key length")
        
        if len(api_secret) < 32 or len(api_secret) > 100:
            raise HTTPException(status_code=400, detail="Invalid API secret length")
        
        # Test API keys - ESKİ ÇALIŞAN YÖNTEMİ KULLAN
        try:
            logger.info(f"Testing API keys for user: {user_id}")
            
            # ESKİ KOD: Doğrudan BinanceClient oluştur (singleton pattern KULLANMA)
            test_client = BinanceClient(api_key, api_secret)
            await test_client.initialize()
            
            balance = await test_client.get_account_balance(use_cache=False)
            logger.info(f"API test successful for user {user_id}, balance: {balance}")
            
            # ESKİ KOD: Doğrudan close çağır
            await test_client.close()
            
        except Exception as test_error:
            logger.error(f"API test failed for user {user_id}: {test_error}")
            raise HTTPException(
                status_code=400, 
                detail=f"API keys test failed: {str(test_error)}"
            )
        
        # Firebase kontrol
        if not global_clients.firebase_initialized or not global_clients.firebase_db:
            logger.warning("Firebase unavailable - API keys validated but not stored")
            return {
                "success": True,
                "message": "API keys tested successfully (Firebase unavailable - temporary storage)",
                "balance": balance,
                "firebase_available": False
            }
        
        # Encrypt and save - ESKİ YÖNTEMİ KULLAN
        try:
            # Crypto modülü import kontrolü
            try:
                from app.utils.crypto import encrypt_data
                logger.info("Crypto module imported successfully")
            except ImportError as import_error:
                logger.error(f"Crypto module import failed: {import_error}")
                raise HTTPException(
                    status_code=500, 
                    detail="Encryption service unavailable. Please contact support."
                )
            
            # Encrypt data
            encrypted_api_key = encrypt_data(api_key)
            encrypted_api_secret = encrypt_data(api_secret)
            
            # Prepare data for Firebase
            api_data = {
                "binance_api_key": encrypted_api_key,
                "binance_api_secret": encrypted_api_secret,
                "api_testnet": testnet,
                "api_keys_set": True,
                "api_updated_at": int(datetime.utcnow().timestamp() * 1000),
                "account_balance": balance,
                "last_api_test": int(datetime.utcnow().timestamp() * 1000)
            }
            
            # Save to Firebase
            user_ref = global_clients.firebase_db.reference(f'users/{user_id}')
            user_ref.update(api_data)
            
            # Clear existing client for this user to force recreation with new keys
            try:
                await global_clients.cleanup_client(user_id)
                logger.info(f"Existing client cleaned for user: {user_id}")
            except Exception as cleanup_error:
                logger.warning(f"Client cleanup error: {cleanup_error}")
            
            logger.info(f"API keys saved successfully for user: {user_id}")
            
            return {
                "success": True,
                "message": "API keys saved and tested successfully",
                "balance": balance,
                "firebase_available": True
            }
            
        except Exception as save_error:
            logger.error(f"API keys save error for user {user_id}: {save_error}")
            logger.error(f"Save error traceback: {traceback.format_exc()}")
            
            # Daha detaylı error response
            error_detail = "Failed to save API keys"
            if "encrypt" in str(save_error).lower():
                error_detail = "Encryption service error"
            elif "firebase" in str(save_error).lower():
                error_detail = "Database save error"
            
            raise HTTPException(
                status_code=500, 
                detail=f"{error_detail}: {str(save_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in save_api_keys for user {current_user.get('uid', 'unknown')}: {e}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, 
            detail=f"API keys could not be saved: {str(e)}"
        )

# Continue with rest of your endpoints...
# (dashboard-data, profile, account, positions, etc. remain the same)

@app.get("/api/user/dashboard-data")
async def get_dashboard_data(current_user: dict = Depends(get_current_user)):
    """Get all dashboard data in a single optimized API call - with singleton clients"""
    try:
        user_id = current_user['uid']
        email = current_user.get('email')
        
        logger.info(f"Dashboard data request for user: {user_id}")
        
        # Initialize response with defaults
        dashboard_data = {
            "profile": {
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
            },
            "stats": {
                "totalTrades": 0,
                "totalPnl": 0.0,
                "winRate": 0.0,
                "botStartTime": None,
                "lastTradeTime": None
            },
            "api_info": {
                "hasKeys": False,
                "maskedApiKey": None,
                "useTestnet": False
            },
            "account": {
                "totalBalance": 0.0,
                "availableBalance": 0.0,
                "unrealizedPnl": 0.0,
                "message": "API keys required"
            },
            "bot_status": {
                "user_id": user_id,
                "is_running": False,
                "symbol": None,
                "position_side": None,
                "status_message": "Bot not running",
                "account_balance": 0.0,
                "position_pnl": 0.0,
                "total_trades": 0,
                "total_pnl": 0.0,
                "last_check_time": None
            },
            "firebase_available": global_clients.firebase_initialized,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        if not global_clients.firebase_initialized or not global_clients.firebase_db:
            logger.warning("Firebase unavailable, returning default dashboard data")
            return dashboard_data
        
        try:
            # Get user data from Firebase
            user_ref = global_clients.firebase_db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            
            if user_data:
                # Profile data
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
                
                dashboard_data["profile"] = {
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
                
                # Stats data
                dashboard_data["stats"] = {
                    "totalTrades": user_data.get("total_trades", 0),
                    "totalPnl": user_data.get("total_pnl", 0.0),
                    "winRate": user_data.get("win_rate", 0.0),
                    "botStartTime": user_data.get("bot_start_time"),
                    "lastTradeTime": user_data.get("last_trade_time")
                }
                
                # API info
                has_keys = user_data.get('api_keys_set', False)
                masked_key = None
                
                if has_keys:
                    encrypted_api_key = user_data.get('binance_api_key')
                    if encrypted_api_key:
                        try:
                            from app.utils.crypto import decrypt_data
                            api_key = decrypt_data(encrypted_api_key)
                            if api_key and len(api_key) >= 8:
                                masked_key = api_key[:8] + "..." + api_key[-4:]
                        except:
                            masked_key = "Encrypted API Key"
                
                dashboard_data["api_info"] = {
                    "hasKeys": has_keys,
                    "maskedApiKey": masked_key,
                    "useTestnet": user_data.get('api_testnet', False)
                }
                
                # Account data (if API keys exist) - Using singleton client
                if has_keys:
                    try:
                        # Use optimized singleton client
                        client = await get_binance_client_for_user(user_id)
                        
                        # Only get account data for private clients
                        if hasattr(client, 'is_public_only') and not client.is_public_only:
                            balance = await client.get_account_balance(use_cache=True)
                            
                            dashboard_data["account"] = {
                                "totalBalance": balance,
                                "availableBalance": balance,
                                "unrealizedPnl": 0.0,
                                "message": "Real Binance data (optimized)"
                            }
                            
                            # Update cache
                            user_ref.update({
                                "account_balance": balance,
                                "last_balance_update": int(datetime.utcnow().timestamp() * 1000)
                            })
                        else:
                            dashboard_data["account"] = {
                                "totalBalance": user_data.get("account_balance", 0.0),
                                "availableBalance": user_data.get("account_balance", 0.0),
                                "unrealizedPnl": 0.0,
                                "message": "Public client - cached data"
                            }
                        
                    except Exception as account_error:
                        logger.error(f"Account data error: {account_error}")
                        dashboard_data["account"] = {
                            "totalBalance": user_data.get("account_balance", 0.0),
                            "availableBalance": user_data.get("account_balance", 0.0),
                            "unrealizedPnl": 0.0,
                            "message": f"Cached data (API error)"
                        }
        
        except Exception as db_error:
            logger.error(f"Database error in dashboard data: {db_error}")
            # Return defaults if database fails
        
        logger.info(f"Dashboard data successfully loaded for user: {user_id}")
        return dashboard_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Dashboard data error: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        # Return minimal fallback data
        return {
            "profile": {
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
                "account_balance": 0.0
            },
            "stats": {
                "totalTrades": 0,
                "totalPnl": 0.0,
                "winRate": 0.0,
                "botStartTime": None,
                "lastTradeTime": None
            },
            "api_info": {
                "hasKeys": False,
                "maskedApiKey": None,
                "useTestnet": False
            },
            "account": {
                "totalBalance": 0.0,
                "availableBalance": 0.0,
                "unrealizedPnl": 0.0,
                "message": "Service error"
            },
            "bot_status": {
                "user_id": current_user['uid'],
                "is_running": False,
                "symbol": None,
                "position_side": None,
                "status_message": "Service error",
                "account_balance": 0.0,
                "position_pnl": 0.0,
                "total_trades": 0,
                "total_pnl": 0.0,
                "last_check_time": None
            },
            "firebase_available": False,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

@app.get("/api/user/api-info")
async def get_api_info(current_user: dict = Depends(get_current_user)):
    """Get API info (masked)"""
    try:
        user_id = current_user['uid']
        
        if not global_clients.firebase_initialized or not global_clients.firebase_db:
            return {
                "hasKeys": False,
                "maskedApiKey": None,
                "useTestnet": False
            }
        
        try:
            user_ref = global_clients.firebase_db.reference(f'users/{user_id}')
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

# Add compatibility endpoint
@app.get("/api/user/api-keys")
async def get_api_keys_status(current_user: dict = Depends(get_current_user)):
    """Get API keys status - same as api-info for compatibility"""
    return await get_api_info(current_user)

# Add other essential endpoints here...
# (Continue with remaining endpoints as needed)

# =================================================================
# STATIC ROUTES
# =================================================================
@app.get("/")
async def read_root():
    return FileResponse("static/index.html", media_type="text/html")

@app.get("/dashboard")
async def read_dashboard():
    return FileResponse("static/dashboard.html", media_type="text/html")

# Catch-all for SPA
@app.get("/{full_path:path}")
async def catch_all(full_path: str):
    """Catch-all route for SPA"""
    if (full_path.startswith("static/") or 
        full_path.endswith((".html", ".js", ".css", ".png", ".jpg", ".ico")) or
        full_path in ["dashboard", "login", "register", "admin"]):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse("static/index.html", media_type="text/html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=int(os.getenv("PORT", 8000)),
        reload=settings.DEBUG
    )
