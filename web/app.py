from __future__ import annotations

import logging

from flask import Flask, render_template, request, jsonify, send_file, Response

from .config import WebConfig
from .consumer import QueueConsumer
from .models import Notice, create_session_factory
from .photo import PhotoProxy
from .sse import notify as _sse_notify, stream_generator

logger = logging.getLogger(__name__)



def create_app() -> Flask:
    # Guard prevents double-init when create_app is called multiple times in tests.
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        )

    config = WebConfig.from_env()
    SessionFactory = create_session_factory(config)
    proxy = PhotoProxy(SessionFactory)

    app = Flask(__name__, template_folder="templates")

    consumer = QueueConsumer(config, on_change=_sse_notify)
    consumer.start_in_thread()

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
                # match on either primary nationality or the comma-separated all_nationalities string
                query = query.filter(
                    (Notice.nationality == nat)
                    | Notice.all_nationalities.ilike(f"%{nat}%")
                )

            total = query.count()
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
            total_alarms = (
                session.query(Notice)
                .filter(Notice.is_updated == True)  # noqa: E712
                .count()
            )
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
        return Response(
            stream_generator(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.route("/api/status")
    def api_status():
        session = SessionFactory()
        try:
            total = session.query(Notice).count()
            alarms = session.query(Notice).filter(Notice.is_updated == True).count()  # noqa: E712
        finally:
            session.close()
        return jsonify({"total": total, "alarms": alarms})

    @app.route("/api/photo/<path:entity_id>")
    def photo_proxy(entity_id: str):
        cache_path, status, mime = proxy.get(entity_id)
        if status == 404:
            return ("", 404)
        return send_file(cache_path, mimetype=mime or "image/jpeg")

    return app


app = create_app()

