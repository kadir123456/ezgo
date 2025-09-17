import firebase_admin
from firebase_admin import credentials, db, auth
import os
import json
from datetime import datetime
from .utils.logger import get_logger

logger = get_logger("firebase_manager")

class FirebaseManager:
    def __init__(self):
        self.db_ref = None
        self.db = None
        try:
            if not firebase_admin._apps:
                cred_json_str = os.getenv("FIREBASE_CREDENTIALS_JSON")
                database_url = os.getenv("FIREBASE_DATABASE_URL")
                if cred_json_str and database_url:
                    cred_dict = json.loads(cred_json_str)
                    cred = credentials.Certificate(cred_dict)
                    firebase_admin.initialize_app(cred, {'databaseURL': database_url})
                    logger.info("Firebase Admin SDK initialized successfully")
                else:
                    logger.warning("Firebase credentials not found")
            if firebase_admin._apps:
                self.db_ref = db.reference('trades')
                self.db = db
        except Exception as e:
            logger.error(f"Firebase initialization error: {e}")

    def log_trade(self, trade_data: dict):
        """Trade verilerini Firebase'e kaydet"""
        if not self.db_ref:
            logger.warning("Database connection not available")
            return
        try:
            if 'timestamp' in trade_data and isinstance(trade_data['timestamp'], datetime):
                trade_data['timestamp'] = trade_data['timestamp'].isoformat()
            self.db_ref.push(trade_data)
            logger.info(f"Trade logged for user {trade_data.get('user_id', 'unknown')}")
        except Exception as e:
            logger.error(f"Trade logging error: {e}")

    def get_user_data(self, user_id: str) -> dict:
        """Kullanıcı verilerini Firebase'den al"""
        try:
            if not self.db:
                logger.warning("Database not available")
                return None
            
            user_ref = self.db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            
            return user_data
            
        except Exception as e:
            logger.error(f"Error getting user data for {user_id}: {e}")
            return None

    def update_user_data(self, user_id: str, data: dict):
        """Kullanıcı verilerini güncelle"""
        try:
            if not self.db:
                logger.warning("Database not available")
                return False
            
            user_ref = self.db.reference(f'users/{user_id}')
            user_ref.update(data)
            
            logger.info(f"User data updated for {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating user data for {user_id}: {e}")
            return False

    def verify_token(self, token: str):
        """Firebase token doğrula"""
        try:
            if not firebase_admin._apps: return None
            return auth.verify_id_token(token)
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            return None

firebase_manager = FirebaseManager()
