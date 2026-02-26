# 🔴 Interpol Kırmızı Liste Takip Sistemi

Interpol tarafından yayınlanan kırmızı liste (Red Notice) verilerini çeken, RabbitMQ kuyruğu üzerinden ileten ve gerçek zamanlı web arayüzünde gösteren bir uygulamadır.

---

## 📐 Mimari

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Network                        │
│                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │ Container A │───▶│ Container C │───▶│ Container B │  │
│  │  (fetcher)  │    │ (rabbitmq)  │    │ (webserver) │  │
│  └─────────────┘    └─────────────┘    └─────────────┘  │
│    - Interpol API     - RabbitMQ          - Flask        │
│    - Periyodik        - Mesaj kuyruğu     - SQLite DB    │
│      veri çekme       - Kalıcı kuyruk     - Socket.IO   │
└─────────────────────────────────────────────────────────┘
```

### Container Açıklamaları

| Container | İşlev |
|-----------|-------|
| **A - Fetcher** | Interpol API'den veri çeker, RabbitMQ'ya gönderir |
| **B - Webserver** | Kuyruğu dinler, DB'ye kaydeder, web arayüzü sunar |
| **C - RabbitMQ** | Mesaj kuyruk sistemi |

---

## 🗂️ Proje Yapısı

```
interpol-watcher/
├── docker-compose.yml          # Tüm containerları ayağa kaldırır
├── .env                        # Ortam değişkenleri (buradan config edilir)
├── README.md
│
├── fetcher/                    # Container A
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config.py               # Env değişkenlerini okur
│   ├── interpol_client.py      # API ile iletişim
│   ├── queue_publisher.py      # RabbitMQ'ya mesaj gönderir
│   ├── main.py                 # Giriş noktası
│   └── test_fetcher.py         # Birim testleri
│
└── webserver/                  # Container B
    ├── Dockerfile
    ├── requirements.txt
    ├── config.py               # Env değişkenlerini okur
    ├── database.py             # SQLite işlemleri
    ├── consumer.py             # RabbitMQ dinleyici
    ├── app.py                  # Flask + SocketIO
    ├── main.py                 # Giriş noktası
    ├── test_webserver.py       # Birim testleri
    └── templates/
        └── index.html          # Web arayüzü
```

---

## 🚀 Kurulum ve Çalıştırma

### Gereksinimler

- [Docker](https://docs.docker.com/get-docker/) (v20+)
- [Docker Compose](https://docs.docker.com/compose/) (v2+)

### 1. Projeyi klonlayın

```bash
git clone https://github.com/kullanici/interpol-watcher.git
cd interpol-watcher
```

### 2. Ortam değişkenlerini ayarlayın (opsiyonel)

`.env` dosyası varsayılan değerlerle hazır gelir. Değiştirmek istediğiniz ayarı düzenleyin:

```bash
nano .env
```

Önemli değişkenler:

| Değişken | Açıklama | Varsayılan |
|----------|----------|------------|
| `FETCH_INTERVAL` | Veri çekme sıklığı (saniye) | `60` |
| `INTERPOL_RESULT_PER_PAGE` | Sayfa başına çekilecek kayıt | `20` |
| `RABBITMQ_USER` | RabbitMQ kullanıcı adı | `admin` |
| `RABBITMQ_PASS` | RabbitMQ şifresi | `admin123` |

### 3. Docker imajlarını build edin ve başlatın

```bash
docker-compose up --build
```

Arka planda çalıştırmak için:

```bash
docker-compose up --build -d
```

### 4. Uygulamaya erişin

| Servis | URL |
|--------|-----|
| 🌐 Web Arayüzü | http://localhost:5000 |
| 🐰 RabbitMQ Yönetim Paneli | http://localhost:15672 |

RabbitMQ paneli için kullanıcı adı/şifre: `.env` dosyasındaki `RABBITMQ_USER` ve `RABBITMQ_PASS`

---

## 🛑 Durdurma

```bash
# Containerları durdur (veriler korunur)
docker-compose stop

# Containerları sil (veriler korunur)
docker-compose down

# Containerları ve verileri tamamen sil
docker-compose down -v
```

---

## 🧪 Testleri Çalıştırma

### Fetcher testleri

```bash
cd fetcher
pip install -r requirements.txt
python -m pytest test_fetcher.py -v
```

### Webserver testleri

```bash
cd webserver
pip install -r requirements.txt
python -m pytest test_webserver.py -v
```

### Tüm testler (Docker ile)

```bash
docker-compose run --rm fetcher python -m pytest test_fetcher.py -v
docker-compose run --rm webserver python -m pytest test_webserver.py -v
```

---

## 🖥️ Web Arayüzü Özellikleri

- **Gerçek zamanlı güncelleme**: Socket.IO sayesinde sayfa yenilemeye gerek yok
- **Yeni kayıt**: Tablonun başına eklenir, yeşil ile vurgulanır
- **Güncellenen kayıt**: Sarı ile vurgulanır + sağ üstte **ALARM** banner gösterilir
- **İstatistikler**: Toplam kayıt, bu oturumda yeni/güncellenen sayısı
- **Fotoğraf**: Interpol'den fotoğraf geliyorsa görüntülenir

---

## 🔧 Geliştirme Notları

### Nesne Tabanlı Yapı

| Sınıf | Dosya | Sorumluluk |
|-------|-------|------------|
| `InterpolClient` | `fetcher/interpol_client.py` | API iletişimi |
| `QueuePublisher` | `fetcher/queue_publisher.py` | RabbitMQ yayıncı |
| `FetcherApp` | `fetcher/main.py` | Koordinatör |
| `Database` | `webserver/database.py` | SQLite CRUD |
| `QueueConsumer` | `webserver/consumer.py` | RabbitMQ dinleyici |

### Kullanılan Teknolojiler

- **Python 3.11**
- **Flask 3.0** — web sunucu
- **Flask-SocketIO** — gerçek zamanlı iletişim
- **Pika** — RabbitMQ Python istemcisi
- **SQLite** — hafif veritabanı
- **RabbitMQ 3** — mesaj kuyruğu
- **Docker + Docker Compose** — konteynerizasyon

---

## 📋 Interpol API

Uygulama Interpol'ün açık REST API'sini kullanır:

```
GET https://ws-public.interpol.int/notices/v1/red?page=1&resultPerPage=20
```

API anahtarı gerektirmez, herkese açıktır.

---

## ❓ Sorun Giderme

**Container başlamıyor:**
```bash
docker-compose logs fetcher
docker-compose logs webserver
docker-compose logs rabbitmq
```

**RabbitMQ bağlantı hatası:**  
RabbitMQ'nun tamamen başlaması birkaç saniye sürebilir. `depends_on` + healthcheck yapılandırılmış olduğundan sistem otomatik bekler.

**Veri gelmiyor:**  
Interpol API'sine internet bağlantısının olduğundan emin olun.
