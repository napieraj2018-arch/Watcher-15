"""Owner-only YouTube OAuth handoff routes, designed for a SYSTEM web browser.

NOT installed automatically. The caller must authenticate the owner before
calling \`\`new_invite\`\`. A durable, encrypted CAS vault and verified Google client
must be provided before mounting routes. No Steel session is used.

IMPORTANT DEPLOYMENT GATE: web/proxy ACCESS LOGGING of callback query strings
must be redacted before mounting these routes. OAuth authorization codes arrive
in the GET query of the callback and must not enter Render/Uvicorn access logs.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route


class HandoffError(RuntimeError):
    """Fixed codes only. Never interpolate provider messages or secrets."""


class CASVault(Protocol):
    async def read(self, key: str) -> tuple[int, dict] | None: ...
    async def write(self, key: str, revision: int | None, data: dict) -> int: ...


class YouTubeClient(Protocol):
    async def begin(self, browser_nonce: str) -> str: ...
    async def finish(self, state: str, code: str, browser_nonce: str) -> dict: ...


INVITE = re.compile(r"^[a-zA-Z0-9_-]{40,150}$")
COOKIE = '__Host-aib-youtube-oauth'
MAX_INVITE_AGE = 300
MAX_BODY_BYTES = 1024


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode('ascii')).hexdigest()


def _html_headers(script_nonce: str = '') -> dict[str, str]:
    csp = "default-src 'none'; base-uri 'none'; form-action 'none'; object-src 'none'; frame-ancestors 'none'"
    if script_nonce:
        csp += "; script-src 'nonce-" + script_nonce + "'; connect-src 'self'"
    return {
        'Cache-Control': 'no-store, max-age=0',
        'Pragma': 'no-cache',
        'Referrer-Policy': 'no-referrer',
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'Content-Security-Policy': csp,
    }


@dataclass
class OwnerYouTubeHandoff:
    """Safe ASGI routes. Call \`\`new_invite\`\` from an owner-authenticated MCP.

    Does NOT install these routes or modify Render configuration. A production
    system must implement quotas, invitation revocation/cleanup and verify a
    real durable CAS store before enabling it. No generic client-supplied URL.
    """
    origin: str
    youtube: YouTubeClient
    vault: CASVault
    now: object = time.time

    def __post_init__(self):
        parsed = urlsplit(self.origin)
        if (parsed.scheme != 'https' or not parsed.hostname or
                parsed.username is not None or parsed.password is not None or
                parsed.query or parsed.fragment or parsed.path not in ('', '/') or
                parsed.port not in (None, 443)):
            raise HandoffError('YOUTUBE_HANDOFF_ORIGIN_INVALID')
        self.origin = 'https://' + parsed.hostname

    async def new_invite(self) -> str:
        """Only authorized server-side callers. No direct public HTTP route."""
        token = secrets.token_urlsafe(48)
        await self.vault.write('invite:' + _hash_secret(token), None,
                               {'expires': float(self.now()) + MAX_INVITE_AGE,
                                'used': False})
        return self.origin + '/youtube/oauth/connect#invite=' + token

    def routes(self) -> list[Route]:
        return [
            Route('/youtube/oauth/connect', self.connect, methods=['GET']),
            Route('/youtube/oauth/claim', self.claim, methods=['POST']),
            Route('/youtube/oauth/callback', self.callback, methods=['GET']),
            Route('/youtube/oauth/done', self.done, methods=['GET']),
        ]

    async def connect(self, request: Request):
        nonce = secrets.token_urlsafe(24)
        # Invitation lives only in URL fragment; no invitation/code in GET logs.
        # A real system browser (Safari/Chrome) is required to complete Google login.
        document = '''<!doctype html><html lang="pl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Połączenie YouTube</title></head><body>
<main><h1>Połącz kanał YouTube</h1>
<p>Otwórz ten ekran w Safari albo Chrome, nie w zdalnej przeglądarce Steel.</p>
<p id="status">Sprawdzam jednorazowe zaproszenie…</p>
<a id="google" hidden rel="noreferrer noopener">Przejdź do zgody Google</a>
</main><script nonce="__NONCE__">
(async () => {
 const status = document.getElementById('status');
 const link = document.getElementById('google');
 const hash = location.hash;
 history.replaceState(null, '', '/youtube/oauth/connect');
 const invitation = new URLSearchParams(hash.replace(/^#/, '')).get('invite');
 if (!invitation) { status.textContent = 'Brak zaproszenia. Wróć do rozmowy.'; return; }
 try {
   const response = await fetch('/youtube/oauth/claim', {
     method: 'POST', credentials: 'same-origin',
     headers: {'Content-Type':'application/json'},
     body: JSON.stringify({invite: invitation}),
     redirect: 'error', cache: 'no-store'
   });
   if (!response.ok) throw new Error('claim-refused');
   const result = await response.json();
   if (!result.google_url || !result.google_url.startsWith('https://accounts.google.com/o/oauth2/v2/auth?'))
     throw new Error('invalid-google-url');
   link.href = result.google_url;
   link.hidden = false;
   link.textContent = 'Zaloguj się do Google w Safari/Chrome';
   status.textContent = 'Wybierz właściwy kanał YouTube. Zgoda będzie wyświetlona przez Google.';
 } catch (_) {
   status.textContent = 'Połączenia nie rozpoczęto. Poproś o nowe zaproszenie.';
 }
})();
</script></body></html>'''.replace('__NONCE__', nonce)
        return HTMLResponse(document, headers=_html_headers(nonce))

    async def claim(self, request: Request):
        def refused(code, status=403):
            return JSONResponse({'error': code}, status_code=status, headers=_html_headers())
        # Reject cross-origin form submissions and origins not generated by us.
        if request.headers.get('origin') != self.origin:
            return refused('YOUTUBE_HANDOFF_ORIGIN_MISMATCH')
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            return refused('YOUTUBE_HANDOFF_JSON_REQUIRED', 415)
        try:
            if int(request.headers.get('content-length') or 0) > MAX_BODY_BYTES:
                return refused('YOUTUBE_HANDOFF_TOO_LARGE', 413)
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > MAX_BODY_BYTES:
                    return refused('YOUTUBE_HANDOFF_TOO_LARGE', 413)
            data = json.loads(raw)
            if not isinstance(data, dict) or set(data) != {'invite'}:
                return refused('YOUTUBE_HANDOFF_INVALID')
            token = data['invite']
            if not isinstance(token, str) or not INVITE.fullmatch(token):
                return refused('YOUTUBE_HANDOFF_INVALID')
            key = 'invite:' + _hash_secret(token)
            row = await self.vault.read(key)
            if not row:
                return refused('YOUTUBE_HANDOFF_INVALID')
            rev, state = row
            if state.get('used') is not False or state.get('expires', 0) < float(self.now()):
                return refused('YOUTUBE_HANDOFF_EXPIRED')
            # CAS consumption precedes any token-related effects; never replay.
            await self.vault.write(key, rev, {'used': True})
            browser_nonce = secrets.token_urlsafe(48)
            google_url = await self.youtube.begin(browser_nonce)
            if not google_url.startswith('https://accounts.google.com/o/oauth2/v2/auth?'):
                return refused('YOUTUBE_HANDOFF_PROVIDER_URL_INVALID')
            response = JSONResponse({'google_url': google_url}, headers=_html_headers())
            response.set_cookie(COOKIE, browser_nonce, secure=True, httponly=True,
                                samesite='lax', path='/', max_age=600)
            return response
        except (json.JSONDecodeError, UnicodeDecodeError):
            return refused('YOUTUBE_HANDOFF_INVALID', 400)
        except Exception:
            # No exception body; never reflect secrets or backend messages.
            return refused('YOUTUBE_HANDOFF_UNCONFIRMED', 503)

    async def callback(self, request: Request):
        # Production access logs MUST redact query BEFORE this handler is enabled.
        # OAuth state AND the first-party browser cookie are checked in youtube.finish.
        def failed():
            response = HTMLResponse('<!doctype html><title>Brak połączenia</title>'
                                    '<p>Połączenie Google nie zostało potwierdzone.</p>',
                                    status_code=403, headers=_html_headers())
            response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='lax')
            return response
        try:
            data = request.query_params
            if (set(data.keys()) != {'state', 'code'}
                    or len(data.getlist('state')) != 1
                    or len(data.getlist('code')) != 1):
                return failed()
            state, code = data.get('state'), data.get('code')
            nonce = request.cookies.get(COOKIE, '')
            if not state or not code or not nonce or len(nonce) < 32:
                return failed()
            result = await self.youtube.finish(state, code, nonce)
            if result.get('connected') is not True:
                return failed()
            response = RedirectResponse('/youtube/oauth/done', status_code=303,
                                        headers=_html_headers())
            response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='lax')
            return response
        except Exception:
            return failed()

    async def done(self, request: Request):
        return HTMLResponse('<!doctype html><html lang="pl"><meta charset="utf-8">'
                            '<title>Zgoda Google</title><h1>Autoryzacja została przetworzona</h1>'
                            '<p>Wróć do ChatGPT, aby sprawdzić kanał i aktualny dostęp.</p></html>',
                            headers=_html_headers())
