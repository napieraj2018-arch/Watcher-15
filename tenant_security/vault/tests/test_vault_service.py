"""Server vault service fail-closed tests; synthetic state and throwaway keys."""
import os
import unittest
from uuid import UUID

from tenant_security.vault.profile_envelope import ProfileEnvelopeCipher, TenantKeyring
from tenant_security.vault.service import (
    ProfileVaultService, ServerVaultConnections, VaultOperationError, VaultState,
)

A = UUID("11111111-1111-4111-8111-111111111111")
B = UUID("22222222-2222-4222-8222-222222222222")
WA = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PA = UUID("aaaaaaaa-0000-4000-8000-000000000001")
TEXT = b"synthetic-state-for-crypto-only"


class FakeDb:
    def __init__(self, tenant, bound=None, commit_fails=False, response=None, row=None):
        self.tenant = tenant
        self.bound = tenant if bound is None else bound
        self.commit_fails = commit_fails
        self.response = response
        self.row = row
        self.append_called = False

    def __enter__(self): return self

    def __exit__(self, kind, value, traceback):
        if self.commit_fails and kind is None:
            raise RuntimeError("SECRET_FIXTURE_SQL_COMMIT_FAILURE")

    def authenticated_tenant(self): return self.bound

    def append(self, envelope, expected):
        self.append_called = True
        return self.response if self.response else ("created", expected+1)

    def latest(self, tenant, workspace, profile):
        return self.row


class VaultServiceTests(unittest.TestCase):
    def setUp(self):
        self.cipher = ProfileEnvelopeCipher(TenantKeyring({A: {"v1": os.urandom(32)}}))
        self.db = FakeDb(A)
        self.service = ProfileVaultService(lambda tenant: self.db, self.cipher)

    def save(self, expected=0):
        return self.service.save(tenant=A,workspace=WA,profile=PA,
                                 expected_previous=expected,key_id="v1",plaintext=TEXT)

    def test_success_returns_committed_revision(self):
        self.assertEqual(self.save(),1)
        self.assertTrue(self.db.append_called)

    def test_misrouted_role_never_appends(self):
        self.db.bound = B
        with self.assertRaisesRegex(VaultOperationError, "tenant_binding_unavailable"):
            self.save()
        self.assertFalse(self.db.append_called)

    def test_commit_failure_is_never_reported_as_success(self):
        self.db.commit_fails=True
        with self.assertRaisesRegex(VaultOperationError, "vault_backend_unavailable"):
            self.save()
        self.assertTrue(self.db.append_called)

    def test_revision_conflict_is_error_not_success(self):
        self.db.response=("revision_conflict",3)
        with self.assertRaisesRegex(VaultOperationError, "revision_conflict"):
            self.save()

    def test_profile_status_or_revocation_rejected(self):
        for status in ("profile_not_available","unauthorized"):
            with self.subTest(status=status):
                self.db.response=(status,None)
                with self.assertRaises(VaultOperationError):
                    self.save()

    def test_unexpected_database_status_fails_closed(self):
        self.db.response=("unknown",None)
        with self.assertRaisesRegex(VaultOperationError, "vault_write_unavailable"):
            self.save()

    def test_success_wrong_revision_never_accepted(self):
        self.db.response=("created",500)
        with self.assertRaisesRegex(VaultOperationError, "vault_write_unavailable"):
            self.save()

    def test_invalid_expected_revision_rejected_without_insert(self):
        for previous in (-1,2**63-1,True,"0"):
            with self.subTest(previous=previous):
                with self.assertRaisesRegex(VaultOperationError, "invalid_expected_revision"):
                    self.save(previous)
        self.assertFalse(self.db.append_called)

    def test_missing_row_is_not_another_tenant_leak(self):
        self.assertIsNone(self.service.load(tenant=A,workspace=WA,profile=PA))

    def test_role_mismatch_on_load_is_rejected(self):
        self.db.bound=B
        with self.assertRaisesRegex(VaultOperationError, "vault_read_unavailable"):
            self.service.load(tenant=A,workspace=WA,profile=PA)

    def test_tampered_envelope_load_is_generic_failure(self):
        envelope = self.cipher.seal(tenant_id=A,workspace_id=WA,profile_id=PA,
            revision=1,key_id="v1",plaintext=TEXT)
        from dataclasses import replace
        self.db.row=replace(envelope,ciphertext=envelope.ciphertext[:-1] +
                            bytes([envelope.ciphertext[-1] ^ 1]))
        with self.assertRaisesRegex(VaultOperationError, "vault_read_unavailable"):
            self.service.load(tenant=A,workspace=WA,profile=PA)

    def test_vault_state_representation_is_redacted(self):
        self.assertEqual(repr(VaultState(1,TEXT)), "<VaultState redacted>")
        self.assertNotIn(TEXT.decode(),repr(self.service))
        self.assertEqual(repr(self.service),"<ProfileVaultService redacted>")

    def test_connection_map_never_discloses_dsn(self):
        mapping=ServerVaultConnections({A:"postgresql://fixture-db@localhost:5432/test"})
        self.assertEqual(repr(mapping), "<ServerVaultConnections redacted>")
        self.assertNotIn("fixture-db",repr(mapping(A)))

    def test_missing_tenant_dsn_fails_closed(self):
        mapping=ServerVaultConnections({B:"test-only-dsn"})
        with self.assertRaisesRegex(VaultOperationError,"vault_backend_unavailable"):
            mapping(A)


if __name__=="__main__":
    unittest.main()
