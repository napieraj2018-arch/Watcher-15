"""Interoperability test between old and patched cryptography AES-GCM.

Only fake app and browser-profile data. No Steel, prod keys, cookies, profiles
or network requests. The two Python virtualenvs are installed separately by CI.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import pathlib
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = pathlib.Path(__file__).resolve().parent
MAGIC=b"AIBCRYPTO-COMPAT-V1\n"
SYNTHETIC_MASTER=b"PUBLIC-TEST-VECTOR-NOT-A-PRODUCTION-KEY"
FIXTURE_COOKIE="FAKE-TEST-COOKIE-DOES-NOT-AUTHENTICATE"
VECTOR=[
  ("app-code", b"ai-browser-source-v1", b"pretend-encrypted-app-core-no-secret"),
  ("profile", b"ai-browser-profile-compatibility-test", json.dumps({
    "cookies":[{"domain":"example.invalid","name":"synthetic",
                "value":FIXTURE_COOKIE,"path":"/"}],
    "origins":[{"origin":"https://example.invalid","localStorage":[
        {"name":"synthetic","value":"TEST-ONLY-LOCAL-STORAGE"}]}]
  },separators=(",",":")).encode()),
  ("store", b"synthetic-store-token-aad", b"fake-bearer-token")
]

def derive(label:str)->bytes:
    return hmac.new(SYNTHETIC_MASTER,label.encode("ascii"),hashlib.sha256).digest()

def pack():
    blobs=[]
    for i,(label,aad,plaintext) in enumerate(VECTOR):
        nonce=bytes([i+1])*12  # Static nonce safe only with these distinct keys/fixture.
        data=AESGCM(derive(label)).encrypt(nonce,plaintext,aad)
        blobs.append({"label":label,"nonce":base64.b64encode(nonce).decode("ascii"),
                      "ciphertext":base64.b64encode(data).decode("ascii")})
    return MAGIC+json.dumps(blobs,separators=(",",":")).encode()

def validate(data:bytes)->None:
    assert data.startswith(MAGIC),"Fixture header incompatible"
    blobs=json.loads(data[len(MAGIC):])
    assert isinstance(blobs,list) and len(blobs)==len(VECTOR)
    for record,(label,aad,plaintext) in zip(blobs,VECTOR):
        assert record.get("label")==label
        nonce=base64.b64decode(record["nonce"],validate=True)
        ciphertext=base64.b64decode(record["ciphertext"],validate=True)
        assert AESGCM(derive(label)).decrypt(nonce,ciphertext,aad)==plaintext
    print("CROSS_CRYPTOGRAPHY_AESGCM_FIXTURES_PASS",flush=True)

def main(argv):
    if len(argv)!=3 or argv[1] not in {"write","read"}:
        raise SystemExit("Use: python test_crypto_interop_vector.py write|read /tmp/output")
    path=pathlib.Path(argv[2])
    if path.is_symlink() or not str(path).startswith("/tmp/"):
        raise SystemExit("Only files under /tmp allowed")
    if argv[1]=="write":
        path.write_bytes(pack())
        validate(path.read_bytes())
    else:
        validate(path.read_bytes())
    return 0

if __name__=="__main__":
    sys.exit(main(sys.argv))
