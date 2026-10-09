"""AES-GCM envelope regressions using synthetic bytes and throwaway keys."""
import os
import unittest
from dataclasses import replace
from uuid import UUID

from tenant_security.vault.profile_envelope import (
    EnvelopeError, ProfileEnvelope, ProfileEnvelopeCipher, TenantKeyring,
)

A = UUID("11111111-1111-4111-8111-111111111111")
B = UUID("22222222-2222-4222-8222-222222222222")
WA = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
WB = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
PA = UUID("aaaaaaaa-0000-4000-8000-000000000001")
PB = UUID("bbbbbbbb-0000-4000-8000-000000000002")
FIXTURE = b'{"source":"synthetic-data-only","value":"test"}'


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.key_a = os.urandom(32)
        self.key_b = os.urandom(32)
        self.key_v2 = os.urandom(32)
        self.cipher = ProfileEnvelopeCipher(TenantKeyring({
            A: {"a-v1": self.key_a, "a-v2": self.key_v2},
            B: {"b-v1": self.key_b}
        }))

    def seal(self, tenant=A, workspace=WA, profile=PA, rev=1, kid="a-v1",
             plaintext=FIXTURE):
        return self.cipher.seal(
            tenant_id=tenant, workspace_id=workspace, profile_id=profile,
            revision=rev, key_id=kid, plaintext=plaintext)

    def open(self, env, tenant=A, workspace=WA, profile=PA, rev=1):
        return self.cipher.open(env, tenant_id=tenant, workspace_id=workspace,
                                profile_id=profile, revision=rev)

    def test_valid_roundtrip(self):
        env = self.seal()
        self.assertEqual(self.open(env), FIXTURE)
        self.assertNotIn(FIXTURE, env.ciphertext)
        self.assertEqual(len(env.nonce), 12)
        self.assertEqual(len(env.ciphertext), len(FIXTURE) + 16)

    def test_same_plaintext_uses_distinct_random_nonce(self):
        first, second = self.seal(), self.seal()
        self.assertNotEqual(first.nonce, second.nonce)
        self.assertNotEqual(first.ciphertext, second.ciphertext)
        self.assertEqual(self.open(first), self.open(second))

    def test_tenant_swap_is_rejected(self):
        env = self.seal()
        with self.assertRaises(EnvelopeError):
            self.open(env, tenant=B)

    def test_workspace_swap_is_rejected(self):
        env = self.seal()
        with self.assertRaises(EnvelopeError):
            self.open(env, workspace=WB)

    def test_profile_swap_is_rejected(self):
        env = self.seal()
        with self.assertRaises(EnvelopeError):
            self.open(env, profile=PB)

    def test_revision_swap_is_rejected(self):
        env = self.seal()
        with self.assertRaises(EnvelopeError):
            self.open(env, rev=2)

    def test_tampered_payload_authentication_fails(self):
        env = self.seal()
        corrupted = env.ciphertext[:-1] + bytes([env.ciphertext[-1] ^ 1])
        with self.assertRaisesRegex(EnvelopeError, "envelope_authentication_failed"):
            self.open(replace(env, ciphertext=corrupted))

    def test_tampered_nonce_authentication_fails(self):
        env = self.seal()
        nonce = env.nonce[:-1] + bytes([env.nonce[-1] ^ 1])
        with self.assertRaises(EnvelopeError):
            self.open(replace(env, nonce=nonce))

    def test_wrong_key_fails_closed(self):
        env = self.seal()
        wrong = ProfileEnvelopeCipher(TenantKeyring({A: {"a-v1": os.urandom(32)}}))
        with self.assertRaisesRegex(EnvelopeError, "envelope_authentication_failed"):
            wrong.open(env, tenant_id=A, workspace_id=WA, profile_id=PA, revision=1)

    def test_missing_key_fails_closed(self):
        env = self.seal()
        missing = ProfileEnvelopeCipher(TenantKeyring({A: {"another-key": os.urandom(32)}}))
        with self.assertRaisesRegex(EnvelopeError, "key_unavailable"):
            missing.open(env, tenant_id=A, workspace_id=WA, profile_id=PA, revision=1)

    def test_rotation_creates_new_revision(self):
        previous = self.seal()
        rotated = self.cipher.reencrypt_next_revision(previous, new_key_id="a-v2")
        self.assertEqual(rotated.revision, 2)
        self.assertEqual(rotated.key_id, "a-v2")
        self.assertNotEqual(rotated.nonce, previous.nonce)
        self.assertNotEqual(rotated.ciphertext, previous.ciphertext)
        self.assertEqual(self.open(previous), FIXTURE)
        self.assertEqual(self.open(rotated, rev=2), FIXTURE)

    def test_new_key_can_read_rotated_after_old_key_revoked(self):
        rotated = self.cipher.reencrypt_next_revision(self.seal(), new_key_id="a-v2")
        only_new = ProfileEnvelopeCipher(TenantKeyring({A: {"a-v2": self.key_v2}}))
        self.assertEqual(only_new.open(rotated,
            tenant_id=A, workspace_id=WA, profile_id=PA, revision=2), FIXTURE)
        with self.assertRaises(EnvelopeError):
            only_new.open(self.seal(),
                tenant_id=A, workspace_id=WA, profile_id=PA, revision=1)

    def test_rotation_same_key_id_rejected(self):
        with self.assertRaisesRegex(EnvelopeError, "rotation_key_unchanged"):
            self.cipher.reencrypt_next_revision(self.seal(), new_key_id="a-v1")

    def test_invalid_key_sizes_rejected(self):
        for raw in (b"", b"k" * 16, b"k" * 33):
            with self.subTest(length=len(raw)):
                with self.assertRaises(EnvelopeError):
                    TenantKeyring({A: {"test": raw}})

    def test_invalid_key_identifiers_rejected(self):
        for label in ("", "space here", "x" * 65, "a/b"):
            with self.subTest(label=label):
                with self.assertRaises(EnvelopeError):
                    TenantKeyring({A: {label: os.urandom(32)}})

    def test_empty_plaintext_rejected(self):
        with self.assertRaises(EnvelopeError):
            self.seal(plaintext=b"")

    def test_oversize_plaintext_rejected(self):
        with self.assertRaises(EnvelopeError):
            self.seal(plaintext=b"x" * 8_000_001)

    def test_wrong_type_plaintext_rejected(self):
        with self.assertRaises(EnvelopeError):
            self.seal(plaintext="not-bytes")

    def test_invalid_revision_or_identifier_rejected(self):
        for revision in (0, -1, 2**63, True):
            with self.subTest(revision=revision):
                with self.assertRaises(EnvelopeError):
                    self.seal(rev=revision)

    def test_invalid_nonce_length_rejected(self):
        env = self.seal()
        with self.assertRaises(EnvelopeError):
            self.open(replace(env, nonce=b"0" * 11))

    def test_invalid_ciphertext_size_rejected(self):
        env = self.seal()
        with self.assertRaises(EnvelopeError):
            self.open(replace(env, ciphertext=b"short"))

    def test_no_sensitive_repr(self):
        env = self.seal()
        self.assertEqual(repr(env), "<ProfileEnvelope redacted>")
        self.assertEqual(repr(self.cipher._keyring), "<TenantKeyring redacted>")
        self.assertNotIn(FIXTURE.decode(), repr(env))
        self.assertNotIn(self.key_a.hex(), repr(self.cipher._keyring))

    def test_cross_tenant_key_cannot_decrypt_a(self):
        env = self.seal()
        wrong_tenant = replace(env, tenant_id=B, key_id="b-v1")
        with self.assertRaises(EnvelopeError):
            self.open(wrong_tenant, tenant=B)


if __name__ == "__main__":
    unittest.main()
