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
    return raw.strip()

def database():
    if not DB_URL:
        raise RuntimeError("missing database")
    return psycopg.connect(DB_URL, connect_timeout=10, options="-c statement_timeout=10000")

def db_ping() -> bool:
    try:
        with database() as conn:
            return conn.execute("SELECT 1").fetchone() == (1,)
    except Exception:
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
    if not logged_in(request):
        raise HTTPException(401, "Najpierw zaloguj się do nowej przeglądarki Neon.")

def require_mutation(request: Request):
    require(request)
    if request.headers.get("x-aib-request") != "same-origin":
        raise HTTPException(403, "Brak potwierdzenia żądania z panelu.")

class BrowserWorkspace:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.playwright = None
        self.browser = None
        self.context = None
        self.profile = None
        self.rev = None

    async def _ensure_engine(self):
        if self.browser is None:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])

    async def _save(self):
        if self.context is None:
            return
        data = await self.context.storage_state(indexed_db=True)
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

    async def open(self, name: str):
        if self.profile == name and self.context is not None:
            return
        await self._close_current()
        row = await asyncio.to_thread(db_load, name)
        if not row:
            raise HTTPException(404, "Profil nie istnieje")
        sealed, version = row
        try:
            state = json.loads(unseal(sealed))
        except Exception:
            raise HTTPException(409, "Nie można odczytać zaszyfrowanego profilu; nie nadpisano go.") from None
        await self._ensure_engine()
        ctx = await self.browser.new_context(
            storage_state=state, viewport=VIEWPORT, accept_downloads=False)
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

    async def action(self, data: dict):
        name = profile_name(data.get("name", ""))
        op = data.get("action")
        async with self.lock:
            await self.open(name)
            page = self.page()
            try:
                if op == "open":
                    pass
                elif op == "go":
                    await page.goto(safe_url(data.get("url", "")), wait_until="domcontentloaded", timeout=25000)
                elif op == "click":
                    x, y = float(data.get("x", -1)), float(data.get("y", -1))
                    if not (0 <= x < VIEWPORT["width"] and 0 <= y < VIEWPORT["height"]):
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
                await self._save()
                return {"ok": True, "title": (await page.title())[:200],
                        "url": safe_display_url(page.url)}
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(502, "Operacja przeglądarki nie powiodła się; dane źródłowe pozostają zachowane.") from None

    async def screenshot(self, name: str):
        async with self.lock:
            await self.open(profile_name(name))
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

@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
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
    response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline' data:; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    return response

@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(ROOT / "index.html", media_type="text/html")

@app.get("/health")
async def health():
    if not configured() or not await asyncio.to_thread(db_ping):
        return JSONResponse({"status": "not_ready", "store": "neon_fresh"}, status_code=503)
    return {"status": "ready", "store": "neon_fresh"}

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
