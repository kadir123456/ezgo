import firebase_admin
from firebase_admin import credentials, db, auth
import os
import json
from datetime import datetime
import logging
import re

logger = logging.getLogger("firebase_manager")

class FirebaseManager:
    def __init__(self):
        self.db_ref = None
        self.db = None
        self.initialized = False
        self._initialize()
        
    def _initialize(self):
        """Initialize Firebase Admin SDK"""
        try:
            if not firebase_admin._apps:
                cred_json_str = os.getenv("FIREBASE_CREDENTIALS_JSON")
                database_url = os.getenv("FIREBASE_DATABASE_URL")
                
                if not cred_json_str or not database_url:
                    logger.error("Firebase credentials not found in environment")
                    return
                
                # Clean and parse JSON string for production
                try:
                    # Remove outer quotes if present
                    if cred_json_str.startswith('"') and cred_json_str.endswith('"'):
                        cred_json_str = cred_json_str[1:-1]
                    
                    # Handle escaped characters
                    import codecs
                    try:
                        cred_json_str = codecs.decode(cred_json_str, 'unicode_escape')
                    except Exception as decode_error:
                        logger.warning(f"Unicode decode failed: {decode_error}")
                    
                    # Remove control characters but keep newlines in private key
                    # Only remove problematic control characters, not \n in private key
                    cred_json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', cred_json_str)
                    
                    # Parse JSON
                    cred_dict = json.loads(cred_json_str)
                    
                    # Validate required fields
                    required_fields = ['type', 'project_id', 'private_key', 'client_email']
                    missing_fields = [field for field in required_fields if field not in cred_dict]
                    
                    if missing_fields:
                        raise ValueError(f"Missing required Firebase fields: {missing_fields}")
                    
                    # Create credentials
                    cred = credentials.Certificate(cred_dict)
                    
                    # Initialize Firebase
                    firebase_admin.initialize_app(cred, {
                        'databaseURL': database_url
                    })
                    
                    logger.info("Firebase Admin SDK initialized successfully")
                    
                except json.JSONDecodeError as json_error:
                    logger.error(f"Firebase credentials JSON parse error: {json_error}")
                    logger.error(f"JSON string length: {len(cred_json_str)}")
                    logger.error(f"First 100 chars: {cred_json_str[:100]}")
                    return
                except Exception as parse_error:
                    logger.error(f"Firebase credentials parse error: {parse_error}")
                    return
                
            # Set up database reference
            if firebase_admin._apps:
                self.db = db
                self.db_ref = db.reference()
                self.initialized = True
                logger.info("Firebase database reference created successfully")
                
                # Test database connection
                try:
                    test_ref = self.db.reference('test')
                    test_ref.set({'timestamp': datetime.now().isoformat()})
                    logger.info("Firebase database connection test successful")
                except Exception as test_error:
                    logger.warning(f"Firebase database test failed: {test_error}")
                
        except Exception as e:
            logger.error(f"Firebase initialization error: {e}")
            self.initialized = False

    def is_initialized(self) -> bool:
        """Check if Firebase is initialized"""
        return self.initialized and self.db is not None

    def get_server_timestamp(self):
        """Get Firebase server timestamp"""
        if self.db:
            return self.db.reference().server_timestamp
        return datetime.now().isoformat()

    def log_trade(self, trade_data: dict):
        """Log trade data to Firebase"""
        if not self.is_initialized():
            logger.warning("Firebase not initialized, cannot log trade")
            return False
            
        try:
            if 'timestamp' in trade_data and isinstance(trade_data['timestamp'], datetime):
                trade_data['timestamp'] = trade_data['timestamp'].isoformat()
                
            trades_ref = self.db.reference('trades')
            new_trade_ref = trades_ref.push(trade_data)
            logger.info(f"Trade logged with ID: {new_trade_ref.key}")
            return True
            
        except Exception as e:
            logger.error(f"Trade logging error: {e}")
            return False

    def get_user_data(self, user_id: str) -> dict:
        """Get user data from Firebase"""
        if not self.is_initialized():
            logger.warning("Firebase not initialized")
            return None
            
        try:
            user_ref = self.db.reference(f'users/{user_id}')
            user_data = user_ref.get()
            
            if user_data:
                logger.info(f"User data retrieved for: {user_id}")
            else:
                logger.info(f"No user data found for: {user_id}")
                
            return user_data
            
        except Exception as e:
            logger.error(f"Error getting user data for {user_id}: {e}")
            return None

    def update_user_data(self, user_id: str, data: dict) -> bool:
        """Update user data in Firebase"""
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

    def create_user_data(self, user_id: str, data: dict) -> bool:
        """Create new user data in Firebase"""
        if not self.is_initialized():
            logger.warning("Firebase not initialized")
            return False
            
        try:
            user_ref = self.db.reference(f'users/{user_id}')
            user_ref.set(data)
            logger.info(f"User data created for {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating user data for {user_id}: {e}")
            return False

    def verify_token(self, token: str):
        """Verify Firebase token"""
        try:
            if not firebase_admin._apps:
                logger.error("Firebase not initialized for token verification")
                return None
                
            decoded_token = auth.verify_id_token(token)
            logger.info(f"Token verified for user: {decoded_token['uid']}")
            return decoded_token
            
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            return None

    def get_all_users(self) -> dict:
        """Get all users (admin only)"""
        if not self.is_initialized():
            return {}
            
        try:
            users_ref = self.db.reference('users')
            users_data = users_ref.get()
            return users_data or {}
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return {}

    def get_payment_notifications(self) -> dict:
        """Get payment notifications (admin only)"""
        if not self.is_initialized():
            return {}
            
        try:
            payments_ref = self.db.reference('payment_notifications')
            payments_data = payments_ref.get()
            return payments_data or {}
        except Exception as e:
            logger.error(f"Error getting payment notifications: {e}")
            return {}

# Global firebase manager instance
firebase_manager = FirebaseManager()
