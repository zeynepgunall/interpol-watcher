from __future__ import annotations

import logging

from flask import Flask, render_template, request, jsonify

from .config import WebConfig
from .consumer import QueueConsumer
from .models import Notice, create_session_factory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("web")


def create_app() -> Flask:
    """
    Flask application factory.

    Creates the SQLAlchemy session factory, sets up the RabbitMQ consumer
    daemon thread, and registers all routes.  Called once at startup (and
    again per test fixture when TESTING=True).
    """
    config = WebConfig.from_env()
    SessionFactory = create_session_factory(config)

    app = Flask(__name__, template_folder="templates")

    consumer = QueueConsumer(config)
    consumer.start_in_thread()

    @app.route("/")
    def index():
        """
        Main listing page.

        Supports optional query params:
          ?q=<name search>   — case-insensitive substring match on name/forename
          ?nat=<ISO-2 code>  — filter by nationality or all_nationalities
          ?page=<int>        — pagination (200 records per page, default 1)

        Notices are ordered: alarms first, then newest first.
        """
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
                # all_nationalities virgüllü string; her iki alanı da kontrol et
                # (örn. nationality='DE' ama all_nationalities='DE,TR' olan kişi TR filtresinde görünsün)
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

    @app.route("/api/status")
    def api_status():
        """
        JSON status endpoint consumed by the front-end JS poller.

        Returns::

            {"total": <int>, "alarms": <int>}

        The browser polls this every 30 s and triggers a full page reload
        only when either counter has changed since the last load.
        """
        session = SessionFactory()
        try:
            total = session.query(Notice).count()
            alarms = session.query(Notice).filter(Notice.is_updated == True).count()  # noqa: E712
        finally:
            session.close()
        return jsonify({"total": total, "alarms": alarms})

    return app


app = create_app()

