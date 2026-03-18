import os, psycopg2, json
from minio import Minio
from io import BytesIO

# Docker ayarları
DB_PARAMS = "dbname='interpol_db' user='interpol' password='interpol123' host='postgres'"
MINIO_CLIENT = Minio("minio:9000", access_key="minioadmin", secret_key="minioadmin", secure=False)
BUCKET = "interpol-photos"
LOCAL_DIR = "/app/temp_photos"
BASE_URL = "http://localhost:9000/interpol-photos"

def migrate():
    conn = psycopg2.connect(DB_PARAMS)
    cur = conn.cursor()
    
    # Klasördeki tüm .jpg dosyalarını al
    files = [f for f in os.listdir(LOCAL_DIR) if f.lower().endswith('.jpg')]
    print(f"📦 Toplam {len(files)} yerel fotoğraf bulundu. İşlem başlıyor...")

    # Dosyaları entity_id bazlı grupla (Galeri desteği için)
    grouped = {}
    for f in files:
        parts = f.split('_')
        if len(parts) >= 2:
            # Örn: 2015_80325.jpg -> 2015/80325
            eid = f"{parts[0]}/{parts[1].split('.')[0]}"
            if eid not in grouped: grouped[eid] = []
            grouped[eid].append(f)

    for eid, photos in grouped.items():
        try:
            photo_urls = []
            photos.sort() # Ana resim (sonsuz olmayan) başa gelsin

            for p in photos:
                file_path = os.path.join(LOCAL_DIR, p)
                with open(file_path, "rb") as f_data:
                    content = f_data.read()
                    # MinIO'ya yükle
                    MINIO_CLIENT.put_object(BUCKET, p, BytesIO(content), len(content), content_type="image/jpeg")
                    photo_urls.append(f"{BASE_URL}/{p}")
            
            # Veritabanını güncelle
            cur.execute(
                "UPDATE notices SET photo_url = %s, image_urls = %s WHERE entity_id = %s",
                (photo_urls[0], json.dumps(photo_urls), eid)
            )
            print(f" Başarıyla taşındı: {eid}")
        except Exception as e:
            print(f" Hata ({eid}): {e}")

    conn.commit()
    cur.close()
    conn.close()
    print("\n🏁 YEREL TAŞIMA TAMAMLANDI! Siteni kontrol edebilirsin.")

if __name__ == "__main__":
    migrate()