import firebase_admin
from firebase_admin import credentials, db, auth
import os
import json
from datetime import datetime
import logging

logger = logging.getLogger("firebase_manager")

class FirebaseManager:
    def __init__(self):
        self.db_ref = None
        self.db = None
        self.initialized = False
        self._initialize()
        
    def _initialize(self):
        """Firebase'i başlat"""
        try:
            if not firebase_admin._apps:
                cred_json_str = os.getenv("FIREBASE_CREDENTIALS_JSON")
                database_url = os.getenv("FIREBASE_DATABASE_URL")
                
                if not cred_json_str or not database_url:
                    logger.error("Firebase credentials not found in environment")
                    return
                
                # JSON string'i temizle ve normalize et
                if cred_json_str.startswith('"') and cred_json_str.endswith('"'):
                    cred_json_str = cred_json_str[1:-1]  # Remove outer quotes
                
                # Escape karakterleri düzelt - daha güvenli yöntem
                import codecs
                cred_json_str = codecs.decode(cred_json_str, 'unicode_escape')
                
                # Control karakterleri temizle
                import re
                # Sadece problematik control karakterleri temizle, \n ve \t koru
                cred_json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', cred_json_str)
                
                cred_dict = json.loads(cred_json_str)
                cred = credentials.Certificate(cred_dict)
                
                firebase_admin.initialize_app(cred, {
                    'databaseURL': database_url
                })
                
                logger.info("Firebase Admin SDK initialized successfully")
                
            if firebase_admin._apps:
                self.db = db
                self.db_ref = db.reference()
                self.initialized = True
                logger.info("Firebase database reference created")
                
        except Exception as e:
            logger.error(f"Firebase initialization error: {e}")
            self.initialized = False

    def is_initialized(self) -> bool:
        """Firebase başlatılmış mı kontrol et"""
        return self.initialized

    def get_server_timestamp(self):
        """Firebase server timestamp döndür"""
        if self.db:
            return self.db.reference().server_timestamp
        return datetime.now().isoformat()

    def log_trade(self, trade_data: dict):
        """Trade verilerini Firebase'e kaydet"""
        if not self.is_initialized():
            logger.warning("Firebase not initialized, cannot log trade")
            return False
            
        try:
            if 'timestamp' in trade_data and isinstance(trade_data['timestamp'], datetime):
                trade_data['timestamp'] = trade_data['timestamp'].isoformat()
                
            trades_ref = self.db.reference('trades')
            trades_ref.push(trade_data)
            logger.info(f"Trade logged for user {trade_data.get('user_id', 'unknown')}")
            return True
            
        except Exception as e:
            logger.error(f"Trade logging error: {e}")
            return False

    def get_user_data(self, user_id: str) -> dict:
        """Kullanıcı verilerini Firebase'den al"""
        if not self.is_initialized():
            logger.warning("Firebase not initialized")
            return None
            
        try:
            user_ref = self.db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            return user_data
            
        except Exception as e:
            logger.error(f"Error getting user data for {user_id}: {e}")
            return None

    def update_user_data(self, user_id: str, data: dict) -> bool:
        """Kullanıcı verilerini güncelle"""
        if not self.is_initialized():
            logger.warning("Firebase not initialized")
            return False
            
        try:
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
            if not firebase_admin._apps:
                return None
            return auth.verify_id_token(token)
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            return None

    def get_all_users(self) -> dict:
        """Tüm kullanıcıları getir (admin için)"""
        if not self.is_initialized():
            return {}
            
        try:
            users_ref = self.db.reference('users')
            return users_ref.get() or {}
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return {}

    def get_payment_notifications(self) -> dict:
        """Ödeme bildirimlerini getir (admin için)"""
        if not self.is_initialized():
            return {}
            
        try:
            payments_ref = self.db.reference('payment_notifications')
            return payments_ref.get() or {}
        except Exception as e:
            logger.error(f"Error getting payment notifications: {e}")
            return {}

# Global firebase manager instance
firebase_manager = FirebaseManager()
