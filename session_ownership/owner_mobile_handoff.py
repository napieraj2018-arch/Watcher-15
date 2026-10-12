"""Owner-scoped, one-time iPhone handoff to an existing Steel profile.

The ChatGPT MCP owner authorizes a SINGLE new Steel browser session. A link
with a fragment-only bearer is exchanged once for an HttpOnly cookie; the
private login view is available only for that specific session. No credentials
pass through the assistant. The existing owner-capability guard still owns the
browser, and all legacy mobile URLs remain disabled.

Steel live-view links are unauthenticated on the provider side. The URL is
never placed in MCP, GitHub, logs or public HTML; it is revealed only in an
authenticated iframe page after the one-time handoff is claimed. A bearer
link must be treated like a short-lived password and never forwarded.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import hmac
import html
import json
import secrets
import time
from urllib.parse import urlsplit, urlunsplit

from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from capability_guard import OwnershipError

SETUP_PATH = "/owner-mobile-login"
SETUP_ORIGIN = "https://ai-browser-cloud.onrender.com"
COOKIE = "__Host-aib-owner-login"
MAX_TTL = 600
MIN_TTL = 120


@dataclass
class Handoff:
    profile: str
    handle: str
    viewer_url: str
    token_digest: bytes
    setup_id_digest: bytes
    expires_at: float
    cookie_digest: bytes | None = None
    claimed: bool = False
    finished: bool = False


def _digest(text: str) -> bytes:
    return hashlib.sha256(text.encode("ascii")).digest()


def _viewer_url(raw: object) -> str:
    """Never embed a provider-returned arbitrary origin."""
    if not isinstance(raw, str) or len(raw) > 1500:
        raise OwnershipError("MOBILE_VIEWER_INVALID")
    try:
        u = urlsplit(raw)
        host = u.hostname or ""
        if (u.scheme != "https" or not (host == "steel.dev" or
                host.endswith(".steel.dev")) or u.username or u.password or
                u.port not in (None, 443) or u.fragment):
            raise ValueError()
        return urlunsplit((u.scheme, u.netloc, u.path, u.query, ""))
    except (ValueError, TypeError):
        raise OwnershipError("MOBILE_VIEWER_INVALID") from None


def _login_url(raw: object) -> str:
    """The pilot opens only Facebook's standard sign-in surface."""
    if raw not in (
        "https://www.facebook.com/login/",
        "https://m.facebook.com/",
    ):
        raise OwnershipError("MOBILE_LOGIN_ORIGIN_NOT_ALLOWED")
    return raw


def _headers(csp: str | None = None) -> dict[str, str]:
    values = {
        "cache-control": "no-store, max-age=0",
        "referrer-policy": "no-referrer",
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
    }
    if csp:
        values["content-security-policy"] = csp
    return values


def _page(body: str, script: str = "") -> HTMLResponse:
    nonce = secrets.token_urlsafe(16)
    style = """
    body{font:16px system-ui,-apple-system,sans-serif;color:#172b3d;
      margin:0;background:#f7f9fc}
    main{max-width:820px;margin:0 auto;padding:14px}
    h1{font-size:21px}
    button{font-size:17px;border:0;border-radius:10px;padding:12px 16px;
      color:white;background:#1667a3}
    iframe{width:100%;height:70vh;min-height:420px;border:1px solid #ccd6e0;
      border-radius:12px;background:white}
    .status{font-size:14px;color:#405365}
    """
    csp = ("default-src 'none'; base-uri 'none'; object-src 'none';"
           " form-action 'self'; connect-src 'self'; img-src data:;"
           " frame-src https://*.steel.dev https://steel.dev;"
           f" script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}';"
           " frame-ancestors 'none'")
    doc = ('<!doctype html><html lang="pl"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width,initial-scale=1">'
           '<title>AI Browser — bezpieczne logowanie</title>'
           f'<style nonce="{nonce}">{style}</style></head><body>'
           f'<main>{body}</main>'
           + (f'<script nonce="{nonce}">{script}</script>' if script else "")
           + '</body></html>')
    return HTMLResponse(doc, headers=_headers(csp))


class OwnerMobileHandoff:
    def __init__(self, guard, *, clock=time.monotonic, origin=SETUP_ORIGIN):
        self.guard, self.clock = guard, clock
        if origin != SETUP_ORIGIN:
            raise OwnershipError("MOBILE_ORIGIN_UNTRUSTED")
        self.origin = origin
        self.lock = asyncio.Lock()
        self.active: Handoff | None = None
        self.original_start = None
        self.original_stop = None

    def routes(self) -> list[Route]:
        return [
            Route(SETUP_PATH, self.home, methods=["GET"]),
            Route(SETUP_PATH + "/claim", self.claim, methods=["POST"]),
            Route(SETUP_PATH + "/view", self.view, methods=["GET"]),
            Route(SETUP_PATH + "/finish", self.finish, methods=["POST"]),
        ]

    async def create(self, args: dict) -> dict:
        """Called solely from the owner-authenticated MCP tool."""
        if set(args) - {"profile", "login_url", "timeout_seconds"}:
            raise OwnershipError("MOBILE_SETUP_PARAMETERS_INVALID")
        profile = args.get("profile")
        if not isinstance(profile, str) or not 1 <= len(profile) <= 64:
            raise OwnershipError("MOBILE_PROFILE_INVALID")
        url = _login_url(args.get("login_url"))
        ttl = args.get("timeout_seconds", MAX_TTL)
        # Existing MCP clients advertise a 900-second setup default.
        # Accept it but cap this bridge to 600 seconds, below the existing
        # 780-second ownership watchdog and provider session timeout.
        if type(ttl) is not int or not MIN_TTL <= ttl <= 900:
            raise OwnershipError("MOBILE_TIMEOUT_INVALID")
        ttl = min(ttl, MAX_TTL)
        if self.original_start is None or self.original_stop is None:
            raise OwnershipError("MOBILE_SETUP_NOT_READY")
        async with self.lock:
            if self.active is not None and not self.active.finished:
                # A timed-out setup may still own a billable session.
                # It must be explicitly closed by the original owner guard.
                raise OwnershipError("MOBILE_SETUP_IN_PROGRESS")
            result = await self.guard.start(self.original_start, {
                "profile": profile, "mode": "write", "start_url": url,
            })
            handle = result.get("session_id")
            lease = self.guard.authorize(handle)
            if lease.profile != profile:
                raise OwnershipError("MOBILE_SETUP_PROFILE_CHANGED")
            remote = getattr(self.guard.sessions()[lease.internal_session_id],
                             "browser", None)
            raw_url = getattr(remote, "_aib_viewer_url", None)
            if not raw_url:
                try:
                    response = await remote.engine.request(
                        "GET", "/sessions/" + remote.remote_id, timeout=12)
                    raw_url = (response.get("debugUrl")
                               or response.get("sessionViewerUrl")
                               or response.get("sessionViewerURL"))
                except Exception:
                    raw_url = None
            try:
                viewer = _viewer_url(raw_url)
            except OwnershipError:
                # The new session is ours; close it with the original guarded
                # path before returning an error. Never leave a viewerless
                # billable Steel session for an unattended login.
                await self.guard.action("browser_stop", self.original_stop,
                                        {"session_id": handle})
                raise OwnershipError("MOBILE_VIEWER_UNAVAILABLE") from None
            token = secrets.token_urlsafe(32)
            setup_id = secrets.token_urlsafe(32)
            self.active = Handoff(profile, handle, viewer, _digest(token),
                                  _digest(setup_id), self.clock() + ttl)
            # Fragment is never sent to Render/Steel access logs or Referer.
            return {
                "status": "ready_for_human_login",
                "profile": profile,
                "setup_url": self.origin + SETUP_PATH + "#s=" + token,
                "setup_id": setup_id,
                "expires_in_seconds": ttl,
                "password_collected_by_chat": False,
                "browser_session_started": True,
            }

    async def cancel(self, args: dict) -> dict:
        """Stop only the session minted for this owner-issued setup ID."""
        if set(args) != {"setup_id"}:
            raise OwnershipError("MOBILE_CANCEL_PARAMETERS_INVALID")
        identifier = args.get("setup_id")
        if (not isinstance(identifier, str)
                or not 32 <= len(identifier) <= 128):
            raise OwnershipError("MOBILE_SETUP_ID_REQUIRED")
        try:
            digest = _digest(identifier)
        except UnicodeError:
            raise OwnershipError("MOBILE_SETUP_ID_REQUIRED") from None
        async with self.lock:
            r = self.active
            if (r is None or r.finished
                    or not hmac.compare_digest(digest,r.setup_id_digest)):
                raise OwnershipError("MOBILE_SETUP_ID_NOT_OWNED")
            result = await self.guard.action(
                "browser_stop", self.original_stop,
                {"session_id":r.handle})
            if (not isinstance(result,dict) or
                    result.get("profile_saved") is not True or
                    result.get("full_profile_saved") is not True):
                raise OwnershipError("MOBILE_SAVE_UNCONFIRMED")
            r.finished = True
            return {"cancelled":True, "profile_saved":True}

    def _get_record(self, token: str) -> Handoff | None:
        r = self.active
        if (r is None or r.finished or self.clock() > r.expires_at or
                len(token) > 150):
            return None
        try:
            if not hmac.compare_digest(_digest(token), r.token_digest):
                return None
            lease = self.guard.authorize(r.handle)
            if lease.profile != r.profile:
                return None
        except (ValueError, UnicodeError, OwnershipError):
            return None
        return r

    def _cookie_record(self, request) -> Handoff | None:
        r = self.active
        supplied = request.cookies.get(COOKIE, "")
        if (r is None or r.finished or not r.claimed
                or self.clock() > r.expires_at + 90
                or r.cookie_digest is None or not 30 <= len(supplied) <= 128):
            return None
        try:
            if not hmac.compare_digest(r.cookie_digest, _digest(supplied)):
                return None
            lease = self.guard.authorize(r.handle)
            if lease.profile != r.profile:
                return None
        except (UnicodeError, ValueError, OwnershipError):
            return None
        return r

    def _same_origin(self, request) -> bool:
        return (request.headers.get("origin") == self.origin
                and request.headers.get("content-type", "").split(";")[0]
                == "application/json")

    async def home(self, request):
        script = """
        (async () => {
          const m = location.hash.match(/^#s=([A-Za-z0-9_-]{30,100})$/);
          history.replaceState(null, "", location.pathname);
          if (!m) {document.getElementById("status").textContent =
                        "Brak ważnego zaproszenia do logowania.";return;}
          try {
            const r = await fetch("/owner-mobile-login/claim", {
              method:"POST",credentials:"same-origin",
              headers:{"Content-Type":"application/json"},
              body:JSON.stringify({token:m[1]})
            });
            if(!r.ok) throw Error("claim");
            location.replace("/owner-mobile-login/view");
          } catch (_) {
            document.getElementById("status").textContent =
              "Nie udało się otworzyć sesji. Link mógł wygasnąć.";
          }
        })();
        """
        return _page('<h1>Logowanie do Facebooka</h1>'
                     '<p>Jednorazowe połączenie z zapisanym profilem AI Browser.</p>'
                     '<p class="status" id="status">Sprawdzanie zaproszenia…</p>',
                     script)

    async def claim(self, request):
        if not self._same_origin(request):
            return JSONResponse({"error":"MOBILE_REQUEST_DENIED"}, status_code=403,
                                headers=_headers())
        try:
            if int(request.headers.get("content-length", "0")) > 256:
                raise ValueError()
            body = await request.body()
            if len(body) > 256:
                raise ValueError()
            data = json.loads(body)
            token = data.get("token") if isinstance(data, dict) else None
        except (ValueError, TypeError):
            token = None
        async with self.lock:
            r = self._get_record(token) if isinstance(token, str) else None
            if r is None or r.claimed:
                return JSONResponse({"error":"MOBILE_LINK_USED_OR_EXPIRED"},
                                    status_code=410, headers=_headers())
            cookie = secrets.token_urlsafe(32)
            r.cookie_digest, r.claimed = _digest(cookie), True
            reply = JSONResponse({"status":"ready"}, headers=_headers())
            reply.set_cookie(COOKIE, cookie, path="/", max_age=MAX_TTL + 90,
                             secure=True, httponly=True, samesite="strict")
            return reply

    async def view(self, request):
        r = self._cookie_record(request)
        if r is None:
            return _page('<h1>Sesja niedostępna</h1>'
                         '<p>Otwórz ważny link logowania lub zakończ sesję w czacie.</p>')
        script = """
        const button = document.getElementById("finish");
        button.onclick = async () => {
          button.disabled = true;
          try {
            const r = await fetch("/owner-mobile-login/finish", {
              method:"POST",credentials:"same-origin",
              headers:{"Content-Type":"application/json"},
              body:"{}"
            });
            if(!r.ok) throw Error("not-saved");
            document.getElementById("viewer").remove();
            document.getElementById("status").textContent =
              "Sesja zamknięta i profil zapisany. Wróć do rozmowy.";
          } catch (_) {
            document.getElementById("status").textContent =
              "Zapisu nie potwierdzono. Nie uruchamiaj kolejnego logowania.";
            button.disabled = false;
          }
        };
        """
        url = html.escape(r.viewer_url, quote=True)
        return _page(
            '<h1>Logowanie do Facebooka</h1>'
            '<p>Wpisz dane wyłącznie na stronie Facebooka w oknie poniżej. '
            'Nie podawaj hasła ani kodu w czacie.</p>'
            f'<iframe id="viewer" src="{url}" title="Interaktywna sesja Steel" '
            'referrerpolicy="no-referrer" allow="clipboard-write"></iframe>'
            '<p><button id="finish" type="button">Zapisz profil i zakończ</button></p>'
            '<p id="status" class="status">Po zalogowaniu użyj przycisku powyżej.</p>',
            script)

    async def finish(self, request):
        if not self._same_origin(request):
            return JSONResponse({"error":"MOBILE_REQUEST_DENIED"}, status_code=403,
                                headers=_headers())
        async with self.lock:
            r = self._cookie_record(request)
            if r is None:
                return JSONResponse({"error":"MOBILE_SESSION_UNAVAILABLE"},
                                    status_code=410, headers=_headers())
            try:
                receipt = await self.guard.action("browser_stop",
                                                  self.original_stop,
                                                  {"session_id":r.handle})
            except Exception:
                return JSONResponse({"error":"MOBILE_SAVE_UNCONFIRMED"},
                                    status_code=503, headers=_headers())
            if (not isinstance(receipt, dict) or
                    receipt.get("profile_saved") is not True or
                    receipt.get("full_profile_saved") is not True):
                return JSONResponse({"error":"MOBILE_SAVE_UNCONFIRMED"},
                                    status_code=503, headers=_headers())
            r.finished = True
            reply = JSONResponse({"status":"saved_and_closed"},
                                 headers=_headers())
            reply.delete_cookie(COOKIE, path="/", secure=True, httponly=True,
                                samesite="strict")
            return reply
