"""Real MCP image-result regressions; no live accounts, Steel or network."""
from __future__ import annotations
import asyncio
import base64
import json
from pathlib import Path
import re
import struct
import sys
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / 'session_ownership'),
               str(ROOT / 'session_ownership' / 'tests')]
from mcp.server.mcpserver.utilities.types import Image
from mcp.server.mcpserver.tools.base import Tool
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ImageContent
from capability_guard import CapabilityGuard, OwnershipError, scrub_result
from multi_capability_guard import MultiCapabilityGuard
from test_sdk_contract import fake_mcp
from test_owner_parallel_mcp import MultiManager
from screenshot_result import image_result, ScreenshotResultError


def png(rgb=(40, 80, 120)):
    def chunk(kind, data):
        return (struct.pack('!I', len(data)) + kind + data
                + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('!IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\x00' + bytes(rgb)))
            + chunk(b'IEND', b''))


def images(value):
    if isinstance(value, ImageContent):
        return [value]
    if isinstance(value, (list, tuple)):
        return [image for item in value for image in images(item)]
    if hasattr(value, 'content'):
        return images(value.content)
    return []


class Encoding(unittest.TestCase):
    def test_in_memory_image_reaches_the_image_protocol(self):
        source = Image(data=png(), format='png')
        result = scrub_result(source, 'internal-synthetic', 'aib_synthetic')
        self.assertIs(type(result), Image)
        self.assertIsNot(source, result)
        self.assertEqual(result.data, source.data)
        self.assertIsNone(result.path)

    def test_image_content_is_copied_without_untrusted_metadata(self):
        source = ImageContent(type='image', mime_type='image/png',
                              data=base64.b64encode(png()).decode())
        result = image_result(source)
        self.assertIs(type(result), Image)
        self.assertEqual(result.data, png())
        self.assertIsNone(result.path)

    def test_public_or_unowned_image_is_refused(self):
        for kwargs in ({}, {'internal_id':'i'}, {'handle':'h'},
                       {'internal_id':'i', 'handle':'h', 'public':True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(OwnershipError):
                scrub_result(Image(data=png()), **kwargs)

    def test_path_backed_image_never_reads_disk(self):
        with patch('builtins.open', side_effect=AssertionError('must not read')):
            with self.assertRaisesRegex(ScreenshotResultError, 'IN_MEMORY_REQUIRED'):
                scrub_result(Image(path='/private/synthetic.png'), 'i', 'h')

    def test_arbitrary_objects_and_nested_images_remain_blocked(self):
        class PretendImage:
            def to_image_content(self):
                raise AssertionError('duck typing forbidden')
        for value in (PretendImage(), [Image(data=png())],
                      {'nested':Image(data=png())}, {'nested':object()}):
            with self.subTest(type=type(value).__name__), self.assertRaises(OwnershipError):
                scrub_result(value, 'i', 'h')

    def test_subclass_cannot_override_image_conversion(self):
        class SubImage(Image):
            def to_image_content(self):
                raise AssertionError('must not call')
        with self.assertRaises(OwnershipError):
            scrub_result(SubImage(data=png()), 'i', 'h')

    def test_corrupt_or_non_png_images_get_fixed_errors(self):
        for value in (Image(data=b'PRIVATE_DATA'), Image(data=png(), format='jpeg'),
                      ImageContent(type='image', mime_type='image/png', data='!PRIVATE!')):
            with self.subTest(type=type(value).__name__), self.assertRaises(ScreenshotResultError) as error:
                image_result(value)
            self.assertNotIn('PRIVATE', str(error.exception))

    def test_oversize_image_refused_before_conversion(self):
        with patch('screenshot_result.MAX_PNG_BYTES', 8):
            for value in (Image(data=png()), ImageContent(
                    type='image', mime_type='image/png',
                    data=base64.b64encode(png()).decode())):
                with self.assertRaisesRegex(ScreenshotResultError, 'TOO_LARGE'):
                    image_result(value)

    def test_existing_json_redaction_unchanged(self):
        data = {'session_id':'internal', 'url':'https://example.test/?private=yes',
                'nested':[{'session_id':'internal'}]}
        for value in (data, json.dumps(data)):
            result = scrub_result(value, 'internal', 'aib_capability')
            if isinstance(result, str): result = json.loads(result)
            self.assertEqual(result['session_id'], 'aib_capability')
            self.assertEqual(result['nested'][0]['session_id'], 'aib_capability')
            self.assertEqual(result['url'], 'https://example.test/')


class WireContract(unittest.IsolatedAsyncioTestCase):
    async def setup_guard(self, mode):
        manager = MultiManager()
        server = fake_mcp(manager)
        seen = []
        async def screenshot(session_id: str, full_page: bool = False) -> Image:
            session = manager._session(session_id)
            seen.append((session.profile, full_page))
            if callable(getattr(session.page, 'screenshot', None)):
                return Image(data=await session.page.screenshot(
                    type='png', full_page=full_page, timeout=10000), format='png')
            color = (11, 22, 33) if session.profile == 'Synthetic-A' else (33, 22, 11)
            return Image(data=png(color), format='png')
        server._tool_manager._tools['browser_screenshot'] = Tool.from_function(
            screenshot, name='browser_screenshot', structured_output=False)
        before = server._tool_manager._tools['browser_screenshot'].parameters.copy()
        guard = (MultiCapabilityGuard(server, manager, capacity=5, watchdog_enabled=False)
                 if mode == 'multi' else
                 CapabilityGuard(server, manager, watchdog_enabled=False))
        guard.install()
        self.assertEqual(before, server._tool_manager._tools['browser_screenshot'].parameters)
        return server, manager, guard, seen

    async def begin(self, server, profile):
        response = await server.call_tool('browser_start', {'profile':profile})
        match = re.search(r'aib_[A-Za-z0-9_-]{43}', str(response))
        self.assertIsNotNone(match)
        return match.group(0)

    async def test_single_and_multi_guard_emit_one_real_mcp_image(self):
        for mode in ('single', 'multi'):
            with self.subTest(mode=mode):
                server, manager, guard, seen = await self.setup_guard(mode)
                handle = await self.begin(server, 'Synthetic-A')
                try:
                    response = await server.call_tool('browser_screenshot',
                        {'session_id':handle, 'full_page':True})
                    content = images(response)
                    self.assertEqual(len(content), 1)
                    self.assertEqual(content[0].mime_type, 'image/png')
                    self.assertEqual(base64.b64decode(content[0].data), png((11,22,33)))
                    self.assertEqual(seen, [('Synthetic-A', True)])
                    self.assertNotIn('INTERNAL_SYNTHETIC_SESSION_', str(response))
                    self.assertNotIn(handle, str(response))
                finally:
                    await server.call_tool('browser_stop', {'session_id':handle})
                self.assertEqual(manager._sessions, {})

    async def test_raw_or_unknown_handle_never_captures_image(self):
        server, manager, guard, seen = await self.setup_guard('multi')
        handle = await self.begin(server, 'Synthetic-A')
        try:
            for wrong in ('INTERNAL_SYNTHETIC_SESSION_1', 'aib_'+'x'*43, ''):
                with self.assertRaises(ToolError):
                    await server.call_tool('browser_screenshot', {'session_id':wrong})
            self.assertEqual(seen, [])
        finally:
            await server.call_tool('browser_stop', {'session_id':handle})

    async def test_parallel_images_belong_to_their_own_profiles(self):
        server, manager, guard, seen = await self.setup_guard('multi')
        first = await self.begin(server, 'Synthetic-A')
        second = await self.begin(server, 'Synthetic-B')
        try:
            results = await asyncio.gather(*(
                server.call_tool('browser_screenshot', {'session_id':handle})
                for handle in (first, second)))
            self.assertEqual(base64.b64decode(images(results[0])[0].data), png((11,22,33)))
            self.assertEqual(base64.b64decode(images(results[1])[0].data), png((33,22,11)))
            self.assertEqual(set(seen), {('Synthetic-A',False),('Synthetic-B',False)})
        finally:
            await server.call_tool('browser_stop', {'session_id':first})
            await server.call_tool('browser_stop', {'session_id':second})

    async def test_actual_chromium_mobile_png_survives_sdk_conversion(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage'])
            try:
                context = await browser.new_context(viewport={'width':390,'height':844})
                page = await context.new_page()
                await page.set_content('<!doctype html><title>Neutral screenshot</title>'
                                       '<h1>AI Browser screenshot acceptance</h1>')
                server, manager, guard, seen = await self.setup_guard('multi')
                handle = await self.begin(server, 'Synthetic-A')
                manager._sessions[guard.authorize(handle).internal_session_id].page = page
                try:
                    response = await server.call_tool('browser_screenshot',
                        {'session_id':handle, 'full_page':False})
                    content = images(response)
                    self.assertEqual(len(content), 1)
                    raw = base64.b64decode(content[0].data)
                    self.assertGreater(len(raw), 100)
                    self.assertEqual(struct.unpack('!II', raw[16:24]), (390,844))
                finally:
                    await server.call_tool('browser_stop', {'session_id':handle})
            finally:
                await browser.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
