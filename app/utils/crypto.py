from cryptography.fernet import Fernet
import base64
import os
import logging
from app.config import settings

logger = logging.getLogger("crypto")

def get_encryption_key():
    """Şifreleme anahtarını environment'dan al"""
    encryption_key = settings.ENCRYPTION_KEY
    
    if not encryption_key:
        logger.error("ENCRYPTION_KEY environment variable not set")
        # Generate a new key for development
        key = Fernet.generate_key()
        logger.warning(f"Generated new encryption key: {key.decode()}")
        logger.warning("Please set this key in your environment variables!")
        return key
    
    try:
        # If it's already bytes, return as is
        if isinstance(encryption_key, bytes):
            return encryption_key
        
        # If it's a string, try to decode
        if isinstance(encryption_key, str):
            # Remove quotes if present
            if encryption_key.startswith('"') and encryption_key.endswith('"'):
                encryption_key = encryption_key[1:-1]
            
            # Try direct encoding first
            try:
                test_key = encryption_key.encode()
                Fernet(test_key)  # Test if valid
                return test_key
            except:
                pass
            
            # Try base64 decode
            try:
                decoded = base64.urlsafe_b64decode(encryption_key)
                Fernet(decoded)  # Test if valid
                return decoded
            except:
                pass
            
            # If all fails, generate new key
            logger.error("Invalid encryption key format, generating new one")
            key = Fernet.generate_key()
            logger.warning(f"Generated new encryption key: {key.decode()}")
            return key
        
        # Fallback: generate new key
        key = Fernet.generate_key()
        logger.warning(f"Generated new encryption key: {key.decode()}")
        return key
        
    except Exception as e:
        logger.error(f"Encryption key error: {e}")
        # Generate new key as fallback
        key = Fernet.generate_key()
        logger.warning(f"Generated new encryption key: {key.decode()}")
        return key

def encrypt_data(data: str) -> str:
    """Verilen metni şifreler"""
    if not data:
        return ""
    
    try:
        key = get_encryption_key()
        cipher_suite = Fernet(key)
        encrypted_text = cipher_suite.encrypt(data.encode('utf-8'))
        return encrypted_text.decode('utf-8')
    except Exception as e:
        logger.error(f"Encryption error: {e}")
        raise Exception(f"Şifreleme hatası: {e}")

def decrypt_data(encrypted_data: str) -> str:
    """Şifrelenmiş metni çözer"""
    if not encrypted_data:
        return ""
    
    try:
        key = get_encryption_key()
        cipher_suite = Fernet(key)
        decrypted_text = cipher_suite.decrypt(encrypted_data.encode('utf-8'))
        return decrypted_text.decode('utf-8')
    except Exception as e:
        logger.error(f"Decryption error: {e}")
        return ""
