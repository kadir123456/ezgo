from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime, timezone
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger("main")

# FastAPI uygulama başlatma - environment'a göre
app = FastAPI(
    title="EzyagoTrading API",
    description="Professional Crypto Futures Trading Bot",
    version="1.0.0",
    debug=settings.DEBUG
)

# CORS middleware ekle
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else ["https://www.ezyago.com", "https://ezyago.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files mount
app.mount("/static", StaticFiles(directory="static"), name="static")

# Import routes
from app.routes.auth import router as auth_router
from app.routes.bot import router as bot_router
from app.routes.user import router as user_router

# Include routers
app.include_router(auth_router)
app.include_router(bot_router)
app.include_router(user_router)

@app.on_event("startup")
async def startup_event():
    """Uygulama başlatma"""
    logger.info("EzyagoTrading starting up...")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    logger.info(f"Maintenance mode: {settings.MAINTENANCE_MODE}")
    
    # Ayarları doğrula
    if not settings.validate_settings():
        logger.warning("Some configuration issues detected")
    
    settings.print_settings()

# Maintenance mode middleware
@app.middleware("http")
async def maintenance_middleware(request, call_next):
    if settings.MAINTENANCE_MODE and not request.url.path.startswith("/health"):
        return JSONResponse(
            status_code=503,
            content={"error": "Maintenance mode", "message": settings.MAINTENANCE_MESSAGE}
        )
    return await call_next(request)

# Health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": settings.ENVIRONMENT,
        "version": "1.0.0",
        "maintenance_mode": settings.MAINTENANCE_MODE,
        "demo_mode": settings.DEMO_MODE_ENABLED
    }

# Firebase config endpoint for frontend
@app.get("/api/firebase-config")
async def get_firebase_config():
    """Frontend için Firebase konfigürasyonu"""
    try:
        firebase_web_config = settings.get_firebase_web_config()
        
        # Eksik alanları kontrol et
        missing_fields = [k for k, v in firebase_web_config.items() if not v]
        if missing_fields:
            logger.warning(f"Missing Firebase config fields: {missing_fields}")
            raise HTTPException(status_code=500, detail=f"Missing Firebase config: {missing_fields}")
        
        return firebase_web_config
    except Exception as e:
        logger.error(f"Firebase config error: {e}")
        raise HTTPException(status_code=500, detail="Firebase configuration error")

# App info endpoint
@app.get("/api/app-info")
async def get_app_info():
    """Uygulama bilgileri"""
    return {
        "bot_price": settings.BOT_PRICE_USD,
        "trial_days": settings.TRIAL_PERIOD_DAYS,
        "monthly_price": settings.MONTHLY_SUBSCRIPTION_PRICE,
        "demo_mode": settings.DEMO_MODE_ENABLED,
        "maintenance_mode": settings.MAINTENANCE_MODE,
        "payment_address": settings.PAYMENT_TRC20_ADDRESS,
        "max_bots_per_user": settings.MAX_BOTS_PER_USER,
        "supported_timeframes": ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
        "leverage_range": {"min": settings.MIN_LEVERAGE, "max": settings.MAX_LEVERAGE},
        "order_size_range": {"min": settings.MIN_ORDER_SIZE_USDT, "max": settings.MAX_ORDER_SIZE_USDT}
    }

# Static file routes
from fastapi.responses import FileResponse

@app.get("/")
async def read_root():
    return FileResponse("static/index.html")

@app.get("/login")
async def read_login():
    return FileResponse("static/login.html")

@app.get("/register")
async def read_register():
    return FileResponse("static/register.html")

@app.get("/dashboard")
async def read_dashboard():
    return FileResponse("static/dashboard.html")

@app.get("/admin")
async def read_admin():
    return FileResponse("static/admin.html")

# Metrics endpoint
@app.get("/metrics")
async def get_metrics():
    """Prometheus metrics endpoint"""
    try:
        from app.utils.metrics import get_metrics_data, get_metrics_content_type
        metrics_data = get_metrics_data()
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=metrics_data, media_type=get_metrics_content_type())
    except Exception as e:
        logger.error(f"Metrics error: {e}")
        return PlainTextResponse("# Metrics not available")

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower()
    )
