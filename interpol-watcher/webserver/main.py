"""
main.py - Webserver Container giriş noktası.
"""

import logging
from app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

if __name__ == "__main__":
    app, socketio, config = create_app()
    
    print(f"""
    ╔══════════════════════════════════════╗
    ║     Interpol Watcher - Web Server    ║
    ╠══════════════════════════════════════╣
    ║  Adres : http://{config.FLASK_HOST}:{config.FLASK_PORT}  ║
    ║  Debug : {str(config.FLASK_DEBUG):<28}║
    ╚══════════════════════════════════════╝
    """)

    socketio.run(
        app,
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG
    )
