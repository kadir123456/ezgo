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
        
        # Create temporary client with provided credentials
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
        if global_clients.firebase_initialized and global_clients.firebase_db:
            # Test write
            test_ref = global_clients.firebase_db.reference('health_check')
            test_ref.set({
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'status': 'healthy'
            })
            health_status["components"]["firebase"] = {
                "status": "healthy",
                "database_connected": True,
                "auth_available": global_clients.firebase_auth is not None
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
    
    # BinanceClient check
    try:
        client_status = {
            "active_user_clients": len(global_clients.binance_clients),
            "default_client_available": global_clients.default_client is not None,
            "client_status": "healthy"
        }
        
        # Test default client
        if global_clients.default_client:
            try:
                # Test with a simple price request
                price = await global_clients.default_client.get_market_price("BTCUSDT")
                client_status["test_price_btc"] = price
                client_status["api_connection"] = "working"
            except Exception as api_error:
                client_status["api_connection"] = f"error: {str(api_error)}"
                client_status["client_status"] = "degraded"
        
        health_status["components"]["binance"] = client_status
        
    except Exception as e:
        health_status["components"]["binance"] = {
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

@app.get("/api/debug/binance-clients")
async def debug_binance_clients():
    """Debug BinanceClient status"""
    if not settings.DEBUG:
        raise HTTPException(status_code=404, detail="Debug mode only")
    
    client_info = {
        "total_user_clients": len(global_clients.binance_clients),
        "default_client_active": global_clients.default_client is not None,
        "user_clients": []
    }
    
    for user_id, client in global_clients.binance_clients.items():
        client_status = {
            "user_id": user_id,
            "client_active": client.client is not None,
            "session_closed": client.client.session.closed if client.client else None,
            "initialization_status": "initialized" if client.client else "failed"
        }
        client_info["user_clients"].append(client_status)
    
    if global_clients.default_client:
        try:
            # Test default client
            price = await global_clients.default_client.get_market_price("BTCUSDT")
            client_info["default_client_test"] = {
                "status": "working",
                "test_price": price
            }
        except Exception as e:
            client_info["default_client_test"] = {
                "status": "error",
                "error": str(e)
            }
    
    return client_info

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
# USER ENDPOINTS - OPTIMIZED WITH SINGLETON CLIENTS
# =================================================================
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
                        if not client.is_public_only:
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
                
                # Bot status
                try:
                    from app.bot_manager import bot_manager
                    bot_status = bot_manager.get_bot_status(user_id)
                    dashboard_data["bot_status"] = bot_status
                except Exception as bot_error:
                    logger.error(f"Bot status error: {bot_error}")
                    dashboard_data["bot_status"] = {
                        "user_id": user_id,
                        "is_running": user_data.get("bot_active", False),
                        "symbol": user_data.get("bot_symbol"),
                        "position_side": None,
                        "status_message": "Bot service unavailable",
                        "account_balance": user_data.get("account_balance", 0.0),
                        "position_pnl": 0.0,
                        "total_trades": user_data.get("total_trades", 0),
                        "total_pnl": user_data.get("total_pnl", 0.0),
                        "last_check_time": user_data.get("last_trade_time")
                    }
            else:
                # Create user data if doesn't exist
                logger.info(f"Creating user data for new user: {user_id}")
                
                trial_expiry = datetime.now(timezone.utc) + timedelta(days=7)
                
                new_user_data = {
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
                user_ref.set(new_user_data)
                logger.info(f"User data created for: {user_id}")
        
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

@app.get("/api/user/positions")
async def get_user_positions(current_user: dict = Depends(get_current_user)):
    """Get user positions - ALWAYS returns array"""
    try:
        user_id = current_user['uid']
        positions = []  # Initialize as empty array
        
        if not global_clients.firebase_initialized or not global_clients.firebase_db:
            return positions  # Return empty array if Firebase unavailable
        
        try:
            user_ref = global_clients.firebase_db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            
            if user_data and user_data.get('api_keys_set'):
                try:
                    # Use optimized singleton client
                    client = await get_binance_client_for_user(user_id)
                    
                    # Only get positions for private clients
                    if not client.is_public_only:
                        # Get all open positions
                        all_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "DOTUSDT"]
                        
                        for symbol in all_symbols:
                            try:
                                symbol_positions = await client.get_open_positions(symbol, use_cache=True)
                                for pos in symbol_positions:
                                    try:
                                        position_amt = float(pos.get('positionAmt', 0))
                                        if position_amt != 0:  # Only include non-zero positions
                                            isolated_wallet = float(pos.get('isolatedWallet', 0))
                                            unrealized_profit = float(pos.get('unRealizedProfit', 0))
                                            
                                            # Safe percentage calculation
                                            percentage = 0.0
                                            if isolated_wallet != 0:
                                                try:
                                                    percentage = (unrealized_profit / isolated_wallet) * 100
                                                except (ZeroDivisionError, TypeError):
                                                    percentage = 0.0
                                            
                                            positions.append({
                                                "symbol": pos.get('symbol', ''),
                                                "positionSide": "LONG" if position_amt > 0 else "SHORT",
                                                "positionAmt": str(abs(position_amt)),
                                                "entryPrice": pos.get('entryPrice', '0'),
                                                "markPrice": pos.get('markPrice', '0'),
                                                "unrealizedPnl": unrealized_profit,
                                                "percentage": percentage,
                                                "leverage": pos.get('leverage', '1'),
                                                "marginType": pos.get('marginType', 'CROSSED')
                                            })
                                    except (ValueError, TypeError, KeyError) as pos_error:
                                        logger.error(f"Error processing position: {pos_error}")
                                        continue  # Skip invalid position data
                            except Exception as symbol_error:
                                logger.error(f"Error getting positions for {symbol}: {symbol_error}")
                                continue
                            
                except Exception as e:
                    logger.error(f"Error getting positions for user {user_id}: {e}")
                    # Return empty array on error
                    
        except Exception as db_error:
            logger.error(f"Database error in positions: {db_error}")
        
        # ALWAYS return array (even if empty)
        return positions
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Positions error: {e}")
        # Return empty array instead of raising exception
        return []

@app.get("/api/user/recent-trades")
async def get_recent_trades(current_user: dict = Depends(get_current_user), limit: int = 10):
    """Get recent trades - ALWAYS returns array"""
    try:
        user_id = current_user['uid']
        trades = []  # Initialize as empty array
        
        if not global_clients.firebase_initialized or not global_clients.firebase_db:
            return trades  # Return empty array if Firebase unavailable
        
        try:
            # Get from Firebase first
            trades_ref = global_clients.firebase_db.reference('trades')
            query = trades_ref.order_by_child('user_id').equal_to(user_id).limit_to_last(limit)
            snapshot = query.get()
            
            if snapshot and isinstance(snapshot, dict):
                for trade_id, trade_data in snapshot.items():
                    try:
                        trades.append({
                            "id": trade_id,
                            "symbol": trade_data.get("symbol", ""),
                            "side": trade_data.get("side", ""),
                            "quantity": float(trade_data.get("quantity", 0)),
                            "price": float(trade_data.get("price", 0)),
                            "quoteQty": float(trade_data.get("quote_qty", 0)),
                            "pnl": float(trade_data.get("pnl", 0)),
                            "status": trade_data.get("status", "UNKNOWN"),
                            "time": trade_data.get("timestamp", 0)
                        })
                    except (ValueError, TypeError, KeyError) as trade_error:
                        logger.error(f"Error processing trade: {trade_error}")
                        continue  # Skip invalid trade data
                        
        except Exception as db_error:
            logger.error(f"Database error in trades: {db_error}")
        
        # If no Firebase data, try Binance (fallback)
        if not trades:
            try:
                user_ref = global_clients.firebase_db.reference(f'users/{user_id}')
                user_data = user_ref.get()
                
                if user_data and user_data.get('api_keys_set'):
                    # Use optimized singleton client
                    client = await get_binance_client_for_user(user_id)
                    
                    # Only get trading history for private clients
                    if not client.is_public_only:
                        # Get recent trades for multiple symbols
                        symbols_to_check = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
                        
                        for symbol in symbols_to_check:
                            try:
                                recent_trades = await client.client.futures_account_trades(symbol=symbol, limit=5)
                                
                                for trade in recent_trades[-5:]:  # Last 5 trades per symbol
                                    try:
                                        trades.append({
                                            "id": str(trade.get('id', '')),
                                            "symbol": trade.get('symbol', ''),
                                            "side": trade.get('side', ''),
                                            "quantity": float(trade.get('qty', 0)),
                                            "price": float(trade.get('price', 0)),
                                            "quoteQty": float(trade.get('quoteQty', 0)),
                                            "pnl": float(trade.get('realizedPnl', 0)),
                                            "status": "FILLED",
                                            "time": trade.get('time', 0)
                                        })
                                    except (ValueError, TypeError, KeyError) as trade_error:
                                        logger.error(f"Error processing Binance trade: {trade_error}")
                                        continue
                                        
                            except Exception as symbol_error:
                                logger.error(f"Error getting trades for {symbol}: {symbol_error}")
                                continue
                            
            except Exception as binance_error:
                logger.error(f"Binance trades fetch failed: {binance_error}")
        
        # Sort by time (most recent first)
        try:
            trades.sort(key=lambda x: x.get("time", 0), reverse=True)
            # Limit to requested number
            trades = trades[:limit]
        except Exception as sort_error:
            logger.error(f"Error sorting trades: {sort_error}")
        
        # ALWAYS return array (even if empty)
        return trades
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Recent trades error: {e}")
        # Return empty array instead of raising exception
        return []

@app.get("/api/user/account")
async def get_account_data(current_user: dict = Depends(get_current_user)):
    """Get account data with optimized client"""
    try:
        user_id = current_user['uid']
        
        # Default values
        account_data = {
            "totalBalance": 0.0,
            "availableBalance": 0.0,
            "unrealizedPnl": 0.0,
            "message": "API keys required"
        }
        
        if not global_clients.firebase_initialized or not global_clients.firebase_db:
            return account_data
        
        try:
            user_ref = global_clients.firebase_db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            
            # If API keys exist, get real Binance data using singleton client
            if user_data and user_data.get('api_keys_set'):
                try:
                    # Use optimized singleton client
                    client = await get_binance_client_for_user(user_id)
                    
                    # Only get account data for private clients
                    if not client.is_public_only:
                        balance = await client.get_account_balance(use_cache=False)
                        
                        account_data = {
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
                        account_data = {
                            "totalBalance": user_data.get("account_balance", 0.0),
                            "availableBalance": user_data.get("account_balance", 0.0),
                            "unrealizedPnl": 0.0,
                            "message": "Public client - cached data"
                        }
                    
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

@app.get("/api/user/profile")
async def get_user_profile(current_user: dict = Depends(get_current_user)):
    """Get user profile with Firebase fallback"""
    try:
        user_id = current_user['uid']
        email = current_user.get('email')
        
        if not global_clients.firebase_initialized or not global_clients.firebase_db:
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
            user_ref = global_clients.firebase_db.reference(f'users/{user_id}')
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

@app.get("/api/user/stats")
async def get_user_stats(current_user: dict = Depends(get_current_user)):
    """Get user stats"""
    try:
        user_id = current_user['uid']
        
        if not global_clients.firebase_initialized or not global_clients.firebase_db:
            return {
                "totalTrades": 0,
                "totalPnl": 0.0,
                "winRate": 0.0,
                "botStartTime": None,
                "lastTradeTime": None
            }
        
        try:
            user_ref = global_clients.firebase_db.reference(f'users/{user_id}')
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
    """Save user API keys with optimized client"""
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
        
        # Test API keys with temporary client
        try:
            test_client = await global_clients.get_binance_client(user_id=None, api_key=api_key, api_secret=api_secret)
            balance = await test_client.get_account_balance(use_cache=False)
            logger.info(f"API test successful for user {user_id}, balance: {balance}")
            
            # Clean up test client
            await test_client.close_connection()
            
        except Exception as e:
            logger.error(f"API test failed: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid API keys: {str(e)}")
        
        if not global_clients.firebase_initialized or not global_clients.firebase_db:
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
            
            api_data = {
                "binance_api_key": encrypted_api_key,
                "binance_api_secret": encrypted_api_secret,
                "api_testnet": testnet,
                "api_keys_set": True,
                "api_updated_at": int(datetime.utcnow().timestamp() * 1000),
                "account_balance": balance
            }
            
            user_ref = global_clients.firebase_db.reference(f'users/{user_id}')
            user_ref.update(api_data)
            
            # Clear existing client for this user to force recreation with new keys
            await global_clients.cleanup_client(user_id)
            
            logger.info(f"API keys saved successfully for user: {user_id}")
            
            return {
                "success": True,
                "message": "API keys saved and tested successfully",
                "balance": balance
            }
            
        except ImportError as import_error:
            logger.error(f"Crypto module import error: {import_error}")
            raise HTTPException(
                status_code=500, 
                detail="Encryption service unavailable. Please contact support."
            )
        except Exception as save_error:
            logger.error(f"API keys save error: {save_error}")
            logger.error(f"Save error traceback: {traceback.format_exc()}")
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to save API keys: {str(save_error)}"
            )
        
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

@app.get("/api/user/api-keys")
async def get_api_keys_status(current_user: dict = Depends(get_current_user)):
    """Get API keys status - same as api-info for compatibility"""
    return await get_api_info(current_user)

# =================================================================
# BOT ENDPOINTS
# =================================================================
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

@app.post("/api/bot/start")
async def start_bot(request: dict, current_user: dict = Depends(get_current_user)):
    """Start bot for user"""
    try:
        user_id = current_user['uid']
        logger.info(f"Bot start request from user: {user_id}")
        
        if not global_clients.firebase_initialized or not global_clients.firebase_db:
            raise HTTPException(status_code=500, detail="Database service unavailable")
        
        # Check subscription
        try:
            user_ref = global_clients.firebase_db.reference(f'users/{user_id}')
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
                user_ref.update({
                    "bot_active": True,
                    "bot_symbol": request.get('symbol', 'BTCUSDT'),
                    "bot_start_time": int(datetime.utcnow().timestamp() * 1000)
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
        if global_clients.firebase_initialized and global_clients.firebase_db:
            try:
                user_ref = global_clients.firebase_db.reference(f'users/{user_id}')
                user_ref.update({
                    "bot_active": False,
                    "bot_stop_time": int(datetime.utcnow().timestamp() * 1000)
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
    """Get supported trading pairs - ALWAYS returns array"""
    try:
        pairs = [
            {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"},
            {"symbol": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT"},
            {"symbol": "BNBUSDT", "baseAsset": "BNB", "quoteAsset": "USDT"},
            {"symbol": "ADAUSDT", "baseAsset": "ADA", "quoteAsset": "USDT"},
            {"symbol": "DOTUSDT", "baseAsset": "DOT", "quoteAsset": "USDT"},
            {"symbol": "LINKUSDT", "baseAsset": "LINK", "quoteAsset": "USDT"},
            {"symbol": "SOLUSDT", "baseAsset": "SOL", "quoteAsset": "USDT"},
            {"symbol": "AVAXUSDT", "baseAsset": "AVAX", "quoteAsset": "USDT"},
            {"symbol": "MATICUSDT", "baseAsset": "MATIC", "quoteAsset": "USDT"},
            {"symbol": "XRPUSDT", "baseAsset": "XRP", "quoteAsset": "USDT"}
        ]
        
        # Try to get live pairs from Binance if possible
        try:
            # Use default client for public data
            default_client = await global_clients.get_binance_client()
            if default_client and default_client.client:
                # Get exchange info for live pairs
                exchange_info = await default_client.client.futures_exchange_info()
                live_pairs = []
                
                for symbol_info in exchange_info.get('symbols', []):
                    if (symbol_info.get('status') == 'TRADING' and 
                        symbol_info.get('quoteAsset') == 'USDT' and
                        symbol_info.get('contractType') == 'PERPETUAL'):
                        
                        live_pairs.append({
                            "symbol": symbol_info.get('symbol'),
                            "baseAsset": symbol_info.get('baseAsset'),
                            "quoteAsset": symbol_info.get('quoteAsset'),
                            "status": symbol_info.get('status')
                        })
                
                # Filter to popular pairs or return all
                popular_symbols = [p["symbol"] for p in pairs]
                filtered_pairs = [p for p in live_pairs if p["symbol"] in popular_symbols]
                
                if filtered_pairs:
                    pairs = filtered_pairs
                    
        except Exception as e:
            logger.error(f"Error getting live trading pairs: {e}")
            # Return default pairs if live data fails
        
        return pairs
        
    except Exception as e:
        logger.error(f"Trading pairs error: {e}")
        # Return default pairs on any error
        return [
            {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"},
            {"symbol": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT"},
            {"symbol": "BNBUSDT", "baseAsset": "BNB", "quoteAsset": "USDT"}
        ]

@app.post("/api/user/close-position")
async def close_position(request: dict, current_user: dict = Depends(get_current_user)):
    """Close position using singleton client"""
    try:
        user_id = current_user['uid']
        symbol = request.get('symbol')
        position_side = request.get('positionSide')
        
        if not symbol or not position_side:
            raise HTTPException(status_code=400, detail="Symbol and position side required")
        
        if not global_clients.firebase_initialized or not global_clients.firebase_db:
            return {
                "success": False,
                "message": "Database service unavailable"
            }
        
        user_ref = global_clients.firebase_db.reference(f'users/{user_id}')
        user_data = user_ref.get()
        
        if not user_data or not user_data.get('api_keys_set'):
            raise HTTPException(status_code=400, detail="API keys required")
        
        # Real position closing using singleton client
        try:
            client = await get_binance_client_for_user(user_id)
            
            # Check if client can perform private operations
            if client.is_public_only:
                raise HTTPException(status_code=400, detail="Private client required for position operations")
            
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
                # Calculate PnL (if available)
                pnl = 0.0
                try:
                    pnl = float(position.get('unRealizedProfit', 0))
                except (ValueError, TypeError):
                    pnl = 0.0
                
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
                    trades_ref = global_clients.firebase_db.reference('trades')
                    trades_ref.push(trade_data)
                except Exception as log_error:
                    logger.error(f"Trade logging error: {log_error}")
                
                # Update user stats
                current_trades = user_data.get('total_trades', 0)
                current_pnl = user_data.get('total_pnl', 0.0)
                
                user_ref.update({
                    'total_trades': current_trades + 1,
                    'total_pnl': current_pnl + pnl,
                    'last_trade_time': int(datetime.utcnow().timestamp() * 1000)
                })
                
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

# =================================================================
# STATIC ROUTES
# =================================================================
@app.get("/")
async def read_root():
    return FileResponse("static/index.html", media_type="text/html")

@app.get("/login")
async def read_login():
    return FileResponse("static/login.html", media_type="text/html")

@app.get("/login.html")
async def read_login_html():
    return FileResponse("static/login.html", media_type="text/html")

@app.get("/register")
async def read_register():
    return FileResponse("static/register.html", media_type="text/html")

@app.get("/register.html")
async def read_register_html():
    return FileResponse("static/register.html", media_type="text/html")

@app.get("/dashboard")
async def read_dashboard():
    return FileResponse("static/dashboard.html", media_type="text/html")

@app.get("/dashboard.html")
async def read_dashboard_html():
    return FileResponse("static/dashboard.html", media_type="text/html")

@app.get("/admin")
async def read_admin():
    return FileResponse("static/admin.html", media_type="text/html")

@app.get("/admin.html")
async def read_admin_html():
    return FileResponse("static/admin.html", media_type="text/html")

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
