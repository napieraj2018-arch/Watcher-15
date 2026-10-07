from pathlib import Path
import base64, io, os, runpy, tarfile
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def safe_extract(tf: tarfile.TarFile, dest: Path):
    dest=dest.resolve()
    for m in tf.getmembers():
        target=(dest/m.name).resolve()
        if dest not in target.parents and target != dest:
            raise RuntimeError('unsafe payload path')
    tf.extractall(dest)

key_b64=os.environ.get('APP_CODE_KEY','')
if not key_b64: raise RuntimeError('APP_CODE_KEY missing')
key=base64.urlsafe_b64decode(key_b64.encode())
parts=sorted(Path('/app').glob('payload.part*'))
if not parts: raise RuntimeError('payload parts missing')
payload=base64.b64decode(''.join(x.read_text().strip() for x in parts))
if not payload.startswith(b'AIBSRC1'): raise RuntimeError('bad payload')
nonce,ct=payload[7:19],payload[19:]
raw=AESGCM(key).decrypt(nonce,ct,b'ai-browser-source-v1')
dest=Path('/tmp/aibrowser-app'); dest.mkdir(parents=True,exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as tf: safe_extract(tf,dest)
os.chdir(dest)
os.environ.setdefault('AI_BROWSER_HOME','/tmp/ai-browser')
os.environ.setdefault('AI_BROWSER_PORTABLE_PROFILES','1')
os.environ.setdefault('AI_BROWSER_MAX_SESSIONS','1')
os.environ.setdefault('AI_BROWSER_HOST','0.0.0.0')
os.environ.setdefault('AI_BROWSER_PORT',os.environ.get('PORT','10000'))
runpy.run_path(str(dest/'server.py'),run_name='__main__')
