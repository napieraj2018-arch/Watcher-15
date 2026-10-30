"""Production composition root for the existing Fresh application.

Same API, database, encryption, owner grants and profile locks as server.py.
Adds classified network failures and observes *implicit* form navigations.
No authentication bypass, request-body capture, or automatic form replay.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import time
from collections import OrderedDict
from urllib.parse import urlsplit

import server

HTTPException = server.HTTPException
MAX_NETWORK_URL = 16384
METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
REASONS = {
    "url_policy", "address_policy", "dns_unavailable", "dns_timeout",
    "transport_unconfirmed", "network_failed",
}


def network_host(url: str) -> str:
    """The UI's short address field is not a limit for provider redirects.

    Preserve HTTPS, public-domain, port and userinfo restrictions. Never return
    paths/query strings, which may contain authentication callback material.
    """
    if not isinstance(url, str) or len(url) > MAX_NETWORK_URL:
        raise ValueError("url_policy")
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        if (p.scheme != "https" or not host or p.username is not None
                or p.password is not None or p.port not in (None, 443)
                or "." not in host or host == "localhost"
                or host.endswith((".local", ".internal", ".localhost"))):
            raise ValueError("url_policy")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("url_policy")
        return host
    except (ValueError, TypeError):
        raise ValueError("url_policy") from None


def origin_only(url: str) -> str:
    try:
        return "https://" + network_host(url)
    except ValueError:
        return "unavailable"


class PublicNetworkPolicy:
    """Same public-address boundary, with distinct failure reasons.

    Positive DNS results are shared only for subresources (10s, 128 hosts).
    Every main-frame request gets a fresh validation. Browser request bodies,
    cookies and headers are never read, changed, logged or resubmitted.
    """
    def __init__(self, observer, resolver=socket.getaddrinfo, clock=time.monotonic):
        self.observer = observer
        self.resolver = resolver
        self.clock = clock
        self.cache = OrderedDict()
        self.slots = asyncio.Semaphore(8)
        # Production pages routinely request dozens of assets from a single
        # host at once. Coalesce identical lookups without relaxing the
        # public-IP requirement; main-frame navigations still revalidate.
        self.inflight = {}

    async def _resolve(self, host):
        async with self.slots:
            return await asyncio.to_thread(
                self.resolver, host, 443, type=socket.SOCK_STREAM)

    async def _shared_resolve(self, host):
        task = self.inflight.get(host)
        if task is None:
            if len(self.inflight) >= 128:
                raise ValueError("dns_timeout")
            async def lookup():
                try:
                    return await self._resolve(host)
                finally:
                    if self.inflight.get(host) is asyncio.current_task():
                        self.inflight.pop(host, None)
            task = asyncio.create_task(lookup())
            # Consume a late exception when all waiters have timed out.
            task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception())
            self.inflight[host] = task
        return await asyncio.shield(task)

    async def addresses(self, host, navigation):
        hit = self.cache.get(host)
        if not navigation and hit and hit > self.clock():
            return
        try:
            async with asyncio.timeout(8):
                # A main navigation must be fresh; subresources may share the
                # same simultaneous DNS lookup, never an unvalidated answer.
                rows = (await self._resolve(host) if navigation
                        else await self._shared_resolve(host))
        except TimeoutError:
            raise ValueError("dns_timeout") from None
        except (OSError, UnicodeError):
            raise ValueError("dns_unavailable") from None
        try:
            public = bool(rows) and all(ipaddress.ip_address(r[4][0]).is_global for r in rows)
        except (ValueError, IndexError, TypeError):
            public = False
        if not public:
            raise ValueError("address_policy")
        self.cache[host] = self.clock() + 10
        self.cache.move_to_end(host)
        while len(self.cache) > 128:
            self.cache.popitem(last=False)

    async def __call__(self, route):
        req = route.request
        try:
            if req.url.startswith(("data:", "blob:", "about:")):
                await route.continue_()
                return
            host = network_host(req.url)
            await self.addresses(host, req.is_navigation_request())
        except ValueError as exc:
            reason = str(exc) if str(exc) in REASONS else "url_policy"
            self.observer(req, reason)
            code = "namenotresolved" if reason.startswith("dns_") else "blockedbyclient"
            await route.abort(code)
            return
        # Continuing a request is attempted ONCE. If Chromium has already
        # handled/closed it, do not issue a second abort or replay a POST.
        try:
            await route.continue_()
        except Exception:
            self.observer(req, "transport_unconfirmed")


class AuditedWorkspace(server.BrowserWorkspace):
    def __init__(self):
        super().__init__()
        self.last_safe_urls = {}
        self.document_methods = {}
        self.document_status = {}
        self.policy_failures = []
        self.resource_failures = []
        self.guarded_context = None
        self.network_policy = PublicNetworkPolicy(self.record_policy_failure)

    @staticmethod
    def main_document(page, req):
        try:
            return req.is_navigation_request() and req.frame == page.main_frame
        except Exception:
            return False

    def record_policy_failure(self, req, reason):
        method = req.method if req.method in METHODS else "OTHER"
        self.policy_failures.append({
            "origin": origin_only(req.url), "method": method,
            "reason": reason if reason in REASONS else "network_failed",
            "url_length": min(len(req.url), MAX_NETWORK_URL + 1),
            "navigation": bool(req.is_navigation_request()),
            "time": int(time.time()),
        })
        self.policy_failures = self.policy_failures[-20:]

    def register_page(self, page):
        if page in self.tab_ids:
            return
        super().register_page(page)
        if page.url.startswith("https://"):
            self.last_safe_urls[page] = page.url

        def requested(req):
            if not self.main_document(page, req):
                return
            self.document_methods[page] = req.method if req.method in METHODS else "OTHER"
            self.document_status.pop(page, None)
            # Record the *previous committed* location, not the POST endpoint.
            if page.url.startswith("https://"):
                self.last_safe_urls.setdefault(page, page.url)

        def committed(frame):
            if frame == page.main_frame and page.url.startswith("https://"):
                if self.document_status.get(page, 200) >= 400:
                    self.failed_pages.add(page)
                # Never persist a form action/callback as an automatic replay
                # target. After a POST, the public origin is a safe GET target.
                if self.document_methods.get(page, "GET") in {"GET", "HEAD"}:
                    self.last_safe_urls[page] = page.url
                else:
                    self.last_safe_urls[page] = origin_only(page.url) + "/"

        def failed(req):
            if not self.main_document(page, req):
                return
            method = req.method if req.method in METHODS else "OTHER"
            self.document_methods[page] = method
            # A manually submitted form bypasses navigate(). Preserve the
            # previous page when Chromium replaces it with chrome-error/about.
            target = self.last_safe_urls.get(page)
            if not target:
                origin = origin_only(req.url)
                target = origin + "/" if origin != "unavailable" else ""
            if target:
                self.pending_urls[page] = target
            self.failed_pages.add(page)
            if self.navigation_failures:
                item = self.navigation_failures[-1]
                if item.get("tab") == self.tab_ids[page]:
                    item["method"] = method
                    item["url_length"] = min(len(req.url), MAX_NETWORK_URL + 1)
                    item["form_resubmitted"] = False

        def response_received(response):
            if self.main_document(page, response.request):
                self.document_status[page] = response.status
                if response.status >= 400:
                    self.failed_pages.add(page)

        # The old diagnostics watched main-frame documents only. A login can
        # display a healthy facebook.com frame while the cross-origin
        # reCAPTCHA script or iframe silently fails. Record only the origin,
        # resource type, an HTTP status or a bounded network failure code.
        # Never retain URLs, form data, cookies, tokens, or console messages.
        def subresource_failure(req):
            if self.main_document(page, req):
                return
            failure = str(req.failure or "unknown")
            failure = (failure if re.fullmatch(r"net::ERR_[A-Z0-9_]+", failure)
                       else "request_failed")
            kind = req.resource_type if req.resource_type in {
                "script", "stylesheet", "xhr", "fetch", "document",
                "image", "font", "websocket", "other"
            } else "other"
            self.resource_failures.append({
                "origin": origin_only(req.url), "kind": kind,
                "failure": failure, "time": int(time.time())})
            self.resource_failures = self.resource_failures[-40:]

        def subresource_status(response):
            if self.main_document(page, response.request) or response.status < 400:
                return
            kind = response.request.resource_type
            self.resource_failures.append({
                "origin": origin_only(response.url),
                "kind": kind if kind in {
                    "script", "stylesheet", "xhr", "fetch", "document",
                    "image", "font", "websocket", "other"
                } else "other",
                "http_status": int(response.status),
                "time": int(time.time())})
            self.resource_failures = self.resource_failures[-40:]

        page.on("response", response_received)
        page.on("response", subresource_status)
        page.on("request", requested)
        page.on("framenavigated", committed)
        page.on("requestfailed", failed)
        page.on("requestfailed", subresource_failure)


    async def navigate(self, page, raw, *, restoring=False):
        if not restoring:
            return await super().navigate(page, raw, restoring=False)
        # Persisted tab URLs may be provider-generated OAuth/checkpoint links
        # longer than the manual address bar's 1500-character limit. A browser
        # restart must not crash the entire vault or replay auth callbacks.
        try:
            target = server.safe_url(raw)
        except HTTPException:
            origin = origin_only(raw)
            if origin == "unavailable":
                self.failed_pages.add(page)
                return False
            target = origin + "/"
        else:
            parsed = urlsplit(target)
            # Never auto-GET an old one-use query/fragment on restart. Keep
            # non-sensitive navigation paths (e.g. /wp-admin/edit.php), but
            # return to the provider homepage for login/callback/checkpoint
            # paths. All cookie/localStorage/IndexedDB state remains intact.
            if parsed.query or parsed.fragment:
                path = (parsed.path or "/")
                unsafe_flow = any(word in path.lower() for word in (
                    "oauth", "callback", "checkpoint", "signin", "login",
                    "recover", "challenge", "verify", "confirm"))
                target = (origin_only(target) + "/" if unsafe_flow else
                          parsed.scheme + "://" + parsed.netloc + path)
        return await super().navigate(page, target, restoring=True)

    async def open(self, name):
        await super().open(name)
        if self.context is not self.guarded_context:
            # Playwright uses the last registered matching route first. This
            # replacement preserves the public-address policy. No fallback to
            # the old catch-all abort handler; no duplicated network request.
            await self.context.route("**/*", self.network_policy)
            self.guarded_context = self.context

    async def _close_current(self):
        await super()._close_current()
        self.last_safe_urls.clear()
        self.document_methods.clear()
        self.document_status.clear()
        self.policy_failures.clear()
        self.resource_failures.clear()
        self.guarded_context = None
        self.network_policy = PublicNetworkPolicy(self.record_policy_failure)

    async def tab_state(self):
        result = await super().tab_state()
        result["policy_failures"] = list(self.policy_failures[-10:])
        result["resource_failures"] = list(self.resource_failures[-20:])
        # Cross-origin frame locations are deliberately reduced to public
        # origins; the real captcha challenge state is owner-only.
        result["frames"] = [
            {"origin": origin_only(frame.url), "main": frame == self.page().main_frame}
            for frame in self.page().frames[:25]
        ]
        return result

    async def diagnostics(self, name):
        async with self.lock:
            if self.context is None or self.profile != server.profile_name(name):
                raise HTTPException(409, "Najpierw otwórz wskazany profil.")
            result = await self.tab_state()
            result["profile"] = self.profile
            result["human"] = self.human
            # No input values, form body, cookies, full action URL or HTML.
            result["forms"] = await self.page().locator("form").evaluate_all(
                "fs=>fs.slice(0,12).map(f=>({method:f.method.toUpperCase(),"
                "origin:(()=>{try{return new URL(f.action).origin}catch{return 'invalid'}})(),"
                "action_length:f.action.length}))")
            return result

    async def action(self, data, automated=False, owner_context=None):
        if data.get("action") == "diagnostics":
            return await self.diagnostics(data.get("name", ""))
        # Explicit reload after an uncertain form failure must never invoke
        # Chromium's form-resubmission path. An owner may return to the prior
        # safe GET page; neither saved body nor credentials are available here.
        if (data.get("action") == "reload" and self.context is not None
                and self.profile == data.get("name")
                and self.page() in self.failed_pages
                and self.document_methods.get(self.page()) not in (None, "GET", "HEAD")):
            target = self.last_safe_urls.get(self.page()) or self.pending_urls.get(self.page())
            if not target:
                raise HTTPException(409, "Wynik formularza nieznany. Otwórz stronę główną; nie ponawiaj formularza.")
            data = {**data, "action": "go", "url": target}
        return await super().action(data, automated=automated, owner_context=owner_context)


# Uvicorn composition root; replace the empty workspace only at process import.
# All existing route authentication, encryption, CAS and handoff functions keep
# using server.workspace. No live workspace is replaced at runtime.
if server.workspace.context is not None:
    raise RuntimeError("Runtime must start before opening any browser profile")
server.workspace = AuditedWorkspace()
app = server.app
