from pathlib import Path
import base64, hashlib, hmac, io, os, runpy, sys, tarfile, urllib.request
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PAYLOAD_URL = "https://ai-browser-vault.floot.app/_cdn/static/14a70d54-e7f0-426a-9374-96528f7405cb-ai-browser-core-v031.aib"

def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")

def derive(master: bytes, label: str) -> bytes:
    return hmac.new(master, label.encode(), hashlib.sha256).digest()

def safe_extract(tf: tarfile.TarFile, dest: Path):
    dest=dest.resolve()
    for m in tf.getmembers():
        target=(dest/m.name).resolve()
        if dest not in target.parents and target != dest:
            raise RuntimeError("unsafe payload path")
    tf.extractall(dest)

master_text=os.environ.get("AI_BROWSER_MASTER_KEY","").strip()
if not master_text:
    raise RuntimeError("AI_BROWSER_MASTER_KEY missing")
master=master_text.encode()

os.environ.setdefault("AI_BROWSER_ADMIN_TOKEN", b64u(derive(master,"admin")))
os.environ.setdefault("AI_BROWSER_PROFILE_KEY", b64u(derive(master,"profile")))
os.environ.setdefault("AI_BROWSER_MCP_TOKEN", b64u(derive(master,"mcp")))
os.environ.setdefault("AI_BROWSER_PROFILE_STORE_TOKEN", b64u(derive(master,"store")))
os.environ.setdefault("AI_BROWSER_PROFILE_STORE_URL","https://ai-browser-vault.floot.app/_api/profile-vault")
os.environ.setdefault("AI_BROWSER_HOME","/tmp/ai-browser")
os.environ.setdefault("AI_BROWSER_PORTABLE_PROFILES","1")
os.environ.setdefault("AI_BROWSER_MAX_SESSIONS","1")
os.environ.setdefault("AI_BROWSER_HOST","0.0.0.0")
os.environ.setdefault("AI_BROWSER_PORT",os.environ.get("PORT","10000"))

key=derive(master,"app-code")
req=urllib.request.Request(PAYLOAD_URL,headers={"User-Agent":"AI-Browser-Bootstrap/0.3.2"})
with urllib.request.urlopen(req,timeout=30) as resp:
    payload=resp.read(10_000_000)
if not payload.startswith(b"AIBSRC1"):
    raise RuntimeError("bad encrypted payload")
nonce,ct=payload[7:19],payload[19:]
raw=AESGCM(key).decrypt(nonce,ct,b"ai-browser-source-v1")
dest=Path("/tmp/aibrowser-app")
dest.mkdir(parents=True,exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(raw),mode="r:gz") as tf:
    safe_extract(tf,dest)
os.chdir(dest)
sys.path.insert(0, str(dest))
runpy.run_path(str(dest/"server.py"),run_name="__main__")
