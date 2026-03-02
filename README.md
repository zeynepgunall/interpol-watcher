# Interpol Red Notice Watcher

Interpol tarafından yayınlanan kırmızı bülten (Red Notice) verilerini periyodik olarak izleyen, RabbitMQ üzerinden işleyen ve web arayüzünde alarm sistemiyle sunan bir Docker tabanlı mikroservis projesi.

## Mimari

```
┌─────────────────────────────────────────────────────────────────┐
│                       docker-compose                            │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │  Container A │    │  Container C │    │   Container B    │  │
│  │   fetcher    │───▶│  rabbitmq    │───▶│  web + consumer  │  │
│  │              │    │              │    │                  │  │
│  │ Interpol API │    │ Message Queue│    │ Flask UI + SQLite│  │
│  └──────────────┘    └──────────────┘    └──────────────────┘  │
│         │                                        │              │
│         └──────────── /data volume ──────────────┘              │
│                   (notices.db + scan_state.json)                │
└─────────────────────────────────────────────────────────────────┘
```

- **Container A – Fetcher**: Interpol public API'sini `INTERPOL_FETCH_INTERVAL_SECONDS` (varsayılan: 300 sn) periyotla tarar. Çekilen her kırmızı bülten JSON mesajı olarak RabbitMQ kuyruğuna yazılır. Tarama ilerlemesi `scan_state.json` ile crash-safe biçimde korunur; servis yeniden başlarsa kaldığı combo'dan devam eder.
- **Container B – Web + Consumer**: Flask web sunucusu ile RabbitMQ consumer aynı container içinde paralel çalışır. Consumer gelen mesajları SQLite'a yazar; aynı `entity_id` için gelen mesajlar `is_updated=True` ile işaretlenir ve web arayüzünde **⚠ ALARM** olarak vurgulanır. `/api/status` endpoint'i ile JS polling her 30 saniyede arayüzü günceller.
- **Container C – RabbitMQ**: Dayanıklı (durable) mesaj kuyruğu. Yönetim paneli `http://localhost:15672` adresinde erişilebilir.

---

## Hızlı Başlangıç

**Gereksinimler:** Docker ve Docker Compose (geliştirme ortamı için Python 3.11+)

```bash
# 1. Repoyu klonlayın
git clone <repo-url> interpol-watcher
cd interpol-watcher

# 2. Tüm servisleri tek komutla başlatın
docker-compose up --build

# 3. Tarayıcıyı açın
#   Web arayüzü  → http://localhost:8000
#   RabbitMQ UI  → http://localhost:15672  (guest / guest)
```

Servisleri arkaplanda çalıştırmak için:

```bash
docker-compose up -d --build
docker-compose logs -f fetcher   # fetcher loglarını takip etmek için
```

---

## Nasıl Çalışır

```
Interpol API
    │
    │  HTTP GET /notices/v1/red  (parametreli, sayfalı)
    ▼
[fetcher/interpol_client.py]
    │  Her pass için yüzlerce (uyruk × yaş aralığı) combo sorgusu
    │  Sonuçlar RedNotice dataclass'ına dönüştürülür
    │  İlerleme /data/scan_state.json'a commit edilir (crash-safe)
    ▼
[fetcher/queue_publisher.py]
    │  Her notice JSON olarak RabbitMQ kuyruğuna basılır
    ▼
RabbitMQ  (durable queue: interpol_red_notices)
    ▼
[web/consumer.py]  ← daemon thread, Flask ile aynı process
    │  Yeni entity_id → INSERT  →  created_at, is_updated=False
    │  Mevcut entity_id → UPDATE → updated_at, is_updated=True  ⚠ ALARM
    ▼
SQLite  (/data/notices.db, shared docker volume)
    ▼
[web/app.py]  Flask
    │  GET /          → Kart görünümü (arama, uyruk filtresi, sayfalama)
    │  GET /api/status → {"total": N, "alarms": N}  (JS polling için)
    ▼
Tarayıcı (her 30 saniyede /api/status → değişiklik varsa reload)
```

---

## Ortam Değişkenleri

Tüm yapılandırma environment variable ile yönetilir. Koda dokunmadan `.env` dosyası oluşturarak değiştirilebilir.

### Fetcher (Container A)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `INTERPOL_BASE_URL` | `https://ws-public.interpol.int` | API temel adresi |
| `INTERPOL_FETCH_INTERVAL_SECONDS` | `300` | Tarama döngüsü aralığı (sn) |
| `REQUEST_DELAY_SECONDS` | `1.5` | API istekleri arası bekleme |
| `STATE_FILE_PATH` | `/data/scan_state.json` | Pass ilerleme dosyası |
| `FETCH_EXTENDED` | `true` | Genişletilmiş çok-geçişli tarama |
| `FETCH_ALL` | `false` | Tüm bültenleri tek geçişte çek |
| `USE_MOCK_DATA` | `false` | Gerçek API yerine örnek veri |
| `ENABLE_PASS_AGE_0_9` | `true` | 0-9 yaş aralığı passları aktif |
| `ENABLE_PASS_IN_PK_1YR` | `true` | IN/PK uyruklu 1 yıllık passlar |
| `VERY_HIGH_NATIONALITIES_1YR` | `IN,PK` | 1 yıllık pass için uyrukhttps |
| `AGE_1YR_MIN` | `18` | 1 yıllık pass minimum yaş |
| `AGE_1YR_MAX` | `45` | 1 yıllık pass maksimum yaş |

### Web + Consumer (Container B)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `DATABASE_URL` | `sqlite:////data/notices.db` | SQLAlchemy bağlantı dizesi |
| `FLASK_ENV` | `production` | Flask ortamı |

### Ortak (RabbitMQ)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `RABBITMQ_HOST` | `rabbitmq` | RabbitMQ hostname |
| `RABBITMQ_PORT` | `5672` | AMQP portu |
| `RABBITMQ_QUEUE_NAME` | `interpol_red_notices` | Kuyruk adı |
| `RABBITMQ_USER` | `guest` | RabbitMQ kullanıcısı |
| `RABBITMQ_PASSWORD` | `guest` | RabbitMQ şifresi |

---

## Arayüz Davranışı

| Durum | Görsel | Açıklama |
|---|---|---|
| Yeni kayıt | Normal kart | `entity_id` ilk kez DB'ye girdi |
| ⚠ ALARM | Kırmızı kenarlık + nabız animasyonu | Aynı `entity_id` yeniden geldi; `is_updated=True` |
| Zaman bilgisi | `ADDED:` / `ALARM:` | `created_at` ve `updated_at` UTC zamanları |

Arayüzde **ad/soyad arama** ve **uyruk filtresi** bulunur. Sayfalama 200 kayıt/sayfa olarak çalışır. Üst bantta aktif alarm sayısı gösterilir.

---

## Testleri Çalıştırma

```bash
# Sanal ortam oluşturun (ilk kez)
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install -r requirements.txt

# Tüm testleri çalıştır
pytest

# Ayrıntılı çıktı ile
pytest -v

# Belirli bir dosyayı çalıştır
pytest tests/test_interpol_client.py -v
pytest tests/test_consumer.py -v
pytest tests/test_app.py -v
```

### Test Kapsamı

| Test Dosyası | Ne Test Eder |
|---|---|
| `tests/test_interpol_client.py` | `RedNotice.from_api_item` parse, HTTP monkeypatch ile `fetch_red_notices` |
| `tests/test_consumer.py` | Yeni kayıt INSERT, mevcut kayıt UPDATE → `is_updated=True`, eksik `entity_id` görmezden gelme |
| `tests/test_app.py` | Flask route'ları (`/`, `/api/status`), sayfalama, arama filtresi |

---

## Klasör Yapısı

```
interpol-watcher/
├── docker-compose.yml          # 3 servisin orkestrasyon tanımı
├── requirements.txt            # Python bağımlılıkları
│
├── fetcher/                    # Container A
│   ├── Dockerfile
│   ├── config.py               # FetcherConfig — tüm env değişkenleri
│   ├── interpol_client.py      # InterpolClient, RedNotice, ScanStateManager, PassContext
│   ├── main.py                 # run_forever() döngüsü
│   └── queue_publisher.py      # RabbitMQ'ya publish
│
├── web/                        # Container B
│   ├── Dockerfile
│   ├── app.py                  # Flask app factory, route'lar
│   ├── config.py               # WebConfig — tüm env değişkenleri
│   ├── consumer.py             # QueueConsumer — RabbitMQ daemon thread
│   ├── models.py               # Notice ORM modeli, SQLAlchemy
│   └── templates/
│       └── index.html          # Kart arayüzü, JS polling
│
└── tests/
    ├── test_interpol_client.py # InterpolClient birim testleri
    ├── test_consumer.py        # QueueConsumer birim testleri
    └── test_app.py             # Flask route testleri
```

---

## Geliştirme Notları

- **Scan state sıfırlamak için** (yeni tam tarama zorlamak):
  ```bash
  docker exec interpol_fetcher rm /data/scan_state.json
  ```
- **Veritabanını sorgulamak için**:
  ```bash
  docker exec interpol_web python -c \
    "from web.models import *; from web.config import *; \
     S = create_session_factory(WebConfig.from_env()); s = S(); \
     print(s.query(Notice).count())"
  ```
- **RabbitMQ yönetim paneli**: `http://localhost:15672` → Queues → `interpol_red_notices`
- `requirements.txt`: Projenin Python bağımlılıkları.
- `fetcher/`
  - `config.py`: Fetcher için environment tabanlı yapılandırma sınıfı.
  - `interpol_client.py`: Interpol public API'si ile haberleşen istemci ve `RedNotice` veri sınıfı.
  - `queue_publisher.py`: RabbitMQ kuyruğuna mesaj gönderen sınıf.
  - `main.py`: Fetcher ana döngüsü (periyodik veri çekimi ve publish).
  - `Dockerfile`: Fetcher container'ı için Docker imajı.
- `web/`
  - `config.py`: Web/consumer tarafı için environment tabanlı konfigürasyon.
  - `models.py`: SQLAlchemy ile `Notice` modeli ve session factory.
  - `consumer.py`: RabbitMQ kuyruğunu dinleyen ve veritabanına yazan consumer sınıfı.
  - `app.py`: Flask uygulaması, `/` endpoint'i ve consumer thread başlatma.
  - `templates/index.html`: Modern, koyu temalı HTML arayüz.
  - `Dockerfile`: Web container'ı için Docker imajı.
- `tests/`
  - `test_interpol_client.py`: Interpol istemcisi için birim testi.

### Notlar

- Proje **Nesne Tabanlı Programlama** prensiplerine uygun şekilde; konfigürasyon, veri modeli, API istemcisi, kuyruk publisher/consumer gibi roller ayrı sınıflara bölünerek tasarlanmıştır.
- Tüm kritik değerler environment değişkenleri ile yönetilebilir olduğu için, farklı ortamlara (test, staging, prod) çok az çabayla uyarlanabilir.
- İstenirse SQLite yerine Postgres gibi başka bir veritabanı çok kolay bir şekilde entegre edilebilir; sadece `DATABASE_URL` değerini uygun SQLAlchemy connection string'i ile değiştirmeniz yeterlidir.

