from __future__ import annotations
import logging
from flask import Flask, render_template, request, jsonify, Response, send_file
from .config import WebConfig
from .consumer import QueueConsumer
from .models import Notice, create_session_factory
from .photo import photo_exists, photo_path, PLACEHOLDER_SVG, start_backfill_thread
from .sse import notify as _sse_notify, stream_generator

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
        )

    config = WebConfig.from_env()
    SessionFactory = create_session_factory(config)

    app = Flask(__name__, template_folder="templates")

    # RabbitMQ consumer'ı arka planda başlat (daemon thread)
    consumer = QueueConsumer(config, on_change=_sse_notify)
    consumer.start_in_thread()

    # Eksik fotoğrafları arka planda indir (bir kez çalışır)
    start_backfill_thread(SessionFactory, delay=1.5)

    # ── ROUTES ──────────────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        per_page = 200
        page = max(1, request.args.get("page", 1, type=int))
        q = request.args.get("q", "").strip()
        nat = request.args.get("nat", "").strip().upper()

        session = SessionFactory()
        try:
            query = session.query(Notice)
            if q:
                like = f"%{q}%"
                query = query.filter(
                    Notice.name.ilike(like) | Notice.forename.ilike(like)
                )
            if nat:
                query = query.filter(
                    (Notice.nationality == nat) |
                    Notice.all_nationalities.ilike(f"%{nat}%")
                )
            total = query.count()
            # Alarmlar (is_updated=True) en üstte gösterilir
            notices = (
                query
                .order_by(Notice.is_updated.desc(), Notice.created_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )
            nationalities = [
                r[0] for r in
                session.query(Notice.nationality)
                .filter(Notice.nationality.isnot(None))
                .distinct()
                .order_by(Notice.nationality)
                .all()
            ]
            total_alarms = session.query(Notice).filter(Notice.is_updated == True).count()
        finally:
            session.close()

        total_pages = max(1, (total + per_page - 1) // per_page)
        return render_template(
            "index.html",
            notices=notices,
            page=page,
            total_pages=total_pages,
            total=total,
            total_alarms=total_alarms,
            per_page=per_page,
            q=q,
            nat=nat,
            nationalities=nationalities,
        )

    @app.route("/api/stream")
    def sse_stream():
        """Server-Sent Events — tarayıcı bu endpoint'i dinler, değişiklikte sayfa yenilenir."""
        return Response(
            stream_generator(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.route("/photos/<path:entity_id>")
    def serve_photo(entity_id: str):
        """Fotoğraf sunma: lokal dosya → Interpol redirect → placeholder SVG."""
        # 1) Lokal dosya varsa serve et
        if photo_exists(entity_id):
            return send_file(
                photo_path(entity_id),
                mimetype="image/jpeg",
                max_age=86400,
            )
        # 2) Fallback: placeholder SVG
        return Response(PLACEHOLDER_SVG, mimetype="image/svg+xml",
                        headers={"Cache-Control": "no-cache"})

    @app.route("/api/status")
    def api_status():
        """SSE çalışmazsa polling fallback için kullanılır."""
        session = SessionFactory()
        try:
            total = session.query(Notice).count()
            alarms = session.query(Notice).filter(Notice.is_updated == True).count()
        finally:
            session.close()
        return jsonify({"total": total, "alarms": alarms})


    return app


app = create_app()