"""Server-Sent Events yöneticisi: bağlı istemcilere gerçek zamanlı bildirim gönderir."""
from __future__ import annotations

import queue
import threading

# SSE kuyruk kapasitesi ve ping aralığı
_QUEUE_SIZE = 20
_PING_TIMEOUT_SECONDS = 25


class SSEManager:
    """Consumer yeni veri işlediğinde tüm bağlı SSE istemcilerine bildirim gönderir. Bağlantıları canlı tutmak için periyodik pingler içerir."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: list[queue.Queue] = []

    def notify(self, event: str) -> None:
        """Consumer tarafından çağrılır.Tüm bağlı istemcilere olay gönderir. Dolu kuyruklar temizlenir."""
        with self._lock:
            dead: list[queue.Queue] = []
            for q in self._clients:
                try:
                    q.put_nowait(event) #yani event client kuyruğuna atılır
                except queue.Full: 
                    dead.append(q)
            for q in dead:
                self._clients.remove(q)

    def stream_generator(self):
        """SSE formatında veri akışı üretir. Bağlantıyı canlı tutmak için periyodik ping gönderir."""
        client_q: queue.Queue = queue.Queue(maxsize=_QUEUE_SIZE)
        with self._lock:
            self._clients.append(client_q)
        try:
            yield "data: connected\n\n"
            while True:
                try:
                    event = client_q.get(timeout=_PING_TIMEOUT_SECONDS)
                    yield f"data: {event}\n\n"
                except queue.Empty:
                    yield ": ping\n\n"
        finally:
            with self._lock:
                if client_q in self._clients:
                    self._clients.remove(client_q)
