"""One-session native iPhone touch controller, independent of Steel's WebRTC UI.

Only reachable after owner-issued mobile handoff has been claimed into a
SameSite HttpOnly cookie. Images are ephemeral Playwright screenshots sent
back to that same client. Input goes through a fixed allowlist of tap, scroll,
field fill, Enter/Tab/Backspace and back/forward/reload. No arbitrary scripts,
URLs, browser profiles or provider IDs are accepted from HTTP.

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
HISTORY_DETACH_TIMEOUT = 2


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
                if not self._safe_login_page(page, rec):
                    return None
                result = await asyncio.wait_for(fn(page, rec), limit)
                # A click or history navigation can redirect while awaited.
                # Never return an image or successful result for a page that
                # has left this handoff's exact service scope.
                return result if self._safe_login_page(page, rec) else None
            finally:
                self.guard.actor_session.reset(token)

    @staticmethod
    def _safe_login_page(page, record) -> bool:
        # The scope comes from the server-owned service selected when this
        # handoff was created. A trusted but unrelated service is still denied.
        # Exact origins prevent suffix matches, userinfo and non-HTTPS input.
        from owner_mobile_handoff import _https_origin
        try:
            return _https_origin(page.url) in record.allowed_origins
        except Exception:
            return False

    @staticmethod
    async def _back_reaches_initial_blank(page) -> bool:
        # The remote backend is Chromium. Read only this page's own history;
        # never accept, return or log navigation entries through HTTP.
        cdp = await page.context.new_cdp_session(page)
        try:
            history = await cdp.send("Page.getNavigationHistory")
            if not isinstance(history,dict):
                raise ValueError("TOUCH_HISTORY_INVALID")
            index,entries = history.get("currentIndex"),history.get("entries")
            if (type(index) is not int or not isinstance(entries,list)
                    or not entries or not 0 <= index < len(entries)
                    or any(not isinstance(entry,dict)
                           or not isinstance(entry.get("url"),str)
                           or not entry["url"] for entry in entries)
                    or entries[index]["url"] != page.url):
                raise ValueError("TOUCH_HISTORY_INVALID")
            # Do not strand a still-authorized login on Chromium's initial
            # blank document, which must remain outside the credential scope.
            return index == 1 and entries[0]["url"] == "about:blank"
        finally:
            await asyncio.wait_for(cdp.detach(), HISTORY_DETACH_TIMEOUT)

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
          let busy = false, start = null, framePending = false, editor = null;
          function announce(t) { status.textContent = t; }
          async function command(payload, followup = null) {
            if (busy) {
              announce("Trwa poprzednia operacja. Spróbuj za chwilę.");
              return false;
            }
            busy = true;
            announce("Wykonuję…");
            try {
              // Keep one busy interval through text acknowledgement and
              // Enter. A failed fill must never submit the old form value.
              for (const action of followup ? [payload, followup] : [payload]) {
                const response = await fetch("/owner-mobile-login/touch/action", {
                  method: "POST", credentials: "same-origin",
                  headers: {"Content-Type": "application/json"},
                  cache: "no-store", body: JSON.stringify(action)
                });
                if (!response.ok) throw Error("unavailable");
              }
              announce("Wykonano. Odświeżam widok…");
              refresh();
              return true;
            } catch (_) {
              announce("Nie udało się sterować. Wpisany tekst nie został usunięty.");
              return false;
            } finally { busy = false; }
          }
          function refresh() {
            // Slow remote screenshots must finish before changing src again.
            // Replacing src every 2 seconds aborts the image in the client
            // while server-side captures pile up behind the same input lock.
            if (document.visibilityState !== "visible" || framePending) return;
            framePending = true;
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
          const sendText = async (element, field, enter = false) => {
            const t=element.value;
            if (!t) {
              if (enter) return command({kind:"key",key:"Enter"});
              announce("Najpierw wpisz tekst na klawiaturze.");
              return false;
            }
            const sent = await command({kind:"text", field, text:t},
              enter ? {kind:"key",key:"Enter"} : null);
            // Only clear sensitive input AFTER the remote browser reports
            // confirmed success. Busy, errors and disconnected sessions must
            // never silently discard a user's typed credentials.
            if (sent && element.value === t) element.value = "";
            return sent;
          };
          for (const [element, field] of [[value,"text"],[pass,"password"]]) {
            // A button takes DOM focus on some phones. Remember only the
            // local editor, never read back the remote field's contents.
            const remember = () => { editor = {element,field}; };
            element.addEventListener("focus", remember);
            element.addEventListener("input", remember);
            element.addEventListener("keydown", e => {
              if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return;
              e.preventDefault();
              if (!e.repeat) sendText(element,field,true);
            });
          }
          document.getElementById("touch-send").onclick =
            () => sendText(value,"text");
          document.getElementById("touch-send-password").onclick =
            () => sendText(pass,"password");
          document.getElementById("touch-enter").onclick = () => editor
            ? sendText(editor.element,editor.field,true)
            : command({kind:"key",key:"Enter"});
          for (const key of ["Tab","Backspace"]) {
            document.getElementById("touch-"+key.toLowerCase()).onclick =
              () => command({kind:"key",key});
          }
          for (const kind of ["back","forward","reload"]) {
            document.getElementById("touch-"+kind).onclick = () => command({kind});
          }
          document.getElementById("touch-refresh").onclick=refresh;
          shot.addEventListener("load", () => {
            framePending = false;
            if (status.textContent === "Łączę z aktywną sesją…")
              announce("Obraz gotowy. Dotknij wybranego miejsca.");
          });
          shot.addEventListener("error", () => {
            framePending = false;
            announce("Brak obrazu. Sesja mogła wygasnąć.");
          });
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
            '<div class="touch-keys">'
            '<button type="button" id="touch-back">Wstecz</button>'
            '<button type="button" id="touch-forward">Dalej</button>'
            '<button type="button" id="touch-reload">Przeładuj stronę</button>'
            '</div>'
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
        async def capture(page, _record):
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
            elif kind in {"back","forward","reload"}:
                if set(data)!={"kind"}:
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

        async def perform(page, record):
            if kind == "tap":
                dimensions = page.viewport_size
                if not isinstance(dimensions,dict):
                    return False
                width,height=dimensions.get("width"),dimensions.get("height")
                if not (type(width) is int and width>0 and
                        type(height) is int and height>0):
                    return False
                await page.mouse.click(max(1,min(width-1,round(data["x"]*width))),
                                       max(1,min(height-1,round(data["y"]*height))))
            elif kind == "scroll":
                await page.mouse.wheel(0,round(data["delta"]))
            elif kind == "key":
                await page.keyboard.press(data["key"])
            elif kind in {"back","forward","reload"}:
                if kind == "back":
                    initial_blank = await self._back_reaches_initial_blank(page)
                    # The page can redirect while CDP history/detach awaits.
                    if not self._safe_login_page(page, record):
                        return False
                    if initial_blank:
                        return True
                navigation = {"back": page.go_back,
                              "forward": page.go_forward,
                              "reload": page.reload}[kind]
                # None means there is no entry in that direction; this is a
                # normal no-op. The enclosing guard rechecks the final origin.
                await navigation(wait_until="domcontentloaded", timeout=10000)
            else:
                # Only fill the *already focused* editable element.
                # A password may NEVER be inserted into text/email fields.
                # Never take a user-supplied CSS selector, script or URL.
                # Pin the exact DOM element before inspecting it. A live
                # locator could re-resolve after navigation and fill a field
                # in a different document with the previously typed value.
                field = await page.locator(":focus").element_handle(timeout=2000)
                if field is None:
                    return False
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
                elif (tag == "INPUT" and
                      inp_type not in ("text","email","search","tel","url","")):
                    return False
                if not self._safe_login_page(page, record):
                    return False
                # An element handle stays bound to the inspected document;
                # navigation detaches it rather than retargeting the input.
                # Playwright fill emits the events React-controlled forms need.
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
