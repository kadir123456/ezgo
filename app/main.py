from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime, timezone
from app.config import settings
from app.utils.metrics import metrics, get_metrics_data, get_metrics_content_type
import logging
import time

# Setup basic logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("main")

# FastAPI uygulama başlatma
app = FastAPI(
    title="EzyagoTrading API",
    description="Professional Crypto Futures Trading Bot",
    version="1.0.0",
    debug=settings.DEBUG
)

# CORS middleware ekle
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

# Static files mount
app.mount("/static", StaticFiles(directory="static"), name="static")

# Import routes
try:
    from app.routes.auth import router as auth_router
    from app.routes.bot import router as bot_router
    from app.routes.user import router as user_router
    
    # Include routers
    app.include_router(auth_router)
    app.include_router(bot_router)
    app.include_router(user_router)
    
    logger.info("All routes loaded successfully")
except Exception as e:
    logger.error(f"Error loading routes: {e}")

@app.on_event("startup")
async def startup_event():
    """Uygulama başlatma"""
    logger.info("EzyagoTrading starting up...")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    logger.info(f"Maintenance mode: {settings.MAINTENANCE_MODE}")
    
    # Firebase bağlantısını kontrol et
    try:
        from app.firebase_manager import firebase_manager
        if firebase_manager.is_initialized():
            logger.info("Firebase connection verified")
        else:
            logger.error("Firebase connection failed - check FIREBASE_CREDENTIALS_JSON")
            logger.error("Make sure Firebase credentials are properly formatted in environment")
    except Exception as e:
        logger.error(f"Firebase initialization error: {e}")
        logger.error("Check FIREBASE_CREDENTIALS_JSON format and content")
    
    # Ayarları doğrula
    try:
        is_valid = settings.validate_settings()
        if not is_valid:
            logger.warning("Some configuration issues detected")
        else:
            logger.info("All settings validated successfully")
    except Exception as e:
        logger.error(f"Settings validation error: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Uygulama kapatma"""
    logger.info("EzyagoTrading shutting down...")
    
    # Tüm aktif botları güvenli şekilde durdur
    try:
        from app.bot_manager import bot_manager
        await bot_manager.shutdown_all_bots()
        logger.info("All bots shutdown completed")
    except Exception as e:
        logger.error(f"Error during bot shutdown: {e}")

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        from app.firebase_manager import firebase_manager
        firebase_status = firebase_manager.is_initialized()
        
        return {
            "status": "healthy" if firebase_status else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "environment": settings.ENVIRONMENT,
            "version": "1.0.0",
            "maintenance_mode": settings.MAINTENANCE_MODE,
            "demo_mode": settings.DEMO_MODE_ENABLED,
            "firebase_connected": firebase_status
        }
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

# HEAD method support for health check
@app.head("/")
async def head_root():
    """HEAD method support for root endpoint"""
    return JSONResponse(content={})

@app.head("/health")
async def head_health():
    """HEAD method support for health endpoint"""
    return JSONResponse(content={})

# Firebase config endpoint for frontend
@app.get("/api/firebase-config")
async def get_firebase_config():
    """Frontend için Firebase konfigürasyonu"""
    try:
        logger.info("Firebase config requested from frontend")
        
        # Directly return Firebase Web config from environment
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
        
        logger.info(f"Firebase config provided for project: {firebase_config['projectId']}")
        return firebase_config
        
    except Exception as e:
        logger.error(f"Firebase config error: {e}")
        raise HTTPException(status_code=500, detail=f"Firebase configuration error: {str(e)}")

# App info endpoint
@app.get("/api/app-info")
async def get_app_info():
    """Uygulama bilgileri"""
    return {
        "bot_price": settings.BOT_PRICE_USD,
        "monthly_price": settings.BOT_PRICE_USD,  # Use BOT_PRICE_USD for consistency
        "trial_days": settings.TRIAL_PERIOD_DAYS,
        "demo_mode": settings.DEMO_MODE_ENABLED,
        "maintenance_mode": settings.MAINTENANCE_MODE,
        "payment_address": settings.PAYMENT_TRC20_ADDRESS,
        "server_ips": settings.SERVER_IPS.split(',') if settings.SERVER_IPS else [],
        "max_bots_per_user": settings.MAX_BOTS_PER_USER,
        "supported_timeframes": ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
        "leverage_range": {"min": settings.MIN_LEVERAGE, "max": settings.MAX_LEVERAGE},
        "order_size_range": {"min": settings.MIN_ORDER_SIZE_USDT, "max": settings.MAX_ORDER_SIZE_USDT}
    }

# Metrics endpoint
@app.get("/metrics")
async def get_metrics():
    """Prometheus metrics endpoint"""
    try:
        metrics_data = get_metrics_data()
        return PlainTextResponse(content=metrics_data, media_type=get_metrics_content_type())
    except Exception as e:
        logger.error(f"Metrics error: {e}")
        return PlainTextResponse("# Metrics not available")

# Static file routes
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
# Catch-all route for SPA
@app.get("/{full_path:path}")
async def catch_all(full_path: str):
    """Catch-all route for SPA routing"""
    # Check if it's a static file request or known HTML file
    if (full_path.startswith("static/") or 
        full_path.endswith(".html") or
        full_path in ["dashboard", "login", "register", "admin"]):
        raise HTTPException(status_code=404, detail="File not found")
    
    # For other paths, serve index.html (SPA routing)
    return FileResponse("static/index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower()
    )
