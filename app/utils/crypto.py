from cryptography.fernet import Fernet
import base64
import os
import logging

logger = logging.getLogger("crypto")

def get_encryption_key():
    """Şifreleme anahtarını environment'dan al"""
    encryption_key = os.getenv("ENCRYPTION_KEY")
    
    if not encryption_key:
        raise ValueError("ENCRYPTION_KEY environment variable not set")
    
    # Base64 decode if needed
    try:
        if encryption_key.startswith('"') and encryption_key.endswith('"'):
            encryption_key = encryption_key[1:-1]  # Remove quotes
        
        # Test if it's a valid Fernet key
        Fernet(encryption_key.encode())
        return encryption_key.encode()
    except Exception:
        # If not valid, try to decode from base64
        try:
            decoded = base64.urlsafe_b64decode(encryption_key)
            return decoded
        except Exception as e:
            raise ValueError(f"Invalid encryption key format: {e}")

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
