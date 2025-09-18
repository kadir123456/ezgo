import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging

logger = logging.getLogger(__name__)

def get_encryption_key():
    """Get or generate encryption key from environment"""
    encryption_key = os.getenv("ENCRYPTION_KEY")
    
    if not encryption_key:
        logger.error("ENCRYPTION_KEY environment variable not set")
        raise ValueError("ENCRYPTION_KEY environment variable is required")
    
    # Convert to bytes if string
    if isinstance(encryption_key, str):
        encryption_key = encryption_key.encode()
    
    # Generate Fernet key from password
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'ezyago_trading_salt_2024',  # Fixed salt for consistency
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(encryption_key))
    return Fernet(key)

def encrypt_data(data: str) -> str:
    """Encrypt string data"""
    try:
        if not data:
            return ""
        
        fernet = get_encryption_key()
        encrypted = fernet.encrypt(data.encode())
        return base64.urlsafe_b64encode(encrypted).decode()
        
    except Exception as e:
        logger.error(f"Encryption error: {e}")
        raise ValueError("Encryption failed")

def decrypt_data(encrypted_data: str) -> str:
    """Decrypt string data"""
    try:
        if not encrypted_data:
            return ""
        
        fernet = get_encryption_key()
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
        decrypted = fernet.decrypt(encrypted_bytes)
        return decrypted.decode()
        
    except Exception as e:
        logger.error(f"Decryption error: {e}")
        raise ValueError("Decryption failed")

def test_encryption():
    """Test encryption/decryption functionality"""
    try:
        test_data = "test_api_key_12345"
        encrypted = encrypt_data(test_data)
        decrypted = decrypt_data(encrypted)
        
        if test_data == decrypted:
            logger.info("Encryption test passed")
            return True
        else:
            logger.error("Encryption test failed - data mismatch")
            return False
            
    except Exception as e:
        logger.error(f"Encryption test failed: {e}")
        return False
