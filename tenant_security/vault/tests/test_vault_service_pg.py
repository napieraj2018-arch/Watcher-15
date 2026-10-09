"""Full server vault adapter → AES-GCM → ephemeral PostgreSQL integration."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import os
import unittest
from uuid import UUID

from tenant_security.vault.profile_envelope import ProfileEnvelopeCipher, TenantKeyring
from tenant_security.vault.service import (
    ProfileVaultService, ServerVaultConnections, VaultOperationError
)

try:
    import psycopg
except ImportError:
    psycopg = None

A=UUID("11111111-1111-4111-8111-111111111111")
B=UUID("22222222-2222-4222-8222-222222222222")
WA=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
WB=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
PA=UUID("aaaaaaaa-0000-4000-8000-000000000001")
PB=UUID("bbbbbbbb-0000-4000-8000-000000000002")
FAKE=b'{"synthetic":"profile-state-fixture-only"}'


@unittest.skipUnless(psycopg and os.getenv("AI_BROWSER_TEST_PG_DSN"),
                     "Throwaway PostgreSQL fixture absent")
class VaultServicePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = os.environ["AI_BROWSER_TEST_PG_DSN"]
        cls.a = os.environ["AI_BROWSER_TEST_VAULT_A_DSN"]
        cls.b = os.environ["AI_BROWSER_TEST_VAULT_B_DSN"]

    def setUp(self):
        self.cipher=ProfileEnvelopeCipher(TenantKeyring({
            A:{"a1":os.urandom(32),"a2":os.urandom(32)},
            B:{"b1":os.urandom(32)},
        }))
        self.conn=ServerVaultConnections({A:self.a,B:self.b})
        self.vault=ProfileVaultService(self.conn,self.cipher)
        with psycopg.connect(self.admin,autocommit=True) as db:
            db.execute("DELETE FROM browser_product.profile_versions_secure")
            db.execute("UPDATE browser_product.profiles SET status='ready' "
                "WHERE (tenant_id=%s AND profile_id=%s) OR (tenant_id=%s AND profile_id=%s)",
                (A,PA,B,PB))
            db.execute("UPDATE browser_product.login_tenant_bindings SET enabled=true "
                "WHERE db_role IN ('fixture_vault_a','fixture_vault_b')")

    def save(self,tenant=A,workspace=WA,profile=PA,revision=0,key_id="a1",
             content=FAKE,service=None):
        return (service or self.vault).save(tenant=tenant,workspace=workspace,
            profile=profile,expected_previous=revision,key_id=key_id,plaintext=content)

    def load(self,tenant=A,workspace=WA,profile=PA,service=None):
        return (service or self.vault).load(tenant=tenant,workspace=workspace,profile=profile)

    def test_real_save_load_roundtrip(self):
        self.assertEqual(self.save(),1)
        restored=self.load()
        self.assertEqual(restored.revision,1)
        self.assertEqual(restored.plaintext,FAKE)
        self.assertEqual(repr(restored),"<VaultState redacted>")

    def test_real_database_never_persists_plaintext(self):
        self.save()
        with psycopg.connect(self.a,autocommit=True) as db:
            row=db.execute("SELECT encrypted_state FROM browser_product.profile_versions_secure").fetchone()
        self.assertNotEqual(row[0],FAKE)
        self.assertNotIn(FAKE,bytes(row[0]))

    def test_wrong_tenant_db_login_fails_before_append(self):
        wrong=ProfileVaultService(ServerVaultConnections({A:self.b}),self.cipher)
        with self.assertRaisesRegex(VaultOperationError,"tenant_binding_unavailable"):
            self.save(service=wrong)
        with psycopg.connect(self.admin,autocommit=True) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM browser_product.profile_versions_secure").fetchone()[0],0)

    def test_metadata_db_login_reused_as_vault_login_fails(self):
        wrong=ProfileVaultService(
            ServerVaultConnections({A:os.environ["AI_BROWSER_TEST_TENANT_A_DSN"]}),
            self.cipher)
        with self.assertRaises(VaultOperationError):
            self.save(service=wrong)

    def test_wrong_revision_cannot_overwrite_existing_blob(self):
        self.save()
        with self.assertRaisesRegex(VaultOperationError,"revision_conflict"):
            self.save()
        with psycopg.connect(self.a,autocommit=True) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM browser_product.profile_versions_secure").fetchone()[0],1)

    def test_cross_tenant_load_is_not_found(self):
        self.save()
        self.assertIsNone(self.load(tenant=B,workspace=WB,profile=PB))
        self.assertIsNone(self.load(tenant=B,workspace=WA,profile=PA))

    def test_disabled_worker_cannot_use_old_session(self):
        self.save()
        with psycopg.connect(self.admin,autocommit=True) as db:
            db.execute("UPDATE browser_product.login_tenant_bindings SET enabled=false "
                "WHERE db_role='fixture_vault_a'")
        with self.assertRaises(VaultOperationError):
            self.save(revision=1)
        with self.assertRaisesRegex(VaultOperationError,"vault_read_unavailable"):
            self.load()

    def test_tampered_stored_ciphertext_never_returns_bytes(self):
        self.save()
        with psycopg.connect(self.admin,autocommit=True) as db:
            db.execute(
                "UPDATE browser_product.profile_versions_secure "
                "SET encrypted_state = set_byte(encrypted_state,0, "
                "get_byte(encrypted_state,0) # 1) WHERE tenant_id=%s", (A,))
        with self.assertRaisesRegex(VaultOperationError,"vault_read_unavailable") as cm:
            self.load()
        self.assertNotIn(FAKE.decode(),str(cm.exception))

    def test_rotation_next_immutable_revision_roundtrip(self):
        self.assertEqual(self.save(),1)
        current=self.load()
        self.assertEqual(self.save(revision=current.revision,key_id="a2",
                                   content=current.plaintext),2)
        newest=self.load()
        self.assertEqual((newest.revision,newest.plaintext),(2,FAKE))
        with psycopg.connect(self.a,autocommit=True) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM browser_product.profile_versions_secure").fetchone()[0],2)

    def test_16_parallel_service_saves_never_double_commit(self):
        barrier=Barrier(16)
        def worker(index):
            barrier.wait(timeout=25)
            try:
                rev=self.save()
                return ("created",rev)
            except VaultOperationError as e:
                return ("rejected",str(e))
        with ThreadPoolExecutor(max_workers=16) as pool:
            outputs=list(pool.map(worker,range(16)))
        self.assertEqual(outputs.count(("created",1)),1)
        self.assertEqual(outputs.count(("rejected","revision_conflict")),15)
        self.assertEqual(self.load().plaintext,FAKE)


if __name__=="__main__":
    unittest.main()
