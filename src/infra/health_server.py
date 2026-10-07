"""health_server.py — Health endpoint HTTP ringan untuk monitoring eksternal.

Endpoint `/health` selalu merespons `OK` selama bot berjalan. Server eksternal
(mis. UptimeRobot yang berada di luar VPS) memantaunya secara berkala; begitu
respons tidak terjawab (karena sistem off / VPS crash), server eksternal itulah
yang mengirim pemberitahuan ke Telegram. Hanya mengandalkan stdlib saja.
"""
from __future__ import annotations

import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("health")

_HEALTH_OK = b"OK"
_HOST      = "0.0.0.0"
_PORT      = 8100


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] in ("/health", "/"):
            body = _HEALTH_OK
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, *_args) -> None:
        # diamkan logging request default agar tidak spam log bot
        pass


class HealthServer:
    """Jalankan HTTP server pada thread daemon."""

    def __init__(self, host: str = _HOST, port: int = _PORT) -> None:
        self._host = host
        self._port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        try:
            self._server = ThreadingHTTPServer((self._host, self._port), _HealthHandler)
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="HealthServer",
                daemon=True,
            )
            self._thread.start()
            log.info(f"Health endpoint aktif → http://{self._host}:{self._port}/health")
        except Exception as e:  # pragma: no cover
            log.warning(f"Gagal menjalankan health endpoint: {e}")

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
