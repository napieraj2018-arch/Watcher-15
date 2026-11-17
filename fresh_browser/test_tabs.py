import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
import server


class Page:
    def __init__(self, url='about:blank'):
        self.url = url
        self.main_frame = object()
        self.events = {}
        self.viewport_size = {'width': 390, 'height': 844}
        self.title = AsyncMock(return_value='Neutral fixture')
        self.screenshot = AsyncMock(return_value=b'png-fixture')
        self.wait_for_timeout = AsyncMock()

    def on(self, event, callback):
        self.events[event] = callback


class Tabs(unittest.IsolatedAsyncioTestCase):
    def workspace(self):
        w = server.BrowserWorkspace()
        parent = Page('https://example.com/login')
        w.context = SimpleNamespace(pages=[parent])
        w.profile = 'fixture'
        w.active_page = parent
        w.register_page(parent)
        w.assert_lease = AsyncMock()
        w._save = AsyncMock()
        return w, parent

    async def test_blank_popup_keeps_login_page(self):
        w, parent = self.workspace()
        popup = Page()
        w.context.pages.append(popup)
        w.register_page(popup)
        self.assertIs(w.page(), parent)
        popup.events['framenavigated'](popup.main_frame)
        self.assertIs(w.page(), parent)
        popup.url = 'https://example.com/verify'
        popup.events['framenavigated'](popup.main_frame)
        self.assertIs(w.page(), popup)

    async def test_closed_active_tab_falls_back_to_web_page(self):
        w, parent = self.workspace()
        w.active_page = Page('https://example.org/closed')
        w.context.pages.append(Page())
        self.assertIs(w.page(), parent)

    async def test_list_and_select_tab_preserve_same_context(self):
        w, parent = self.workspace()
        popup = Page()
        w.context.pages.append(popup)
        w.register_page(popup)
        context = w.context
        data = await w.action({'name': 'fixture', 'action': 'tabs'}, automated=True)
        self.assertEqual(len(data['tabs']), 2)
        self.assertTrue(data['tabs'][0]['active'])
        await w.action({'name': 'fixture', 'action': 'select_tab', 'text': w.tab_id(popup)}, automated=True)
        self.assertIs(w.page(), popup)
        self.assertIs(w.context, context)
        with self.assertRaises(server.HTTPException):
            await w.action({'name': 'fixture', 'action': 'select_tab', 'text': 'missing'}, automated=True)

    async def test_stale_screenshot_click_rejected_before_input(self):
        w, parent = self.workspace()
        with self.assertRaises(server.HTTPException) as exc:
            await w.action({'name': 'fixture', 'action': 'click', 'page_id': 'old-tab', 'x': 10, 'y': 10})
        self.assertEqual(exc.exception.status_code, 409)
        w._save.assert_not_awaited()

    async def test_frames_read_only_and_bound_to_selected_page(self):
        w, parent = self.workspace()
        png, headers = await w.screenshot('fixture', owner_context=w.context, with_metadata=True)
        self.assertEqual(png, b'png-fixture')
        self.assertEqual(headers['X-AIB-Page'], w.tab_id(parent))
        self.assertEqual(headers['X-AIB-Origin'], 'https://example.com')
        w._save.assert_not_awaited()

    async def test_diagnostics_exclude_credentials_and_urls(self):
        w, parent = self.workspace()
        request = SimpleNamespace(is_navigation_request=lambda: True, frame=parent.main_frame,
                                  failure='net::ERR_ABORTED', url='https://example.com/login?token=private')
        parent.events['requestfailed'](request)
        parent.events['response'](SimpleNamespace(request=request, status=403, url=request.url))
        data = await w.tab_state()
        self.assertNotIn('private', str(data))
        self.assertEqual(data['navigation_failures'][0]['failure'], 'net::ERR_ABORTED')
        self.assertEqual(data['navigation_failures'][1]['status'], 403)
