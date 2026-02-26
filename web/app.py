from __future__ import annotations

import logging

from flask import Flask, render_template

from .config import WebConfig
from .consumer import QueueConsumer
from .models import Notice, create_session_factory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("web")


def create_app() -> Flask:
    config = WebConfig.from_env()
    SessionFactory = create_session_factory(config)

    app = Flask(__name__, template_folder="templates")

    consumer = QueueConsumer(config)
    consumer.start_in_thread()

    @app.route("/")
    def index():
        session = SessionFactory()
        try:
            notices = (
                session.query(Notice)
                .order_by(Notice.created_at.desc())
                .limit(100)
                .all()
            )
        finally:
            session.close()
        return render_template("index.html", notices=notices)

    return app


app = create_app()

