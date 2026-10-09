"""Compatibility and integrity checks for prospective cryptography upgrade.

Synthetic master key and profile contents only. Do not load any real encrypted
customer profile, Steel API key or production master key in CI.
"""
import base64
import hashlib
import hmac
import json
import os
import unittest

from cryptography import __version__ as crypto_version
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def derive(master:bytes,label:str)->bytes:
    return hmac.new(master,label.encode("utf-8"),hashlib.sha256).digest()

MASTER=b"synthetic-browser-test-only-never-a-real-secret"
APP_AAD=b"ai-browser-source-v1"
PROFILE_AAD=b"ai-browser-profile-test-only"

class CryptographyUpgradeTests(unittest.TestCase):
    def test_exact_approved_crypto_major(self):
        self.assertTrue(crypto_version.startswith("50."),crypto_version)

    def test_bootstrap_app_code_key_derivation(self):
        key=derive(MASTER,"app-code")
        self.assertEqual(len(key),32)
        self.assertNotEqual(key,derive(MASTER,"profile"))
        self.assertNotEqual(key,derive(MASTER,"mcp"))

    def test_bootstrap_payload_encryption_roundtrip(self):
        key=derive(MASTER,"app-code")
        plaintext=b"synthetic-program-payload-no-secrets"
        nonce=b"\0"*12
        sealed=AESGCM(key).encrypt(nonce,plaintext,APP_AAD)
        self.assertEqual(AESGCM(key).decrypt(nonce,sealed,APP_AAD),plaintext)

    def test_bootstrap_wrong_master_fails_authentication(self):
        plaintext=b"synthetic-program-payload-no-secrets"
        sealed=AESGCM(derive(MASTER,"app-code")).encrypt(b"\x01"*12,plaintext,APP_AAD)
        with self.assertRaises(InvalidTag):
            AESGCM(derive(b"different-synthetic-master","app-code")).decrypt(
                b"\x01"*12,sealed,APP_AAD)

    def test_bootstrap_wrong_context_fails_authentication(self):
        key=derive(MASTER,"app-code")
        sealed=AESGCM(key).encrypt(b"\x02"*12,b"test payload",APP_AAD)
        with self.assertRaises(InvalidTag):
            AESGCM(key).decrypt(b"\x02"*12,sealed,b"other-app-context")

    def test_tampered_profile_ciphertext_is_rejected(self):
        key=derive(MASTER,"profile")
        nonce=b"\x03"*12
        sealed=bytearray(AESGCM(key).encrypt(nonce,b"test browser storage",PROFILE_AAD))
        sealed[len(sealed)//2]^=1
        with self.assertRaises(InvalidTag):
            AESGCM(key).decrypt(nonce,bytes(sealed),PROFILE_AAD)

    def test_profile_json_roundtrip_without_real_cookies(self):
        fake={"cookies":[{"name":"TEST_ONLY","domain":"example.test",
                          "value":"synthetic-opaque-marker"}],
              "origins":[{"origin":"https://example.test","localStorage":[
                  {"name":"TEST_ONLY","value":"synthetic-opaque-marker"}]}]}
        src=json.dumps(fake,separators=(",",":")).encode("utf-8")
        key=derive(MASTER,"profile")
        nonce=b"\x04"*12
        sealed=AESGCM(key).encrypt(nonce,src,PROFILE_AAD)
        decoded=json.loads(AESGCM(key).decrypt(nonce,sealed,PROFILE_AAD))
        self.assertEqual(decoded,fake)

    def test_portable_token_base64_compatibility(self):
        sample=derive(MASTER,"store")
        encoded=base64.urlsafe_b64encode(sample).decode("ascii").rstrip("=")
        self.assertEqual(base64.urlsafe_b64decode(encoded+"="*((-len(encoded))%4)),sample)

    def test_large_synthetic_snapshot_roundtrip(self):
        key=derive(MASTER,"profile")
        payload=os.urandom(512*1024)
        nonce=b"\x05"*12
        encrypted=AESGCM(key).encrypt(nonce,payload,PROFILE_AAD)
        self.assertEqual(AESGCM(key).decrypt(nonce,encrypted,PROFILE_AAD),payload)

if __name__=="__main__":
    unittest.main(verbosity=2)
