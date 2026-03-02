from __future__ import annotations

import logging
import os
import queue
import threading

import requests as _requests
from flask import Flask, render_template, request, jsonify, send_file, Response

from .config import WebConfig
from .consumer import QueueConsumer
from .models import Notice, create_session_factory

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
#  Photo proxy — singleton requests.Session with Interpol warmup      #
# ------------------------------------------------------------------ #
_INTERPOL_BASE = "https://ws-public.interpol.int"
_PHOTO_CACHE_DIR = os.getenv("PHOTO_CACHE_DIR", "/data/photos")
_photo_session: _requests.Session | None = None

# ------------------------------------------------------------------ #
#  Server-Sent Events — broadcast to all connected browser tabs        #
# ------------------------------------------------------------------ #
_sse_lock: threading.Lock = threading.Lock()
_sse_clients: list[queue.Queue] = []


def _sse_notify(event: str) -> None:
    """Push an event string to every connected SSE client (thread-safe)."""
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try:
                q.put_nowait(event)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)


def _get_photo_session() -> _requests.Session:
    """
    Lazily create (and warm up) a requests.Session for fetching Interpol photos.

    The warmup GET to interpol.int sets the browser-like cookies that the
    API expects, mirroring what InterpolClient does in the fetcher.
    """
    global _photo_session
    if _photo_session is None:
        s = _requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "same-site",
        })
        try:
            s.get("https://www.interpol.int/", timeout=10)
            logger.info("Photo proxy session warmed up")
        except Exception as exc:
            logger.warning("Photo session warmup failed (proceeding anyway): %s", exc)
        _photo_session = s
    return _photo_session


def create_app() -> Flask:
    """
    Flask application factory.

    Creates the SQLAlchemy session factory, sets up the RabbitMQ consumer
    daemon thread, and registers all routes.  Called once at startup (and
    again per test fixture when TESTING=True).
    """
    # Configure logging once at app-factory time (guard prevents double-init
    # when create_app is called multiple times in tests).
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        )

    config = WebConfig.from_env()
    SessionFactory = create_session_factory(config)

    app = Flask(__name__, template_folder="templates")

    consumer = QueueConsumer(config, on_change=_sse_notify)
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

    @app.route("/api/stream")
    def sse_stream():
        """
        Server-Sent Events endpoint.

        The browser keeps a persistent connection here.  Whenever the
        RabbitMQ consumer saves a new or updated notice, _sse_notify()
        puts a message in the client's queue and the browser receives
        it instantly — no polling delay.

        A keepalive comment (': ping') is sent every 25 s so proxies and
        browsers don't close the idle connection.
        """
        def generate():
            client_q: queue.Queue = queue.Queue(maxsize=20)
            with _sse_lock:
                _sse_clients.append(client_q)
            try:
                yield "data: connected\n\n"
                while True:
                    try:
                        event = client_q.get(timeout=25)
                        yield f"data: {event}\n\n"
                    except queue.Empty:
                        yield ": ping\n\n"  # keepalive
            finally:
                with _sse_lock:
                    if client_q in _sse_clients:
                        _sse_clients.remove(client_q)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
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

    @app.route("/api/photo/<path:entity_id>")
    def photo_proxy(entity_id: str):
        """
        Image proxy for Interpol red notice photos.

        Flow:
          1. Sanitise entity_id to dash format (e.g. '1993-27493').
          2. Return the file from disk cache (/data/photos/) if already saved.
          3. Otherwise look up the stored thumbnail_url in the DB; if absent,
             derive it from the entity_id (Interpol's standard URL pattern).
          4. Fetch the image from Interpol using a session with warmup cookies.
          5. Persist to disk cache so subsequent requests are instant.
          6. Return image bytes with the correct Content-Type.

        Returns HTTP 404 (empty body) when Interpol has no photo for this entity.
        """
        # Normalise: slash-format entity_ids from DB → dash-format for URL/file
        safe = entity_id.replace("/", "-").replace("..", "").strip("/")
        cache_path = os.path.join(_PHOTO_CACHE_DIR, safe + ".jpg")

        # ── 1. Serve from disk cache ──────────────────────────────────────────
        if os.path.isfile(cache_path):
            return send_file(cache_path, mimetype="image/jpeg")

        # ── 2. Determine source URL ──────────────────────────────────────────
        # Try to get the stored URL from the DB first (most accurate)
        db_session = SessionFactory()
        try:
            # Entity is stored in DB with slash format
            slash_id = safe.replace("-", "/", 1)  # only first dash is the year separator
            notice = (
                db_session.query(Notice)
                .filter(Notice.entity_id == slash_id)
                .one_or_none()
            )
            thumbnail_url = (
                notice.thumbnail_url if notice and notice.thumbnail_url
                else f"{_INTERPOL_BASE}/notices/v1/red/{safe}/images/1/thumbnail"
            )
        finally:
            db_session.close()

        # ── 3. Fetch from Interpol ────────────────────────────────────────────
        try:
            resp = _get_photo_session().get(thumbnail_url, timeout=15)
            if resp.status_code == 200 and resp.content:
                os.makedirs(_PHOTO_CACHE_DIR, exist_ok=True)
                with open(cache_path, "wb") as fh:
                    fh.write(resp.content)
                logger.info("Cached photo for %s (%d bytes)", safe, len(resp.content))
                return send_file(
                    cache_path,
                    mimetype=resp.headers.get("Content-Type", "image/jpeg"),
                )
            logger.debug("No photo for %s — Interpol returned %d", safe, resp.status_code)
        except Exception as exc:
            logger.warning("Photo fetch failed for %s: %s", safe, exc)

        return ("", 404)

    return app


app = create_app()

