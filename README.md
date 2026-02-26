## Interpol Kırmızı Bülten İzleyici

Bu proje, Interpol tarafından yayınlanan kırmızı bülten verilerini belirli periyotlarla çeker, bir mesaj kuyruğuna (RabbitMQ) yazar, kuyruktan okunan verileri bir veritabanına kaydeder ve basit bir web arayüzü üzerinden gösterir.

Mimari üç container'dan oluşur:

- **Container A – Fetcher (`fetcher`)**: Interpol kırmızı bülten verisini periyodik olarak **Interpol public API** üzerinden çeker ve RabbitMQ kuyruğuna mesaj olarak yazar.
- **Container B – Web Sunucu (`web`)**: Python/Flask tabanlı bir web sunucusudur. RabbitMQ kuyruğunu dinler, gelen mesajları veritabanına (SQLite) kaydeder ve kayıtları HTML arayüz ile kullanıcıya sunar. Daha önce kayıtlı bir kişinin kaydında güncelleme olursa arayüzde **alarm** olarak vurgulanır.
- **Container C – RabbitMQ (`rabbitmq`)**: Mesaj kuyruğu sistemi.

Tüm yapı `docker-compose` ile ayağa kalkacak şekilde hazırlanmıştır.

### Kurulum Gereksinimleri

- Docker
- Docker Compose

Geliştirme amaçlı olarak ayrıca:

- Python 3.11
- `pip` (opsiyonel, testleri lokal çalıştırmak isterseniz)

### Ortam Değişkenleri

Tüm kritik yapılandırmalar environment üzerinden yönetilir ve koda dokunmadan değiştirilebilir:

- **Genel / RabbitMQ**
  - `RABBITMQ_HOST` (varsayılan: `rabbitmq`)
  - `RABBITMQ_PORT` (varsayılan: `5672`)
  - `RABBITMQ_QUEUE_NAME` (varsayılan: `interpol_red_notices`)
  - `RABBITMQ_USER` (varsayılan: `guest`)
  - `RABBITMQ_PASSWORD` (varsayılan: `guest`)

- **Fetcher (Container A)**
  - `INTERPOL_BASE_URL` (varsayılan: `https://ws-public.interpol.int`)
  - `INTERPOL_FETCH_INTERVAL_SECONDS` (varsayılan: `300` – 5 dakika)

- **Web (Container B)**
  - `DATABASE_URL` (varsayılan: `sqlite:///data/notices.db`)
  - `FLASK_ENV` (varsayılan: `production`)

Bu değişkenleri proje kök dizininde `.env` dosyası oluşturarak veya docker-compose komutu ile environment üzerinden kolayca verebilirsiniz.

### Projeyi Çalıştırma

Proje kök klasöründe (`interpol-watcher`) aşağıdaki komutu çalıştırın:

```bash
docker-compose up --build
```

Bu komut:

- `rabbitmq` servisini (yönetim paneli ile beraber),
- `fetcher` servisini (periyodik veri toplayıcı),
- `web` servisini (Flask web arayüzü ve RabbitMQ consumer)

olarak üç containerı birlikte ayağa kaldırır.

Çalıştıktan sonra:

- Web arayüzü: `http://localhost:8000`
- RabbitMQ yönetim paneli: `http://localhost:15672` (kullanıcı adı/şifre varsayılan `guest`/`guest`)

Fetcher, Interpol API'sine her `INTERPOL_FETCH_INTERVAL_SECONDS` saniyede bir istek atar ve son kırmızı bültenleri çekip kuyruğa yazar. Web container'ı içindeki consumer thread RabbitMQ kuyruğunu dinler, gelen mesajları SQLite veritabanına kaydeder ve ana sayfadaki tabloyu güncel tutar.

### Uygulama Davranışı

- **Yeni kayıt**: Kuyruktan gelen ve veritabanında daha önce bulunmayan `entity_id` değerine sahip kişiler yeni kayıt olarak işaretlenir.
- **Güncellenen kayıt (alarm)**: Aynı `entity_id` için yeni bir mesaj alınırsa, ilgili veritabanı kaydı güncellenir ve `is_updated = True` alanı set edilir. Arayüzde bu satır **kırmızı kenarlık ve "ALARM – Güncellendi" etiketi** ile işaretlenir.
- **Zaman bilgisinin gösterimi**:
  - `created_at`: İlk kayıt zamanını,
  - `updated_at`: Son güncelleme zamanını
  gösterir.

Arayüz, son 100 kaydı (en yeni en üstte olacak şekilde) listeler.

### Testleri Çalıştırma

Lokal ortamda (opsiyonel) testleri çalıştırmak için:

```bash
pip install -r requirements.txt
pytest
```

Mevcut testler:

- `tests/test_interpol_client.py`: Interpol API istemcisinin dönen JSON yapısını doğru şekilde `RedNotice` nesnelerine dönüştürdüğünü doğrular (HTTP isteği `monkeypatch` ile sahte response üzerinden test edilir).

İsterseniz benzer şekilde:

- Veritabanı modeli (`Notice`) ve
- RabbitMQ consumer davranışı

için de ek ünite testleri yazabilirsiniz.

### Klasör Yapısı

- `docker-compose.yml`: Üç container'ın orkestrasyon dosyası.
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

