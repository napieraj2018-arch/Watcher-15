"""Owner handoff authorization boundaries, without real accounts or database."""
import base64
import os
import secrets
import time
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault('AIB_FRESH_DATABASE_URL', 'postgresql://fixture.invalid/db')
os.environ.setdefault('AIB_FRESH_ADMIN_TOKEN', secrets.token_urlsafe(40))
os.environ.setdefault('AIB_FRESH_MCP_TOKEN', secrets.token_urlsafe(40))
os.environ.setdefault('AIB_FRESH_DATA_KEY', base64.b64encode(secrets.token_bytes(32)).decode())
import server
from fastapi.testclient import TestClient


class OwnerAccess(unittest.TestCase):
    def setUp(self):
        self.previous = server.workspace
        server.workspace = server.BrowserWorkspace()
        server.workspace.context = object()
        server.workspace.profile = 'facebook-klinika'
        server.OWNER_GRANTS.clear()
        self.c = TestClient(server.app, base_url='https://testserver')
        self.headers = {'x-aib-request': 'same-origin', 'origin': 'https://testserver'}

    def tearDown(self):
        self.c.close()
        server.OWNER_GRANTS.clear()
        server.workspace = self.previous

    def issue(self):
        r = self.c.post('/mcp', headers={'authorization': 'Bearer ' + server.MCP_TOKEN}, json={
            'id': 1, 'method': 'tools/call', 'params': {'name': 'fresh_browser',
            'arguments': {'action': 'owner_access', 'name': 'facebook-klinika'}}})
        import json
        data = json.loads(r.json()['result']['content'][0]['text'])
        self.assertNotIn(server.ADMIN, data['url'])
        self.assertNotIn(server.MCP_TOKEN, data['url'])
        return data['url'].split('#')[1]

    def pair(self, token):
        return self.c.post('/owner/api/pair', headers=self.headers, json={'token': token})

    def test_one_use_profile_scope_and_cookie_flags(self):
        token = self.issue()
        self.assertEqual(self.c.get('/owner/api/profiles').status_code, 401)
        r = self.pair(token)
        self.assertEqual(r.status_code, 200)
        for flag in ['HttpOnly', 'Secure', 'SameSite=strict', 'Path=/owner']:
            self.assertIn(flag, r.headers['set-cookie'])
        self.assertEqual(self.pair(token).status_code, 401)
        self.assertEqual(self.c.get('/owner/api/profiles').json()['profiles'], [{'name': 'facebook-klinika'}])
        self.assertEqual(self.c.get('/api/profiles').status_code, 401)
        self.assertEqual(self.c.post('/owner/api/profiles', headers=self.headers, json={'name': 'other'}).status_code, 405)
        self.assertEqual(self.c.get('/owner/api/screen?name=other').status_code, 403)
        self.assertEqual(self.c.post('/owner/api/action', headers=self.headers, json={'name': 'other', 'action': 'open'}).status_code, 403)
        self.assertEqual(self.c.post('/owner/api/action', headers=self.headers, json={'name': 'facebook-klinika', 'action': 'snapshot'}).status_code, 403)

    def test_expiry_and_closed_context_revoke(self):
        token = self.issue()
        server.OWNER_GRANTS[server.owner_digest(token)]['expires'] = time.time() - 1
        self.assertEqual(self.pair(token).status_code, 401)
        self.assertEqual(self.pair(self.issue()).status_code, 200)
        server.workspace.context = object()  # even reopening the SAME profile invalidates access
        self.assertEqual(self.c.get('/owner/api/session').status_code, 401)

    def test_csrf_and_logout(self):
        token = self.issue()
        self.assertEqual(self.c.post('/owner/api/pair', json={'token': token}).status_code, 403)
        self.assertEqual(self.c.post('/owner/api/pair', headers={**self.headers, 'origin': 'https://evil.invalid'}, json={'token': token}).status_code, 403)
        self.assertEqual(self.pair(token).status_code, 200)
        self.assertEqual(self.c.post('/owner/api/action', json={'name': 'facebook-klinika', 'action': 'handoff'}).status_code, 403)
        self.assertEqual(self.c.post('/owner/api/logout', headers=self.headers).status_code, 200)
        self.assertEqual(self.c.get('/owner/api/session').status_code, 401)

    def test_issue_does_not_take_control_and_owner_can_handoff(self):
        token = self.issue()
        self.assertFalse(server.workspace.human)
        self.pair(token)
        with patch.object(server.workspace, 'action', new=AsyncMock(return_value={'ok': True})) as action:
            r = self.c.post('/owner/api/action', headers=self.headers, json={'name': 'facebook-klinika', 'action': 'handoff', 'human': True})
            self.assertEqual(r.status_code, 200)
            self.assertIs(action.call_args.kwargs['owner_context'], server.workspace.context)
        server.workspace.human = True
        r = self.c.post('/mcp', headers={'authorization': 'Bearer ' + server.MCP_TOKEN}, json={
            'id': 2, 'method': 'tools/call', 'params': {'name': 'fresh_browser',
            'arguments': {'action': 'owner_access', 'name': 'facebook-klinika'}}})
        self.assertTrue(r.json()['result']['isError'])


class ContextRace(unittest.IsolatedAsyncioTestCase):
    async def test_stale_session_cannot_reopen_or_switch(self):
        w = server.BrowserWorkspace()
        old = object()
        w.context = object()
        w.profile = 'other'
        with self.assertRaises(server.HTTPException):
            await w.action({'name': 'facebook-klinika', 'action': 'open'}, owner_context=old)
        self.assertEqual(w.profile, 'other')
        with self.assertRaises(server.HTTPException):
            await w.screenshot('other', owner_context=old)
