# Interpol Red Notice Watcher

Bu proje, Interpol'ün herkese açık Red Notice API'sini düzenli aralıklarla tarayan, bulunan kayıtları RabbitMQ üzerinden asenkron biçimde işleyen, verileri veritabanında saklayan ve web arayüzünde canlı olarak gösteren bir izleme sistemidir.

Sistem tek parça bir CRUD uygulaması değildir. Asıl amaç, büyük hacimli taramayı web katmanından ayırmak, gelen kayıtları güvenli şekilde kuyruklamak, değişiklikleri alarm mantığıyla işaretlemek ve her notice için zaman içinde zenginleşen bir profil oluşturmaktır.

## İçindekiler

- [Ne İşe Yarar](#ne-işe-yarar)
- [Öne Çıkan Özellikler](#öne-çıkan-özellikler)
- [Mimari](#mimari)
- [Veri Akışı](#veri-akışı)
- [Bileşenler](#bileşenler)
- [Dizin Yapısı](#dizin-yapısı)
- [Kurulum Gereksinimleri](#kurulum-gereksinimleri)
- [Hızlı Başlangıç](#hızlı-başlangıç)
- [Servislere Erişim](#servislere-erişim)
- [Konfigürasyon Mantığı](#konfigürasyon-mantığı)
- [Çevre Değişkenleri](#çevre-değişkenleri)
- [Çalışma Modları](#çalışma-modları)
- [Veritabanı Modeli](#veritabanı-modeli)
- [Web Arayüzü ve HTTP Uçları](#web-arayüzü-ve-http-uçları)
- [Fotoğraf Depolama Stratejisi](#fotoğraf-depolama-stratejisi)
- [Operasyon Rehberi](#operasyon-rehberi)
- [Yerel Geliştirme](#yerel-geliştirme)
- [Testler](#testler)
- [Bilinen Sınırlamalar ve Teknik Notlar](#bilinen-sınırlamalar-ve-teknik-notlar)

## Ne İşe Yarar

Sistem şu problemi çözer:

- Interpol Red Notice verisini periyodik olarak toplar.
- Büyük taramayı küçük ve tekrar edilebilir sorgu kombinasyonlarına böler.
- Aynı kişiyi tekrar görürse değişiklik tespiti yapar.
- Değişiklikleri alarm olarak işaretler.
- Kayıt detaylarını sonradan arka planda tamamlar.
- Fotoğrafları yerel disk veya MinIO üzerinde saklar.
- Sonuçları arama, filtreleme, sıralama ve detay modalı olan bir web arayüzünde gösterir.

Kısacası bu repo, "Interpol notices toplansın, farklar kaçmasın, operatör de tek ekrandan takip etsin" ihtiyacına yönelik hazırlanmış bir izleme hattıdır.

## Öne Çıkan Özellikler

- Tam tarama, genişletilmiş tarama ve hafif tarama olmak üzere üç farklı fetch davranışı vardır.
- Tarama ilerlemesi `scan_state.json` içinde tutulur; fetcher yeniden başlarsa kaldığı yerden devam eder.
- Fetcher ile veri yazımı birbirinden RabbitMQ ile ayrılmıştır; API gecikmesi web katmanını bloke etmez.
- Aynı `entity_id` için alan değişikliği tespit edilirse kayıt `is_updated=True` olur ve alarm sayılır.
- Alan değişiklikleri ayrıca `notice_changes` tablosunda geçmiş olarak tutulur.
- Web tarafı detayları sonradan backfill eder; ilk gelen özet payload kaybolmaz.
- Arayüz canlı güncelleme için SSE kullanır, SSE olmazsa polling'e düşer.
- Kapak fotoğrafı ve galeri fotoğrafları MinIO'ya taşınabilir; MinIO yoksa yerel dosya fallback'i vardır.
- Alarm penceresi zaman bazlıdır; eskiyen alarmlar süpürülür.

## Mimari

Proje Docker Compose ile beş servis ayağa kaldırır:

```text
Interpol Public API
        |
        v
+-------------------+
|      fetcher      |
| python -m ...     |
| full/extended scan|
+-------------------+
        |
        v
+-------------------+
|     RabbitMQ      |
| durable queue     |
+-------------------+
        |
        v
+-------------------+       +-------------------+
|        web        | <-->  |     PostgreSQL    |
| Flask + gunicorn  |       | notices + changes |
| consumer thread   |       +-------------------+
| sweeper thread    |
| detail backfill   |       +-------------------+
+-------------------+ <-->  |       MinIO       |
        |                   | photo object store|
        v                   +-------------------+
     Browser
```

Önemli tasarım kararı:

- `web` container'ı yalnızca HTTP sunmuyor. Aynı process içinde RabbitMQ consumer, alarm sweeper ve detay backfill thread'lerini de başlatıyor.
- Bu yüzden `web/Dockerfile` içindeki Gunicorn ayarı bilinçli olarak `-w 1` kullanıyor. Worker sayısını rastgele artırırsanız her worker kendi consumer thread'ini başlatır ve davranış değişir.

## Veri Akışı

1. `fetcher.main` ortam değişkenlerini okuyup `FetchOrchestrator` oluşturur.
2. `InterpolClient`, Interpol sitesine warmup isteği atarak session/cookie hazırlar.
3. Fetcher seçilen tarama moduna göre çoklu sorgu kombinasyonlarıyla Red Notice listesini çeker.
4. Her yeni `RedNotice` nesnesi RabbitMQ kuyruğuna JSON olarak basılır.
5. `web.consumer.QueueConsumer` kuyruktan mesajları tek tek alır.
6. `NoticeService.upsert()` kayıt yeni mi, aynı mı, değişmiş mi karar verir.
7. Değişen alanlar `notice_changes` tablosuna yazılır, `is_updated=True` yapılır.
8. İlk fırsatta detay uçları çağrılır:
   - `/notices/v1/red/{id}`
   - `/notices/v1/red/{id}/images`
9. Detaylardan suç, doğum yeri, fiziksel bilgiler, diller ve galeri fotoğrafları alınır.
10. Web arayüzü SSE veya polling ile toplam kayıt/alarm değişimini fark eder ve sayfayı yeniler.

## Bileşenler

### 1. `fetcher/`

Fetcher katmanı üç temel iş yapar:

- Interpol API çağrılarını yapmak
- Tarama stratejisini belirlemek
- Sonuçları RabbitMQ'ya yayınlamak

Ana dosyalar:

- `fetcher/main.py`: Ana döngü ve mod seçimi
- `fetcher/interpol_client.py`: HTTP istekleri, retry, warmup, pagination, ban backoff
- `fetcher/passes.py`: Tüm tarama kombinasyonları
- `fetcher/queue_publisher.py`: RabbitMQ publish mantığı
- `fetcher/scan_state.py`: Crash-safe ilerleme durumu
- `fetcher/notice.py`: API cevabını `RedNotice` modeline çevirir

Fetcher davranış detayları:

- 403 alınırsa session sıfırlanır.
- Ban backoff süreleri sırasıyla 10, 20 ve 30 dakikadır.
- Pagination sonsuz döngüye girerse aynı sayfa kimlikleri tekrarlandığında süreç kesilir.
- Her pass ilerlemesi belirli aralıklarla state dosyasına yazılır.

### 2. RabbitMQ

RabbitMQ bu sistemde sadece "mesaj aracı" değildir; fetch hızını veri işleme hızından ayıran tampon katmandır.

- Kuyruk adı varsayılan olarak `interpol_red_notices`
- Queue durable olarak declare edilir
- Mesajlar persistent (`delivery_mode=2`) olarak gönderilir
- Consumer `prefetch_count=1` ile çalışır

Bu sayede fetcher bir batch bulduğunda, veritabanı veya detay çekimiyle beklemeden kuyruk basmaya devam edebilir.

### 3. `web/`

`web` paketi hem web uygulaması hem de veri işleme katmanıdır.

Ana dosyalar:

- `web/app.py`: Flask uygulaması ve tüm route'lar
- `web/consumer.py`: RabbitMQ consumer, sweeper, backfill thread'leri
- `web/notice_service.py`: upsert, değişiklik tespiti, detay çekme
- `web/models.py`: SQLAlchemy ORM modelleri
- `web/sse.py`: canlı bildirim yönetimi
- `web/photo.py`: yerel fotoğraf indirme/fallback
- `web/minio_storage.py`: MinIO bağlantı ve upload işlemleri

### 4. PostgreSQL

Veritabanı tarafında iki ana tablo vardır:

- `notices`
- `notice_changes`

Şema migration aracıyla değil, SQLAlchemy `create_all()` ile otomatik oluşturulur. Bu basit kurulum sağlar ama şema evrimi açısından sınırlıdır.

### 5. MinIO

MinIO opsiyonel ama aktif durumda düşünülmüş bir object storage katmanıdır.

- Bucket yoksa otomatik oluşturulur.
- Bucket için public read policy uygulanır.
- Kapak fotoğrafı ve galeri fotoğrafları S3 uyumlu objeler olarak saklanabilir.

MinIO yoksa sistem tamamen çökmez; yerel dosya fallback'i devreye girer.

## Dizin Yapısı

Temel uygulama ağacı şu şekildedir:

```text
interpol-watcher/
├─ docker-compose.yml
├─ .env.example
├─ requirements.txt
├─ local_migrate.py
├─ fetcher/
│  ├─ Dockerfile
│  ├─ main.py
│  ├─ interpol_client.py
│  ├─ notice.py
│  ├─ passes.py
│  ├─ queue_publisher.py
│  ├─ scan_state.py
│  └─ config.py
├─ web/
│  ├─ Dockerfile
│  ├─ app.py
│  ├─ consumer.py
│  ├─ notice_service.py
│  ├─ models.py
│  ├─ photo.py
│  ├─ sse.py
│  ├─ minio_storage.py
│  ├─ config.py
│  └─ templates/
│     └─ index.html
├─ shared/
│  ├─ message.py
│  └─ utils.py
└─ tests/
   ├─ conftest.py
   ├─ test_app.py
   ├─ test_consumer.py
   ├─ test_interpol_client.py
   └─ test_notice_service.py
```

## Kurulum Gereksinimleri

Docker ile çalıştırma için:

- Docker
- Docker Compose v2 (`docker compose`)

Yerel geliştirme için:

- Python 3.11+
- PostgreSQL ve RabbitMQ'yu ya lokal kurulu tutmak ya da Docker ile ayağa kaldırmak
- İsteğe bağlı MinIO

## Hızlı Başlangıç

### Seçenek 1: Docker ile tam sistem

PowerShell:

```powershell
cd .\interpol-watcher
Copy-Item .env.example .env
docker compose up --build -d
```

Servisleri kontrol et:

```powershell
docker compose ps
docker compose logs -f web
docker compose logs -f fetcher
```

### Çok önemli konfigürasyon notu

`.env.example` dosyasında şu satır var:

```env
DATABASE_URL=sqlite:////data/notices.db
```

Bu şu anlama gelir:

- `.env.example` dosyasını olduğu gibi `.env` olarak kopyalarsanız web servisi SQLite kullanır.
- Docker Compose içinde PostgreSQL servisi yine ayağa kalkar ama aktif olarak kullanılmayabilir.
- PostgreSQL kullanmak istiyorsanız `.env` içindeki `DATABASE_URL` değerini aşağıdaki gibi değiştirin:

```env
DATABASE_URL=postgresql://interpol:interpol123@postgres:5432/interpol_db
```

Yani bu repo iki farklı persistence düzeniyle çalışabiliyor:

- SQLite tabanlı hafif mod
- PostgreSQL tabanlı container içi mod

### Seçenek 2: PostgreSQL'i açıkça kullanarak başlatmak

```powershell
cd .\interpol-watcher
Copy-Item .env.example .env
```

Ardından `.env` içinde `DATABASE_URL` satırını PostgreSQL olacak şekilde düzenleyin ve başlatın:

```powershell
docker compose up --build -d
```

## Servislere Erişim

Varsayılan portlar:

- Web arayüzü: `http://localhost:8000`
- RabbitMQ AMQP: `localhost:5672`
- RabbitMQ yönetim paneli: `http://localhost:15672`
- PostgreSQL: `localhost:5432`
- MinIO API: `http://localhost:9000`
- MinIO Console: `http://localhost:9001`

Varsayılan giriş bilgileri:

- RabbitMQ: `guest / guest`
- PostgreSQL: `interpol / interpol123`
- MinIO: `minioadmin / minioadmin`

## Konfigürasyon Mantığı

Bu projede ayarların nereden geldiğini anlamak önemlidir, çünkü üç katman birden vardır:

1. `.env`
2. `docker-compose.yml` içindeki `${VAR:-default}` değerleri
3. Python kodundaki `os.getenv(..., default)` fallback'leri

Pratikte öncelik sırası:

```text
.env > docker-compose default > Python default
```

Bu yüzden bazı değerlerin iki yerde farklı görünüyor olması tesadüf değildir. Örneğin:

- `REQUEST_DELAY_SECONDS` Python kodunda `1.5`
- `.env.example` içinde `2.0`
- `docker-compose.yml` içinde fetcher için `3.0`

Deploy ederken hangi kaynağın baskın olduğuna bakmadan sadece tek bir dosyaya güvenmeyin.

## Çevre Değişkenleri

### Ortak altyapı

| Değişken | Varsayılan | Kullanıldığı yer | Açıklama |
| --- | --- | --- | --- |
| `RABBITMQ_HOST` | `rabbitmq` | fetcher, web | RabbitMQ host adı |
| `RABBITMQ_PORT` | `5672` | fetcher, web | RabbitMQ portu |
| `RABBITMQ_QUEUE_NAME` | `interpol_red_notices` | fetcher, web | Queue adı |
| `RABBITMQ_USER` | `guest` | fetcher, web | RabbitMQ kullanıcı adı |
| `RABBITMQ_PASSWORD` | `guest` | fetcher, web | RabbitMQ şifresi |
| `INTERPOL_BASE_URL` | `https://ws-public.interpol.int` | fetcher, web | Interpol public API kök URL'i |
| `DATABASE_URL` | Docker'da Postgres fallback, `.env.example` içinde SQLite | web | SQLAlchemy bağlantı adresi |

### Fetcher ayarları

| Değişken | Varsayılan | Açıklama |
| --- | --- | --- |
| `INTERPOL_FETCH_INTERVAL_SECONDS` | `300` | Tarama döngüleri arasındaki bekleme süresi |
| `INTERPOL_FETCH_ALL` | `true` | Tam taramayı etkinleştirir |
| `INTERPOL_FETCH_EXTENDED` | `false` | Genişletilmiş taramayı etkinleştirir |
| `REQUEST_DELAY_SECONDS` | Kodda `1.5`, compose'ta `3.0` | Sayfalar arası istek gecikmesi |
| `STATE_FILE_PATH` | `/data/scan_state.json` | Tarama state dosyası |
| `ENABLE_PASS_AGE_0_9` | `true` | 0-9 yaş özel pass'lerini açar |
| `ENABLE_PASS_IN_PK_1YR` | `true` | Belirli yüksek yoğunluklu ülkeler için 1 yaş granüler pass açar |
| `VERY_HIGH_NATIONALITIES_1YR` | `IN,PK` | 1 yıllık yaş taramasında kullanılacak ülke listesi |
| `AGE_1YR_MIN` | `10` | 1 yıllık yaş taramasının alt sınırı |
| `AGE_1YR_MAX` | `99` | 1 yıllık yaş taramasının üst sınırı |

### Web ve detay backfill ayarları

| Değişken | Varsayılan | Açıklama |
| --- | --- | --- |
| `FLASK_ENV` | `production` | Flask çalışma modu |
| `DETAIL_BACKFILL_ENABLED` | `true` | Detayı eksik kayıtlar için arka plan backfill thread'ini açar |
| `DETAIL_BACKFILL_BATCH_SIZE` | `25` | Her batch'te kaç kayıt detaylandırılacak |
| `DETAIL_BACKFILL_IDLE_SECONDS` | `30` | Batch aralarında boşta bekleme süresi |
| `DETAIL_REQUEST_DELAY_SECONDS` | `1.5` | Detay API çağrıları arasındaki gecikme |
| `PHOTOS_DIR` | `/data/photos` | MinIO yoksa yerel fotoğraf klasörü |

### MinIO ayarları

| Değişken | Varsayılan | Açıklama |
| --- | --- | --- |
| `MINIO_ENDPOINT` | `minio:9000` | S3 endpoint |
| `MINIO_ACCESS_KEY` | `minioadmin` | Erişim anahtarı |
| `MINIO_SECRET_KEY` | `minioadmin` | Gizli anahtar |
| `MINIO_BUCKET` | `interpol-photos` | Kullanılacak bucket adı |
| `MINIO_SECURE` | `false` | HTTPS kullanılsın mı |
| `MINIO_PUBLIC_URL` | `http://localhost:9000` | Tarayıcıya döndürülen public URL kökü |

### Docker Compose tarafındaki servis özel ayarları

| Değişken | Varsayılan | Servis |
| --- | --- | --- |
| `RABBITMQ_DEFAULT_USER` | `guest` | rabbitmq |
| `RABBITMQ_DEFAULT_PASS` | `guest` | rabbitmq |
| `POSTGRES_USER` | `interpol` | postgres |
| `POSTGRES_PASSWORD` | `interpol123` | postgres |
| `POSTGRES_DB` | `interpol_db` | postgres |

## Çalışma Modları

Fetcher'ın davranışı iki ana bayrakla belirlenir:

### 1. Tam tarama modu

`INTERPOL_FETCH_ALL=true`

Bu modda:

- `full_scan_passes()` içindeki çok sayıda kombinasyon çalışır.
- Milliyet, arama kararı ülkesi, cinsiyet, yaş aralığı ve bunların kombinasyonları taranır.
- Amaç tek sorguyla alınamayan büyük veri setini daha küçük parçalar halinde toplamaktır.
- Yeni bulunan notice'lar anında stream edilerek RabbitMQ'ya gönderilir.

### 2. Genişletilmiş tarama modu

`INTERPOL_FETCH_EXTENDED=true`

Bu mod, tam taramaya ek derinlik sağlamak için daha özel pass'ler içerir. Özellikle:

- çok yoğun milliyet grupları
- 1 yıllık yaş kırılımları
- 0-9 yaş ve 100+ yaş segmentleri
- `sexId=U` varyasyonları

### 3. Hafif mod

Hem `INTERPOL_FETCH_ALL=false` hem `INTERPOL_FETCH_EXTENDED=false` ise fetcher sadece son kayıtları çeker:

- `fetch_red_notices(result_per_page=160)`
- toplu bir istek
- düşük maliyet
- gelişmiş tarama kapsamı yok

### Modların birlikte kullanımı

Kod şu an her iki bayrak da `true` ise önce tam tarama, sonra genişletilmiş tarama yapar. Bu mümkündür ama maliyetlidir. Böyle bir kullanım bilinçli yapılmalıdır.

## Veritabanı Modeli

### `notices` tablosu

Ana alanlar:

- Kimlik: `entity_id`
- Temel kimlik bilgileri: `name`, `forename`, `date_of_birth`
- Milliyet: `nationality`, `all_nationalities`
- Özet suç bilgisi: `arrest_warrant`
- Fotoğraf: `photo_url`
- Alarm/meta: `created_at`, `updated_at`, `is_updated`
- Detay zenginleştirme: `charges`, `charge_translation`, `issuing_countries`
- Doğum/fiziksel alanlar: `place_of_birth`, `country_of_birth_id`, `sex_id`, `height`, `weight`, `eyes_colors_id`, `hairs_id`, `distinguishing_marks`
- Dil/fotoğraf galerisi: `languages_spoken`, `image_urls`
- Detay çekim zamanı: `detail_fetched_at`

### `notice_changes` tablosu

Bu tablo her değişikliği olay bazlı saklar:

- `entity_id`
- `field_name`
- `old_value`
- `new_value`
- `changed_at`

Böylece sadece "alarm oldu" değil, "hangi alan neye döndü" sorusu da cevaplanır.

### Alarm mantığı

- `NoticeService` izlenen alanlardan herhangi biri değişirse kaydı `UPDATED` sayar.
- Bu durumda `is_updated=True` olur.
- `web.models.ALARM_WINDOW_SECONDS = 60`
- `QueueConsumer` içindeki sweeper thread her `15` saniyede bir çalışır.
- `updated_at` alarm penceresini geçtiyse `is_updated=False` yapar.

Yani alarm kalıcı bir flag değil, zaman pencereli bir görünürlük mekanizmasıdır.

## Web Arayüzü ve HTTP Uçları

### Arayüz özellikleri

Ana sayfada şu özellikler vardır:

- kart bazlı listeleme
- isim/soyisim araması
- milliyet filtresi
- sıralama:
  - newest
  - oldest
  - name_asc
  - name_desc
- sayfalama (`200` kayıt/sayfa)
- alarm vurgusu
- modal içinde detay profil
- galeri görselleri
- change history görünümü

### Canlı güncelleme

Canlılık iki katmanlıdır:

1. `/api/stream` üzerinden SSE
2. 10 saniyede bir `/api/status` polling fallback

SSE bağlantısı koparsa arayüz sessizce polling ile devam eder.

### HTTP uçları

| Uç | Metot | Amaç |
| --- | --- | --- |
| `/` | `GET` | Liste ekranı |
| `/api/status` | `GET` | Toplam kayıt ve alarm sayısı |
| `/api/stream` | `GET` | Server-Sent Events akışı |
| `/photos/<entity_id>` | `GET` | Kapak fotoğrafını MinIO/local/placeholder sırasıyla sunar |
| `/api/notice/<entity_id>` | `GET` | Tek notice detayını JSON döner |

### `/api/notice/<entity_id>` çıktısı

Bu uç temel olarak şunları döner:

- notice temel alanları
- detay alanları
- `image_urls`
- `detail_fetched_at`
- son 50 değişikliği içeren `change_history`

Frontend tarafı route'a slash yerine ilk `-` ile normalize edilmiş `entity_id` de gönderebilir.

## Fotoğraf Depolama Stratejisi

Sistem iki seviyede fotoğraf işi yapar:

### 1. Kapak fotoğrafı

Özet payload içinde `photo_url` gelirse:

- MinIO aktifse önce MinIO'ya yüklemeyi dener
- MinIO başarısızsa veya kapalıysa yerel dosyaya indirir

### 2. Galeri fotoğrafları

Detay API'sindeki `/images` uçlarından gelen fotoğraflar:

- MinIO aktifse obje olarak yüklenir
- değilse orijinal URL'ler `image_urls` içinde tutulur

### Sunum sırası

`/photos/<entity_id>` route'u şu sırayla çalışır:

1. MinIO objesi var mı
2. Yerel dosya var mı
3. SVG placeholder dön

## Operasyon Rehberi

### Log izleme

```powershell
docker compose logs -f fetcher
docker compose logs -f web
docker compose logs -f rabbitmq
docker compose logs -f minio
```

### Servis sağlığını kontrol etme

```powershell
docker compose ps
```

Compose dosyasında healthcheck tanımları vardır:

- RabbitMQ: `rabbitmq-diagnostics -q ping`
- MinIO: health endpoint
- PostgreSQL: `pg_isready`
- Fetcher: process kontrolü
- Web: `/api/status` çağrısı

### Tarama state'ini sıfırlama

Fetcher kaldığı yerden devam eder. Baştan taratmak isterseniz state dosyasını silin:

```powershell
docker exec interpol_fetcher sh -lc "rm -f /data/scan_state.json"
docker restart interpol_fetcher
```

Alternatif olarak ilgili volume içeriğini temizleyebilirsiniz ama bu daha geniş etkili olur.

### Alarm davranışını anlamak

Arayüzde kırmızı "UPDATED" kartı görüyorsanız:

- aynı `entity_id` yeniden işlendi
- izlenen alanlardan biri değişti
- sweeper bu alarmı henüz temizlemedi

Kartta düz `UPDATED` etiketi varsa kayıt daha önce alarm olmuş ama aktif alarm penceresi bitmiş olabilir.

### MinIO'ya eski yerel fotoğrafları taşıma

Repo kökünde `local_migrate.py` adlı yardımcı script bulunur. Bu script:

- `/app/temp_photos` içindeki `.jpg` dosyalarını okur
- MinIO bucket'ına yükler
- `notices.photo_url` ve `notices.image_urls` alanlarını günceller

Script şu an parametreli değildir; host, bucket ve klasör değerleri kod içinde sabittir. Çalıştırmadan önce kendi ortamınıza göre gözden geçirin.

## Yerel Geliştirme

### 1. Sanal ortam ve bağımlılıklar

```powershell
cd .\interpol-watcher
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Altyapıyı Docker ile, uygulamayı lokal çalıştırma

Bu en pratik geliştirme modelidir:

```powershell
docker compose up -d rabbitmq postgres minio
```

Ardından PowerShell ortam değişkenlerini ayarlayın:

```powershell
$env:PYTHONPATH = "."
$env:RABBITMQ_HOST = "localhost"
$env:RABBITMQ_PORT = "5672"
$env:RABBITMQ_QUEUE_NAME = "interpol_red_notices"
$env:RABBITMQ_USER = "guest"
$env:RABBITMQ_PASSWORD = "guest"
$env:DATABASE_URL = "postgresql://interpol:interpol123@localhost:5432/interpol_db"
$env:MINIO_ENDPOINT = "localhost:9000"
$env:MINIO_ACCESS_KEY = "minioadmin"
$env:MINIO_SECRET_KEY = "minioadmin"
$env:MINIO_BUCKET = "interpol-photos"
$env:MINIO_PUBLIC_URL = "http://localhost:9000"
```

Web'i çalıştırın:

```powershell
python -m flask --app web.app run --host 0.0.0.0 --port 8000
```

Fetcher'ı ayrı terminalde çalıştırın:

```powershell
python -m fetcher.main
```

### 3. SQLite ile en hafif yerel çalışma

Web tarafını hızlıca denemek için:

```powershell
$env:PYTHONPATH = "."
$env:DATABASE_URL = "sqlite:///./local_notices.db"
python -m flask --app web.app run --host 0.0.0.0 --port 8000
```

Bu modda RabbitMQ ve fetcher olmadan arayüz açılır ama veri akışı yoktur.

## Testler

### Önerilen çalıştırma biçimi

Bu repo için doğrudan `pytest` yerine `python -m pytest` kullanmak daha güvenlidir; modül çözümlemesi tutarlı olur.

```powershell
python -m pytest --basetemp=.pytest_tmp
```

### İnceleme sırasında doğrulanan durum

Kod tabanı 18 Mart 2026 tarihinde incelendiğinde test durumu şu şekildeydi:

- `python -m pytest tests/test_interpol_client.py::test_fetch_red_notices_parses_items -q` başarılı
- tam test paketi yeşil değil

Gözlenen nedenler:

- `tests/test_app.py`, artık kodda bulunmayan `web.photo.start_backfill_thread` fonksiyonunu patch etmeye çalışıyor
- `tests/test_consumer.py` ve `tests/test_notice_service.py`, `WebConfig` sınıfının eski imzasına göre fixture oluşturuyor
- Windows ortamında pytest temp klasörü için `--basetemp` vermek daha güvenli

Yani test klasörü var ama güncel uygulama davranışıyla tamamen senkron değil. README'yi kullanarak sistemi ayağa kaldırırken testlerin tamamının şu an için referans doğrulama seti olduğunu varsaymayın.

## Bilinen Sınırlamalar ve Teknik Notlar

### 1. Web container'ı çok rol üstleniyor

`web` servisi şu rollerin hepsini birlikte taşıyor:

- HTTP sunucu
- RabbitMQ consumer
- sweeper
- detail backfill

Bu küçük kurulum için pratik ama ölçekleme açısından sıkışık bir tasarım.

### 2. Worker sayısını artırmak güvenli değil

Gunicorn worker sayısını artırmak, her worker için yeni consumer thread'leri doğurabilir. Bu da istemediğiniz şekilde çoklu tüketim veya beklenmeyen yan etkiler üretir.

### 3. Şema migration altyapısı yok

Tablolar `create_all()` ile oluşuyor. Versiyonlu migration akışı yok. Üretim ortamı düşünülüyorsa Alembic gibi bir araç eklemek gerekir.

### 4. Queue publisher her batch'te bağlantı açıyor

`QueuePublisher.publish_notices()` her çağrıda yeni RabbitMQ bağlantısı açıp kapatıyor. Trafik büyürse connection reuse daha verimli olur.

### 5. SQLite ve PostgreSQL birlikte düşünülmüş

Bu esneklik faydalı ama `.env.example` ile `docker-compose.yml` arasındaki varsayılan fark yüzünden ilk kurulumda kafa karıştırabilir.

### 6. Testler teknik borç içeriyor

Testlerin bir kısmı güncel kodun sınıf imzaları ve fonksiyon adlarıyla uyuşmuyor.

### 7. MinIO bucket politikası public read

Bu geliştirme kolaylığı sağlar ama internetten erişilen gerçek bir ortamda dikkat gerektirir.

## Son Notlar

Bu proje operasyonel olarak şu fikir üzerine kurulu:

- fetcher veri toplar
- queue tampon görevi görür
- consumer veriyi anlamlandırır
- web operatöre görünür hale getirir

Sistemi üretimde kullanacaksanız özellikle şu üç konuyu ayrıca ele alın:

- varsayılan parolaları değiştirmek
- Gunicorn/consumer ayrımını netleştirmek
- migration ve test altyapısını güncellemek
