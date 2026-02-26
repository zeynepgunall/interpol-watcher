"""
app.py - Flask uygulaması ve Socket.IO entegrasyonu.
Web sunucusunun tüm route'larını ve event'lerini tanımlar.
"""

import logging
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO

from config import Config
from database import Database
from consumer import QueueConsumer

logger = logging.getLogger(__name__)


def create_app() -> tuple:
    """
    Flask uygulamasını ve tüm bileşenlerini oluşturur.
    
    Returns:
        tuple: (Flask app, SocketIO instance)
    """
    config = Config()

    # Flask ve SocketIO başlat
    app = Flask(__name__)
    app.secret_key = config.SECRET_KEY
    
    # eventlet async_mode: production ortamı için uygun
    socketio = SocketIO(app, async_mode="eventlet", cors_allowed_origins="*")

    # Veritabanı ve consumer oluştur
    db = Database(config.DB_PATH)
    consumer = QueueConsumer(
        host=config.RABBITMQ_HOST,
        port=config.RABBITMQ_PORT,
        user=config.RABBITMQ_USER,
        password=config.RABBITMQ_PASS,
        queue_name=config.QUEUE_NAME,
        db=db,
        socketio=socketio
    )

    # ─────────────────────────────────────────
    # HTTP Route'lar
    # ─────────────────────────────────────────

    @app.route("/")
    def index():
        """Ana sayfa: tüm kayıtları gösterir."""
        notices = db.get_all()
        stats = db.get_stats()
        return render_template("index.html", notices=notices, stats=stats)

    @app.route("/api/notices")
    def api_notices():
        """JSON formatında tüm kayıtları döner (API endpoint)."""
        notices = db.get_all()
        return jsonify({"notices": notices, "count": len(notices)})

    @app.route("/api/stats")
    def api_stats():
        """İstatistikleri JSON olarak döner."""
        return jsonify(db.get_stats())

    # ─────────────────────────────────────────
    # Socket.IO Event'leri
    # ─────────────────────────────────────────

    @socketio.on("connect")
    def on_connect():
        """İstemci bağlandığında mevcut verileri gönder."""
        logger.info("Yeni istemci bağlandı.")

    @socketio.on("disconnect")
    def on_disconnect():
        logger.info("İstemci bağlantısı kesildi.")

    # Consumer'ı başlat (ayrı thread'de)
    consumer.start()

    return app, socketio, config
