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
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from capability_guard import OwnershipError
from owner_mobile_touch import NativeTouchController

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
    service_name: str
    allowed_origins: frozenset[str]
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
        # Steel's remote player is meant for human takeovers. Explicitly
        # request interactive controls rather than relying on the provider's
        # evolving debugUrl defaults. Never allow an existing
        # interactive=false query to disable mouse and keyboard input.
        params = dict(parse_qsl(u.query, keep_blank_values=True))
        if host == "api.steel.dev" and u.path.endswith("/player"):
            params["interactive"] = "true"
            params["showControls"] = "true"
        return urlunsplit((u.scheme, u.netloc, u.path,
                           urlencode(params), ""))
    except (ValueError, TypeError):
        raise OwnershipError("MOBILE_VIEWER_INVALID") from None


@dataclass(frozen=True)
class LoginService:
    """Server-owned login scope; callers cannot supply an origin allowlist."""
    name: str
    start_url: str
    entry_hosts: frozenset[str]
    allowed_origins: frozenset[str]


_FACEBOOK_HOSTS = frozenset({
    "facebook.com", "www.facebook.com", "m.facebook.com",
    "business.facebook.com", "web.facebook.com",
})
_FACEBOOK_ORIGINS = frozenset("https://" + host for host in _FACEBOOK_HOSTS)
_GOOGLE_LOGIN_ORIGINS = frozenset({"https://accounts.google.com"})
_CHATGPT_ORIGINS = frozenset({
    "https://chatgpt.com", "https://www.chatgpt.com",
    "https://chat.openai.com", "https://auth.openai.com",
    "https://auth0.openai.com", "https://setup.auth.openai.com",
})

# Fixed first-party login destinations, with only the known identity-provider
# redirects needed by that service. Never use the union for an individual
# handoff: a ChatGPT login must not become a credential relay to Metricool.
# Canonical login pages: chatgpt.com/auth/login, app.metricool.com/login,
# canva.com/login and accounts.google.com/ServiceLogin. OpenAI's published
# network guidance identifies auth.openai.com, auth0.openai.com and
# setup.auth.openai.com; asset/CDN domains are deliberately excluded here.
_LOGIN_SERVICES = (
    LoginService("Facebook", "https://www.facebook.com/login/",
                 _FACEBOOK_HOSTS, _FACEBOOK_ORIGINS),
    LoginService("Instagram", "https://www.instagram.com/accounts/login/",
                 frozenset({"instagram.com", "www.instagram.com"}),
                 frozenset({"https://instagram.com", "https://www.instagram.com"})
                 | _FACEBOOK_ORIGINS),
    LoginService("ChatGPT", "https://chatgpt.com/auth/login",
                 frozenset({"chatgpt.com", "www.chatgpt.com", "chat.openai.com",
                            "auth.openai.com", "auth0.openai.com",
                            "setup.auth.openai.com"}),
                 _CHATGPT_ORIGINS | _GOOGLE_LOGIN_ORIGINS),
    LoginService("Metricool", "https://app.metricool.com/login",
                 frozenset({"metricool.com", "www.metricool.com", "app.metricool.com"}),
                 frozenset({"https://app.metricool.com"})
                 | _GOOGLE_LOGIN_ORIGINS | _FACEBOOK_ORIGINS),
    LoginService("Canva", "https://www.canva.com/login/",
                 frozenset({"canva.com", "www.canva.com"}),
                 frozenset({"https://canva.com", "https://www.canva.com"})
                 | _GOOGLE_LOGIN_ORIGINS | _FACEBOOK_ORIGINS),
    LoginService("Google", "https://accounts.google.com/ServiceLogin",
                 frozenset({"accounts.google.com", "myaccount.google.com",
                            "mail.google.com"}),
                 _GOOGLE_LOGIN_ORIGINS | frozenset({
                     "https://myaccount.google.com", "https://mail.google.com"})),
    # Existing owner sites from docs/CONNECTED_SERVICES.md. WordPress
    # authentication remains on that site's exact origin, without SSO scope.
    LoginService("WordPress — Architekt", "https://architekt.radom.pl/poradnik/wp-login.php",
                 frozenset({"architekt.radom.pl"}),
                 frozenset({"https://architekt.radom.pl"})),
    LoginService("WordPress — Napieraj i Synowie", "https://weterynarz.radom.pl/wp-login.php",
                 frozenset({"weterynarz.radom.pl"}),
                 frozenset({"https://weterynarz.radom.pl"})),
)
_LOGIN_BY_HOST = {host: service for service in _LOGIN_SERVICES
                  for host in service.entry_hosts}


def _https_origin(raw: object) -> str:
    """Strict origin parser shared by setup and the private touch bridge."""
    error = "MOBILE_LOGIN_ORIGIN_NOT_ALLOWED"
    if (not isinstance(raw, str) or not 1 <= len(raw) <= 8192
            or any(ord(ch) < 33 or ord(ch) == 127 or ch == "\\"
                   for ch in raw)):
        raise OwnershipError(error)
    try:
        u = urlsplit(raw)
        host = u.hostname or ""
        if (u.scheme != "https" or not host or u.username is not None
                or u.password is not None or u.port not in (None, 443)):
            raise ValueError()
        return "https://" + host
    except (TypeError, ValueError):
        raise OwnershipError(error) from None


def _login_service(raw: object) -> LoginService:
    """Resolve an exact official host; discard supplied paths and redirects."""
    if not isinstance(raw, str) or len(raw) > 2048:
        raise OwnershipError("MOBILE_LOGIN_ORIGIN_NOT_ALLOWED")
    origin = _https_origin(raw)
    service = _LOGIN_BY_HOST.get(origin.removeprefix("https://"))
    if service is None:
        raise OwnershipError("MOBILE_LOGIN_ORIGIN_NOT_ALLOWED")
    return service


def _login_url(raw: object) -> str:
    """Start only at a pinned login page, never a supplied deep-link/query."""
    service = _login_service(raw)
    # Preserve the original Facebook mobile entry point for existing clients.
    if _https_origin(raw) == "https://m.facebook.com":
        return "https://m.facebook.com/"
    return service.start_url


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
    main{max-width:620px;margin:0 auto;
      padding:16px 18px calc(70px + env(safe-area-inset-bottom))}
    h1{font-size:23px;line-height:1.25;margin:12px 0 16px}
    p{line-height:1.55}
    button,.open-fullscreen{display:block;width:100%;box-sizing:border-box;
      padding:16px;border:0;border-radius:13px;font:600 17px system-ui,
      -apple-system,sans-serif;text-align:center;min-height:54px}
    button{color:white;background:#245c86}
    .open-fullscreen{background:#1766aa;color:#fff;text-decoration:none}
    .steps{background:#eaf1fa;border-radius:13px;padding:14px 18px;
      margin:20px 0}
    .steps p{margin:4px 0}
    .actions{display:grid;gap:14px;margin:18px 0}
    .status{font-size:14px;color:#405365;line-height:1.5}
    .touch-shell{border:1px solid #bccbdc;border-radius:13px;
      overflow:hidden;background:#101b2a;margin:14px 0 8px}
    #touch-shot{display:block;width:100%;height:auto;min-height:180px;
      touch-action:none;-webkit-user-select:none;user-select:none;
      -webkit-touch-callout:none;background:#101b2a}
    .touch-field{background:#fff;padding:12px;border:1px solid #d9e3ec;
      border-radius:12px;margin:12px 0}
    .touch-field label{display:block;font-size:14px;font-weight:650;margin-bottom:7px}
    .touch-field input,.touch-field select{width:100%;box-sizing:border-box;font-size:17px;
      padding:13px;border:1px solid #b9c8d7;border-radius:9px;
      background:#fff;color:#162a3e;margin-bottom:9px}
    .touch-field button{background:#1766aa}
    .touch-keys{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:12px 0}
    .touch-keys button{font-size:15px;padding:13px 4px}
    @media (max-width:480px){
      main{padding:12px 16px calc(78px + env(safe-area-inset-bottom))}
      h1{font-size:22px}
    }
    """
    csp = ("default-src 'none'; base-uri 'none'; object-src 'none';"
           " form-action 'self'; connect-src 'self'; img-src 'self' data:;"
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
        self.touch = NativeTouchController(self)

    def routes(self) -> list[Route]:
        return [
            Route(SETUP_PATH, self.home, methods=["GET"]),
            Route(SETUP_PATH + "/claim", self.claim, methods=["POST"]),
            Route(SETUP_PATH + "/view", self.view, methods=["GET"]),
            Route(SETUP_PATH + "/finish", self.finish, methods=["POST"]),
            *self.touch.routes(),
        ]

    async def create(self, args: dict) -> dict:
        """Called solely from the owner-authenticated MCP tool."""
        if set(args) - {"profile", "login_url", "timeout_seconds"}:
            raise OwnershipError("MOBILE_SETUP_PARAMETERS_INVALID")
        profile = args.get("profile")
        if not isinstance(profile, str) or not 1 <= len(profile) <= 64:
            raise OwnershipError("MOBILE_PROFILE_INVALID")
        service = _login_service(args.get("login_url"))
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
                # An invite can outlive a *successfully saved and released*
                # browser, for example after the owner guard's watchdog closes
                # an abandoned iPhone window. Elapsed time alone is NEVER
                # sufficient to clear it: require evidence that the exact
                # owner lease is gone via the guarded saved-stop path.
                previous = self.active
                try:
                    self.guard._assess()
                except OwnershipError:
                    raise OwnershipError("MOBILE_SETUP_IN_PROGRESS") from None
                prior_digest = _digest(previous.handle)
                still_leased = any(
                    hmac.compare_digest(prior_digest, lease.capability_digest)
                    for lease in self.guard.leases.values()
                )
                same_profile_live = (
                    previous.profile in self.guard.by_profile
                    or any(getattr(session, "profile", None) == previous.profile
                           for session in self.guard.sessions().values())
                )
                if self.guard.quarantined or still_leased or same_profile_live:
                    # Never release, adopt, or silently discard a provider
                    # session with an uncertain close/save receipt.
                    raise OwnershipError("MOBILE_SETUP_IN_PROGRESS")
                previous.finished = True
                previous.cookie_digest = None
                previous.viewer_url = ""
            # The deployed SteelContextFix applies a 508x1074 mobile
            # viewport only when browser_start explicitly requests a visible
            # session. The former implicit headless=True produced a wide
            # desktop page squeezed into an iPhone-sized Steel player.
            result = await self.guard.start(self.original_start, {
                "profile": profile, "mode": "write", "start_url": url,
                "headless": False,
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
            # The owner watchdog has a fixed deadline established at start.
            # Provider setup and the optional viewer lookup can consume its
            # budget. Never advertise a fresh 600 seconds after those awaits.
            if self.guard.leases.get(lease.internal_session_id) is not lease:
                raise OwnershipError("MOBILE_SETUP_SESSION_EXPIRED")
            issued_at = self.clock()
            available = self.guard.with_lifecycle({}, lease)["remaining_seconds"]
            ttl = min(ttl, available)
            if ttl <= 0:
                # This session belongs to this start. Finish its guarded full
                # save-close before failing; do not mint an unusable invite or
                # leave a hidden lease when startup exhausted the login budget.
                receipt = await self.guard.action(
                    "browser_stop", self.original_stop, {"session_id": handle})
                if (not isinstance(receipt, dict)
                        or receipt.get("profile_saved") is not True
                        or receipt.get("full_profile_saved") is not True):
                    raise OwnershipError("MOBILE_SAVE_UNCONFIRMED")
                raise OwnershipError("MOBILE_SETUP_BUDGET_EXHAUSTED")
            token = secrets.token_urlsafe(32)
            setup_id = secrets.token_urlsafe(32)
            self.active = Handoff(profile, handle, viewer, _digest(token),
                                  _digest(setup_id), issued_at + ttl,
                                  service.name, service.allowed_origins)
            # Fragment is never sent to Render/Steel access logs or Referer.
            return {
                "status": "ready_for_human_login",
                "profile": profile,
                "service": service.name,
                "login_origin": _https_origin(url),
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
        # A one-time invitation is consumed on first claim. Returning via
        # iPhone Back / reopening the same link must resume ONLY the
        # already-claimed browser session authenticated by its HttpOnly
        # cookie, not try to claim the fragment bearer a second time.
        if self._cookie_record(request) is not None:
            return RedirectResponse(SETUP_PATH + "/view", status_code=303,
                                    headers=_headers())
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
        return _page('<h1>Bezpieczne logowanie</h1>'
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
            document.getElementById("fullscreen").remove();
            document.getElementById("touch").remove();
            button.remove();
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
        profile = html.escape(r.profile, quote=True)
        service = html.escape(r.service_name, quote=True)
        return _page(
            f'<h1>Logowanie — {service}</h1>'
            f'<p class="status">Osobny profil: <strong>{profile}</strong></p>'
            '<div class="steps">'
            '<p><strong>1.</strong> Otwórz sterowanie dotykowe.</p>'
            f'<p><strong>2.</strong> Zaloguj się do {service}. '
            'Hasło i kod wpisujesz tam, nie w czacie.</p>'
            '<p><strong>3.</strong> Wróć strzałką Wstecz do tej strony, '
            'a następnie wybierz „Zapisz profil i zakończ”.</p>'
            '</div>'
            '<div class="actions">'
            '<a id="touch" class="open-fullscreen" '
            'href="/owner-mobile-login/touch">'
            'Sterowanie dotykowe — iPhone</a>'
            f'<a id="fullscreen" class="open-fullscreen" href="{url}" '
            'rel="noreferrer">Alternatywa: podgląd Steel</a>'
            '<button id="finish" type="button">Zapisz profil i zakończ</button>'
            '</div>'
            '<p id="status" class="status">Możesz wrócić do tej strony '
            'w tej samej przeglądarce bez ponownego użycia zaproszenia. '
            'Sesja logowania jest krótkotrwała.</p>',
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
