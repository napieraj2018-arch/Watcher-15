"""Separate Neon-only browser. No Floot/legacy credentials, sessions or bootstrap."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import uuid
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
DB_URL = os.environ.get("AIB_FRESH_DATABASE_URL", "")
ADMIN = os.environ.get("AIB_FRESH_ADMIN_TOKEN", "")
MCP_TOKEN = os.environ.get("AIB_FRESH_MCP_TOKEN", "")
DATA_KEY = os.environ.get("AIB_FRESH_DATA_KEY", "")
COOKIE = "aib_fresh_session"
VIEWPORT = {"width": 1280, "height": 800}
MAX_STATE = 12_000_000

def configured() -> bool:
    try:
        return (bool(DB_URL) and len(ADMIN) >= 32 and
                len(base64.b64decode(DATA_KEY, validate=True)) == 32)
    except (ValueError, TypeError):
        return False

def data_key() -> bytes:
    if not configured():
        raise RuntimeError("fresh-browser settings incomplete")
    return base64.b64decode(DATA_KEY, validate=True)

def seal(raw: bytes, key: bytes | None = None) -> bytes:
    if len(raw) > MAX_STATE:
        raise ValueError("profile state too large")
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key or data_key()).encrypt(nonce, raw, b"aib-fresh-profile-v1")

def unseal(ciphertext: bytes, key: bytes | None = None) -> bytes:
    if len(ciphertext) < 29 or len(ciphertext) > MAX_STATE + 128:
        raise ValueError("invalid sealed profile size")
    return AESGCM(key or data_key()).decrypt(ciphertext[:12], ciphertext[12:], b"aib-fresh-profile-v1")

def profile_name(name: str) -> str:
    if not isinstance(name, str) or not PROFILE_RE.fullmatch(name):
        raise HTTPException(400, "Nazwa profilu: małe litery, cyfry, _ lub -, maksymalnie 40.")
    return name

def safe_url(raw: str) -> str:
    if not isinstance(raw, str) or len(raw) > 1500:
        raise HTTPException(400, "Nieprawidłowy adres")
    parts = urlsplit(raw.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        raise HTTPException(400, "Podaj pełny adres HTTPS.")
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise HTTPException(400, "Ten adres nie jest publiczny")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if "." not in host:
            raise HTTPException(400, "Adres wymaga domeny")
    else:
        raise HTTPException(400, "Nie otwieramy adresów IP")
    if parts.port not in (None, 443):
        raise HTTPException(400, "Niedozwolony port")
    return raw.strip()

def database():
    if not DB_URL:
        raise RuntimeError("missing database")
    return psycopg.connect(DB_URL, connect_timeout=10)

def db_ping() -> bool:
    try:
        with database() as conn:
            return conn.execute("SELECT 1").fetchone() == (1,)
    except Exception as exc:
        print("AIB_FRESH_DB_PROBE_FAILED", type(exc).__name__, getattr(exc, "sqlstate", None), flush=True)
        return False

def db_list():
    with database() as conn:
        return [dict(name=n, updated_at=t.isoformat(), revision=int(v))
                for n, t, v in conn.execute(
                    "SELECT name, updated_at, revision FROM fresh_browser.profiles ORDER BY name").fetchall()]

def db_load(name: str):
    with database() as conn:
        row = conn.execute("SELECT sealed_state,revision FROM fresh_browser.profiles WHERE name=%s", (name,)).fetchone()
        return (bytes(row[0]), int(row[1])) if row else None

def db_create(name: str):
    blank = json.dumps({"cookies": [], "origins": []}).encode("utf-8")
    with database() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO fresh_browser.profiles (name,sealed_state) VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING name",
                        (name, seal(blank)))
            return cur.fetchone() is not None

def db_save(name: str, encrypted: bytes, rev: int):
    with database() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO fresh_browser.profile_versions (name,revision,sealed_state) SELECT name,revision,sealed_state FROM fresh_browser.profiles WHERE name=%s AND revision=%s ON CONFLICT DO NOTHING", (name, rev))
            cur.execute("UPDATE fresh_browser.profiles SET sealed_state=%s, revision=revision+1, updated_at=NOW() WHERE name=%s AND revision=%s RETURNING revision",
                        (encrypted, name, rev))
            row = cur.fetchone()
            return int(row[0]) if row else None

def _signature(data: str) -> str:
    return hmac.new(ADMIN.encode(), data.encode(), hashlib.sha256).hexdigest()

def session_value() -> str:
    exp = str(int(time.time()) + 12 * 60 * 60)
    payload = "v1." + exp
    return payload + "." + _signature(payload)

def logged_in(request: Request) -> bool:
    if not configured():
        return False
    supplied = request.cookies.get(COOKIE, "")
    try:
        version, exp, sig = supplied.split(".")
        msg = version + "." + exp
        return (version == "v1" and len(exp) <= 13 and int(exp) > time.time()
                and hmac.compare_digest(sig, _signature(msg)))
    except (ValueError, AttributeError):
        return False

def require(request: Request):
    service = request.headers.get("authorization", "")
    if len(MCP_TOKEN) >= 32 and hmac.compare_digest(service, "Bearer " + MCP_TOKEN):
        return
    if not logged_in(request):
        raise HTTPException(401, "Najpierw zaloguj się do nowej przeglądarki Neon.")

def require_panel_origin(request: Request):
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Niezgodne źródło żądania")
    if request.headers.get("x-aib-request") != "same-origin":
        raise HTTPException(403, "Brak potwierdzenia żądania z panelu.")

def require_mutation(request: Request):
    require(request)
    require_panel_origin(request)

class BrowserWorkspace:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.playwright = None
        self.browser = None
        self.context = None
        self.profile = None
        self.rev = None
        self.lease = None
        self.history = []
        self.human = False

    async def _ensure_engine(self):
        if self.browser is None:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])

    async def _save(self):
        if self.context is None:
            return
        await self.assert_lease()
        data = await self.context.storage_state(indexed_db=True)
        data["aib_tabs"] = [p.url for p in self.context.pages if p.url.startswith("https://")]
        data["aib_history"] = self.history[-200:]
        data["aib_viewport"] = self.page().viewport_size or VIEWPORT
        data["aib_profile"] = self.profile
        blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
        encrypted = seal(blob)
        nxt = await asyncio.to_thread(db_save, self.profile, encrypted, self.rev)
        if nxt is None:
            raise HTTPException(409, "Profil został zmieniony w innym procesie; zapis zatrzymano.")
        self.rev = nxt

    async def _close_current(self):
        if self.context is not None:
            await self._save()
            await self.context.close()
            self.context = None
            self.profile = None
            self.rev = None
            if self.lease:
                await asyncio.to_thread(self.lease.close)
                self.lease = None
            self.human = False

    async def assert_lease(self):
        if not self.lease or self.lease.closed:
            raise HTTPException(409, "Utracono blokadę profilu; zatrzymano sterowanie.")
        try:
            await asyncio.to_thread(self.lease.execute, "SELECT 1")
        except Exception:
            raise HTTPException(409, "Utracono blokadę profilu; wymagane sprawdzenie zapisu.") from None

    async def open(self, name: str):
        if self.profile == name and self.context is not None:
            return
        await self._close_current()
        lease = await asyncio.to_thread(database)
        lease.autocommit = True
        got = await asyncio.to_thread(lambda: lease.execute("SELECT pg_try_advisory_lock(hashtextextended(%s,0))", ("fresh:" + name,)).fetchone()[0])
        if not got:
            await asyncio.to_thread(lease.close)
            raise HTTPException(409, "Profil jest używany przez inny proces.")
        self.lease = lease
        row = await asyncio.to_thread(db_load, name)
        if not row:
            await asyncio.to_thread(lease.close)
            self.lease = None
            raise HTTPException(404, "Profil nie istnieje")
        sealed, version = row
        try:
            state = json.loads(unseal(sealed))
        except Exception:
            await asyncio.to_thread(lease.close)
            self.lease = None
            raise HTTPException(409, "Nie można odczytać zaszyfrowanego profilu; nie nadpisano go.") from None
        try:
            await self._ensure_engine()
        except Exception:
            await asyncio.to_thread(lease.close)
            self.lease = None
            raise
        if state.get("aib_profile", name) != name:
            await asyncio.to_thread(lease.close)
            self.lease = None
            raise HTTPException(409, "Niezgodność profilu; dane zachowano.")
        ctx = await self.browser.new_context(
            storage_state={k: state[k] for k in ("cookies", "origins")}, viewport=state.get("aib_viewport", VIEWPORT), accept_downloads=False,
            service_workers="block")
        async def guard(route):
            try:
                url = route.request.url
                if url.startswith(("data:", "blob:", "about:")):
                    await route.continue_(); return
                host = urlsplit(safe_url(url)).hostname
                addresses = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
                if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                    await route.abort(); return
                await route.continue_()
            except Exception:
                await route.abort()
        await ctx.route("**/*", guard)
        self.history = state.get("aib_history", [])
        for url in state.get("aib_tabs", [])[:10]:
            page = await ctx.new_page()
            try:
                await page.goto(safe_url(url), wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass
        if not ctx.pages:
            await ctx.new_page()
        self.context = ctx
        self.profile = name
        self.rev = version

    def page(self):
        if self.context is None:
            raise HTTPException(409, "Najpierw otwórz profil")
        pages = self.context.pages
        if not pages:
            raise HTTPException(409, "Brak karty przeglądarki")
        return pages[-1]

    async def action(self, data: dict, automated=False, owner_context=None):
        name = profile_name(data.get("name", ""))
        op = data.get("action")
        async with self.lock:
            if owner_context is not None and (self.context is not owner_context or self.profile != name):
                raise HTTPException(409, "Sesja tego linku została zamknięta. Poproś o nowy link.")
            if automated and (self.human or (self.context is not None and self.profile != name)):
                raise HTTPException(409, "Profil jest zajęty lub steruje nim właściciel.")
            await self.open(name)
            await self.assert_lease()
            if automated and self.human:
                raise HTTPException(409, "Właściciel przejął sterowanie; poczekaj na oddanie sterowania.")
            page = self.page()
            try:
                if op == "handoff":
                    self.human = bool(data.get("human", True))
                elif op == "snapshot":
                    return {"url": safe_display_url(page.url), "title": await page.title(),
                            "text": (await page.locator("body").inner_text())[:16000],
                            "elements": await page.locator("a,button,input,textarea,select").evaluate_all("els => els.slice(0,150).map((e,i)=>({index:i,tag:e.tagName,type:e.type||'',label:(e.innerText||e.getAttribute('aria-label')||e.getAttribute('placeholder')||'').slice(0,120)}))")}
                elif op == "upload":
                    index = int(data.get("index", -1))
                    if not 0 <= index < 150:
                        raise HTTPException(400, "Nieprawidłowy element pliku")
                    field = page.locator("a,button,input,textarea,select").nth(index)
                    if await field.get_attribute("type") != "file":
                        raise HTTPException(400, "To nie jest pole pliku")
                    raw = base64.b64decode(data.get("base64", ""), validate=True)
                    if len(raw) > 8_000_000:
                        raise HTTPException(400, "Maksymalny plik: 8 MB")
                    filename = re.sub(r"[^A-Za-z0-9._-]", "_", str(data.get("filename", "upload.bin")))[:120]
                    await field.set_input_files({"name": filename, "mimeType": "application/octet-stream", "buffer": raw})
                elif op == "fill":
                    index = int(data.get("index", -1))
                    if not 0 <= index < 150:
                        raise HTTPException(400, "Nieprawidłowy element")
                    field = page.locator("a,button,input,textarea,select").nth(index)
                    if automated and await field.get_attribute("type") == "password":
                        raise HTTPException(403, "Hasła wpisuje właściciel w panelu")
                    await field.fill(str(data.get("text", ""))[:10000])
                elif op == "click_element":
                    index = int(data.get("index", -1))
                    if not 0 <= index < 150:
                        raise HTTPException(400, "Nieprawidłowy element")
                    await page.locator("a,button,input,textarea,select").nth(index).click(timeout=10000)
                elif op == "viewport":
                    size = {"width":390,"height":844} if data.get("text") == "mobile" else VIEWPORT
                    await page.set_viewport_size(size)
                elif op == "back":
                    await page.go_back(wait_until="domcontentloaded", timeout=20000)
                elif op == "forward":
                    await page.go_forward(wait_until="domcontentloaded", timeout=20000)
                elif op == "reload":
                    await page.reload(wait_until="domcontentloaded", timeout=20000)
                elif op == "new_tab":
                    await self.context.new_page()
                elif op == "open":
                    pass
                elif op == "go":
                    await page.goto(safe_url(data.get("url", "")), wait_until="domcontentloaded", timeout=25000)
                elif op == "click":
                    x, y = float(data.get("x", -1)), float(data.get("y", -1))
                    viewport = page.viewport_size or VIEWPORT
                    if not (0 <= x < viewport["width"] and 0 <= y < viewport["height"]):
                        raise HTTPException(400, "Kliknięcie poza ekranem")
                    await page.mouse.click(x, y)
                elif op == "type":
                    s = data.get("text")
                    if not isinstance(s, str) or len(s) > 1000:
                        raise HTTPException(400, "Za długi tekst")
                    await page.keyboard.type(s, delay=15)
                elif op == "press":
                    key = data.get("key")
                    if key not in {"Enter", "Tab", "Escape", "Backspace", "ArrowDown", "ArrowUp",
                                   "ControlOrMeta+A", "ControlOrMeta+V", "Space"}:
                        raise HTTPException(400, "Nieobsługiwany klawisz")
                    await page.keyboard.press(key)
                elif op == "scroll":
                    delta = int(data.get("delta", 0))
                    if abs(delta) > 2000:
                        raise HTTPException(400, "Za dalekie przewinięcie")
                    await page.mouse.wheel(0, delta)
                elif op == "save":
                    pass
                elif op == "close":
                    await self._close_current()
                    return {"ok": True, "closed": True}
                else:
                    raise HTTPException(400, "Nieznane polecenie")
                await page.wait_for_timeout(400)
                if op in {"go", "back", "forward"}:
                    self.history.append({"url": page.url, "time": int(time.time())})
                await self._save()
                return {"ok": True, "human": self.human, "title": (await page.title())[:200],
                        "url": safe_display_url(page.url)}
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(502, "Operacja przeglądarki nie powiodła się; dane źródłowe pozostają zachowane.") from None

    async def screenshot(self, name: str, owner_context=None):
        async with self.lock:
            if owner_context is not None and self.context is not owner_context:
                raise HTTPException(409, "Sesja tego linku została zamknięta.")
            if self.context is None or self.profile != profile_name(name):
                raise HTTPException(409, "Otwórz wybrany profil przed pobraniem obrazu.")
            try:
                return await self.page().screenshot(type="png", animations="disabled", timeout=20000)
            except Exception:
                raise HTTPException(502, "Nie można wykonać zrzutu ekranu.") from None

    async def shutdown(self):
        async with self.lock:
            await self._close_current()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()

def safe_display_url(raw: str) -> str:
    if raw.startswith(("https://", "http://")):
        parts = urlsplit(raw)
        return parts.scheme + "://" + (parts.hostname or "")
    return "Nowa karta"

workspace = BrowserWorkspace()

# Independent, short-lived capabilities. Never expose the administrator/MCP key.
OWNER_COOKIE = "aib_owner_session"
OWNER_GRANTS = {}

def owner_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()

def prune_owner_grants():
    for key, grant in list(OWNER_GRANTS.items()):
        if grant["expires"] <= time.time() or grant["context"] is not workspace.context:
            del OWNER_GRANTS[key]

async def issue_owner_access(name):
    name = profile_name(name)
    async with workspace.lock:
        if workspace.context is None or workspace.profile != name or workspace.human:
            raise HTTPException(409, "Najpierw otwórz ten profil; nie przerywaj sterowania właściciela.")
        prune_owner_grants()
        if len(OWNER_GRANTS) >= 16:
            raise HTTPException(429, "Zbyt wiele aktywnych linków. Użyj poprzedniego lub poczekaj.")
        token = secrets.token_urlsafe(32)
        OWNER_GRANTS[owner_digest(token)] = {
            "name": name, "context": workspace.context,
            "expires": time.time() + 600, "kind": "link"}
        return token

def require_owner(request):
    prune_owner_grants()
    token = request.cookies.get(OWNER_COOKIE, "")
    grant = OWNER_GRANTS.get(owner_digest(token))
    if not grant or grant["kind"] != "session":
        raise HTTPException(401, "Dostęp wygasł. Poproś ChatGPT o nowy link do profilu.")
    if grant["name"] != workspace.profile or workspace.context is None:
        raise HTTPException(409, "Sesja tego linku została zamknięta.")
    return grant

@asynccontextmanager
async def lifespan(_app: FastAPI):
    async def autosave():
        while True:
            await asyncio.sleep(15)
            async with workspace.lock:
                if workspace.context:
                    try:
                        await workspace._save()
                    except Exception:
                        workspace.human = True
    saver = asyncio.create_task(autosave())
    yield
    saver.cancel()
    try:
        await workspace.shutdown()
    except Exception:
        pass

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

@app.middleware("http")
async def headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline' data:; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    return response

@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(ROOT / "index.html", media_type="text/html")

@app.get("/health")
async def health():
    if not configured():
        return JSONResponse({"status": "not_ready", "store": "neon_fresh", "reason": "configuration"}, status_code=503)
    if not await asyncio.to_thread(db_ping):
        return JSONResponse({"status": "not_ready", "store": "neon_fresh", "reason": "database"}, status_code=503)
    return {"status": "ready", "store": "neon_fresh"}

@app.get("/owner/", response_class=HTMLResponse)
async def owner_index():
    return FileResponse(ROOT / "index.html", media_type="text/html")

@app.post("/owner/api/pair")
async def owner_pair(request: Request, response: Response):
    require_panel_origin(request)
    data = await request.json()
    token = data.get("token", "") if isinstance(data, dict) else ""
    if not isinstance(token, str) or len(token) > 100:
        raise HTTPException(401, "Nieprawidłowy link dostępu")
    async with workspace.lock:
        prune_owner_grants()
        key = owner_digest(token)
        grant = OWNER_GRANTS.get(key)
        if not grant or grant["kind"] != "link":
            raise HTTPException(401, "Link wygasł lub został już użyty. Poproś o nowy link.")
        del OWNER_GRANTS[key]
        session = secrets.token_urlsafe(32)
        OWNER_GRANTS[owner_digest(session)] = {**grant, "expires": time.time() + 3600, "kind": "session"}
    response.set_cookie(OWNER_COOKIE, session, max_age=3600,
                        httponly=True, secure=True, samesite="strict", path="/owner")
    return {"ok": True, "owner": True, "profile": grant["name"]}

@app.get("/owner/api/session")
async def owner_session(request: Request):
    grant = require_owner(request)
    return {"ok": True, "owner": True, "profile": grant["name"]}

@app.get("/owner/api/profiles")
async def owner_profiles(request: Request):
    grant = require_owner(request)
    return {"profiles": [{"name": grant["name"]}]}

@app.post("/owner/api/action")
async def owner_action(request: Request):
    require_panel_origin(request)
    grant = require_owner(request)
    payload = await request.json()
    if not isinstance(payload, dict) or payload.get("name") != grant["name"]:
        raise HTTPException(403, "Ten link pozwala sterować wyłącznie wskazanym profilem.")
    if payload.get("action") not in {"open", "go", "handoff", "back", "reload", "save", "close", "type", "press", "scroll", "viewport", "click"}:
        raise HTTPException(403, "Polecenie niedostępne w tym panelu.")
    return await workspace.action(payload, owner_context=grant["context"])

@app.get("/owner/api/screen")
async def owner_screen(request: Request, name: str):
    grant = require_owner(request)
    if name != grant["name"]:
        raise HTTPException(403, "Ten link nie udostępnia innego profilu.")
    png = await workspace.screenshot(name, owner_context=grant["context"])
    return Response(png, media_type="image/png")

@app.post("/owner/api/logout")
async def owner_logout(request: Request, response: Response):
    require_panel_origin(request)
    require_owner(request)
    OWNER_GRANTS.pop(owner_digest(request.cookies.get(OWNER_COOKIE, "")), None)
    response.delete_cookie(OWNER_COOKIE, path="/owner")
    return {"ok": True}

@app.get("/api/session")
async def check(request: Request):
    require(request)
    return {"ok": True, "store": "neon_fresh"}

@app.post("/api/login")
async def login(request: Request, response: Response):
    if not configured():
        raise HTTPException(503, "Konfiguracja nowej przeglądarki niekompletna")
    data = await request.json()
    candidate = data.get("token", "")
    if not isinstance(candidate, str) or not hmac.compare_digest(candidate, ADMIN):
        raise HTTPException(401, "Nieprawidłowy klucz administratora")
    response.set_cookie(COOKIE, session_value(), max_age=43200,
                        httponly=True, secure=True, samesite="strict", path="/")
    return {"ok": True}

@app.post("/api/logout")
async def logout(request: Request, response: Response):
    require_mutation(request)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}

@app.get("/api/profiles")
async def profiles(request: Request):
    require(request)
    try:
        return {"profiles": await asyncio.to_thread(db_list)}
    except Exception:
        raise HTTPException(503, "Neon jest chwilowo niedostępny") from None

@app.post("/api/profiles")
async def create_profile(request: Request):
    require_mutation(request)
    data = await request.json()
    name = profile_name(data.get("name", ""))
    try:
        if not await asyncio.to_thread(db_create, name):
            raise HTTPException(409, "Profil o tej nazwie już istnieje.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Nie udało się zapisać w Neon") from None
    return {"ok": True, "profile": name}

@app.post("/api/action")
async def action(request: Request):
    require_mutation(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(400, "Nieprawidłowe polecenie")
    return await workspace.action(payload)

@app.get("/api/screen")
async def screen(request: Request, name: str):
    require(request)
    png = await workspace.screenshot(name)
    return Response(png, media_type="image/png")

FIXTURE = """<!doctype html><title>AI Browser acceptance</title><form><input id='field' placeholder='Neutral test'><button type='button' onclick="document.querySelector('output').textContent=document.querySelector('input').value">Check</button></form><output></output>"""

async def acceptance(args):
    name = profile_name(args.get("name", ""))
    if not name.startswith("acceptance-"):
        raise HTTPException(400, "Dedicated synthetic profile required")
    phase = args.get("text", "seed")
    async with workspace.lock:
        if workspace.context is not None:
            raise HTTPException(409, "Close your owned profile first")
        if phase == "seed" and not await asyncio.to_thread(db_create, name):
            raise HTTPException(409, "Synthetic profile already exists")
        await workspace.open(name)
        page = await workspace.context.new_page()
        await workspace.context.route("https://aib-acceptance.invalid/**", lambda r: r.fulfill(status=200, content_type="text/html", body=FIXTURE))
        await page.goto("https://aib-acceptance.invalid/")
        if phase == "seed":
            await page.locator("#field").fill("neutral-form-ok")
            await page.locator("button").click()
            assert await page.locator("output").inner_text() == "neutral-form-ok"
            await page.evaluate("""async () => {
                document.cookie='acceptance=neon-v2; Secure; SameSite=Strict; path=/';
                localStorage.setItem('acceptance','neon-v2');
                await new Promise((resolve,reject)=>{
                  const q=indexedDB.open('aib_acceptance',1);
                  q.onupgradeneeded=()=>q.result.createObjectStore('data');
                  q.onerror=reject;
                  q.onsuccess=()=>{const db=q.result,t=db.transaction('data','readwrite');t.objectStore('data').put('neon-v2','marker');t.oncomplete=()=>{db.close();resolve()};t.onerror=reject;};
                });
            }""")
            workspace.history.append({"url": page.url, "time": int(time.time())})
            await workspace._close_current()
            return {"phase": "seed", "form": True, "saved_closed": True}
        checks = await page.evaluate("""async () => ({cookie:document.cookie.includes('acceptance=neon-v2'),localStorage:localStorage.getItem('acceptance')==='neon-v2',indexedDB:await new Promise((resolve,reject)=>{const q=indexedDB.open('aib_acceptance',1);q.onerror=reject;q.onsuccess=()=>{const db=q.result;if(!db.objectStoreNames.contains('data')){db.close();resolve(false);return;}const t=db.transaction('data'),r=t.objectStore('data').get('marker');r.onsuccess=()=>{db.close();resolve(r.result==='neon-v2')};r.onerror=reject;}})})""")
        checks['history'] = any(x.get('url') == 'https://aib-acceptance.invalid/' for x in workspace.history)
        await workspace._close_current()
        return {"phase": "verify", "checks": checks, "all_passed": all(checks.values()), "saved_closed": True}

def db_checkpoint(task_id, payload=None, revision=None):
    with database() as conn:
        if payload is None:
            row = conn.execute("SELECT sealed_state,revision FROM fresh_browser.tasks WHERE id=%s", (task_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Brak zadania")
            return {"id": task_id, "checkpoint": json.loads(unseal(bytes(row[0]))), "revision": row[1]}
        raw = json.dumps(payload).encode()
        if len(raw) > 50000:
            raise HTTPException(400, "Za duży checkpoint")
        if revision is None:
            row = conn.execute("INSERT INTO fresh_browser.tasks (id,sealed_state) VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING revision", (task_id,seal(raw))).fetchone()
        else:
            row = conn.execute("UPDATE fresh_browser.tasks SET sealed_state=%s,revision=revision+1 WHERE id=%s AND revision=%s RETURNING revision", (seal(raw),task_id,revision)).fetchone()
        if not row:
            raise HTTPException(409, "Konflikt checkpointu")
        return {"id": task_id, "revision": row[0]}

@app.get("/api/status")
async def status(request: Request):
    require(request)
    return {"profile": workspace.profile, "human": workspace.human, "revision": workspace.rev}

@app.post("/mcp")
async def mcp(request: Request):
    supplied = request.headers.get("authorization", "")
    if len(MCP_TOKEN) < 32 or not hmac.compare_digest(supplied, "Bearer " + MCP_TOKEN):
        raise HTTPException(401, "MCP authorization required")
    msg = await request.json()
    method, ident = msg.get("method"), msg.get("id")
    if ident is None:
        return Response(status_code=202)
    if method == "server/discover":
        result = {"supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}}}
    elif method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "AI Browser Neon Fresh", "version": "2.0.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": "fresh_browser", "description": "Owner browser: list_profiles, create_profile, open, go, snapshot, click_element, fill, press, scroll, back, forward, reload, new_tab, save, close, screenshot, checkpoint. Use snapshot before elements. Never supply passwords, MFA or CAPTCHA; owner uses mobile handoff. Checkpoints must exclude credentials and capabilities. Unknown writes must be verified before retry.", "inputSchema": {"type": "object", "properties": {"action": {"type": "string"}, "name": {"type": "string"}, "url": {"type": "string"}, "index": {"type": "integer"}, "text": {"type": "string"}, "key": {"type": "string"}, "delta": {"type": "integer"}, "base64": {"type": "string"}, "filename": {"type": "string"}, "task_id": {"type": "string"}, "checkpoint": {"type": "object"}, "revision": {"type": "integer"}}, "required": ["action"]}}]}
        for name, description in [("profile_list", "List new Neon Fresh profile metadata only. No legacy Floot data."), ("browser_sessions", "List active Neon Fresh sessions only.")]:
            result["tools"].append({"name":name,"description":description,"inputSchema":{"type":"object","properties":{}}})
    elif method == "tools/call":
        try:
            tool_name = msg.get("params", {}).get("name")
            if tool_name == "profile_list":
                value = await asyncio.to_thread(db_list)
                return {"jsonrpc":"2.0","id":ident,"result":{"content":[{"type":"text","text":json.dumps(value)}]}}
            if tool_name == "browser_sessions":
                value = [{"profile":workspace.profile,"human":workspace.human}] if workspace.context else []
                return {"jsonrpc":"2.0","id":ident,"result":{"content":[{"type":"text","text":json.dumps(value)}]}}
            if tool_name != "fresh_browser":
                raise HTTPException(400, "Unknown tool")
            args = msg["params"].get("arguments", {})
            action = args.get("action")
            if action == "acceptance":
                value = await acceptance(args)
            elif action == "list_profiles":
                value = {"profiles": await asyncio.to_thread(db_list)}
            elif action == "create_profile":
                value = {"created": await asyncio.to_thread(db_create, profile_name(args.get("name", "")))}
            elif action == "owner_access":
                token = await issue_owner_access(args.get("name", ""))
                value = {"url": str(request.base_url).rstrip("/") + "/owner/#" + token,
                         "profile": args.get("name"), "expires_in": 600,
                         "instructions": "Open this one-use link yourself, then choose Przejmij sterowanie. Never enter credentials in ChatGPT."}
            elif action == "checkpoint":
                task_id = profile_name(args.get("task_id", ""))
                value = await asyncio.to_thread(db_checkpoint,task_id,args.get("checkpoint"),args.get("revision"))
            elif action == "screenshot":
                png = await workspace.screenshot(profile_name(args.get("name", "")))
                return {"jsonrpc": "2.0", "id": ident, "result": {"content": [{"type": "image", "mimeType": "image/png", "data": base64.b64encode(png).decode()}]}}
            elif action == "handoff":
                raise HTTPException(403, "Only the owner may change control mode")
            else:
                value = await workspace.action(args, automated=True)
            result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
        except HTTPException as exc:
            result = {"isError": True, "content": [{"type": "text", "text": str(exc.detail)}]}
        except Exception as exc:
            print("AIB_FRESH_TOOL_ERROR", type(exc).__name__, flush=True)
            result = {"isError": True, "content": [{"type": "text", "text": "Operation failed (" + type(exc).__name__ + "); verify before retry"}]}
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}

if __name__ == "__main__":
    key = secrets.token_bytes(32)
    assert unseal(seal(b'{"ok":true}', key), key) == b'{"ok":true}'
    assert profile_name("gmail_main") == "gmail_main"
    try:
        safe_url("http://localhost")
    except HTTPException:
        pass
    else:
        raise AssertionError("not HTTPS")
    assert safe_url("https://accounts.google.com/") == "https://accounts.google.com/"
    print("SELFTEST PASS: isolated encryption, profile name and URL gate")

