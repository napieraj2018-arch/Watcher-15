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
import html
import json
import secrets
from typing import Any

from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

PATH = "/owner-mobile-login/touch"
FRAME_PATH = PATH + "/frame"
ACTION_PATH = PATH + "/action"
TABS_PATH = PATH + "/tabs"
MAX_REQUEST_BYTES = 900
MAX_FIELD_CHARS = 250
FRAME_TIMEOUT = 13
ACTION_TIMEOUT = 15
HISTORY_DETACH_TIMEOUT = 2
FOCUS_KINDS = frozenset({"text", "email", "password", "code", "tel", "number"})

TOUCH_STYLE = """
html:has(.touch-app),body:has(.touch-app){height:100%;overflow:hidden;overscroll-behavior:none}
main:has(>.touch-app){max-width:none;margin:0;padding:0}
.touch-app{position:fixed;inset:0;box-sizing:border-box;height:100dvh;
  display:flex;flex-direction:column;background:#f1f4f7;color:#182230;
  padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom)}
.touch-app *{box-sizing:border-box}
.touch-app [hidden]{display:none!important}
.touch-app button{min-height:44px;border-radius:10px;padding:9px 10px;
  font-size:14px;line-height:1.2;touch-action:manipulation}
.touch-app button:focus-visible,.touch-app input:focus-visible,.touch-app select:focus-visible{
  outline:3px solid #55a5fa;outline-offset:2px}
.touch-top{display:flex;align-items:center;gap:10px;padding:9px 12px;
  border-bottom:1px solid #dde4eb;background:#fff;flex-shrink:0}
.touch-identity{flex:1;min-width:0}
.touch-identity h1{font-size:16px;margin:0;line-height:1.25;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.touch-identity p{font-size:11px;margin:3px 0 0;color:#586577;line-height:1.2;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#touch-finish{width:auto;min-height:42px;flex-shrink:0;background:#163f36;
  color:#fff;font-size:13px;padding:10px 12px}
.touch-livebar{display:flex;align-items:center;gap:7px;padding:6px 12px;
  background:#fff;min-height:31px;flex-shrink:0;font-size:11px;color:#526176}
.touch-dot{width:7px;height:7px;background:#98a5b5;border-radius:50%;flex-shrink:0}
.touch-app[data-image=ready] .touch-dot{background:#18825c}
.touch-app[data-image=stale] .touch-dot{background:#b57012}
#touch-age{flex:1;min-width:0}
#touch-session-time{font-variant-numeric:tabular-nums;white-space:nowrap}
.touch-profile-state{display:flex;justify-content:space-between;gap:8px;padding:0 12px 7px;
  background:#fff;color:#697586;font-size:10px;line-height:1.3;flex-shrink:0}
#touch-viewport{position:relative;flex:1;min-height:120px;overflow:hidden;
  background:#e2e7ee;isolation:isolate;touch-action:none;overscroll-behavior:none}
#touch-stage{position:absolute;top:50%;left:50%;width:100%;height:100%;
  transform:translate(-50%,-50%);line-height:0}
#touch-shot{display:block;width:100%;height:100%;min-height:0;max-width:none;
  max-height:none;touch-action:none;user-select:none;-webkit-user-select:none;
  -webkit-touch-callout:none;background:#fff;border:0;object-fit:fill}
.touch-wait{position:absolute;inset:0;display:grid;place-content:center;
  padding:24px;text-align:center;color:#566274;font-size:15px;line-height:1.55}
.touch-wait strong{display:block;color:#263447;font-size:18px;margin-bottom:8px}
.touch-notice{padding:7px 12px;background:#fff;border-top:1px solid #e0e6ec;
  flex-shrink:0;min-height:33px}
#touch-status{font-size:12px;line-height:1.4;color:#465568;margin:0}
.touch-dock{display:grid;grid-template-columns:48px 48px 1fr 68px 64px;gap:4px;
  padding:6px 9px;background:#fff;border-top:1px solid #dde4eb;flex-shrink:0}
.touch-dock button{background:#eef2f6;color:#26364a;min-height:49px;font-size:12px;padding:7px 2px}
.touch-dock .touch-arrow{font-size:24px;font-weight:500}
#touch-keyboard{background:#173e36;color:#fff;font-size:13px}
.touch-dock button[aria-expanded=true],.touch-dock button[aria-pressed=true]{background:#d9e8f5;color:#174c7b}
.touch-sheet{background:#fff;flex-shrink:0;border-top:1px solid #d5dfe8;
  padding:10px 12px;box-shadow:0 -5px 16px #17344d0a}
.touch-sheet-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}
.touch-sheet-head strong{font-size:13px;font-weight:650}
.touch-sheet-head button{width:auto;min-height:30px;padding:5px 9px;color:#5c6878;background:#f0f3f6;font-size:12px}
.touch-modes{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;margin-bottom:9px}
.touch-modes button{min-height:33px;background:#eff3f6;color:#526175;font-size:13px}
.touch-modes button[aria-pressed=true]{background:#dcece5;color:#174b38}
.touch-entry-row{display:flex;gap:7px;align-items:stretch}
.touch-entry{min-width:0;flex:1}
.touch-entry label{display:block;font-size:11px;color:#5c6879;margin:0 0 4px}
.touch-entry input{display:block;width:100%;height:47px;border:1px solid #b7c5d3;
  border-radius:10px;padding:10px 12px;font:17px system-ui,-apple-system,sans-serif;
  background:#fff;color:#16283d;line-height:1.3;min-width:0}
.touch-entry-row button{width:auto;align-self:flex-end;min-height:47px;background:#245c86;padding:8px 13px}
.touch-editor-actions{display:flex;gap:6px;margin-top:8px}
.touch-editor-actions button{font-size:12px;min-height:36px;background:#edf2f6;color:#334860;flex:1;padding:8px 4px}
.touch-editor-actions #touch-enter{background:#173e36;color:#fff;flex:1.4}
.touch-editor-hint{font-size:11px;line-height:1.35;color:#637184;margin:7px 0 0}
.touch-menu-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px}
.touch-menu-grid button{background:#eef3f7;color:#334b63;font-size:12px;min-height:42px}
.touch-sheet label[for=touch-tabs]{font-size:12px;font-weight:650;display:block;margin-bottom:6px}
#touch-tabs{font:15px system-ui,-apple-system,sans-serif;background:#f9fbfd;color:#24364a;
  width:100%;min-height:44px;border:1px solid #c4d0dc;border-radius:9px;padding:8px}
#touch-tabs-hint{font-size:11px;line-height:1.35;color:#647386;margin:7px 0 0}
.touch-help{font-size:11px;line-height:1.45;color:#637184;margin:10px 0 0}
.touch-ended{margin:auto;padding:28px 24px;text-align:center;max-width:480px}
.touch-ended h2{font-size:23px;margin:12px 0;color:#173e36}
.touch-ended p{font-size:15px;line-height:1.6;margin:10px 0;color:#536175}
.touch-ended-mark{display:grid;place-items:center;width:56px;height:56px;border-radius:50%;
  background:#dbeee5;color:#176348;font-size:27px;margin:auto}
.touch-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(min-width:700px){.touch-app{max-width:900px;left:50%;right:auto;width:100%;
  transform:translateX(-50%);box-shadow:0 0 35px #253e5018}}
.touch-app[data-compact=true] .touch-top{padding:5px 10px}
.touch-app[data-compact=true] .touch-identity p{display:none}
.touch-app[data-compact=true] .touch-livebar{padding:3px 10px;min-height:22px}
.touch-app[data-compact=true] .touch-notice{padding:4px 10px;min-height:25px}
.touch-app[data-compact=true] .touch-sheet{padding:7px 10px}
.touch-app[data-compact=true] .touch-editor-hint{display:none}
.touch-app[data-compact=true] .touch-dock{padding:4px 8px}
.touch-app[data-compact=true] .touch-dock button{min-height:42px}
.touch-app[data-compact=true] .touch-editor-actions{margin-top:5px}
.touch-app[data-compact=true] #touch-viewport{min-height:0}
.touch-app[data-compact=true] #touch-editor .touch-sheet-head,
.touch-app[data-compact=true] #touch-editor .touch-modes,
.touch-app[data-compact=true] .touch-entry label{display:none}
.touch-app[data-compact=true] .touch-entry input,
.touch-app[data-compact=true] .touch-entry-row button{height:44px;min-height:44px}
"""


class NativeTouchController:
    def __init__(self, handoff):
        self.handoff = handoff
        self.guard = handoff.guard
        # References are private to the one claimed handoff. They never carry
        # browser/provider IDs and cannot select a page in another context.
        self._tab_record = None
        self._tab_refs = {}
        self._selected_page = None

    def routes(self) -> list[Route]:
        return [
            Route(PATH, self.home, methods=["GET"]),
            Route(FRAME_PATH, self.frame, methods=["GET"]),
            Route(TABS_PATH, self.tabs, methods=["GET"]),
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

    async def _with_session(self, request, fn, *, limit=ACTION_TIMEOUT):
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
                session = self.guard.manager._session(sid)
                result = await asyncio.wait_for(fn(session, rec), limit)
                return result if self._record(request) else None
            finally:
                self.guard.actor_session.reset(token)

    def _pages(self, session, record):
        if self._tab_record is not record:
            self._tab_record = record
            self._tab_refs = {}
            self._selected_page = None
        # Even after the original tab closes, its context remains the exact
        # context owned by this lease. Never use browser-wide context lists.
        pages = [page for page in session.page.context.pages
                 if not page.is_closed()]
        if not any(page is self._selected_page for page in pages):
            # A completed OAuth popup often closes itself. Return to the
            # original tab if it survives; do not adopt another session.
            self._selected_page = (session.page if session.page in pages
                                   else pages[0] if pages else None)
        return pages

    def _tab_inventory(self, session, record):
        from owner_mobile_handoff import _https_origin
        pages = self._pages(session, record)
        previous, refs, rows = self._tab_refs, {}, []
        for page in pages:
            if not self._safe_login_page(page, record):
                continue
            ref = next((key for key, value in previous.items() if value is page),
                       None) or secrets.token_urlsafe(12)
            refs[ref] = page
            # Titles, URL paths and queries can contain private values.
            # Display only the exact approved origin and an ordinal label.
            rows.append({"ref": ref,
                         "label": f"Karta {len(rows)+1} — "
                                  + _https_origin(page.url)[8:],
                         "active": page is self._selected_page})
        self._tab_refs = refs
        return {"tabs": rows}

    async def _do(self, request, fn, *, limit=ACTION_TIMEOUT, ref=None):
        async def operate(session, record):
            self._tab_inventory(session, record)
            page = self._selected_page
            if (page is None or not self._safe_login_page(page, record)
                    or (ref is not None and self._tab_refs.get(ref) is not page)):
                return None
            result = await fn(page, record)
            # A click or history navigation can redirect while awaited.
            # Never return an image or successful result for a page that
            # has left this handoff's exact service scope.
            return result if self._safe_login_page(page, record) else None
        return await self._with_session(request, operate, limit=limit)

    async def tabs(self, request):
        async def inventory(session, record):
            result = self._tab_inventory(session, record)
            page = self._selected_page
            result["focus_kind"] = None
            if page is not None and self._safe_login_page(page, record):
                kind = await self._focused_kind(page)
                # Only a fixed field-type hint is returned, never a value,
                # name, label, selector or contents of a cross-origin iframe.
                if (any(candidate is page for candidate in self._pages(session, record))
                        and self._safe_login_page(page, record)):
                    result["focus_kind"] = kind
            return result
        try:
            result = await self._with_session(request, inventory)
        except Exception:
            result = None
        if not isinstance(result, dict):
            return JSONResponse({"error": "TOUCH_AUTH_REQUIRED"},
                                status_code=403, headers=self._headers())
        return JSONResponse(result, headers=self._headers())

    @staticmethod
    async def _focused_kind(page):
        try:
            kind = await asyncio.wait_for(page.evaluate("""() => {
                const el = document.activeElement;
                if (!el || el.disabled || el.readOnly) return null;
                if (el.tagName === 'TEXTAREA') return 'text';
                if (el.tagName !== 'INPUT') return null;
                const type = (el.type || 'text').toLowerCase();
                if (type === 'password') return 'password';
                if (!['text','email','search','tel','url','number'].includes(type))
                    return null;
                const autocomplete = (el.getAttribute('autocomplete') || '')
                    .toLowerCase().split(/\\s+/);
                if (autocomplete.includes('one-time-code')) return 'code';
                return ['email','tel','number'].includes(type) ? type : 'text';
            }"""), timeout=0.6)
        except Exception:
            return None
        return kind if isinstance(kind, str) and kind in FOCUS_KINDS else None

    async def _switch_tab(self, request, ref):
        async def select(session, record):
            self._tab_inventory(session, record)
            page = self._tab_refs.get(ref)
            if page is None:
                return False
            await page.bring_to_front()
            if (not any(candidate is page for candidate in self._pages(session, record))
                    or not self._safe_login_page(page, record)):
                return False
            self._selected_page = page
            return True
        return await self._with_session(request, select)

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
        pair = self._record(request)
        if pair is None:
            # A phone commonly reloads this exact landing URL after returning
            # from mail or after a successful close. Its bounded receipt
            # cookie may still read status without regaining browser control.
            if self.handoff._receipt_record(request) is not None:
                return await self.handoff.view(request)
            return Response("Sesja niedostępna. Wróć do rozmowy.", status_code=403,
                            media_type="text/plain", headers=self._headers())
        record, _lease = pair
        from owner_mobile_handoff import _page
        service = html.escape(record.service_name, quote=True)
        profile = html.escape(record.profile, quote=True)
        script = r"""
        (() => {
          const byId = id => document.getElementById(id);
          const app = byId("touch-app"), shot = byId("touch-shot");
          const viewport = byId("touch-viewport"), stage = byId("touch-stage");
          const status = byId("touch-status"), tabs = byId("touch-tabs");
          const keyboard = byId("touch-editor"), menu = byId("touch-menu");
          const value = byId("touch-value"), pass = byId("touch-password");
          const code = byId("touch-code"), finish = byId("touch-finish");
          const fields = {text:value, password:pass, code};
          const pointers = new Map();
          let busy = false, ending = false, ended = false, controlAllowed = true;
          let framePending = false, frameWanted = false, frameAbort = null;
          let tabsPending = false, statePending = false, tabsSignature = "";
          let currentRef = null, displayedRef = null, editor = null;
          let submittedEditor = null;
          let mode = "text", focusKind = null, noticeKind = "connection";
          let lastFrame = 0, lastTabs = 0, lastState = 0, deferredImage = null;
          let zoom = 1, panX = 0, panY = 0, gesture = null, pinching = false;
          let imageWidth = 508, imageHeight = 1074;
          let layoutStamp = "", keyboardAnchor = {x:0.5,y:0.4};
          const visible = () => document.visibilityState === "visible";
          function announce(text, kind = "info") {
            status.textContent = text;
            noticeKind = kind;
          }
          function readyForInput() {
            return controlAllowed && !ending && !ended && currentRef &&
              displayedRef === currentRef && Date.now() - lastFrame < 15000;
          }
          function layout() {
            const visual = window.visualViewport;
            // Safari's keyboard shrinks only the visual viewport; CSS
            // height media queries keep seeing the full layout viewport.
            app.dataset.compact = String((visual ? visual.height : window.innerHeight) <= 550);
            if (visual) {
              app.style.height = visual.height + "px";
              app.style.top = visual.offsetTop + "px";
            }
            const width = viewport.clientWidth, height = viewport.clientHeight;
            // Keep fields readable above the phone keyboard. Crop the image
            // around the owner's last tap instead of shrinking the full page.
            const fit = keyboard.hidden ? Math.min(width / imageWidth, height / imageHeight) : width / imageWidth;
            const w = Math.max(1, imageWidth * fit * zoom);
            const h = Math.max(1, imageHeight * fit * zoom);
            const stamp = [keyboard.hidden,width,height,imageWidth,imageHeight,zoom].join(":");
            if (!keyboard.hidden && stamp !== layoutStamp) {
              panX = (0.5-keyboardAnchor.x)*w;
              panY = (0.5-keyboardAnchor.y)*h;
            }
            layoutStamp = stamp;
            panX = Math.max(-Math.max(0,(w-width)/2), Math.min(Math.max(0,(w-width)/2),panX));
            panY = Math.max(-Math.max(0,(h-height)/2), Math.min(Math.max(0,(h-height)/2),panY));
            stage.style.width = w + "px";
            stage.style.height = h + "px";
            stage.style.transform = "translate(calc(-50% + " + panX + "px),calc(-50% + " + panY + "px))";
          }
          function setZoom(next) {
            zoom = Math.max(1,Math.min(3,next));
            if (zoom === 1) panX = panY = 0;
            byId("touch-zoom").setAttribute("aria-pressed",String(zoom > 1));
            byId("touch-zoom-label").textContent = zoom === 1 ? "Powiększ" : zoom.toFixed(1).replace(".",",") + "×";
            layout();
            announce(zoom === 1 ? "Dotknij strony. Przesuń palcem, aby ją przewinąć." :
              "Przesuwasz powiększony obraz. Dotknij, aby wybrać element.");
          }
          function setMode(next, focus = false) {
            mode = next;
            for (const name of Object.keys(fields)) {
              byId("touch-field-"+name).hidden = name !== mode;
              byId("touch-mode-"+name).setAttribute("aria-pressed",String(name === mode));
            }
            if (focus) {
              fields[mode].focus({preventScroll:true});
              editor = {element:fields[mode], field:mode === "password" ? "password" : "text", ref:currentRef};
            }
            layout();
          }
          function openKeyboard(focus = true) {
            if (ending || ended) return;
            keyboard.hidden = false;
            menu.hidden = true;
            byId("touch-keyboard").setAttribute("aria-expanded","true");
            byId("touch-more").setAttribute("aria-expanded","false");
            const pending = fields[mode].value;
            const mayFocus = focus && (!pending || (editor &&
              editor.element === fields[mode] && editor.ref === currentRef));
            setMode(mode,mayFocus);
            if (focus && !mayFocus)
              announce("Karta się zmieniła. Wybierz ponownie pole tekstu lub hasła.");
          }
          function closeKeyboard() {
            keyboard.hidden = true;
            byId("touch-keyboard").setAttribute("aria-expanded","false");
            if (Object.values(fields).includes(document.activeElement)) document.activeElement.blur();
            layout();
          }
          function applyFocus(kind, suggest) {
            focusKind = ["text","email","password","code","tel","number"].includes(kind) ? kind : null;
            const labels = {text:"Pole tekstowe",email:"E-mail / login",password:"Pole hasła",
              code:"Kod jednorazowy",tel:"Numer telefonu",number:"Pole liczbowe"};
            byId("touch-field-hint").textContent = labels[focusKind] || "Najpierw wybierz pole na stronie";
            if (focusKind === "code" && submittedEditor && submittedEditor.ref === currentRef &&
                submittedEditor.element !== code && !code.value) {
              // Both confirmed and ambiguous responses can advance to code
              // verification. Never let Enter reuse the old editor on the
              // newly observed field, or adopt a nonempty local code.
              const unconfirmed = submittedEditor.unconfirmed;
              if (document.activeElement === submittedEditor.element) document.activeElement.blur();
              editor = null; submittedEditor = null;
              setMode("code");
              announce(unconfirmed ?
                "Strona prosi teraz o kod. Wpisz go poniżej. Poprzedni wpis pozostał na telefonie; nie wysyłam go ponownie." :
                "Strona prosi teraz o kod. Wpisz go poniżej i wybierz Wpisz i Enter.");
            }
            if (focusKind && !Object.values(fields).some(field => field.value)) {
              const next = focusKind === "password" ? "password" :
                ["code","number"].includes(focusKind) ? "code" : "text";
              if (!Object.values(fields).includes(document.activeElement)) setMode(next);
              value.inputMode = focusKind === "email" ? "email" : focusKind === "tel" ? "tel" : "text";
            }
            if (suggest && focusKind) openKeyboard(false);
          }
          async function readJSON(path, options = {}, timeout = 20000) {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(),timeout);
            try {
              const response = await fetch(path,{credentials:"same-origin",cache:"no-store",
                ...options,signal:controller.signal});
              if (!response.ok) {
                const error = new Error("request-unconfirmed");
                error.status = response.status;
                throw error;
              }
              return await response.json();
            } finally { clearTimeout(timer); }
          }
          async function command(payload, followup = null, sourceEditor = null) {
            if (busy) {
              announce("Trwa poprzednia operacja. Spróbuj za chwilę.");
              return false;
            }
            if (ending || ended || !controlAllowed) return false;
            const boundRef = currentRef;
            if (payload.kind !== "switch_tab" && !readyForInput()) {
              announce("Czekam na aktualny obraz wybranej karty.","connection");
              refresh(true);
              return false;
            }
            busy = true;
            announce("Wykonuję…");
            try {
              for (const action of followup ? [payload,followup] : [payload]) {
                await readJSON("/owner-mobile-login/touch/action",{
                  method:"POST",headers:{"Content-Type":"application/json"},
                  body:JSON.stringify(action.kind === "switch_tab" ? action : {...action,ref:boundRef})
                });
              }
              announce("Wykonano. Odświeżam widok…");
              if (sourceEditor) submittedEditor = {element:sourceEditor,ref:boundRef,unconfirmed:false};
              return true;
            } catch (_) {
              if (sourceEditor) submittedEditor = {element:sourceEditor,ref:boundRef,unconfirmed:true};
              announce("Nie udało się potwierdzić czynności. Sprawdź obraz. Wpisany tekst został na telefonie.","error");
              return false;
            } finally {
              busy = false;
              // Refresh even after an ambiguous response: login can already
              // have advanced to a code/challenge. Never replay the action.
              if (payload.kind !== "switch_tab") refresh(true);
              refreshTabs(payload.kind === "tap" || (payload.kind === "key" && payload.key === "Tab"));
            }
          }
          async function imageURL(blob) {
            return await new Promise((resolve,reject) => {
              const reader = new FileReader();
              reader.onload = () => resolve(reader.result);
              reader.onerror = () => reject(new Error("image-unavailable"));
              reader.readAsDataURL(blob);
            });
          }
          async function showImage(url,ref) {
            if (ended || ending || ref !== currentRef) return;
            if (pointers.size) { deferredImage = {url,ref}; return; }
            await new Promise((resolve,reject) => {
              const done = () => { clearTimeout(timer); shot.onload = shot.onerror = null; };
              const timer = setTimeout(() => { done(); reject(new Error("image-timeout")); },5000);
              shot.onload = () => { done(); resolve(); };
              shot.onerror = () => { done(); reject(new Error("image-unavailable")); };
              shot.src = url;
            });
            if (ended || ending || ref !== currentRef) return;
            imageWidth = shot.naturalWidth || 508;
            imageHeight = shot.naturalHeight || 1074;
            displayedRef = ref;
            lastFrame = Date.now();
            shot.style.pointerEvents = "";
            app.dataset.image = "ready";
            byId("touch-wait").hidden = true;
            if (noticeKind === "connection") announce("Obraz gotowy. Dotknij pola na stronie.");
            layout();
            updateAge();
          }
          async function refresh(immediate = false) {
            if (ended || ending || busy || !controlAllowed || !visible() || !currentRef || pointers.size) return;
            if (framePending) { if (immediate) frameWanted = true; return; }
            framePending = true;
            const ref = currentRef;
            const controller = new AbortController();
            frameAbort = controller;
            const timer = setTimeout(() => controller.abort(),15000);
            try {
              const response = await fetch("/owner-mobile-login/touch/frame?ref="+
                encodeURIComponent(ref)+"&t="+Date.now(),{
                  credentials:"same-origin",cache:"no-store",signal:controller.signal});
              if (!response.ok) throw new Error("image-unavailable");
              const blob = await response.blob();
              if (!blob.size || blob.size > 4000000) throw new Error("image-unavailable");
              await showImage(await imageURL(blob),ref);
            } catch (_) {
              if (!ended && !ending && visible()) {
                app.dataset.image = "stale";
                if (!lastFrame || Date.now()-lastFrame > 8000)
                  announce("Obraz chwilowo niedostępny. Sprawdzam połączenie…","connection");
                refreshTabs();
              }
            } finally {
              clearTimeout(timer);
              framePending = false;
              if (frameAbort === controller) frameAbort = null;
              if (frameWanted || ref !== currentRef) {
                frameWanted = false;
                if (!ended && !ending) setTimeout(() => refresh(),0);
              }
            }
          }
          async function refreshTabs(suggest = false) {
            if (tabsPending || busy || ending || ended || pointers.size || !visible()) return;
            tabsPending = true;
            lastTabs = Date.now();
            try {
              const data = await readJSON("/owner-mobile-login/touch/tabs",{},8000);
              if (ending || ended) return;
              if (!Array.isArray(data.tabs)) return;
              const selected = data.tabs.find(tab => tab.active)?.ref || null;
              if (selected !== currentRef) {
                currentRef = selected;
                displayedRef = null;
                editor = null;
                submittedEditor = null;
                deferredImage = null;
                keyboardAnchor = {x:0.5,y:0.4}; layoutStamp = "";
                zoom = 1; panX = panY = 0;
                byId("touch-zoom").setAttribute("aria-pressed","false");
                byId("touch-zoom-label").textContent = "Powiększ";
                shot.style.pointerEvents = "none";
                app.dataset.image = "stale";
                announce(selected ? "Czekam na aktualny obraz wybranej karty." :
                  "Wybierz kartę logowania w menu Więcej.","connection");
                refresh(true);
                layout();
              }
              applyFocus(data.focus_kind,suggest);
              const signature = JSON.stringify(data.tabs);
              if (signature !== tabsSignature) {
                tabsSignature = signature;
                tabs.replaceChildren();
                if (!data.tabs.some(tab => tab.active)) {
                  const prompt = document.createElement("option");
                  prompt.value = ""; prompt.textContent = "Wybierz kartę logowania"; prompt.selected = true;
                  tabs.appendChild(prompt);
                }
                for (const tab of data.tabs) {
                  const option = document.createElement("option");
                  option.value = tab.ref; option.textContent = tab.label; option.selected = tab.active;
                  tabs.appendChild(option);
                }
                tabs.disabled = data.tabs.length === 0 || (data.tabs.length === 1 && data.tabs[0].active);
                byId("touch-more-label").textContent = data.tabs.length > 1 ? "Karty ("+data.tabs.length+")" : "Więcej";
                byId("touch-tabs-hint").textContent = data.tabs.length > 1 ?
                  "Otwarta jest dodatkowa karta logowania. Wybierz ją z listy." :
                  "Karty należą do tej samej, prywatnej sesji.";
              }
            } catch (_) { /* Image and session status report connection failures. */ }
            finally { tabsPending = false; }
          }
          tabs.onchange = async () => {
            if (!tabs.value) return;
            const switched = await command({kind:"switch_tab",ref:tabs.value});
            if (switched) {
              editor = null;
              menu.hidden = true;
              byId("touch-more").setAttribute("aria-expanded","false");
              announce("Czekam na aktualny obraz wybranej karty.","connection");
              layout();
            }
            tabsSignature = "";
            refreshTabs();
          };
          const sendText = async (element, field, enter = false) => {
            const text = element.value;
            if (!text) {
              if (enter) return command({kind:"key",key:"Enter"});
              announce("Wpisz tekst w polu klawiatury.");
              return false;
            }
            if (!editor || editor.element !== element || editor.ref !== currentRef) {
              announce("Karta się zmieniła. Wybierz ponownie pole tekstu lub hasła.");
              return false;
            }
            const sent = await command({kind:"text",field,text},
              enter ? {kind:"key",key:"Enter"} : null,element);
            if (sent && element.value === text) element.value = "";
            return sent;
          };
          for (const [name,element] of Object.entries(fields)) {
            const field = name === "password" ? "password" : "text";
            element.addEventListener("focus",() => {
              submittedEditor = null;
              editor = {element,field,ref:currentRef};
            });
            // Keep a pending editor bound to the tab explicitly focused by
            // its owner. A background tab change never rebinds secret input.
            element.addEventListener("keydown",e => {
              if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return;
              e.preventDefault();
              if (!e.repeat) sendText(element,field,true);
            });
            byId("touch-mode-"+name).onclick = () => setMode(name,true);
          }
          byId("touch-editor-form").onsubmit = e => { e.preventDefault(); };
          byId("touch-send").onclick = () => sendText(value,"text");
          byId("touch-send-password").onclick = () => sendText(pass,"password");
          byId("touch-send-code").onclick = () => sendText(code,"text");
          byId("touch-enter").onclick = () => editor ?
            sendText(editor.element,editor.field,true) : command({kind:"key",key:"Enter"});
          byId("touch-tab").onclick = () => command({kind:"key",key:"Tab"});
          byId("touch-backspace").onclick = () => command({kind:"key",key:"Backspace"});
          for (const kind of ["back","forward","reload"])
            byId("touch-"+kind).onclick = () => command({kind});
          byId("touch-refresh").onclick = () => { refresh(true); refreshTabs(); refreshState(); };
          byId("touch-scroll-up").onclick = () => command({kind:"scroll",delta:-500});
          byId("touch-scroll-down").onclick = () => command({kind:"scroll",delta:500});
          byId("touch-keyboard").onclick = () => keyboard.hidden ? openKeyboard(true) : closeKeyboard();
          byId("touch-keyboard-close").onclick = closeKeyboard;
          byId("touch-more").onclick = () => {
            const opening = menu.hidden;
            closeKeyboard(); menu.hidden = !opening;
            byId("touch-more").setAttribute("aria-expanded",String(opening));
            if (opening) refreshTabs();
            layout();
          };
          byId("touch-menu-close").onclick = () => {
            menu.hidden = true; byId("touch-more").setAttribute("aria-expanded","false"); layout();
          };
          byId("touch-zoom").onclick = () => setZoom(zoom < 1.5 ? 1.7 : zoom < 2.3 ? 2.4 : 1);
          const fraction = (v,start,size) => Math.max(0,Math.min(1,(v-start)/Math.max(1,size)));
          function distance() {
            const [a,b] = [...pointers.values()];
            return Math.hypot(a.x-b.x,a.y-b.y);
          }
          shot.addEventListener("pointerdown",e => {
            e.preventDefault();
            if (!readyForInput()) return;
            pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
            shot.setPointerCapture(e.pointerId);
            if (pointers.size === 1) {
              gesture = {x:e.clientX,y:e.clientY,panX,panY,zoom}; pinching = false;
            } else if (pointers.size === 2) {
              pinching = true; gesture = {distance:distance(),zoom};
            }
          });
          shot.addEventListener("pointermove",e => {
            if (!pointers.has(e.pointerId) || !gesture) return;
            e.preventDefault();
            pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
            if (pointers.size === 2 && gesture.distance) {
              zoom = Math.max(1,Math.min(3,gesture.zoom*distance()/Math.max(1,gesture.distance)));
              byId("touch-zoom").setAttribute("aria-pressed",String(zoom > 1));
              byId("touch-zoom-label").textContent = zoom.toFixed(1).replace(".",",")+"×";
              layout();
            } else if (!pinching && (zoom > 1 || !keyboard.hidden)) {
              panX = gesture.panX+e.clientX-gesture.x; panY = gesture.panY+e.clientY-gesture.y; layout();
            }
          });
          function releasePointer(e,cancelled = false) {
            if (!pointers.has(e.pointerId)) return;
            pointers.delete(e.pointerId);
            const start = gesture;
            if (!pointers.size) {
              gesture = null;
              if (!cancelled && !pinching && start) {
                const dx = e.clientX-start.x, dy = e.clientY-start.y;
                const box = shot.getBoundingClientRect();
                if (Math.abs(dx)<12 && Math.abs(dy)<12) {
                  keyboardAnchor = {x:fraction(e.clientX,box.left,box.width),
                    y:fraction(e.clientY,box.top,box.height)};
                  command({kind:"tap",...keyboardAnchor});
                } else if (!keyboard.hidden) {
                  const area = viewport.getBoundingClientRect();
                  keyboardAnchor = {x:fraction(area.left+area.width/2,box.left,box.width),
                    y:fraction(area.top+area.height/2,box.top,box.height)};
                } else if (zoom === 1 && Math.abs(dy)>25) {
                  command({kind:"scroll",delta:Math.max(-950,Math.min(950,-dy*2))});
                }
              }
              pinching = false;
              if (deferredImage) {
                const image = deferredImage; deferredImage = null;
                showImage(image.url,image.ref).catch(() => refresh(true));
              }
            }
          }
          shot.addEventListener("pointerup",e => { e.preventDefault(); releasePointer(e); });
          shot.addEventListener("pointercancel",e => releasePointer(e,true));
          function updateAge() {
            if (ended) return;
            const age = lastFrame ? Math.floor((Date.now()-lastFrame)/1000) : null;
            byId("touch-age").textContent = age === null ? "Łączenie z Twoją sesją…" :
              age < 5 ? "Ty sterujesz · obraz aktualny" : "Ostatni obraz: "+age+" s temu";
            if (age !== null && age > 8) app.dataset.image = "stale";
          }
          function completed(data) {
            if (data.status !== "saved_and_closed" || data.profile_saved !== true ||
                data.full_profile_saved !== true) return false;
            ended = true; ending = false; controlAllowed = false;
            if (frameAbort) frameAbort.abort();
            for (const element of Object.values(fields)) element.value = "";
            editor = null; submittedEditor = null; deferredImage = null;
            shot.removeAttribute("src");
            for (const id of ["touch-viewport","touch-livebar","touch-profile-state","touch-notice","touch-editor","touch-menu","touch-dock"])
              byId(id).hidden = true;
            finish.hidden = true;
            byId("touch-ended").hidden = false;
            return true;
          }
          function applyState(data) {
            if (ended || !data || typeof data !== "object" || completed(data)) return;
            const savedAt = data.last_successful_backup_at;
            byId("touch-backup-state").textContent = data.portable_backup_ok === true ?
              "Kopia okresowa: " + (Number.isFinite(savedAt) ?
                new Date(savedAt*1000).toLocaleTimeString("pl-PL",{hour:"2-digit",minute:"2-digit"}) : "potwierdzona") :
              data.portable_backup_ok === false ? "Kopia okresowa: niepotwierdzona" : "Kopia okresowa: sprawdzam";
            byId("touch-auth-state").textContent = data.auth_verified === true ? "Logowanie potwierdzone" :
              data.authentication_stage === "verification_required" ? "Potrzebne potwierdzenie" :
              "Logowanie do sprawdzenia";
            if (Number.isFinite(data.remaining_seconds)) {
              const seconds = Math.max(0,Math.floor(data.remaining_seconds));
              byId("touch-session-time").textContent = Math.floor(seconds/60)+":"+String(seconds%60).padStart(2,"0");
            }
            if (data.status === "saving") {
              ending = true; finish.disabled = true;
              announce("Zapisuję profil i zamykam sesję. Zaczekaj na potwierdzenie.");
            } else if (data.status === "expired") {
              controlAllowed = false;
              announce("Czas sterowania minął. Oczekuję na potwierdzenie zapisu.","error");
            } else if (data.status === "save_unconfirmed") {
              controlAllowed = false; ending = true; finish.disabled = true;
              announce("Zapisu nie potwierdzono. Wróć do rozmowy, aby sprawdzić tę sesję.","error");
            } else if (data.status === "active" && !ending) controlAllowed = true;
          }
          async function refreshState() {
            if (ended || statePending || !visible()) return;
            statePending = true; lastState = Date.now();
            try { applyState(await readJSON("/owner-mobile-login/status",{},8000)); }
            catch (error) {
              if ([401,403,410].includes(error.status)) {
                controlAllowed = false;
                announce("Sesja niedostępna. Wróć do rozmowy, aby sprawdzić zapis.","error");
              }
            } finally { statePending = false; }
          }
          finish.onclick = async () => {
            if (ended || ending) return;
            if (busy) { announce("Zaczekaj na zakończenie bieżącej czynności."); return; }
            ending = true; finish.disabled = true;
            if (frameAbort) frameAbort.abort();
            announce("Zapisuję profil i zamykam sesję. Zaczekaj na potwierdzenie.");
            try {
              const data = await readJSON("/owner-mobile-login/finish",{
                method:"POST",headers:{"Content-Type":"application/json"},body:"{}"
              },25000);
              if (!completed(data)) {
                applyState(data);
                announce("Sprawdzam potwierdzenie zapisu. Nie zamykaj jeszcze tego ekranu.");
              }
            } catch (_) {
              announce("Sprawdzam potwierdzenie zapisu. Nie ponawiam zamknięcia.","connection");
            } finally { if (!ended) refreshState(); }
          };
          const wake = () => {
            if (visible() && !ended) { layout(); refreshState(); refreshTabs(); refresh(true); }
          };
          document.addEventListener("visibilitychange",() => {
            if (visible()) wake(); else if (frameAbort) frameAbort.abort();
          });
          window.addEventListener("focus",wake);
          window.addEventListener("pageshow",wake);
          window.addEventListener("resize",layout);
          if (window.visualViewport) {
            window.visualViewport.addEventListener("resize",layout);
            window.visualViewport.addEventListener("scroll",layout);
          }
          if (window.ResizeObserver) new ResizeObserver(layout).observe(viewport);
          layout(); refreshState(); refreshTabs();
          setInterval(() => {
            if (!visible() || ended) return;
            if (!busy) refresh();
            if (Date.now()-lastTabs > 3500) refreshTabs();
            if (Date.now()-lastState > 5500) refreshState();
          },1800);
          setInterval(updateAge,1000);
        })();
        """
        body = f"""
        <section id="touch-app" class="touch-app" data-image="connecting">
          <header class="touch-top">
            <div class="touch-identity"><h1>{service} · Twoje logowanie</h1><p>{profile}</p></div>
            <button type="button" id="touch-finish">Zapisz i wróć</button>
          </header>
          <div class="touch-livebar" id="touch-livebar">
            <span class="touch-dot" aria-hidden="true"></span><span id="touch-age">Łączenie z Twoją sesją…</span>
            <span id="touch-session-time" aria-label="Pozostały czas sterowania"></span>
          </div>
          <div id="touch-profile-state" class="touch-profile-state">
            <span id="touch-backup-state">Kopia okresowa: sprawdzam</span>
            <span id="touch-auth-state">Logowanie do sprawdzenia</span>
          </div>
          <div id="touch-viewport" aria-label="Sterowanie dotykowe zdalną stroną">
            <div id="touch-stage"><img id="touch-shot" alt="Widok Twojej zdalnej przeglądarki"
              draggable="false" referrerpolicy="no-referrer"></div>
            <div id="touch-wait" class="touch-wait"><div><strong>Otwieram Twoją stronę</strong>
              Za chwilę możesz dotykać elementów i wpisać dane na klawiaturze telefonu.</div></div>
          </div>
          <div id="touch-notice" class="touch-notice"><p id="touch-status" role="status" aria-live="polite">
            Łączę z aktywną sesją…</p></div>
          <section id="touch-editor" class="touch-sheet" aria-label="Klawiatura logowania" hidden>
            <div class="touch-sheet-head"><strong id="touch-field-hint">Najpierw wybierz pole na stronie</strong>
              <button type="button" id="touch-keyboard-close" aria-label="Schowaj klawiaturę">Schowaj</button></div>
            <div class="touch-modes" aria-label="Rodzaj wpisywanych danych">
              <button type="button" id="touch-mode-text" aria-pressed="true">Login / tekst</button>
              <button type="button" id="touch-mode-password" aria-pressed="false">Hasło</button>
              <button type="button" id="touch-mode-code" aria-pressed="false">Kod</button>
            </div>
            <form id="touch-editor-form" autocomplete="on" novalidate>
              <div id="touch-field-text" class="touch-entry-row"><div class="touch-entry">
                <label for="touch-value">Login lub tekst do wybranego pola</label>
                <input id="touch-value" name="username" type="text" inputmode="email" autocomplete="username"
                  placeholder="Login lub e-mail" autocapitalize="off" autocorrect="off" spellcheck="false" enterkeyhint="go" maxlength="250"></div>
                <button type="button" id="touch-send">Wpisz</button></div>
              <div id="touch-field-password" class="touch-entry-row" hidden><div class="touch-entry">
                <label for="touch-password">Hasło do wybranego pola hasła</label>
                <input id="touch-password" name="password" type="password" autocomplete="current-password"
                  placeholder="Wpisz lub wklej hasło" autocapitalize="off" autocorrect="off" spellcheck="false" enterkeyhint="go" maxlength="250"></div>
                <button type="button" id="touch-send-password">Wpisz</button></div>
              <div id="touch-field-code" class="touch-entry-row" hidden><div class="touch-entry">
                <label for="touch-code">Kod do wybranego pola na stronie</label>
                <input id="touch-code" name="verification-code" type="text" inputmode="numeric"
                  placeholder="Kod SMS lub z aplikacji" autocomplete="one-time-code" autocapitalize="off" spellcheck="false" enterkeyhint="go" maxlength="250"></div>
                <button type="button" id="touch-send-code">Wpisz</button></div>
            </form>
            <div class="touch-editor-actions">
              <button type="button" id="touch-tab">Następne pole</button>
              <button type="button" id="touch-backspace">Usuń znak</button>
              <button type="button" id="touch-enter">Wpisz i Enter</button>
            </div>
            <p class="touch-editor-hint">Możesz wkleić dane lub wybrać hasło w menedżerze telefonu. Panel nie zapisuje haseł.</p>
          </section>
          <section id="touch-menu" class="touch-sheet" aria-label="Karty i narzędzia widoku" hidden>
            <div class="touch-sheet-head"><strong>Karty i widok</strong>
              <button type="button" id="touch-menu-close">Zamknij menu</button></div>
            <label for="touch-tabs">Karta logowania</label>
            <select id="touch-tabs" disabled><option>Główna karta</option></select>
            <p id="touch-tabs-hint">Karty należą do tej samej, prywatnej sesji.</p>
            <div class="touch-menu-grid">
              <button type="button" id="touch-refresh">Odśwież obraz</button>
              <button type="button" id="touch-reload">Przeładuj stronę</button>
              <button type="button" id="touch-scroll-up">Przewiń w górę</button>
              <button type="button" id="touch-scroll-down">Przewiń w dół</button>
            </div>
            <p class="touch-help">Dotykasz strony w Twojej prywatnej sesji. Powiększ obraz, jeśli elementy są drobne.
              Po logowaniu wybierz „Zapisz i wróć” u góry — bez przechodzenia do innego ekranu.</p>
          </section>
          <nav id="touch-dock" class="touch-dock" aria-label="Sterowanie stroną">
            <button type="button" id="touch-back" class="touch-arrow" aria-label="Wstecz">‹</button>
            <button type="button" id="touch-forward" class="touch-arrow" aria-label="Dalej">›</button>
            <button type="button" id="touch-keyboard" aria-expanded="false" aria-controls="touch-editor">Klawiatura</button>
            <button type="button" id="touch-zoom" aria-pressed="false"><span id="touch-zoom-label">Powiększ</span></button>
            <button type="button" id="touch-more" aria-expanded="false" aria-controls="touch-menu"><span id="touch-more-label">Więcej</span></button>
          </nav>
          <section id="touch-ended" class="touch-ended" role="status" hidden>
            <div class="touch-ended-mark" aria-hidden="true">✓</div><h2>Profil zapisany</h2>
            <p>Sesja przeglądarki jest zamknięta. Wróć do rozmowy w ChatGPT, aby kontynuować zadanie.</p>
            <p>Zapis profilu potwierdzony. Stan logowania będzie sprawdzony przy powrocie do zadania.</p>
          </section>
        </section>
        """
        return _page(body,script,extra_style=TOUCH_STYLE)

    async def frame(self, request):
        async def capture(page, _record):
            return await page.screenshot(type="jpeg", quality=65,
                                         full_page=False, timeout=10000)
        try:
            result = await self._do(request, capture, limit=FRAME_TIMEOUT,
                                    ref=request.query_params.get("ref"))
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
            ref=data.get("ref")
            if (not isinstance(ref,str) or len(ref)!=16 or
                    any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
                        for c in ref)):
                raise ValueError()
            kind = data.get("kind")
            if kind == "tap":
                if set(data)!={"kind","x","y","ref"}:
                    raise ValueError()
                x,y=data["x"],data["y"]
                if not (self._num(x) and self._num(y)
                        and 0<=x<=1 and 0<=y<=1):
                    raise ValueError()
            elif kind == "scroll":
                if set(data)!={"kind","delta","ref"} or not self._num(data["delta"]):
                    raise ValueError()
                if not -1000<=data["delta"]<=1000:
                    raise ValueError()
            elif kind == "key":
                if set(data)!={"kind","key","ref"} or data["key"] not in {
                    "Enter","Tab","Backspace"}:
                    raise ValueError()
            elif kind in {"back","forward","reload"}:
                if set(data)!={"kind","ref"}:
                    raise ValueError()
            elif kind == "switch_tab":
                if set(data)!={"kind","ref"}:
                    raise ValueError()
            elif kind == "text":
                if set(data)!={"kind","field","text","ref"}:
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
                # History may restore a committed document without a new DOM
                # lifecycle event. A deferred resource must not turn an already
                # completed back/forward navigation into a misleading timeout.
                wait_until = "domcontentloaded" if kind == "reload" else "commit"
                await navigation(wait_until=wait_until, timeout=10000)
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
                      inp_type not in ("text","email","search","tel","url","number","")):
                    return False
                if not self._safe_login_page(page, record):
                    return False
                # An element handle stays bound to the inspected document;
                # navigation detaches it rather than retargeting the input.
                # Playwright fill emits the events React-controlled forms need.
                await field.fill(data["text"], timeout=7000)
            return True
        try:
            ok = (await self._switch_tab(request, data["ref"])
                  if kind == "switch_tab" else await self._do(request, perform,ref=ref))
        except Exception:
            ok = None
        if ok is not True:
            return JSONResponse({"error":"TOUCH_ACTION_FAILED"},
                                status_code=409, headers=self._headers())
        return JSONResponse({"status":"ok"},headers=self._headers())
