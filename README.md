# Interpol Red Notice Watcher

Interpol tarafından yayınlanan kırmızı bülten (Red Notice) verilerini periyodik olarak izleyen, RabbitMQ üzerinden asenkron olarak işleyen, verileri PostgreSQL veritabanında saklayan ve web arayüzünde modern bir tasarımla anlık ("alarm") sunan, tamamen Dockerize edilmiş bir mikroservis projesi.

---

## 📌 İçindekiler
- [Mimari ve Çalışma Mantığı](#mimari-ve-çalişma-mantiği)
- [Öne Çıkan Özellikler](#öne-çikan-özellikler)
- [Gereksinimler](#gereksinimler)
- [Hızlı Kurulum (Docker ile)](#hizli-kurulum-docker-ile)
- [Çevresel Değişkenler (.env)](#çevresel-değişkenler-env)
- [Web Arayüzü ve Sistem Davranışları](#web-arayüzü-ve-sistem-davranişlari)
- [Fotoğrafları Yerel Olarak İndirme](#fotoğraflari-yerel-olarak-i̇ndirme)
- [Birim Testleri (Pytest)](#birim-testleri-pytest)
- [Geliştirici Notları ve İpuçları](#geliştirici-notlari-ve-i̇puçlari)

---

## 🏛️ Mimari ve Çalışma Mantığı

Sistem temel olarak 3 ayrı Docker konteynerinden (Fetcher, RabbitMQ, Web+Consumer+DB) oluşur ve aralarındaki asenkron mesajlaşma sayesinde birbirlerini bloke etmeden çalışırlar:

```text
┌─────────────────────────────────────────────────────────────────┐
│                       docker-compose                            │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐   │
│  │ Container A  │    │ Container B  │    │   Container C    │   │
│  │   fetcher  ──│───▶│   rabbitmq ──│───▶│ web + consumer   │   │
│  │ (python loop)│    │(mesaj kuyruğu)    │ (flask + thread) │   │
│  └──────────────┘    └──────────────┘    └──────────────────┘   │
│         │                                        │              │
│       ┌─┴────────────────────────────────────────┴─┐            │
│       │                 volumes                    │            │
│       │ postgresql_data      web_data (scan_state) │            │
│       └────────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

1. **Fetcher (Container A):** 
   - Interpol public API'sini parametrelerle (`INTERPOL_FETCH_INTERVAL_SECONDS` vb.) periyodik olarak tarar.
   - Yaş aralığı ve uyruk bazlı (özel yüksek riskli ülkeler vb.) kombine pass'ler göndererek API sınırını aşmayı başarır.
   - Elde ettiği `RedNotice` nesnelerini bir JSON payload'u haline getirip **RabbitMQ**'ya fırlatır.
   - Her tur sonrasında ilerlemesini container-volume içindeki `scan_state.json`'a işler (Çökme durumunda kaldığı yerden devam edebilmesi için *crash-safe* tasarlanmıştır).

2. **RabbitMQ (Container B):** 
   - İletişim için dayanıklı (`durable`) AMQP mesaj kuyruğudur. Fetcher'ın hız bağımsız olarak ilettiği mesajları PostgreSQL'e veya Consumer thread'ine güvenli şekilde paslar. Yönetim paneli `http://localhost:15672` tadır.

3. **Web + Consumer + Postgres (Container C & D):**
   - **Consumer (Daemon Thread):** Arka planda `pika` kütüphanesi ile RabbitMQ'yu dinler. `entity_id` eşsiz olacak şekilde PostgreSQL DB'sine kayıt girer (INSERT) veya eski kayıt güncellendiyse bunu işaretler (`is_updated=True`).
   - **Postgres (Database):** Web uygulamasının ve Consumer'ın ortak veritabanıdır (`interpol_db`). Özel `volume` sayesinde restart'ta bile korunan veri depolar.
   - **Web UI (Flask):** SQLite/PostgreSQL fark etmeksizin DB'yi sorgular ve modern bir arayüzde yayınlar. JS Polling mantığı sayesinde arayüzdeki veriler her 30 saniyede bir otomatik canlanır.

---

## 🚀 Öne Çıkan Özellikler

- **Crash-Safe Scan:** Çok uzun süren Interpol taramasında internet koparsa ve script kapanırsa bile `scan_state.json` ile kalındığı bloktan devam edebilme.
- **Asenkron Kuyruk (RabbitMQ):** Veri toplayıcısının (Fetcher) bekleme yapmadan sadece mesaj gönderme görevini üstlenmesi performansı son derece arttırır.
- **Güçlü Veritabanı (PostgreSQL):** Docker compose üzerinde otomatik olarak hazır hâle gelen veritabanı yığını.
- **Anında Alarmlar (UI):** Zaten sistemde olan bir kişi, bir süre sonra Interpol tarafından güncellenirse (örneğin yeri tespit edildi vs.) Consumer bu kaydı veritabanında "🔴 ALARM" olarak (kırmızı nabız efektiyle) belirgin hâle getirir.
- **Batch Resim İndiricisi:** Şüphelilerin fotoğraflarını direkt diske indiren anti-ban özellikli asenkron (delaylı) ekstra Script. 

---

## ⚙️ Gereksinimler

Proje hiçbir ekstra bağımlılığa ihtiyaç duymadan, doğrudan `docker` altyapısı ile her şeyi ayağa kaldırmaktadır. Sadece şunların yüklü olması gerekir:
- **Docker** ve **Docker Compose**

*(Geliştirme veya testing amacı ile local çalıştıracaksanız `Python 3.11+` tavsiye edilir.)*

---

## 🛠️ Hızlı Kurulum (Docker ile)

Gereksinimler sağlandıktan sonra terminal üzerinden sadece 2 komutla tüm sistemi ayağa kaldırabilirsiniz:

```bash
# 1. Repoyu klonlayıp içine girin
git clone <repo-url> interpol-watcher
cd interpol-watcher

# 2. Örnek konfigürasyon dosyasını (ENV) yaratın ve isterseniz değiştirin
cp .env.example .env

# 3. Tüm sistemi arka planda (detached) orkestre edin
docker-compose up --build -d
```

Compose dosyası `depends_on` ile önce **PostgreSQL** ve **RabbitMQ** altyapısının ayağa kalkmasını, sonrasında **Web** sunucusu ve **Fetcher** container'ının güvenle başlatılmasını sağlayacaktır.

```bash
# Servis durumlarını izlemek için loglar:
docker-compose logs -f fetcher    # Fetcher'ın API ile olan trafiğini görmek için
docker-compose logs -f web        # Gelen Consumer logları ve Web trafiği
```

---

## 🌐 Web Arayüzü ve Sistem Davranışları

1. **Erişim:** [http://localhost:8000](http://localhost:8000) adresine gittiğinizde web paneli açılacaktır.
2. **Kırmızı Alarm:** 
   - Kartların etrafında yanıp sönen bir kırmızı çerçeve görürseniz bu kişi **zaten sistemde kayıtlıdır** ve farklı veya aynı verilerle tekrar sisteme girdiği anlaşıldığı için *ALARMA* dönüşmüştür.
3. **Gerçek Zamanlılık (Polling):** `index.html` içinde çalışan bir JavaScript periyodik olarak her 30 saniyede bir Flask `/api/status` endpoint'ine gider. Eğer toplam alarm sayısı veya toplam kişi sayısında bir değişiklik varsa F5'e basmasanız dahi verileri günceller.
4. **Filtreler:** Uygulamanın üst sekmesindeki input barlardan Şüpheli Adı ve **Uyruğu (Örn: IN, PK, TR)** filtreleyebilirsiniz.

---

## 🔑 Çevresel Değişkenler (.env)

Projeyi derlemeden (rebuild yapmadan) ayarları değiştirebileceğiniz çevreleyici (.env) değişkenlerden bazıları şunlardır:

### Ortak Veritabanı ve Mesajlaşma Konfigürasyonları
| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `DATABASE_URL` | `postgresql://interpol:interpol123@postgres:5432/interpol_db` | PostgreSQL veritabanı URI adresi |
| `RABBITMQ_HOST` | `rabbitmq` | Docker compose içindeki local ağ alias'ı |
| `RABBITMQ_PORT` | `5672` | AMQP standart portu |

### Fetcher (Container A) Özelleştirmeleri
| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `INTERPOL_BASE_URL` | `https://ws-public.interpol.int` | Interpol public API URL |
| `INTERPOL_FETCH_INTERVAL_SECONDS` | `300` | Ne sıklıkla döngülerin tamamlanıp baştan aranacağı (Saniye) |
| `REQUEST_DELAY_SECONDS` | `3.0` | IP engeli almamak (403 ban) için API call'ları arasında ne kadar yavaşlanacağı |
| `VERY_HIGH_NATIONALITIES_1YR` | `IN,PK` | Çok fazla suç barındırdığı için çok dar bir parametrede incelenecek ülkeler |
| `ENABLE_PASS_AGE_0_9` | `true` | Çok geniş yaş grubu interpollerinde bebek/çocuk bandını inceler |

---

## 🖼️ Fotoğrafları Yerel Olarak İndirme

Şüphelere ait fotoğrafların internet erişimleri (Interpol API kısıtlamaları veya expire olması) kapanabilir diye ayrı olarak fotoğrafları veritabanından bulup local diske indirecek özel bir helper (yardımcı script) vardır:

**Kurulumu ve Kullanımı:**
Kendi ana işletim sisteminizde (bilgisayarınızda) bağımlılıkları yükleyin:
```bash
pip install requests psycopg2-binary
```
Scripti çalıştırın:
```bash
python download_photos.py
```
- DB'ye dışarıdan (`localhost:5432` üzerinden) bağlanarak photo URL bulur.
- Random bekleme (delay) ekleyerek Interpol IP-Ban korumasından kurtulur.
- Inen .jpg dosyalarını `./photos/` içerisine kaydeder.
- Bu işlem bittikten sonra inen dosyaları Web Container'a atabilirsiniz:
  ```bash
  docker cp photos/. interpol_web:/data/photos/
  ```

---

## 🧪 Birim Testleri (Pytest)

Projenin test coverage'ı çok yüksek olacak şekilde `pytest` kullanılarak oluşturulmuştur. Testleri container haricinde kendi ortamınızda test edebilirsiniz. Gerekli kütüphaneleri `pip install -r requirements.txt` ile kurduktan sonra:

```bash
# Tüm Testleri çalıştır
pytest -v

# Sadece Fetcher modülünün spesifik Interpol API MOCK testlerini çalıştır
pytest tests/test_interpol_client.py -v

# Sadece RabbitMQ Queue/Consumer yapısını ve DB logic'ini test et
pytest tests/test_consumer.py -v
```

**Not:** Testler hiçbir zaman PostgreSQL ve RabbitMQ araması yapmamaktadır. Memory içi Local veri kaynağı veya Mocking kullanarak simüle edilmiştir.

---

## 👨‍💻 Geliştirici Notları ve İpuçları

- **RabbitMQ Dashboard:** `http://localhost:15672` üzerinden girebilirsiniz (Varsayılan User: `guest` Pass: `guest`). Queues tablonuz içinde `interpol_red_notices` öğesine tıklayarak "Purge" diyerek içerdeki sıkışmış tüm eski verileri silme şansınız var.
- **Fetch Tarama Belleğini Sıfırlamak:** Tarama döngüsü çok uzun olduğu için `fetcher` kaldığı yerden devam edecektir. Veriyi kasıtlı sildiniz ve en baştan çekmek isterseniz terminale şunu girerek `state` dosyasını sıfırlayabilirsiniz:
  ```bash
  docker exec interpol_fetcher rm -f /data/scan_state.json
  docker restart interpol_fetcher
  ```
- **Farklı Veritabanı Geçişi:** PostgreSQL yerine tekrar bir Local SQLite veya MySQL geçmek isterseniz docker compose dosyasındaki `DATABASE_URL` adreslerini uygun SQLAlchemy diline çevirmeniz yeterlidir; kod yapısı ORM olduğundan kod tarafında tek değişim yapmanız gerekmez.

---
_Bu README otonom bir sistem ile Interpol projeniz için kapsamlı olarak hazırlanmıştır._
