from fastapi import APIRouter, HTTPException
from app.config import settings

router = APIRouter(prefix="/api", tags=["config"])

@router.get("/firebase-config")
async def get_firebase_config():
    """
    Frontend'in kullanacağı Firebase config değerlerini döner
    """
    try:
        firebase_config = {
            "apiKey": settings.FIREBASE_WEB_API_KEY,
            "authDomain": settings.FIREBASE_WEB_AUTH_DOMAIN,
            "projectId": settings.FIREBASE_WEB_PROJECT_ID,
            "appId": settings.FIREBASE_WEB_APP_ID,
        }

        # Eğer herhangi bir değer boşsa hata verdiriyoruz
        if not all(firebase_config.values()):
            raise Exception("Eksik Firebase config ayarı")

        return firebase_config
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Firebase config alınamadı: {str(e)}")

@router.get("/app-info")
async def get_app_info():
    """
    Uygulama genel bilgilerini döner (ödeme, trial vs.)
    """
    try:
        app_info = {
            "payment_address": settings.PAYMENT_TRC20_ADDRESS,
            "bot_price": settings.BOT_PRICE_USD,
            "trial_days": settings.TRIAL_PERIOD_DAYS,
            "demo_mode": settings.DEMO_MODE_ENABLED,
            "maintenance_mode": settings.MAINTENANCE_MODE,
        }
        return app_info
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"App info alınamadı: {str(e)}")
