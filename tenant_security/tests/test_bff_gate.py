"""No browser, accounts or network. Only synthetic tenant IDs."""
import hashlib
import unittest
from dataclasses import replace
from io import BytesIO
from json import dumps
from uuid import UUID

from tenant_security.bff.gate import Principal, TenantBFF, exercise_wsgi, COOKIE_NAME

A = UUID('11111111-1111-4111-8111-111111111111')
B = UUID('22222222-2222-4222-8222-222222222222')
USER = UUID('aaaaaaaa-2222-4222-8222-aaaaaaaaaaaa')
WA = UUID('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
WB = UUID('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')
PA = UUID('aaaaaaaa-0000-4000-8000-000000000001')
PB = UUID('bbbbbbbb-0000-4000-8000-000000000002')
SESSION_A = 'A' * 48
SESSION_B = 'B' * 48
CSRF = 'X' * 40
IDEMPOTENCY = 'K' * 40
ORIGIN = 'https://browser.example.test'
COOKIE_A = f'{COOKIE_NAME}={SESSION_A}'
COOKIE_B = f'{COOKIE_NAME}={SESSION_B}'


class FakeRepository:
    data = {A: {WA: [(PA, 'TEST-A')]}, B: {WB: [(PB, 'TEST-B')]}}
    def __init__(self, tenant, *, bound=None, fail_commit=False, raise_on_read=False,
                 forced_code=None, shared_tasks=None):
        self.tenant = tenant
        self.bound = tenant if bound is None else bound
        self.fail_commit = fail_commit
        self.raise_on_read = raise_on_read
        self.tasks = []
        self.forced_code = forced_code
        self.shared_tasks = shared_tasks if shared_tasks is not None else {}

    def __enter__(self): return self
    def __exit__(self, *_):
        if self.fail_commit:
            raise RuntimeError('SYNTHETIC commit failed: should never be disclosed')

    def authenticated_tenant(self): return self.bound
    def workspace_exists(self, tenant, workspace):
        return tenant == self.tenant and workspace in self.data.get(self.tenant, {})
    def list_profiles(self, tenant, workspace):
        if self.raise_on_read: raise RuntimeError('SYNTHETIC SQL error 12345')
        return [dict(profile_id=str(p), name=n, status='ready')
                for p, n in self.data[tenant][workspace]]
    def enqueue(self, tenant, workspace, profile, task):
        if profile not in dict(self.data.get(tenant, {}).get(workspace, [])).keys():
            return ("profile_not_available", None)
        if self.forced_code:
            return (self.forced_code, "queued" if self.forced_code == "existing" else None)
        bound = (tenant, workspace, profile)
        if task in self.shared_tasks:
            if self.shared_tasks[task] != bound:
                return ("idempotency_conflict", None)
            return ("existing", "queued")
        self.shared_tasks[task] = bound
        self.tasks.append((tenant, workspace, profile, task))
        return ("created", "queued")


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.active = {SESSION_A: Principal(A, USER, 'operator', hashlib.sha256(CSRF.encode()).hexdigest()),
                       SESSION_B: Principal(B, USER, 'viewer', hashlib.sha256(CSRF.encode()).hexdigest())}
        self.repositories = []
        self.force_bound = None
        self.fail_commit = False
        self.fail_read = False
        self.auth_unavailable = False
        self.forced_code = None
        self.saved_tasks = {}
        def resolver(digest):
            if self.auth_unavailable: raise RuntimeError('secret-backed DB unavailable')
            for token, principal in self.active.items():
                if hashlib.sha256(token.encode()).hexdigest() == digest:
                    return principal
            return None
        def repository_factory(tenant):
            repo = FakeRepository(tenant, bound=self.force_bound,
                                  fail_commit=self.fail_commit, raise_on_read=self.fail_read,
                                  forced_code=self.forced_code, shared_tasks=self.saved_tasks)
            self.repositories.append(repo)
            return repo
        self.bff = TenantBFF(resolver, repository_factory, allowed_origin=ORIGIN)

    def request(self, method='GET', workspace=WA, resource='profiles', cookie=COOKIE_A, **kwargs):
        extra = kwargs.pop('extra_headers', {}) or {}
        if method == 'POST':
            extra = {'HTTP_IDEMPOTENCY_KEY': IDEMPOTENCY, **extra}
        return exercise_wsgi(self.bff, method=method,
            path=f'/api/workspaces/{workspace}/{resource}', cookie=cookie,
            extra_headers=extra, **kwargs)

    def test_a_only_reads_a_profile(self):
        code, doc, headers = self.request()
        self.assertEqual(code, 200)
        self.assertEqual([p['name'] for p in doc['profiles']], ['TEST-A'])
        self.assertNotIn('TEST-B', str(doc))
        self.assertNotIn('provider_profile_ref', str(doc))
        self.assertEqual(headers['Cache-Control'], 'no-store, private')

    def test_b_only_reads_b_profile(self):
        code, doc, _ = self.request(cookie=COOKIE_B, workspace=WB)
        self.assertEqual(code, 200)
        self.assertEqual(doc['profiles'][0]['name'], 'TEST-B')

    def test_header_tenant_spoof_is_ignored(self):
        code, doc, _ = self.request(extra_headers={'HTTP_X_TENANT_ID': str(B)})
        self.assertEqual(code, 200)
        self.assertEqual(doc['profiles'][0]['name'], 'TEST-A')

    def test_cross_tenant_workspace_is_404(self):
        code, doc, _ = self.request(workspace=WB)
        self.assertEqual((code, doc), (404, {'error': 'not_found'}))

    def test_missing_or_duplicate_or_malformed_cookie_rejected(self):
        cookies = [None, '', COOKIE_A + '; ' + COOKIE_A,
                   COOKIE_A.replace('A', '%41'), f'{COOKIE_NAME}=bad',
                   'irrelevant=abc']
        for cookie in cookies:
            with self.subTest(cookie=cookie):
                self.assertEqual(self.request(cookie=cookie)[0], 401)

    def test_revoked_unknown_token_denied(self):
        self.active.pop(SESSION_A)
        self.assertEqual(self.request()[0], 401)

    def test_session_store_failure_is_nonleaking(self):
        self.auth_unavailable = True
        code, doc, _ = self.request()
        self.assertEqual((code, doc), (503, {'error': 'auth_unavailable'}))

    def test_http_rejected_even_with_valid_session(self):
        self.assertEqual(self.request(scheme='http')[0], 403)

    def test_db_role_misrouting_rejected(self):
        self.force_bound = B
        code, doc, _ = self.request()
        self.assertEqual((code, doc), (503, {'error': 'tenant_binding_unavailable'}))

    def test_unknown_user_role_rejected(self):
        self.active[SESSION_A] = replace(self.active[SESSION_A], access_role='owner-god')
        self.assertEqual(self.request()[0], 403)

    def test_post_valid_queue_does_not_accept_client_selected_state(self):
        code, doc, headers = self.request(method='POST', resource='tasks',
                            origin=ORIGIN, csrf=CSRF, body={'profile_id': str(PA)})
        self.assertEqual(code, 202)
        self.assertEqual(doc['state'], 'queued')
        self.assertEqual(len(self.repositories[-1].tasks), 1)
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')

    def test_viewer_cannot_mutate_even_with_valid_csrf(self):
        self.assertEqual(self.request(method='POST', resource='tasks',
            cookie=COOKIE_B, workspace=WB, origin=ORIGIN, csrf=CSRF,
            body={'profile_id': str(PB)})[0], 403)

    def test_post_wrong_or_missing_origin_or_csrf_rejected(self):
        for origin, csrf in [(None, CSRF), ('https://evil.test', CSRF),
                             (ORIGIN, None), (ORIGIN, 'Y' * 40)]:
            with self.subTest(origin=origin, csrf=csrf):
                code, _, _ = self.request(method='POST', resource='tasks',
                    origin=origin, csrf=csrf, body={'profile_id': str(PA)})
                self.assertEqual(code, 403)
                self.assertEqual(self.repositories, [])

    def test_forged_client_ids_or_task_state_are_rejected(self):
        for bad in [
            {'profile_id': str(PA), 'tenant_id': str(B)},
            {'profile_id': str(PA), 'state': 'done'},
            {'profile_id': str(PA), 'workspace_id': str(WB)},
            {'profile_id': str(PA), 'task_id': str(PB)},
        ]:
            with self.subTest(fields=list(bad)):
                code, _, _ = self.request(method='POST', resource='tasks',
                    origin=ORIGIN, csrf=CSRF, body=bad)
                self.assertEqual(code, 400)
                self.assertEqual(self.repositories, [])

    def test_post_cross_tenant_profile_never_queues(self):
        code, doc, _ = self.request(method='POST', resource='tasks',
            origin=ORIGIN, csrf=CSRF, body={'profile_id': str(PB)})
        self.assertEqual((code, doc), (404, {'error': 'not_found'}))
        self.assertEqual(self.repositories[-1].tasks, [])

    def test_post_wrong_content_type(self):
        self.assertEqual(self.request(method='POST', resource='tasks',
            origin=ORIGIN, csrf=CSRF, body={'profile_id': str(PA)},
            content_type='text/plain')[0], 415)

    def test_db_read_exception_no_leak(self):
        self.fail_read = True
        code, doc, _ = self.request()
        self.assertEqual((code, doc), (503, {'error': 'backend_unavailable'}))
        self.assertNotIn('SYNTHETIC', str(doc))

    def test_commit_failure_never_returns_202(self):
        self.fail_commit = True
        code, doc, _ = self.request(method='POST', resource='tasks',
            origin=ORIGIN, csrf=CSRF, body={'profile_id': str(PA)})
        self.assertEqual((code, doc), (503, {'error': 'backend_unavailable'}))

    def test_invalid_uuid_and_unknown_route(self):
        self.assertEqual(exercise_wsgi(self.bff, path='/api/workspaces/notuuid/profiles')[0], 404)
        self.assertEqual(exercise_wsgi(self.bff, path='/api/workspaces/'+str(WA)+'/delete')[0], 404)

    def test_no_client_role_fallback_when_data_binding_missing(self):
        self.force_bound = None
        self.assertEqual(self.request()[0], 200)
        self.force_bound = B
        self.assertEqual(self.request()[0], 503)

    def test_cookie_or_body_never_returned_in_errors(self):
        code, doc, _ = self.request(cookie=COOKIE_A + '; ' + COOKIE_A)
        self.assertEqual(code, 401)
        self.assertNotIn(SESSION_A, str(doc))

    def test_post_reads_only_declared_wsgi_body_length(self):
        data = dumps({'profile_id': str(PA)}).encode('utf-8')
        class ExactLengthStream(BytesIO):
            def read(self, size=-1):
                if size != len(data):
                    raise AssertionError('WSGI reader requested more than Content-Length')
                return super().read(size)
        env = {'wsgi.url_scheme': 'https', 'REQUEST_METHOD': 'POST',
               'PATH_INFO': f'/api/workspaces/{WA}/tasks',
               'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(data)),
               'wsgi.input': ExactLengthStream(data), 'HTTP_COOKIE': COOKIE_A,
               'HTTP_ORIGIN': ORIGIN, 'HTTP_X_AIB_CSRF': CSRF,
               'HTTP_IDEMPOTENCY_KEY': IDEMPOTENCY}
        got = {}
        def start_response(status, headers):
            got['code'] = int(status[:3])
        list(self.bff(env, start_response))
        self.assertEqual(got['code'], 202)

    def test_post_with_truncated_body_rejected(self):
        code, doc, _ = self.request(method='POST', resource='tasks',
            origin=ORIGIN, csrf=CSRF, body=b'{"profile_id":"bad')
        self.assertEqual(code, 400)



    def test_quota_limit_returns_429_and_not_success(self):
        self.forced_code = "quota_reached"
        code, doc, _ = self.request(method="POST", resource="tasks", origin=ORIGIN,
            csrf=CSRF, body={"profile_id": str(PA)})
        self.assertEqual((code, doc), (429, {"error": "tenant_queue_full"}))
        self.assertEqual(self.repositories[-1].tasks, [])

    def test_existing_idempotency_state_returned_only_from_database(self):
        self.forced_code = "existing"
        code, doc, _ = self.request(method="POST", resource="tasks", origin=ORIGIN,
            csrf=CSRF, body={"profile_id": str(PA)})
        self.assertEqual(code, 200)
        self.assertEqual(doc["state"], "queued")

    def test_queue_failure_is_fail_closed_not_202(self):
        for status in ("unavailable", "unknown_state"):
            with self.subTest(status=status):
                self.forced_code = status
                code, doc, _ = self.request(method="POST", resource="tasks",
                    origin=ORIGIN, csrf=CSRF, body={"profile_id": str(PA)})
                self.assertEqual((code, doc), (503, {"error": "queue_unavailable"}))

    def test_queue_stale_or_unauthorized_rejected(self):
        for status, expected in (("unauthorized", 403),
                                 ("idempotency_conflict", 409)):
            with self.subTest(status=status):
                self.forced_code = status
                code, doc, _ = self.request(method="POST", resource="tasks",
                    origin=ORIGIN, csrf=CSRF, body={"profile_id": str(PA)})
                self.assertEqual(code, expected)


    def test_retry_same_key_is_idempotent(self):
        first, data_first, _ = self.request(method="POST", resource="tasks",
            origin=ORIGIN, csrf=CSRF, body={"profile_id": str(PA)})
        second, data_second, _ = self.request(method="POST", resource="tasks",
            origin=ORIGIN, csrf=CSRF, body={"profile_id": str(PA)})
        self.assertEqual((first, second), (202, 200))
        self.assertEqual(data_first["task_id"], data_second["task_id"])
        self.assertEqual(len(self.saved_tasks), 1)

    def test_different_retry_keys_create_distinct_tasks(self):
        first, data_first, _ = self.request(method="POST", resource="tasks",
            origin=ORIGIN, csrf=CSRF, body={"profile_id": str(PA)})
        second, data_second, _ = self.request(method="POST", resource="tasks",
            origin=ORIGIN, csrf=CSRF, body={"profile_id": str(PA)},
            extra_headers={"HTTP_IDEMPOTENCY_KEY": "P" * 40})
        self.assertEqual((first, second), (202, 202))
        self.assertNotEqual(data_first["task_id"], data_second["task_id"])
        self.assertEqual(len(self.saved_tasks), 2)

    def test_retry_key_is_scoped_to_authenticated_user(self):
        first, first_data, _ = self.request(method="POST", resource="tasks",
            origin=ORIGIN, csrf=CSRF, body={"profile_id": str(PA)})
        other_user = UUID("abababab-0000-4000-8000-abababababab")
        self.active[SESSION_B] = Principal(A, other_user, "operator",
            hashlib.sha256(CSRF.encode()).hexdigest())
        second, second_data, _ = self.request(method="POST", resource="tasks",
            cookie=COOKIE_B, origin=ORIGIN, csrf=CSRF,
            body={"profile_id": str(PA)})
        self.assertEqual((first, second), (202, 202))
        self.assertNotEqual(first_data["task_id"], second_data["task_id"])

    def test_missing_and_invalid_idempotency_keys_rejected(self):
        for key in (None, "short", "has spaces included", "x" * 97, "bad,key"):
            with self.subTest(key=key):
                code, data, _ = exercise_wsgi(
                    self.bff, method="POST",
                    path=f"/api/workspaces/{WA}/tasks", cookie=COOKIE_A,
                    origin=ORIGIN, csrf=CSRF, body={"profile_id": str(PA)},
                    extra_headers=({"HTTP_IDEMPOTENCY_KEY": key} if key else {}),
                )
                self.assertEqual((code, data),
                    (400, {"error": "invalid_idempotency_key"}))

    def test_duplicate_json_property_fails_closed(self):
        body = ('{"profile_id":"' + str(PA) + '","profile_id":"' + str(PA) + '"}').encode()
        code, data, _ = self.request(method="POST", resource="tasks",
            origin=ORIGIN, csrf=CSRF, body=body)
        self.assertEqual((code, data), (400, {"error": "invalid_json"}))
        self.assertEqual(self.repositories, [])

    def test_nonfinite_json_values_are_rejected(self):
        for raw in (b'{"profile_id":NaN}', b'{"profile_id":Infinity}'):
            with self.subTest(raw=raw):
                code, data, _ = self.request(method="POST", resource="tasks",
                    origin=ORIGIN, csrf=CSRF, body=raw)
                self.assertEqual((code, data), (400, {"error": "invalid_json"}))


if __name__ == '__main__':
    unittest.main()
