"""Integration test against throwaway PostgreSQL 16 only, NEVER customer DB."""
import hashlib
import os
import unittest
from uuid import UUID

from tenant_security.bff.gate import COOKIE_NAME, TenantBFF, exercise_wsgi
from tenant_security.bff.postgres import PgSessionResolver, ServerTenantConnections

try:
    import psycopg
except ImportError:
    psycopg = None

A = UUID('11111111-1111-4111-8111-111111111111')
B = UUID('22222222-2222-4222-8222-222222222222')
UA = UUID('aaaaaaaa-0000-4000-8000-000000001111')
UB = UUID('bbbbbbbb-0000-4000-8000-000000002222')
WA = UUID('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
WB = UUID('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')
PA = UUID('aaaaaaaa-0000-4000-8000-000000000001')
PB = UUID('bbbbbbbb-0000-4000-8000-000000000002')
ORIGIN = 'https://browser.example.test'
TOKEN_A = 'C' * 48
TOKEN_B = 'D' * 48
CSRF = 'R' * 48


@unittest.skipUnless(psycopg and os.environ.get('AI_BROWSER_TEST_PG_DSN'),
                     'isolated PostgreSQL 16 fixture absent')
class PostgreSQLTenantBFFTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin_dsn = os.environ['AI_BROWSER_TEST_PG_DSN']
        cls.auth_dsn = os.environ['AI_BROWSER_TEST_BFF_AUTH_DSN']
        cls.a_dsn = os.environ['AI_BROWSER_TEST_TENANT_A_DSN']
        cls.b_dsn = os.environ['AI_BROWSER_TEST_TENANT_B_DSN']
        with psycopg.connect(cls.admin_dsn, autocommit=True) as cx:
            cx.execute('CREATE ROLE fixture_bff_auth LOGIN IN ROLE browser_bff_auth')
            cx.execute("UPDATE browser_product.login_tenant_bindings SET enabled=true WHERE db_role='fixture_tenant_b'")
            for tenant, user, role, token in [
                (A, UA, 'operator', TOKEN_A), (B, UB, 'viewer', TOKEN_B)
            ]:
                cx.execute('INSERT INTO browser_auth.memberships(principal_id,tenant_id,access_role) '
                           'VALUES(%s,%s,%s)', (user, tenant, role))
                cx.execute('INSERT INTO browser_auth.sessions('
                           'session_digest,principal_id,tenant_id,csrf_digest,expires_at) '
                           "VALUES(%s,%s,%s,%s,now()+interval '1 hour')",
                           (hashlib.sha256(token.encode()).hexdigest(), user, tenant,
                            hashlib.sha256(CSRF.encode()).hexdigest()))
        cls.app = TenantBFF(
            PgSessionResolver(cls.auth_dsn),
            ServerTenantConnections({A: cls.a_dsn, B: cls.b_dsn}), allowed_origin=ORIGIN,
        )

    def req(self, tenant='a', workspace=None, method='GET', resource='profiles', body=None, **kwargs):
        cookie = f'{COOKIE_NAME}={TOKEN_A if tenant == "a" else TOKEN_B}'
        work = workspace or (WA if tenant == 'a' else WB)
        return exercise_wsgi(self.app, method=method,
            path=f'/api/workspaces/{work}/{resource}', cookie=cookie, body=body, **kwargs)

    def test_real_rls_a_cannot_see_b_even_with_tenant_header(self):
        code, doc, _ = self.req(extra_headers={'HTTP_X_TENANT_ID': str(B)})
        self.assertEqual(code, 200)
        self.assertTrue(all(p['profile_id'] != str(PB) for p in doc['profiles']))
        self.assertEqual(self.req(workspace=WB)[0], 404)

    def test_real_rls_b_can_only_see_b(self):
        code, doc, _ = self.req(tenant='b')
        self.assertEqual(code, 200)
        self.assertEqual({p['profile_id'] for p in doc['profiles']}, {str(PB)})
        self.assertEqual(self.req(tenant='b', workspace=WA)[0], 404)

    def test_real_pg_state_injection_rejected_and_queued_positive(self):
        response = self.req(method='POST', resource='tasks', origin=ORIGIN, csrf=CSRF,
                            body={'profile_id': str(PA), 'state': 'done'})
        self.assertEqual(response[0], 400)
        code, doc, _ = self.req(method='POST', resource='tasks', origin=ORIGIN, csrf=CSRF,
                                body={'profile_id': str(PA)})
        self.assertEqual(code, 202)
        self.assertEqual(doc['state'], 'queued')
        with psycopg.connect(self.a_dsn, autocommit=True) as cx:
            row = cx.execute('SELECT state FROM browser_product.browser_tasks WHERE task_id=%s',
                             (doc['task_id'],)).fetchone()
            self.assertEqual(row, ('queued',))

    def test_real_pg_cross_tenant_profile_never_enqueues(self):
        code, doc, _ = self.req(method='POST', resource='tasks', origin=ORIGIN, csrf=CSRF,
                                body={'profile_id': str(PB)})
        self.assertEqual((code, doc), (404, {'error': 'not_found'}))

    def test_real_pg_viewer_cannot_enqueue(self):
        self.assertEqual(self.req(tenant='b', method='POST', resource='tasks',
            origin=ORIGIN, csrf=CSRF, body={'profile_id': str(PB)})[0], 403)

    def test_misconfigured_dsn_for_a_bound_to_b_denied(self):
        bad = TenantBFF(PgSessionResolver(self.auth_dsn),
            ServerTenantConnections({A: self.b_dsn}), allowed_origin=ORIGIN)
        code, doc, _ = exercise_wsgi(bad, path=f'/api/workspaces/{WA}/profiles',
            cookie=f'{COOKIE_NAME}={TOKEN_A}')
        self.assertEqual((code, doc), (503, {'error': 'tenant_binding_unavailable'}))

    def test_auth_role_not_allowed_to_read_raw_sessions(self):
        with psycopg.connect(self.auth_dsn, autocommit=True) as cx:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                cx.execute('SELECT * FROM browser_auth.sessions LIMIT 1')
            self.assertIsNone(cx.execute("SELECT * FROM browser_auth.resolve_session(%s)",
                ('e' * 64,)).fetchone())

    def test_revocation_and_disabled_membership_are_enforced(self):
        digest = hashlib.sha256(TOKEN_A.encode()).hexdigest()
        try:
            with psycopg.connect(self.admin_dsn, autocommit=True) as cx:
                cx.execute('UPDATE browser_auth.sessions SET revoked_at=now() WHERE session_digest=%s', (digest,))
            self.assertEqual(self.req()[0], 401)
        finally:
            with psycopg.connect(self.admin_dsn, autocommit=True) as cx:
                cx.execute('UPDATE browser_auth.sessions SET revoked_at=NULL WHERE session_digest=%s', (digest,))
        try:
            with psycopg.connect(self.admin_dsn, autocommit=True) as cx:
                cx.execute('UPDATE browser_auth.memberships SET enabled=false WHERE principal_id=%s', (UA,))
            self.assertEqual(self.req()[0], 401)
        finally:
            with psycopg.connect(self.admin_dsn, autocommit=True) as cx:
                cx.execute('UPDATE browser_auth.memberships SET enabled=true WHERE principal_id=%s', (UA,))


if __name__ == '__main__':
    unittest.main()
