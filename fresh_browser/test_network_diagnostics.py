"""Login-network diagnostics and DNS concurrency tests: no real accounts."""
import asyncio
import json
import socket
import time
import unittest
from types import SimpleNamespace

import server
from navigation_runtime import AuditedWorkspace, PublicNetworkPolicy

PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
PRIVATE = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]


class FakeRoute:
    def __init__(self, url, main=False):
        self.request = SimpleNamespace(
            url=url, method="GET", resource_type="script",
            is_navigation_request=lambda: main)
        self.continued, self.aborted = 0, []

    async def continue_(self):
        self.continued += 1

    async def abort(self, code):
        self.aborted.append(code)


class DNSCoalescing(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_resources_share_one_public_dns_resolution(self):
        resolved = []
        def resolver(host, port, **kw):
            resolved.append(host)
            time.sleep(.06)
            return PUBLIC
        rejected = []
        policy = PublicNetworkPolicy(lambda req, reason: rejected.append(reason),
                                     resolver=resolver)
        routes = [FakeRoute("https://cdn.fixture.invalid/script" + str(i))
                  for i in range(32)]
        await asyncio.gather(*(policy(r) for r in routes))
        self.assertEqual(len(resolved), 1)
        self.assertEqual(rejected, [])
        self.assertTrue(all(r.continued == 1 and not r.aborted for r in routes))
        # A main-frame redirect gets a fresh DNS validation despite caching.
        main = FakeRoute("https://cdn.fixture.invalid/login", main=True)
        await policy(main)
        self.assertEqual(len(resolved), 2)
        self.assertEqual(main.continued, 1)

    async def test_concurrent_private_address_rejection_is_not_relaxed(self):
        resolved = []
        def resolver(host, port, **kw):
            resolved.append(host)
            time.sleep(.04)
            return PRIVATE
        rejected = []
        policy = PublicNetworkPolicy(lambda req, reason: rejected.append(reason),
                                     resolver=resolver)
        routes = [FakeRoute("https://internal.fixture.invalid/static" + str(i))
                  for i in range(12)]
        await asyncio.gather(*(policy(r) for r in routes))
        self.assertEqual(len(resolved), 1)
        self.assertEqual(rejected, ["address_policy"] * 12)
        self.assertTrue(all(r.continued == 0 and r.aborted == ["blockedbyclient"]
                            for r in routes))


class FakeFrame:
    def __init__(self, url):
        self.url = url


class FakePage:
    def __init__(self):
        self.url = "https://www.facebook.com/"
        self.main_frame = FakeFrame(self.url)
        self.frames = [self.main_frame, FakeFrame(
            "https://www.google.com/recaptcha/enterprise/anchor?k=SYNTHETIC_SECRET")]
        self.handlers = {}

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    async def title(self):
        return "Facebook"

    def locator(self, selector):
        return SimpleNamespace(evaluate_all=self.form_entries)

    async def form_entries(self, js):
        return []

    def emit(self, event, value):
        for handler in self.handlers.get(event, []):
            handler(value)



class RestoreSafetyTests(unittest.IsolatedAsyncioTestCase):
    class Page:
        def __init__(self):
            self.url = "about:blank"
            self.calls = []
        def on(self, *_args):
            return None
        async def goto(self, url, **kwargs):
            self.calls.append(url)
            self.url = url
            return SimpleNamespace(status=200)
        async def wait_for_timeout(self, *_args):
            return None

    async def test_long_saved_facebook_checkpoint_is_restored_to_homepage(self):
        w = AuditedWorkspace()
        p = self.Page()
        uri = "https://www.facebook.com/checkpoint/?state=" + "SYNTHETIC_PRIVATE_CODE" * 140
        with self.assertRaises(server.HTTPException):
            server.safe_url(uri)
        self.assertTrue(await w.navigate(p, uri, restoring=True))
        self.assertEqual(p.calls, ["https://www.facebook.com/"])
        self.assertNotIn("SYNTHETIC_PRIVATE_CODE", repr(p.calls))
        self.assertEqual(w.navigation_state(p), "ready")

    async def test_short_callback_query_never_replayed(self):
        w = AuditedWorkspace()
        p = self.Page()
        self.assertTrue(await w.navigate(p,
            "https://www.facebook.com/checkpoint/?code=ONCE&state=PRIVATE",
            restoring=True))
        self.assertEqual(p.calls, ["https://www.facebook.com/"])

    async def test_regular_wordpress_page_keeps_path_without_query(self):
        w = AuditedWorkspace()
        p = self.Page()
        self.assertTrue(await w.navigate(p,
            "https://weterynarz.radom.pl/wp-admin/edit.php?post_type=page",
            restoring=True))
        self.assertEqual(p.calls,
            ["https://weterynarz.radom.pl/wp-admin/edit.php"])

    async def test_invalid_saved_private_address_never_navigated(self):
        w = AuditedWorkspace()
        p = self.Page()
        self.assertFalse(await w.navigate(p,
            "https://127.0.0.1/checkpoint/?state=PRIVATE", restoring=True))
        self.assertEqual(p.calls, [])
        self.assertEqual(w.navigation_state(p), "failed")

    async def test_explicit_address_bar_keeps_existing_url_limit(self):
        w = AuditedWorkspace()
        p = self.Page()
        with self.assertRaises(server.HTTPException):
            await w.navigate(p,
                "https://www.facebook.com/" + ("x" * 2000), restoring=False)
        self.assertEqual(p.calls, [])

class BrowserDiagnosticRegressions(unittest.IsolatedAsyncioTestCase):
    async def test_challenge_iframe_and_resource_failures_omit_query_and_body(self):
        browser = AuditedWorkspace()
        page = FakePage()
        browser.profile = "acceptance-facebook-diag"
        browser.context = SimpleNamespace(pages=[page])
        browser.active_page = page
        browser.register_page(page)
        req = SimpleNamespace(
            url="https://www.google.com/recaptcha/enterprise/bframe?"
                "token=SYNTHETIC_SECRET&password=HIDDEN",
            method="GET", resource_type="document",
            failure="net::ERR_FAILED",
            is_navigation_request=lambda: False)
        page.emit("requestfailed", req)
        response_req = SimpleNamespace(
            url="https://www.gstatic.com/recaptcha/api2/other?"
                "secret=HIDDEN", resource_type="script",
            is_navigation_request=lambda: False)
        page.emit("response", SimpleNamespace(
            request=response_req, status=403, url=response_req.url))
        state = await browser.diagnostics(browser.profile)
        self.assertEqual(state["profile"], browser.profile)
        self.assertTrue(any(f["origin"] == "https://www.google.com"
                            for f in state["frames"]))
        self.assertEqual(len(state["resource_failures"]), 2)
        self.assertEqual(state["resource_failures"][0]["failure"], "net::ERR_FAILED")
        self.assertEqual(state["resource_failures"][1]["http_status"], 403)
        compact = json.dumps(state)
        self.assertNotIn("SYNTHETIC_SECRET", compact)
        self.assertNotIn("password=", compact)
        self.assertNotIn("HIDDEN", compact)
        self.assertNotIn("/recaptcha/", compact)

    async def test_read_only_diagnostics_do_not_change_profile_state(self):
        browser = AuditedWorkspace()
        page = FakePage()
        browser.profile = "acceptance-facebook-diag"
        browser.context = SimpleNamespace(pages=[page])
        browser.active_page = page
        browser.human = True
        browser.register_page(page)
        first = await browser.diagnostics(browser.profile)
        second = await browser.diagnostics(browser.profile)
        self.assertEqual(first["frames"], second["frames"])
        self.assertEqual(browser.profile, "acceptance-facebook-diag")
        self.assertTrue(browser.human)
        self.assertIsNone(browser.rev)
        self.assertIsNone(browser.lease)


if __name__ == "__main__":
    unittest.main()
