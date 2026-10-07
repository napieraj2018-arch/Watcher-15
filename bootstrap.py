from pathlib import Path
import base64, hashlib, hmac, io, json, os, sys, tarfile, time, urllib.request
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PAYLOAD_URL = "https://ai-browser-vault.floot.app/_cdn/static/86b8829a-8a44-47ff-bc6e-914c561f11a0-ai-browser-core-v034.aib"

def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")

def b64ud(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

def derive(master: bytes, label: str) -> bytes:
    return hmac.new(master, label.encode(), hashlib.sha256).digest()

def safe_extract(tf: tarfile.TarFile, dest: Path):
    dest = dest.resolve()
    for m in tf.getmembers():
        target = (dest / m.name).resolve()
        if dest not in target.parents and target != dest:
            raise RuntimeError("unsafe payload path")
    tf.extractall(dest)

master_text = os.environ.get("AI_BROWSER_MASTER_KEY", "").strip()
if not master_text:
    raise RuntimeError("AI_BROWSER_MASTER_KEY missing")
master = master_text.encode()

os.environ.setdefault("AI_BROWSER_ADMIN_TOKEN", b64u(derive(master, "admin")))
os.environ.setdefault("AI_BROWSER_PROFILE_KEY", b64u(derive(master, "profile")))
os.environ.setdefault("AI_BROWSER_MCP_TOKEN", b64u(derive(master, "mcp")))
os.environ.setdefault("AI_BROWSER_PROFILE_STORE_TOKEN", b64u(derive(master, "store")))
os.environ.setdefault("AI_BROWSER_PROFILE_STORE_URL", "https://ai-browser-vault.floot.app/_api/profile-vault")
os.environ.setdefault("AI_BROWSER_HOME", "/tmp/ai-browser")
os.environ.setdefault("AI_BROWSER_PORTABLE_PROFILES", "1")
os.environ.setdefault("AI_BROWSER_MAX_SESSIONS", "1")
os.environ.setdefault("AI_BROWSER_HOST", "0.0.0.0")
os.environ.setdefault("AI_BROWSER_PORT", os.environ.get("PORT", "10000"))

key = derive(master, "app-code")
req = urllib.request.Request(PAYLOAD_URL, headers={"User-Agent": "AI-Browser-Bootstrap/0.3.7"})
with urllib.request.urlopen(req, timeout=30) as resp:
    payload = resp.read(10_000_000)
if not payload.startswith(b"AIBSRC1"):
    raise RuntimeError("bad encrypted payload")
nonce, ct = payload[7:19], payload[19:]
raw = AESGCM(key).decrypt(nonce, ct, b"ai-browser-source-v1")
dest = Path("/tmp/aibrowser-app")
dest.mkdir(parents=True, exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
    safe_extract(tf, dest)
os.chdir(dest)
sys.path.insert(0, str(dest))

import server as appserver
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, RedirectResponse

BRIDGE_SIGN_KEY = derive(master, "bridge-sign")
BRIDGE_ENC_KEY = derive(master, "bridge-enc")
BRIDGE_MAX_FUTURE = 300

def _safe_json(obj):
    return json.loads(json.dumps(obj, default=str, ensure_ascii=False))

def _bridge_decode(request: Request):
    try:
        expires = int(request.path_params.get("expires", "0"))
    except Exception:
        raise ValueError("invalid_expiry")
    now = int(time.time())
    if expires < now - 5 or expires > now + BRIDGE_MAX_FUTURE:
        raise ValueError("expired_or_future_request")
    action = request.path_params.get("action", "")
    sig = request.path_params.get("sig", "")
    packed = request.query_params.get("p", "")
    if not packed:
        raise ValueError("missing_payload")
    msg = f"{expires}|{action}|{packed}".encode()
    expected = b64u(hmac.new(BRIDGE_SIGN_KEY, msg, hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise ValueError("bad_signature")
    blob = b64ud(packed)
    if len(blob) < 13:
        raise ValueError("bad_payload")
    nonce, ciphertext = blob[:12], blob[12:]
    clear = AESGCM(BRIDGE_ENC_KEY).decrypt(nonce, ciphertext, f"{expires}|{action}".encode())
    data = json.loads(clear.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("payload_must_be_object")
    return action, data

@appserver.mcp.custom_route("/bridge/{expires}/{sig}/{action}", methods=["GET"])
async def assistant_bridge(request: Request):
    try:
        action, d = _bridge_decode(request)
        m = appserver.manager
        if action == "profiles":
            out = await m.list_profiles()
        elif action == "sessions":
            out = await m.list_sessions()
        elif action == "start":
            out = await m.start(str(d["profile"]), mode=str(d.get("mode", "read_only")), headless=True, start_url=str(d.get("url", "about:blank")))
        elif action == "status":
            out = await m.status(str(d["sid"]))
        elif action == "set_mode":
            out = await m.set_mode(str(d["sid"]), str(d["mode"]))
        elif action == "stop":
            out = await m.stop(str(d["sid"]))
        elif action == "flush":
            out = await m.flush_profile(str(d["sid"]))
        elif action == "navigate":
            out = await m.navigate(str(d["sid"]), str(d["url"]))
        elif action == "snapshot":
            out = await m.snapshot(str(d["sid"]), max_text_chars=int(d.get("max_text_chars", 14000)), max_elements=int(d.get("max_elements", 180)))
        elif action == "screenshot":
            image = await m.screenshot_bytes(str(d["sid"]), bool(d.get("full_page", False)))
            return Response(image, media_type="image/png", headers={"Cache-Control": "no-store"})
        elif action == "click_ref":
            out = await m.click(str(d["sid"]), ref=str(d.get("ref", "")) or None, selector=None)
        elif action == "click_xy":
            out = await m.manual_click(str(d["sid"]), float(d["x"]), float(d["y"]))
        elif action == "fill_ref":
            out = await m.fill(str(d["sid"]), str(d.get("text", "")), ref=str(d.get("ref", "")) or None, selector=None)
        elif action == "type":
            out = await m.manual_type(str(d["sid"]), str(d.get("text", "")))
        elif action == "press":
            out = await m.press(str(d["sid"]), str(d["key"]), ref=str(d.get("ref", "")) or None, selector=None)
        elif action == "scroll":
            out = await m.scroll(str(d["sid"]), str(d.get("direction", "down")), int(d.get("pixels", 700)))
        elif action == "manual_scroll":
            out = await m.manual_scroll(str(d["sid"]), float(d.get("delta_y", 700)))
        elif action == "links":
            out = await m.links(str(d["sid"]), bool(d.get("visible_only", True)), int(d.get("limit", 200)))
        elif action == "back":
            out = await m.back(str(d["sid"]))
        elif action == "forward":
            out = await m.forward(str(d["sid"]))
        elif action == "reload":
            out = await m.reload(str(d["sid"]))
        elif action == "wait":
            out = await m.wait(str(d["sid"]), int(d.get("milliseconds", 1000)))
        elif action == "tabs":
            out = await m.tabs(str(d["sid"]))
        elif action == "switch_tab":
            out = await m.switch_tab(str(d["sid"]), int(d["index"]))
        elif action == "new_tab":
            out = await m.new_tab(str(d["sid"]), str(d.get("url", "about:blank")))
        elif action == "close_tab":
            out = await m.close_tab(str(d["sid"]), int(d.get("index", -1)))
        elif action == "metadata":
            out = await m.page_metadata(str(d["sid"]))
        elif action == "network":
            out = await m.network_log(str(d["sid"]), str(d.get("contains", "")), int(d.get("limit", 120)))
        elif action == "console":
            out = await m.console_log(str(d["sid"]), int(d.get("limit", 100)))
        elif action == "frames":
            out = await m.frames(str(d["sid"]))
        elif action == "frame_snapshot":
            out = await m.frame_snapshot(str(d["sid"]), int(d["frame_index"]), int(d.get("max_text_chars", 10000)), int(d.get("max_elements", 120)))
        elif action == "dialogs":
            out = await m.dialogs(str(d["sid"]))
        elif action == "staged_files":
            out = await m.staged_files()
        elif action == "upload_staged":
            out = await m.upload(str(d["sid"]), file_path=m.staged_path(str(d["file_id"])), ref=str(d.get("ref", "")) or None, selector=None)
        elif action == "audit":
            out = await m.recent_audit(limit=int(d.get("limit", 50)), profile=str(d.get("profile", "")) or None, session_id=str(d.get("sid", "")) or None)
        elif action == "diagnostics":
            sid = str(d["sid"])
            snap = await m.snapshot(sid, max_text_chars=int(d.get("max_text_chars", 12000)), max_elements=int(d.get("max_elements", 120)))
            meta = await m.page_metadata(sid)
            console = await m.console_log(sid, int(d.get("console_limit", 80)))
            network = await m.network_log(sid, str(d.get("network_contains", "")), int(d.get("network_limit", 100)))
            out = {"snapshot": snap, "metadata": meta, "console": console, "network": network}
        elif action == "setup":
            profile = str(d["profile"])
            login_url = str(d["url"])
            timeout_seconds = max(60, min(int(d.get("timeout_seconds", 900)), 3600))
            result = await m.start(profile, mode="write", headless=True, start_url=login_url)
            setup_id = appserver.secrets.token_urlsafe(10)
            cap = appserver.secrets.token_urlsafe(32)
            appserver.SETUP_SESSIONS[setup_id] = {"session_id": result["session_id"], "profile": profile, "cap": cap, "expires_at": time.time() + timeout_seconds}
            out = {"setup_id": setup_id, "profile": profile, "setup_url": f"{appserver._public_url()}/setup/{setup_id}#{cap}", "expires_in_seconds": timeout_seconds}
        else:
            return JSONResponse({"error": "unknown_action"}, status_code=404)
        return JSONResponse(_safe_json({"ok": True, "action": action, "result": out}), headers={"Cache-Control": "no-store"})
    except Exception as exc:
        safe = appserver.manager.safe_error_message(str(exc))[:700]
        return JSONResponse({"ok": False, "error": safe}, status_code=400, headers={"Cache-Control": "no-store"})

@appserver.mcp.custom_route("/mobile-access/{expires}/{sig}", methods=["GET"])
async def mobile_access(request: Request):
    try:
        expires = int(request.path_params.get("expires", "0"))
        now = int(time.time())
        if expires < now - 5 or expires > now + 900:
            return JSONResponse({"error": "expired"}, status_code=401)
        sig = request.path_params.get("sig", "")
        expected = b64u(hmac.new(BRIDGE_SIGN_KEY, f"mobile|{expires}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return JSONResponse({"error": "bad_signature"}, status_code=401)
        response = RedirectResponse(url="/admin", status_code=302)
        response.set_cookie("aibrowser_admin", appserver.ADMIN_TOKEN, httponly=True, secure=request.url.scheme == "https", samesite="strict", max_age=60 * 60 * 24 * 30)
        return response
    except Exception:
        return JSONResponse({"error": "invalid"}, status_code=401)

host = os.environ.get("AI_BROWSER_HOST", "127.0.0.1")
port = int(os.environ.get("AI_BROWSER_PORT", "8765"))
explicit_path = os.environ.get("AI_BROWSER_MCP_PATH", "").strip()
path_token = os.environ.get("AI_BROWSER_MCP_TOKEN", "").strip()
if explicit_path:
    mcp_path = explicit_path
elif path_token:
    mcp_path = "/mcp/" + path_token
else:
    mcp_path = "/mcp"
if not mcp_path.startswith("/"):
    mcp_path = "/" + mcp_path
appserver.mcp.run(
    transport="streamable-http",
    host=host,
    port=port,
    streamable_http_path=mcp_path,
    stateless_http=True,
    json_response=True,
)
