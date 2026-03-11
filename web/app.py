"""Flask web uygulamasını kaldırır,gerekli bileşenleri bağlar,HHTP Endpointleri tanımlar,RabbitMQ consumer'ını başlatır."""
from __future__ import annotations

import logging

from flask import Flask, render_template, request, jsonify, Response, send_file

from .config import WebConfig
from .consumer import QueueConsumer
from .models import Notice, create_session_factory, get_session
from .photo import photo_exists, photo_path, PLACEHOLDER_SVG
from .sse import SSEManager

logger = logging.getLogger(__name__)

_PER_PAGE = 200


# Flask uygulamasını oluşturur, RabbitMQ consumer'ı başlatır ve HTTP endpoint'lerini tanımlar.
def create_app() -> Flask:
    if not logging.root.handlers:
        #logging ayarlanır
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        )
    #config ve bağımlılıklar oluşturulur,env vars'den config okunur,DB session factory oluşturulur, SSE manager oluşturulur.
    config = WebConfig.from_env()
    session_factory = create_session_factory(config) #veritabanı bağlantısı için session factory oluşturur
    sse_manager = SSEManager() #UI’a gerçek zamanlı event göndermek için SSE manager oluşturuluyor.

    app = Flask(__name__, template_folder="templates") #Flask uygulaması başlat

    consumer = QueueConsumer(config, on_change=sse_manager.notify) #değişiklik olduğunda sse_manager.notify() çağrılır, bu da bağlı SSE istemcilerine bildirim gönderir.
    consumer.start_in_thread() #RabbitMQ consumer'ı ayrı bir thread'de başlatır, böylece ana thread HTTP isteklerini işleyebilir. 

    @app.route("/") #Ana sayfa endpoint'i: notice'leri listeler, arama ve filtreleme sağlar, sayfalama yapar.
    def index():
        page = max(1, request.args.get("page", 1, type=int))
        q = request.args.get("q", "").strip()
        nat = request.args.get("nat", "").strip().upper()

        with get_session(session_factory) as session:
            query = session.query(Notice)
            if q:
                like = f"%{q}%"
                query = query.filter(
                    Notice.name.ilike(like) | Notice.forename.ilike(like) # isim veya soyisim araması yapılır, büyük/küçük harf duyarsızdır.
                )
            if nat:
                query = query.filter(
                    (Notice.nationality == nat)
                    | Notice.all_nationalities.ilike(f"%{nat}%") # ulusalite araması yapılır, büyük/küçük harf duyarsızdır.
                )
            total = query.count()

            notices = (
                query.order_by(Notice.is_updated.desc(), Notice.created_at.desc()) #sıralama
                .offset((page - 1) * _PER_PAGE) #sayfalama için offset ve limit uygulanır
                .limit(_PER_PAGE)
                .all()
            )
            nationalities = [
                r[0]
                for r in session.query(Notice.nationality)
                .filter(Notice.nationality.isnot(None))
                .distinct()
                .order_by(Notice.nationality)
                .all()
            ]
            total_alarms = (
                session.query(Notice).filter(Notice.is_updated.is_(True)).count()
            )

        total_pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
        return render_template(
            "index.html",
            notices=notices,
            page=page,
            total_pages=total_pages,
            total=total,
            total_alarms=total_alarms,
            per_page=_PER_PAGE,
            q=q,
            nat=nat,
            nationalities=nationalities,
        )

    @app.route("/api/stream")
    def sse_stream():
        """Tarayıcı bu endpoint'i dinler, değişiklikte sayfa yenilenir.Amaç: UI'a real-time update göndermek"""
        return Response(
            sse_manager.stream_generator(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.route("/photos/<path:entity_id>")
    def serve_photo(entity_id: str):
        """lokal dosya varsa onu, yoksa placeholder SVG döner."""
        if photo_exists(entity_id):
            return send_file(
                photo_path(entity_id),
                mimetype="image/jpeg",
                max_age=86400,
            )
        return Response(
            PLACEHOLDER_SVG,
            mimetype="image/svg+xml",
            headers={"Cache-Control": "no-cache"},
        )

    @app.route("/api/status") #/api/status endpoint’i toplam kayıt ve alarm sayısını JSON olarak döndürüyor.
    def api_status():
        """SSE çalışmazsa polling fallback(belirli aralıklarla kontrol) olarak kullanılır."""
        with get_session(session_factory) as session:
            total = session.query(Notice).count()
            alarms = (
                session.query(Notice).filter(Notice.is_updated.is_(True)).count()
            )
        return jsonify({"total": total, "alarms": alarms})

    return app


app = create_app() #Uygulama oluşturulur, bu app.run() ile çalıştırılır. Flask uygulaması başlatılır, HTTP isteklerini dinlemeye hazır hale gelir.
