"""Flask web uygulamasını kaldırır,gerekli bileşenleri bağlar,HHTP Endpointleri tanımlar,RabbitMQ consumer'ını başlatır."""
from __future__ import annotations

from sqlalchemy import nullsfirst, nullslast

import json
import logging

from flask import Flask, render_template, request, jsonify, Response, send_file, redirect

from .config import WebConfig
from .consumer import QueueConsumer
from .minio_storage import MinioStorage
from .models import Notice, NoticeChange, create_session_factory, get_session
from .photo import photo_exists, photo_path, PLACEHOLDER_SVG
from .sse import SSEManager

logger = logging.getLogger(__name__)

_PER_PAGE = 200


# Flask uygulamasını oluşturur, RabbitMQ consumer'ı başlatır ve HTTP endpoint'lerini tanımlar.
def create_app() -> Flask:
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        )
    config = WebConfig.from_env()
    session_factory = create_session_factory(config)
    sse_manager = SSEManager()
    minio = MinioStorage(
        endpoint=config.minio_endpoint,
        access_key=config.minio_access_key,
        secret_key=config.minio_secret_key,
        bucket=config.minio_bucket,
        secure=config.minio_secure,
        public_url=config.minio_public_url,
    )

    app = Flask(__name__, template_folder="templates")

    consumer = QueueConsumer(config, on_change=sse_manager.notify)
    consumer.start_in_thread()

    @app.route("/")
    def index():
        page = max(1, request.args.get("page", 1, type=int))
        q = request.args.get("q", "").strip()
        nat = request.args.get("nat", "").strip().upper()
        sort = request.args.get("sort", "newest").strip()

        with get_session(session_factory) as session:
            query = session.query(Notice)
            if q:
                like = f"%{q}%"
                query = query.filter(
                    Notice.name.ilike(like) | Notice.forename.ilike(like)
                )
            if nat:
                query = query.filter(
                    (Notice.nationality == nat)
                    | Notice.all_nationalities.ilike(f"%{nat}%")
                )
            total = query.count()

            if sort == "oldest":
                query = query.order_by(Notice.is_updated.desc(), Notice.created_at.asc())
            elif sort == "name_asc":
                query = query.order_by(Notice.is_updated.desc(), nullsfirst(Notice.name.asc()), nullsfirst(Notice.forename.asc()))
            elif sort == "name_desc":
                query = query.order_by(Notice.is_updated.desc(), nullslast(Notice.name.desc()), nullslast(Notice.forename.desc()))
            else:
                query = query.order_by(Notice.is_updated.desc(), Notice.created_at.desc())

            notices = (
                query
                .offset((page - 1) * _PER_PAGE)
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
            sort=sort,
            nationalities=nationalities,
        )

    @app.route("/api/stream")
    def sse_stream():
        """Tarayıcı bu endpoint'i dinler, değişiklikte sayfa yenilenir."""
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
        """MinIO'dan public URL'e redirect eder. MinIO yoksa local dosyadan, o da yoksa placeholder."""
        if minio.enabled:
            object_name = minio.object_name_for(entity_id)
            if minio.object_exists(object_name):
                return redirect(minio.public_photo_url(entity_id), code=302)
        # MinIO yoksa local fallback
        if photo_exists(entity_id):
            return send_file(photo_path(entity_id), mimetype="image/jpeg", max_age=86400)
        return Response(PLACEHOLDER_SVG, mimetype="image/svg+xml", headers={"Cache-Control": "no-cache"})

    @app.route("/api/status")
    def api_status():
        """SSE çalışmazsa polling fallback olarak kullanılır."""
        with get_session(session_factory) as session:
            total = session.query(Notice).count()
            alarms = (
                session.query(Notice).filter(Notice.is_updated.is_(True)).count()
            )
        return jsonify({"total": total, "alarms": alarms})

    @app.route("/api/notice/<path:entity_id>")
    def api_notice_detail(entity_id: str):
        """
        Tek bir notice'ın tüm detay bilgilerini JSON olarak döner.
        Frontend modal açılırken bu endpoint'i çağırır.
        entity_id URL'de "2025-102375" formatında gelir, DB'de "2025/102375" olarak saklanır.
        """
        normalized = entity_id.replace("-", "/", 1) if "/" not in entity_id else entity_id

        with get_session(session_factory) as session:
            notice = session.query(Notice).filter(Notice.entity_id == normalized).one_or_none()
            if notice is None:
                return jsonify({"error": "Kayıt bulunamadı"}), 404

            # Değişiklik geçmişi
            changes = (
                session.query(NoticeChange)
                .filter(NoticeChange.entity_id == normalized)
                .order_by(NoticeChange.changed_at.desc())
                .limit(50)
                .all()
            )
            change_history = [
                {
                    "field_name": c.field_name,
                    "old_value":  c.old_value,
                    "new_value":  c.new_value,
                    "changed_at": c.changed_at.isoformat() if c.changed_at else None,
                }
                for c in changes
            ]

            return jsonify({
                "entity_id":            notice.entity_id,
                "name":                 notice.name,
                "forename":             notice.forename,
                "date_of_birth":        notice.date_of_birth,
                "nationality":          notice.nationality,
                "all_nationalities":    notice.all_nationalities,
                "arrest_warrant":       notice.arrest_warrant,
                "sex_id":               notice.sex_id,
                "place_of_birth":       notice.place_of_birth,
                "country_of_birth_id":  notice.country_of_birth_id,
                # Suç
                "charges":              notice.charges,
                "charge_translation":   notice.charge_translation,
                "issuing_countries":    notice.issuing_countries,
                # Fiziksel
                "height":               notice.height,
                "weight":               notice.weight,
                "eyes_colors_id":       notice.eyes_colors_id,
                "hairs_id":             notice.hairs_id,
                "distinguishing_marks": notice.distinguishing_marks,
                # Dil
                "languages_spoken":     notice.languages_spoken,
                # Fotoğraflar
                "image_urls":           json.loads(notice.image_urls or "[]"),
                "photo_url":            notice.photo_url,
                # Meta
                "is_updated":           notice.is_updated,
                "created_at":           notice.created_at.isoformat() if notice.created_at else None,
                "updated_at":           notice.updated_at.isoformat() if notice.updated_at else None,
                "detail_fetched_at":    notice.detail_fetched_at.isoformat() if notice.detail_fetched_at else None,
                # Değişiklik geçmişi
                "change_history":       change_history,
            })

    return app


app = create_app()
