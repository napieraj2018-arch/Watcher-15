"""One-session native iPhone touch controller, independent of Steel's WebRTC UI.

Only reachable after owner-issued mobile handoff has been claimed into a
SameSite HttpOnly cookie. Images are ephemeral Playwright screenshots sent
back to that same client. Input goes through a fixed allowlist of tap, scroll,
field fill and Enter/Tab/Backspace. No arbitrary scripts, URLs, browser
profiles or provider IDs are accepted from HTTP.

The optional private keyboard sends a value from the user's phone to the
exact selected remote field over HTTPS. We never persist, return, inspect or
log the field's contents; this is not a credentials-management service.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

PATH = "/owner-mobile-login/touch"
FRAME_PATH = PATH + "/frame"
ACTION_PATH = PATH + "/action"
MAX_REQUEST_BYTES = 900
MAX_FIELD_CHARS = 250
FRAME_TIMEOUT = 13
ACTION_TIMEOUT = 15


class NativeTouchController:
    def __init__(self, handoff):
        self.handoff = handoff
        self.guard = handoff.guard

    def routes(self) -> list[Route]:
        return [
            Route(PATH, self.home, methods=["GET"]),
            Route(FRAME_PATH, self.frame, methods=["GET"]),
            Route(ACTION_PATH, self.action, methods=["POST"]),
        ]

    def _record(self, request):
        record = self.handoff._cookie_record(request)
        if record is None or self.guard.quarantined:
            return None
        try:
            lease = self.guard.authorize(record.handle)
        except Exception:
            return None
        if (lease.recovery_required or lease.profile != record.profile
                or lease.internal_session_id not in self.guard.sessions()
                or self.guard.leases.get(lease.internal_session_id) is not lease):
            return None
        return record, lease

    async def _do(self, request, fn, *, limit=ACTION_TIMEOUT):
        pair = self._record(request)
        if pair is None:
            return None
        rec, lease = pair
        sid = lease.internal_session_id
        lock = self.guard.session_locks.get(sid)
        if lock is None:
            return None
        async with lock:
            if (self.guard.quarantined or self.guard.leases.get(sid) is not lease
                    or lease.recovery_required or sid not in self.guard.sessions()
                    or not self._record(request)):
                return None
            token = self.guard.actor_session.set(sid)
            try:
                page = self.guard.manager._session(sid).page
                return await asyncio.wait_for(fn(page), limit)
            finally:
                self.guard.actor_session.reset(token)

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "cache-control": "no-store, max-age=0",
            "referrer-policy": "no-referrer",
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
        }

    async def home(self, request):
        if self._record(request) is None:
            return Response("Sesja niedostępna. Wróć do rozmowy.", status_code=403,
                            media_type="text/plain", headers=self._headers())
        # The regular owner-mobile document builder supplies a unique CSP
        # nonce, a closed frame-ancestors policy and no external dependencies.
        from owner_mobile_handoff import _page
        script = r"""
        (() => {
          const shot = document.getElementById("touch-shot");
          const status = document.getElementById("touch-status");
          const value = document.getElementById("touch-value");
          const pass = document.getElementById("touch-password");
          let busy = false, start = null;
          function announce(t) { status.textContent = t; }
          async function command(payload) {
            if (busy) return;
            busy = true;
            try {
              const response = await fetch("/owner-mobile-login/touch/action", {
                method: "POST", credentials: "same-origin",
                headers: {"Content-Type": "application/json"},
                cache: "no-store", body: JSON.stringify(payload)
              });
              if (!response.ok) throw Error("unavailable");
              announce("Wykonano. Odświeżam widok…");
              refresh();
            } catch (_) { announce("Nie udało się sterować. Sesja mogła wygasnąć."); }
            finally { busy = false; }
          }
          function refresh() {
            if (document.visibilityState === "visible")
              shot.src = "/owner-mobile-login/touch/frame?t=" + Date.now();
          }
          const fraction = (v, a, size) =>
            Math.max(0, Math.min(1, (v - a) / Math.max(size, 1)));
          shot.addEventListener("pointerdown", e => {
            e.preventDefault();
            start = {x: e.clientX, y: e.clientY, at: Date.now()};
            shot.setPointerCapture(e.pointerId);
          });
          shot.addEventListener("pointerup", e => {
            if (!start) return;
            e.preventDefault();
            const dx = e.clientX - start.x, dy = e.clientY - start.y;
            const box = shot.getBoundingClientRect();
            if (Math.abs(dy) > 30 || Math.abs(dx) > 50) {
              command({kind:"scroll", delta:Math.max(-950,Math.min(950,-dy*2))});
            } else {
              command({kind:"tap", x:fraction(e.clientX,box.left,box.width),
                       y:fraction(e.clientY,box.top,box.height)});
            }
            start = null;
          });
          shot.addEventListener("pointercancel", () => {start=null;});
          const sendText = (element, field) => {
            const t=element.value;
            if (!t) {announce("Najpierw wpisz tekst na klawiaturze.");return;}
            command({kind:"text", field, text:t});
            element.value = "";
          };
          document.getElementById("touch-send").onclick =
            () => sendText(value,"text");
          document.getElementById("touch-send-password").onclick =
            () => sendText(pass,"password");
          for (const key of ["Enter","Tab","Backspace"]) {
            document.getElementById("touch-"+key.toLowerCase()).onclick =
              () => command({kind:"key",key});
          }
          document.getElementById("touch-refresh").onclick=refresh;
          shot.addEventListener("error", () =>
            announce("Brak obrazu. Sesja mogła wygasnąć."));
          refresh();
          setInterval(() => {
            if (!busy && document.visibilityState === "visible") refresh();
          }, 2100);
        })();
        """
        return _page(
            '<h1>Sterowanie dotykowe — iPhone</h1>'
            '<p>Dotknij miejsca na obrazie, aby kliknąć. Przesuń palcem '
            'po obrazie, aby przewinąć stronę.</p>'
            '<div class="touch-shell">'
            '<img id="touch-shot" alt="Widok Twojej zdalnej przeglądarki" '
            'draggable="false" referrerpolicy="no-referrer"></div>'
            '<p id="touch-status" role="status" class="status">'
            'Łączę z aktywną sesją…</p>'
            '<div class="touch-field"><label for="touch-value">'
            'Zwykły tekst do zaznaczonego pola</label>'
            '<input id="touch-value" type="text" autocapitalize="off" '
            'spellcheck="false" autocomplete="off" maxlength="250">'
            '<button type="button" id="touch-send">Wpisz tekst</button></div>'
            '<div class="touch-field"><label for="touch-password">'
            'Hasło do zaznaczonego pola hasła</label>'
            '<input id="touch-password" type="password" autocomplete="off" '
            'spellcheck="false" maxlength="250">'
            '<button type="button" id="touch-send-password">'
            'Wpisz hasło</button></div>'
            '<p class="status">Tekst przechodzi przez nasz zabezpieczony '
            'serwer wprost do aktywnego pola zdalnej strony; '
            'nie jest zapisywany. Nie wpisuj haseł w czacie.</p>'
            '<div class="touch-keys">'
            '<button type="button" id="touch-enter">Enter</button>'
            '<button type="button" id="touch-tab">Tab</button>'
            '<button type="button" id="touch-backspace">Usuń</button>'
            '</div>'
            '<button type="button" id="touch-refresh">Odśwież obraz</button>'
            '<p><a href="/owner-mobile-login/view">Wróć do zapisu profilu</a></p>',
            script
        )

    async def frame(self, request):
        async def capture(page):
            return await page.screenshot(type="jpeg", quality=65,
                                         full_page=False, timeout=10000)
        try:
            result = await self._do(request, capture, limit=FRAME_TIMEOUT)
        except Exception:
            result = None
        if not isinstance(result, bytes) or len(result) < 4 or len(result)>4_000_000:
            return Response(status_code=410, headers=self._headers())
        return Response(result, media_type="image/jpeg", headers=self._headers())

    @staticmethod
    def _num(value: Any) -> bool:
        return type(value) in (float,int) and not isinstance(value, bool)

    async def action(self, request):
        if not self.handoff._same_origin(request) or self._record(request) is None:
            return JSONResponse({"error":"TOUCH_AUTH_REQUIRED"},
                                status_code=403, headers=self._headers())
        try:
            size = int(request.headers.get("content-length", "0"))
            if not 2 <= size <= MAX_REQUEST_BYTES:
                raise ValueError()
            raw = await request.body()
            if len(raw)>MAX_REQUEST_BYTES:
                raise ValueError()
            data = json.loads(raw)
            if not isinstance(data,dict):
                raise ValueError()
            kind = data.get("kind")
            if kind == "tap":
                if set(data)!={"kind","x","y"}:
                    raise ValueError()
                x,y=data["x"],data["y"]
                if not (self._num(x) and self._num(y)
                        and 0<=x<=1 and 0<=y<=1):
                    raise ValueError()
            elif kind == "scroll":
                if set(data)!={"kind","delta"} or not self._num(data["delta"]):
                    raise ValueError()
                if not -1000<=data["delta"]<=1000:
                    raise ValueError()
            elif kind == "key":
                if set(data)!={"kind","key"} or data["key"] not in {
                    "Enter","Tab","Backspace"}:
                    raise ValueError()
            elif kind == "text":
                if set(data)!={"kind","field","text"}:
                    raise ValueError()
                if (data["field"] not in ("text","password")
                        or not isinstance(data["text"],str)
                        or not 1<=len(data["text"])<=MAX_FIELD_CHARS
                        or any(ord(c)<32 and c not in "\n\t"
                               for c in data["text"])):
                    raise ValueError()
            else:
                raise ValueError()
        except (ValueError,TypeError,KeyError,UnicodeError):
            return JSONResponse({"error":"TOUCH_INVALID_ACTION"},
                                status_code=400, headers=self._headers())

        async def perform(page):
            if kind == "tap":
                dimensions = page.viewport_size
                if not isinstance(dimensions,dict):
                    return False
                width,height=dimensions.get("width"),dimensions.get("height")
                if not (type(width) is int and width>0 and
                        type(height) is int and height>0):
                    return False
                await page.mouse.click(max(1,min(width-1,round(data["x"]*width))),
                                       max(1,min(height-1,round(data["y"]*height))),
                                       timeout=7000)
            elif kind == "scroll":
                await page.mouse.wheel(0,round(data["delta"]))
            elif kind == "key":
                await page.keyboard.press(data["key"])
            else:
                # Only fill the *already focused* editable element.
                # A password may NEVER be inserted into text/email fields.
                # Never take a user-supplied CSS selector, script or URL.
                field = page.locator(":focus")
                info = await field.evaluate("""el => ({
                    tag: el.tagName, type: el.type || "",
                    disabled: !!el.disabled, readOnly: !!el.readOnly
                })""")
                if not isinstance(info,dict):
                    return False
                tag=info.get("tag")
                inp_type=str(info.get("type","")).lower()
                if (tag not in ("INPUT","TEXTAREA")
                        or info.get("disabled") or info.get("readOnly")):
                    return False
                if data["field"]=="password":
                    if tag!="INPUT" or inp_type!="password":
                        return False
                elif inp_type not in ("text","email","search","tel","url",""):
                    return False
                # Playwright locator.fill emits real input/change events,
                # including for React-controlled forms.
                await field.fill(data["text"], timeout=7000)
            return True
        try:
            ok = await self._do(request, perform)
        except Exception:
            ok = None
        if ok is not True:
            return JSONResponse({"error":"TOUCH_ACTION_FAILED"},
                                status_code=409, headers=self._headers())
        return JSONResponse({"status":"ok"},headers=self._headers())
