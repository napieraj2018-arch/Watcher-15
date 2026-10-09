"""Integration regressions with synthetic encrypted state on ephemeral PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import os
import unittest
from uuid import UUID

from tenant_security.vault.profile_envelope import (
    EnvelopeError, ProfileEnvelope, ProfileEnvelopeCipher, TenantKeyring,
)

try:
    import psycopg
except ImportError:
    psycopg = None

A = UUID("11111111-1111-4111-8111-111111111111")
B = UUID("22222222-2222-4222-8222-222222222222")
WA = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
WB = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
PA = UUID("aaaaaaaa-0000-4000-8000-000000000001")
PB = UUID("bbbbbbbb-0000-4000-8000-000000000002")
FIXTURE = b'{"synthetic":"no-real-cookies-or-user-logins"}'


@unittest.skipUnless(psycopg and os.getenv("AI_BROWSER_TEST_PG_DSN"),
                     "Throwaway PostgreSQL fixture not provided")
class PostgreSQLVaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = os.environ["AI_BROWSER_TEST_PG_DSN"]
        cls.a = os.environ["AI_BROWSER_TEST_VAULT_A_DSN"]
        cls.b = os.environ["AI_BROWSER_TEST_VAULT_B_DSN"]
        cls.bff = os.environ["AI_BROWSER_TEST_TENANT_A_DSN"]

    def setUp(self):
        self.keys = TenantKeyring({
            A: {"a-1": os.urandom(32), "a-2": os.urandom(32)},
            B: {"b-1": os.urandom(32)},
        })
        self.cipher = ProfileEnvelopeCipher(self.keys)
        with psycopg.connect(self.admin, autocommit=True) as db:
            db.execute("DELETE FROM browser_product.profile_versions_secure")
            db.execute("UPDATE browser_product.profiles SET status='ready' "
                       "WHERE (tenant_id=%s AND profile_id=%s) "
                       "OR (tenant_id=%s AND profile_id=%s)",
                       (A, PA, B, PB))
            db.execute("UPDATE browser_product.login_tenant_bindings SET enabled=true "
                       "WHERE db_role IN ('fixture_vault_a','fixture_vault_b')")

    def seal(self, tenant=A, workspace=WA, profile=PA, kid="a-1", revision=1):
        return self.cipher.seal(tenant_id=tenant, workspace_id=workspace,
            profile_id=profile, revision=revision, key_id=kid, plaintext=FIXTURE)

    def append(self, dsn, envelope, expected_previous):
        with psycopg.connect(dsn, autocommit=True) as db:
            return db.execute(
                "SELECT status_code,stored_revision FROM "
                "browser_product.append_encrypted_profile(%s,%s,%s,%s,%s,%s)",
                (envelope.workspace_id, envelope.profile_id, expected_previous,
                 envelope.key_id, envelope.nonce, envelope.ciphertext),
            ).fetchone()

    def latest(self, dsn, tenant=A, profile=PA):
        with psycopg.connect(dsn, autocommit=True) as db:
            row = db.execute(
                "SELECT tenant_id,workspace_id,profile_id,revision,key_id,nonce,encrypted_state "
                "FROM browser_product.profile_versions_secure "
                "WHERE tenant_id=%s AND profile_id=%s ORDER BY revision DESC LIMIT 1",
                (tenant, profile),
            ).fetchone()
            if not row:
                return None
            return ProfileEnvelope(*row)

    def test_pg_successful_authentic_encrypted_roundtrip(self):
        envelope = self.seal()
        self.assertEqual(self.append(self.a, envelope, 0), ("created", 1))
        stored = self.latest(self.a)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.nonce, envelope.nonce)
        self.assertEqual(stored.ciphertext, envelope.ciphertext)
        self.assertNotEqual(stored.ciphertext, FIXTURE)
        self.assertEqual(self.cipher.open(stored,tenant_id=A,
            workspace_id=WA,profile_id=PA,revision=1), FIXTURE)

    def test_pg_tenant_b_cannot_read_or_append_for_a(self):
        envelope = self.seal()
        self.assertEqual(self.append(self.a,envelope,0), ("created",1))
        self.assertIsNone(self.latest(self.b,tenant=A,profile=PA))
        self.assertEqual(self.append(self.b,envelope,0),
                         ("profile_not_available",None))

    def test_pg_a_cannot_read_b_even_knowing_profile_uuid(self):
        envelope = self.seal(tenant=B,workspace=WB,profile=PB,kid="b-1")
        self.assertEqual(self.append(self.b,envelope,0), ("created",1))
        self.assertIsNone(self.latest(self.a,tenant=B,profile=PB))

    def test_pg_metadata_bff_cannot_read_raw_ciphertext(self):
        with psycopg.connect(self.bff, autocommit=True) as db:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                db.execute("SELECT encrypted_state FROM "
                           "browser_product.profile_versions_secure")

    def test_pg_vault_role_cannot_direct_insert_or_delete(self):
        envelope = self.seal()
        self.assertEqual(self.append(self.a,envelope,0), ("created",1))
        with psycopg.connect(self.a, autocommit=True) as db:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                db.execute("DELETE FROM browser_product.profile_versions_secure")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                db.execute("INSERT INTO browser_product.profile_versions_secure("
                           "tenant_id,workspace_id,profile_id,revision,key_id,nonce,encrypted_state)"
                           "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                           (A,WA,PA,2,envelope.key_id,envelope.nonce,envelope.ciphertext))

    def test_pg_rotation_appends_without_overwriting_prior_version(self):
        first = self.seal()
        self.assertEqual(self.append(self.a,first,0), ("created",1))
        next_env = self.cipher.reencrypt_next_revision(first,new_key_id="a-2")
        self.assertEqual(self.append(self.a,next_env,1), ("created",2))
        with psycopg.connect(self.a, autocommit=True) as db:
            rows = db.execute(
                "SELECT revision,key_id FROM browser_product.profile_versions_secure "
                "ORDER BY revision"
            ).fetchall()
        self.assertEqual(rows,[(1,"a-1"),(2,"a-2")])
        current = self.latest(self.a)
        self.assertEqual(self.cipher.open(current,tenant_id=A,
            workspace_id=WA,profile_id=PA,revision=2),FIXTURE)
        with self.assertRaises(EnvelopeError):
            self.cipher.open(current,tenant_id=A,workspace_id=WA,
                             profile_id=PA,revision=1)

    def test_pg_stale_revision_is_rejected(self):
        first = self.seal()
        self.assertEqual(self.append(self.a,first,0), ("created",1))
        other = self.seal()
        self.assertEqual(self.append(self.a,other,0), ("revision_conflict",1))
        with psycopg.connect(self.a,autocommit=True) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM "
                "browser_product.profile_versions_secure").fetchone()[0],1)

    def test_pg_nonce_collision_is_rejected(self):
        first = self.seal()
        self.assertEqual(self.append(self.a,first,0), ("created",1))
        second = self.cipher.reencrypt_next_revision(first,new_key_id="a-2")
        # Same nonce/key pairing as an earlier version must never be accepted.
        duplicate = self.seal(kid="a-1",revision=2)
        duplicate = ProfileEnvelope(
            tenant_id=duplicate.tenant_id, workspace_id=duplicate.workspace_id,
            profile_id=duplicate.profile_id,revision=duplicate.revision,
            key_id=first.key_id,nonce=first.nonce,ciphertext=duplicate.ciphertext)
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.append(self.a,duplicate,1)
        # A valid rotated version can still be appended after the rejection.
        self.assertEqual(self.append(self.a,second,1), ("created",2))

    def test_pg_disabled_vault_role_is_denied(self):
        first = self.seal(tenant=B,workspace=WB,profile=PB,kid="b-1")
        self.assertEqual(self.append(self.b,first,0), ("created",1))
        with psycopg.connect(self.admin,autocommit=True) as db:
            db.execute("UPDATE browser_product.login_tenant_bindings SET enabled=false "
                       "WHERE db_role='fixture_vault_b'")
        self.assertIsNone(self.latest(self.b,tenant=B,profile=PB))
        self.assertEqual(self.append(self.b,first,1),("unauthorized",None))

    def test_pg_paused_profile_fails_closed(self):
        envelope = self.seal()
        with psycopg.connect(self.admin,autocommit=True) as db:
            db.execute("UPDATE browser_product.profiles SET status='paused' "
                       "WHERE tenant_id=%s AND profile_id=%s", (A,PA))
        self.assertEqual(self.append(self.a,envelope,0),
                         ("profile_not_available",None))

    def test_pg_16_concurrent_writers_only_one_revision_wins(self):
        workers = 16
        gate = Barrier(workers)
        def attempt(i):
            envelope = self.seal()
            gate.wait(timeout=20)
            return self.append(self.a,envelope,0)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(attempt,range(workers)))
        self.assertEqual(results.count(("created",1)), 1)
        self.assertEqual(results.count(("revision_conflict",1)),15)
        with psycopg.connect(self.a,autocommit=True) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM "
                "browser_product.profile_versions_secure").fetchone()[0],1)
        latest = self.latest(self.a)
        self.assertEqual(self.cipher.open(latest,tenant_id=A,workspace_id=WA,
            profile_id=PA,revision=1), FIXTURE)


if __name__ == "__main__":
    unittest.main()
