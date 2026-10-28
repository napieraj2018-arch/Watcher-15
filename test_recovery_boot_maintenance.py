"""Offline fail-closed, redaction and crash-loop prevention regressions."""
from __future__ import annotations
import io
import unittest
from contextlib import redirect_stdout
from threading import Thread
import httpx
from recovery_boot_maintenance import (_Server, _MaintenanceHandler,
    wait_until_recovered, verify_provider_idle, REASON)
from provider_recovery_gate import RecoveryRateLimited


class Tests(unittest.TestCase):
    def test_maintenance_health_is_explicitly_degraded_and_all_mcp_denied(self):
        srv = _Server(('127.0.0.1', 0), _MaintenanceHandler)
        thread = Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{srv.server_port}'
        try:
            with httpx.Client(trust_env=False, timeout=5) as c:
                health = c.get(url+'/health?code=PRIVATE-SHOULD-NOT-LEAK')
                self.assertEqual(health.status_code, 200)
                self.assertEqual(health.json()['status'], 'degraded')
                self.assertIs(health.json()['browser_available'], False)
                self.assertEqual(health.json()['retry_after_seconds'],900)
                srv.next_retry_seconds = 3600
                longer = c.get(url+'/health')
                self.assertEqual(longer.headers['retry-after'],'3600')
                self.assertEqual(longer.json()['retry_after_seconds'],3600)
                for route in ('/mcp/secret?token=EXAMPLE',
                              '/owner-mobile-login/touch/action',
                              '/youtube/oauth/callback?code=EXAMPLE',
                              '/wp-admin/', '/unknown', '/health'):
                    res = c.post(url+route, content=b'sensitive-user-content')
                    self.assertEqual(res.status_code, 503)
                    self.assertEqual(res.json()['error'], REASON)
                    self.assertNotIn('EXAMPLE', res.text)
                    self.assertNotIn('sensitive-user-content', res.text)
                    self.assertEqual(res.headers['cache-control'], 'no-store')
                home = c.get(url+'/')
                self.assertEqual(home.status_code, 200)
                self.assertIn('tryb ochronny', home.text)
                self.assertEqual(c.head(url+'/health').status_code, 200)
        finally:
            srv.shutdown()
            srv.server_close()
            thread.join(timeout=2)

    def test_wait_never_grants_access_before_both_fresh_proofs(self):
        class FakeServer:
            def __init__(self, *a): self.calls=[]
            def serve_forever(self): self.calls.append('serve')
            def shutdown(self): self.calls.append('stop')
            def server_close(self): self.calls.append('close')
        sleeps=[]; attempts=[]; checks=[]; servers=[]
        def factory(*args):
            instance=FakeServer(*args); servers.append(instance); return instance
        def sleep(s): sleeps.append(s)
        def gate():
            attempts.append(1)
            if len(attempts)<3: raise RuntimeError('private retry detail')
        def provider():
            checks.append(1)
            return len(checks)>=2
        with redirect_stdout(io.StringIO()) as logs:
            wait_until_recovered(gate, provider, host='127.0.0.1', port=1,
                                 retry_seconds=4, sleeper=sleep, server_factory=factory)
        self.assertEqual(len(attempts),4)
        self.assertEqual(len(checks),2)
        self.assertEqual(sleeps,[4,4,4,4])
        self.assertIn('RECOVERY_UNCONFIRMED',logs.getvalue())
        self.assertNotIn('private retry detail',logs.getvalue())
        self.assertEqual(servers[0].calls,['serve','stop','close'])

    def test_retry_after_is_respected_and_429_backoff_increases(self):
        class FakeServer:
            def serve_forever(self): pass
            def shutdown(self): pass
            def server_close(self): pass
        attempts=[]; sleeps=[]
        def gate():
            attempts.append(1)
            if len(attempts)<=2: raise RecoveryRateLimited(3600)
        with redirect_stdout(io.StringIO()) as output:
            wait_until_recovered(gate,lambda:True,port=1,
                retry_seconds=900,initial_retry_seconds=900,
                sleeper=sleeps.append,server_factory=lambda *_:FakeServer())
        self.assertEqual(sleeps,[900,3600,7200])
        self.assertEqual(len(attempts),3)
        self.assertIn('RECOVERY_RATE_LIMITED',output.getvalue())
        self.assertNotIn('DO_NOT_PRINT',output.getvalue())
    def test_initial_retry_after_is_respected(self):
        class FakeServer:
            def serve_forever(self): pass
            def shutdown(self): pass
            def server_close(self): pass
        sleeps=[]
        with redirect_stdout(io.StringIO()):
            wait_until_recovered(lambda:None,lambda:True,port=1,
                initial_retry_seconds=7200,sleeper=sleeps.append,
                server_factory=lambda *_:FakeServer())
        self.assertEqual(sleeps,[7200])
    def test_never_treat_false_provider_quiet_as_verified(self):
        class FakeServer:
            def serve_forever(self): pass
            def shutdown(self): pass
            def server_close(self): pass
        n=0
        def sleep(_):
            nonlocal n
            n+=1
            if n>=3: raise StopIteration()
        with self.assertRaises(StopIteration),redirect_stdout(io.StringIO()):
            wait_until_recovered(lambda:None,lambda:False,port=1,
                                 retry_seconds=4,sleeper=sleep,
                                 server_factory=lambda *_:FakeServer())
        self.assertEqual(n,3)

    def test_steel_inventory_strictly_read_only(self):
        def transport(request):
            self.assertEqual(request.method,'GET')
            self.assertEqual(request.url.host,'api.steel.dev')
            self.assertEqual(request.headers['steel-api-key'],'synthetic')
            self.assertEqual(request.url.params['status'],'live')
            return httpx.Response(200,json={'sessions':[]})
        with httpx.Client(transport=httpx.MockTransport(transport),trust_env=False) as c:
            self.assertTrue(verify_provider_idle('synthetic',client=c))

    def test_live_steel_session_denied(self):
        with httpx.Client(transport=httpx.MockTransport(
            lambda r:httpx.Response(200,json={'sessions':[{'id':'test','status':'live'}]})),trust_env=False) as c:
            with self.assertRaisesRegex(RuntimeError,'LIVE_OR_UNCONFIRMED'):
                verify_provider_idle('synthetic',client=c)

    def test_provider_http_429_and_redirect_denied(self):
        for status in (429,302,401,500):
            with httpx.Client(transport=httpx.MockTransport(
                lambda r:httpx.Response(status,json={'private':'DO_NOT_SHOW'})),trust_env=False) as c:
                with self.assertRaisesRegex(RuntimeError,'INVENTORY_UNAVAILABLE') as exc:
                    verify_provider_idle('synthetic',client=c)
                self.assertNotIn('DO_NOT_SHOW',str(exc.exception))

    def test_provider_malformed_denied(self):
        for body in ('{}','{"sessions":null}','[1,2]','invalid'):
            with httpx.Client(transport=httpx.MockTransport(
                lambda r:httpx.Response(200,text=body)),trust_env=False) as c:
                with self.assertRaises(RuntimeError):
                    verify_provider_idle('synthetic',client=c)

    def test_requires_provider_key(self):
        with self.assertRaisesRegex(RuntimeError,'CREDENTIAL_UNAVAILABLE'):
            verify_provider_idle('')

    def test_maintenance_config_denies_invalid_input(self):
        for port in (0,-1,70000):
            with self.assertRaisesRegex(RuntimeError,'CONFIG_INVALID'):
                wait_until_recovered(lambda:None,lambda:True,port=port,
                                     server_factory=lambda *_:None)


if __name__=='__main__': unittest.main(verbosity=2)
