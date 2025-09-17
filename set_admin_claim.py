import os
import firebase_admin
from firebase_admin import credentials, auth
import json
from dotenv import load_dotenv # python-dotenv kütüphanesi kurulu olmalı

# .env dosyasını yükle
# Bu, FIREBASE_CREDENTIALS_JSON ortam değişkeninin .env dosyasından okunmasını sağlar.
load_dotenv()

try:
    # Ortam değişkeninizden Firebase kimlik bilgilerini yükleyin
    firebase_credentials_json = os.environ.get('FIREBASE_CREDENTIALS_JSON')
    if not firebase_credentials_json:
        raise ValueError("FIREBASE_CREDENTIALS_JSON ortam değişkeni bulunamadı. Lütfen .env dosyanızı veya ortam değişkenlerinizi kontrol edin.")
    
    cred_dict = json.loads(firebase_credentials_json)
    
    # Firebase Admin SDK'yı başlat
    # Uygulama zaten başlatılmışsa hata vermemesi için kontrol eklenmiştir.
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        print("Firebase Admin SDK başarıyla başlatıldı.")
    else:
        print("Firebase Admin SDK zaten başlatılmış.")

except ValueError as e:
    print(f"Hata: Firebase kimlik bilgileri yüklenemedi. {e}")
    exit(1)
except Exception as e:
    print(f"Genel hata (Firebase başlatma): {e}")
    exit(1)

# Admin yapmak istediğiniz kullanıcının Firebase Authentication UID'si
# Bu UID'yi Firebase Console -> Authentication bölümünden almalısınız.
# Sizin sağladığınız UID'yi buraya ekledim.
ADMIN_USER_UID = "6bDNl3mDIogu2gOoOAZT9WYzUAh1" 

try:
    # Bu UID'ye 'admin: True' custom claim'ini ata
    auth.set_custom_user_claims(ADMIN_USER_UID, {'admin': True})
    print(f"✅ Admin claim set for UID: {ADMIN_USER_UID}")
    print("🔄 User needs to logout and login again for admin access")
    
    # Verify the claim was set
    user_record = auth.get_user(ADMIN_USER_UID)
    claims = user_record.custom_claims or {}
    if claims.get('admin'):
        print("✅ Admin claim verified successfully")
    else:
        print("❌ Admin claim verification failed")

except Exception as e:
    print(f"Hata: Admin yetkisi atanırken bir sorun oluştu: {e}")
    print("Lütfen UID'nin geçerli olduğundan ve Firebase Admin SDK'nın doğru başlatıldığından emin olun.")
