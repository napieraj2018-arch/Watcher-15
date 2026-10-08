from pathlib import Path
import ast, base64, hashlib, hmac, io, os, runpy, sys, tarfile, urllib.request
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PAYLOAD_URL = "https://ai-browser-vault.floot.app/_cdn/static/7cc26794-4051-41b8-862f-792995b14e58-ai-browser-core-v041.aib"
REPAIR_URL = "https://ai-browser-vault.floot.app/_cdn/static/0f27c7da-53b5-4247-a0b6-5585adbc9926-ai-browser-repair-v042.aib"
REPAIR_SHA256 = "3460cac9927fa8911659a73f5766524243f952f76adf446f287434becb550764"


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def derive(master: bytes, label: str) -> bytes:
    return hmac.new(master, label.encode(), hashlib.sha256).digest()


def safe_extract(tf: tarfile.TarFile, dest: Path):
    dest = dest.resolve()
    for m in tf.getmembers():
        target = (dest / m.name).resolve()
        if dest not in target.parents and target != dest:
            raise RuntimeError("unsafe payload path")
    tf.extractall(dest)


def load_mobile_repair(dest: Path) -> None:
    """Load a separately encrypted additive repair, without changing profile keys.
    Existing master/application/profile keys are never exported or logged.
    """
    repair_key_text = os.environ.get("AI_BROWSER_REPAIR_KEY", "").strip()
    if not repair_key_text:
        raise RuntimeError("AI_BROWSER_REPAIR_KEY missing")
    repair_key = base64.urlsafe_b64decode(repair_key_text)
    if len(repair_key) != 32:
        raise RuntimeError("invalid repair deployment key")
    request = urllib.request.Request(REPAIR_URL, headers={"User-Agent": "AI-Browser-Repair/0.4.2"})
    with urllib.request.urlopen(request, timeout=30) as response:
        sealed = response.read(2_000_001)
    if len(sealed) > 2_000_000 or hashlib.sha256(sealed).hexdigest() != REPAIR_SHA256:
        raise RuntimeError("repair archive integrity check failed")
    if not sealed.startswith(b"AIBRPR1"):
        raise RuntimeError("invalid repair archive")
    plain = AESGCM(repair_key).decrypt(sealed[7:19], sealed[19:], b"ai-browser-repair-v042")
    repair_dir = dest / "mobile-repair-042"
    repair_dir.mkdir(parents=True, exist_ok=True)
    allowed = {"repair_v042.py", "mobile_v042.html"}
    with tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz") as tf:
        members = tf.getmembers()
        if {m.name for m in members} != allowed or len(members) != 2:
            raise RuntimeError("unexpected repair archive members")
        for member in members:
            if not member.isfile() or member.size > 1_000_000:
                raise RuntimeError("invalid repair archive member")
            source = tf.extractfile(member)
            if source is None:
                raise RuntimeError("missing repair archive member")
            (repair_dir / member.name).write_bytes(source.read())
    sys.path.insert(0, str(repair_dir))
    source_path = dest / "server.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    guard = next((i for i, node in enumerate(tree.body)
                  if isinstance(node, ast.If)
                  and isinstance(node.test, ast.Compare)
                  and isinstance(node.test.left, ast.Name)
                  and node.test.left.id == "__name__"
                  and len(node.test.ops) == 1 and isinstance(node.test.ops[0], ast.Eq)
                  and len(node.test.comparators) == 1
                  and isinstance(node.test.comparators[0], ast.Constant)
                  and node.test.comparators[0].value == "__main__"), None)
    if guard is None:
        raise RuntimeError("AI_BROWSER_REPAIR_INCOMPATIBLE_BOOT")
    hooks = ast.parse("from repair_v042 import install as _install_mobile_repair\n_install_mobile_repair(globals())\nfrom steel_runtime import install as _install_steel_runtime\n_install_steel_runtime(globals())\nfrom steel_context_fix import install as _install_context_fix\n_install_context_fix(globals())\nfrom auth_status_v052 import install as _install_auth_status\n_install_auth_status(globals())\n").body
    tree.body[guard:guard] = hooks
    ast.fix_missing_locations(tree)
    namespace = {"__name__": "__main__", "__file__": str(source_path),
                 "__package__": None, "__spec__": None, "__cached__": None}
    exec(compile(tree, str(source_path), "exec"), namespace)


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
req = urllib.request.Request(PAYLOAD_URL, headers={"User-Agent": "AI-Browser-Bootstrap/0.4.1"})
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
if os.environ.get("AI_BROWSER_REPAIR_ENABLED", "0") == "1":
    load_mobile_repair(dest)
else:
    runpy.run_path(str(dest / "server.py"), run_name="__main__")
