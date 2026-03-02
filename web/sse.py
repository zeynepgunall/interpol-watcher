"""Server-Sent Events: shared state, broadcast helper, and stream generator."""
from __future__ import annotations

import queue
import threading

_lock: threading.Lock = threading.Lock()
_clients: list[queue.Queue] = []


def notify(event: str) -> None:
    """Push an event string to every connected SSE client (thread-safe)."""
    with _lock:
        dead = []
        for q in _clients:
            try:
                q.put_nowait(event)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _clients.remove(q)


def stream_generator():
    """Yield SSE-formatted lines; keeps the connection alive with periodic pings."""
    client_q: queue.Queue = queue.Queue(maxsize=20)
    with _lock:
        _clients.append(client_q)
    try:
        yield "data: connected\n\n"
        while True:
            try:
                event = client_q.get(timeout=25)
                yield f"data: {event}\n\n"
            except queue.Empty:
                yield ": ping\n\n"  # keepalive so proxies don't close idle connections
    finally:
        with _lock:
            if client_q in _clients:
                _clients.remove(client_q)
