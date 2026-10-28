"""Fail-closed HTTP maintenance state for a rate-limited provider recovery vault.

Used ONLY after an authenticated boot recovery check receives HTTP 429.
This mode never loads browser runtime, decrypts profiles, creates sessions,
accepts MCP/owner actions, or treats a previous verification as current.
"""
from __future__ import annotations

import json
import threading
import time
import httpx
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from provider_recovery_gate import RecoveryRateLimited

RETRY_SECONDS = 900
MAX_EXPONENTIAL_BACKOFF = 21600  # 6 hours absent a longer explicit Retry-After  # 15 minutes, rather than a rapid crash/restart loop.
REASON = "AI_BROWSER_RECOVERY_PROVIDER_RATE_LIMITED"


def verify_provider_idle(steel_api_key: str, *, client: httpx.Client | None = None) -> bool:
    """Read-only independent Steel live-session inventory before leaving 429 mode.

    Fail closed on any non-200, unexpected shape, redirects, active sessions,
    or exceptions. This never releases/adopts a provider session.
    """
    if not steel_api_key:
        raise RuntimeError("RECOVERY_PROVIDER_CREDENTIAL_UNAVAILABLE")
    owned = client is None
    if owned:
        client = httpx.Client(timeout=httpx.Timeout(15, connect=8),
                              follow_redirects=False, trust_env=False)
    try:
        response = client.get("https://api.steel.dev/v1/sessions",
                              params={"status": "live", "limit": 100},
                              headers={"steel-api-key": steel_api_key},
                              follow_redirects=False)
        if response.status_code != 200 or len(response.content) > 2_000_000:
            raise RuntimeError("RECOVERY_PROVIDER_INVENTORY_UNAVAILABLE")
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError("RECOVERY_PROVIDER_INVENTORY_INVALID") from None
        if not isinstance(data, dict) or data.get("sessions") != []:
            raise RuntimeError("RECOVERY_PROVIDER_LIVE_OR_UNCONFIRMED")
        return True
    except httpx.HTTPError:
        raise RuntimeError("RECOVERY_PROVIDER_INVENTORY_UNAVAILABLE") from None
    finally:
        if owned:
            client.close()


class _MaintenanceHandler(BaseHTTPRequestHandler):
    server_version = "AI-Browser-Maintenance"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    def log_message(self, _format: str, *_args: object) -> None:
        # Do not log paths/query parameters: OAuth callbacks may contain codes.
        pass

    def _response(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Retry-After", str(max(
            RETRY_SECONDS, int(getattr(self.server, "next_retry_seconds", RETRY_SECONDS)))))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _serve(self) -> None:
        route = self.path.split("?", 1)[0]  # route is never logged or echoed.
        if self.command in {"GET", "HEAD"} and route in {"/health", "/"}:
            # A healthy TCP listener is not evidence of an available browser.
            if route == "/health":
                body = json.dumps({"status": "degraded", "browser_available": False,
                                   "recovery_confirmed": False, "error": REASON,
                                   "retry_after_seconds": max(
                                       RETRY_SECONDS, int(getattr(
                                           self.server, "next_retry_seconds", RETRY_SECONDS)))}).encode()
                return self._response(200, body, "application/json; charset=utf-8")
            body = ("<!doctype html><meta charset='utf-8'><title>AI Browser — tryb ochronny</title>"
                    "<h1>AI Browser — tryb ochronny</h1>"
                    "<p>Magazyn sesji ogranicza liczbę żądań. "
                    "Przeglądarka pozostaje zablokowana do bezpiecznej weryfikacji. "
                    "Nie wpisuj ponownie haseł.</p>").encode("utf-8")
            return self._response(200, body, "text/html; charset=utf-8")
        body = json.dumps({"error": REASON, "retryable": True,
                           "browser_available": False, "recovery_confirmed": False}).encode()
        return self._response(503, body, "application/json; charset=utf-8")

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = _serve


class _Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def wait_until_recovered(
    gate: Callable[[], object], provider_quiet: Callable[[], bool],
    *, host: str = "0.0.0.0", port: int = 10000,
    retry_seconds: float = RETRY_SECONDS,
    initial_retry_seconds: float | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    server_factory: Callable = _Server,
) -> None:
    """Hold a truthful limited HTTP surface while all privileged actions fail.

    The real app only starts after BOTH fresh vault recovery and independent
    empty Steel provider inventory. Unknown results never become approval.
    """
    if (not 1 <= port <= 65535 or not isinstance(retry_seconds, (int, float))
            or not 1 <= retry_seconds <= 604800
            or (initial_retry_seconds is not None and
                (not isinstance(initial_retry_seconds, (int, float))
                 or not 1 <= initial_retry_seconds <= 604800))):
        raise RuntimeError("RECOVERY_MAINTENANCE_CONFIG_INVALID")
    delay = max(retry_seconds, initial_retry_seconds or retry_seconds)
    httpd = server_factory((host, port), _MaintenanceHandler)
    thread = threading.Thread(target=httpd.serve_forever, name="aib-maintenance", daemon=True)
    thread.start()
    print("AI_BROWSER_MAINTENANCE_ENTER " + REASON, flush=True)
    try:
        while True:
            # Expose only the bounded wait; never a provider token or response.
            httpd.next_retry_seconds = int(delay)
            sleeper(delay)
            try:
                gate()
            except RecoveryRateLimited as exc:
                # Respect an explicit upstream window, otherwise exponential
                # backoff prevents hammering a daily hosting cap every 15 min.
                delay = max(exc.retry_after_seconds,
                            min(max(delay * 2, retry_seconds),
                                MAX_EXPONENTIAL_BACKOFF))
                print("AI_BROWSER_MAINTENANCE_HOLD RECOVERY_RATE_LIMITED", flush=True)
                continue
            except Exception:
                delay = retry_seconds
                print("AI_BROWSER_MAINTENANCE_HOLD RECOVERY_UNCONFIRMED", flush=True)
                continue
            try:
                if provider_quiet() is not True:
                    raise RuntimeError("RECOVERY_PROVIDER_UNCONFIRMED")
            except Exception:
                delay = retry_seconds
                print("AI_BROWSER_MAINTENANCE_HOLD RECOVERY_UNCONFIRMED", flush=True)
                continue
            print("AI_BROWSER_MAINTENANCE_CLEAR VERIFIED_FRESH_AND_PROVIDER_IDLE", flush=True)
            return
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)
