import os
import firebase_admin
from firebase_admin import credentials, auth
import json
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

try:
    # Firebase credentials'ı yükle
    firebase_credentials_json = os.environ.get('FIREBASE_CREDENTIALS_JSON')
    if not firebase_credentials_json:
        raise ValueError("FIREBASE_CREDENTIALS_JSON ortam değişkeni bulunamadı")
    
    # JSON string'i temizle
    if firebase_credentials_json.startswith('"') and firebase_credentials_json.endswith('"'):
        firebase_credentials_json = firebase_credentials_json[1:-1]
    
    import codecs
    firebase_credentials_json = codecs.decode(firebase_credentials_json, 'unicode_escape')
    
    # Control karakterleri temizle
    import re
    firebase_credentials_json = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', firebase_credentials_json)
    
    cred_dict = json.loads(firebase_credentials_json)
    
    # Firebase Admin SDK'yı başlat
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        print("✅ Firebase Admin SDK başarıyla başlatıldı.")
    else:
        print("✅ Firebase Admin SDK zaten başlatılmış.")

except Exception as e:
    print(f"❌ Firebase başlatma hatası: {e}")
    exit(1)

# Admin yapmak istediğiniz kullanıcının UID'si
ADMIN_USER_UID = "6bDNl3mDIogu2gOoOAZT9WYzUAh1"

try:
    # Önce kullanıcının mevcut olduğunu kontrol et
    user_record = auth.get_user(ADMIN_USER_UID)
    print(f"👤 Kullanıcı bulundu: {user_record.email}")
    
    # Admin claim'ini ata
    auth.set_custom_user_claims(ADMIN_USER_UID, {'admin': True})
    print(f"✅ Admin claim atandı: {ADMIN_USER_UID}")
    
    # Claim'i doğrula
    updated_user = auth.get_user(ADMIN_USER_UID)
    claims = updated_user.custom_claims or {}
    
    if claims.get('admin'):
        print("✅ Admin claim başarıyla doğrulandı!")
        print("🔄 Kullanıcının çıkış yapıp tekrar giriş yapması gerekiyor")
    else:
        print("❌ Admin claim doğrulanamadı")

except auth.UserNotFoundError:
    print(f"❌ Kullanıcı bulunamadı: {ADMIN_USER_UID}")
    print("Firebase Console'dan doğru UID'yi kontrol edin")
except Exception as e:
    print(f"❌ Admin claim atama hatası: {e}")
