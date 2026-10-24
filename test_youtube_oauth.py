"""Offline tests only: synthetic identities, mock HTTP, no live Google writes."""
import asyncio
import copy
import hashlib
import json
import unittest
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo
from datetime import datetime
import httpx
from youtube_oauth import (API, AUTH, TOKEN, THUMBNAIL, SCOPE, Config, Vault,
                           YouTube, YouTubeError, prepare_update, digest)

CID = 'UC' + 'A' * 22
VID = 'A' * 11
CONFIG = Config('fixture.apps.googleusercontent.com', 'synthetic-client-secret',
                'https://app.example/youtube/oauth/callback', CID)
BASE = {'id': VID, 'etag': 'etag-before', 'snippet': {
    'channelId': CID, 'title': 'Before', 'description': 'Keep description',
    'tags': ['keep'], 'categoryId': '19', 'defaultLanguage': 'pl'},
    'status': {'privacyStatus': 'private', 'license': 'youtube', 'embeddable': False,
               'publicStatsViewable': False, 'selfDeclaredMadeForKids': False}}


class Store:
    """TEST DOUBLE only. Not a production storage implementation."""
    durable = True
    def __init__(self): self.rows = {}
    async def read(self, key): return self.rows.get(key)
    async def write(self, key, expected, envelope):
        actual = self.rows.get(key)
        if (actual[0] if actual else None) != expected:
            raise YouTubeError('YOUTUBE_CAS_CONFLICT')
        revision = (expected or 0) + 1
        self.rows[key] = (revision, envelope)
        return revision


class Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 1000
        self.store = Store()
        self.vault = Vault(self.store, b'K' * 32, 'synthetic-owner', CONFIG)
        self.video = copy.deepcopy(BASE)
        self.calls = []
        self.fail = None
        self.channel = CID
        self.scope = SCOPE
        self.return_refresh = True
        self.api = YouTube(CONFIG, self.vault, clock=lambda: self.now,
                           transport=httpx.MockTransport(self.handler))

    def handler(self, request):
        self.calls.append(request)
        if self.fail:
            failure = self.fail
            if failure == 'timeout' and request.method == 'PUT':
                self.apply_update(json.loads(request.content))
                raise httpx.ReadTimeout('secret must not escape', request=request)
            if isinstance(failure, int):
                return httpx.Response(failure, json={'error': 'private-provider-message'})
        if str(request.url) == TOKEN:
            payload = {'access_token': 'synthetic-access', 'token_type': 'Bearer',
                       'expires_in': 3600, 'scope': self.scope}
            if self.return_refresh: payload['refresh_token'] = 'synthetic-refresh'
            return httpx.Response(200, json=payload)
        if request.url.path.endswith('/channels'):
            return httpx.Response(200, json={'items': [{'id': self.channel}]})
        if request.url.path.endswith('/thumbnails/set'):
            return httpx.Response(200, json={'items': [{'default': {'url': 'https://i.ytimg.com/fixture.jpg'}}]})
        if request.method == 'PUT':
            self.apply_update(json.loads(request.content))
            self.video['etag'] = 'etag-after'
        return httpx.Response(200, json={'items': [copy.deepcopy(self.video)]})

    def apply_update(self, body):
        for part in ('snippet', 'status'):
            if part in body:
                readonly = {'channelId': self.video['snippet']['channelId']} if part == 'snippet' else {}
                self.video[part] = {**copy.deepcopy(body[part]), **readonly}

    async def login(self):
        url = await self.api.begin('B' * 40)
        state = parse_qs(urlsplit(url).query)['state'][0]
        result = await self.api.finish(state, 'synthetic-code', 'B' * 40)
        return url, state, result

    async def test_oauth_pkce_offline_and_pinned_destinations(self):
        url, state, result = await self.login()
        q = parse_qs(urlsplit(url).query)
        self.assertTrue(url.startswith(AUTH + '?'))
        self.assertEqual(q['scope'], [SCOPE])
        self.assertEqual(q['access_type'], ['offline'])
        self.assertEqual(q['code_challenge_method'], ['S256'])
        self.assertNotIn('client_secret', q)
        self.assertNotIn('code_verifier', q)
        self.assertTrue(result['connected'])
        token_request = self.calls[0]
        self.assertEqual(str(token_request.url), TOKEN)
        self.assertNotIn('synthetic-code', str(token_request.url))

    async def test_wrong_cookie_does_not_consume_state(self):
        url = await self.api.begin('B' * 40)
        state = parse_qs(urlsplit(url).query)['state'][0]
        with self.assertRaisesRegex(YouTubeError, 'STATE_INVALID'):
            await self.api.finish(state, 'code', 'C' * 40)
        self.assertEqual(self.calls, [])
        self.assertTrue((await self.api.finish(state, 'code', 'B' * 40))['connected'])

    async def test_state_cannot_be_replayed(self):
        _, state, _ = await self.login()
        before = len(self.calls)
        with self.assertRaisesRegex(YouTubeError, 'STATE_INVALID'):
            await self.api.finish(state, 'code', 'B' * 40)
        self.assertEqual(before, len(self.calls))

    async def test_expired_state(self):
        url = await self.api.begin('B' * 40)
        self.now += 601
        with self.assertRaisesRegex(YouTubeError, 'STATE_INVALID'):
            await self.api.finish(parse_qs(urlsplit(url).query)['state'][0], 'code', 'B' * 40)
        self.assertEqual(self.calls, [])

    async def test_wrong_channel_never_stores_token(self):
        self.channel = 'UC' + 'Z' * 22
        with self.assertRaisesRegex(YouTubeError, 'WRONG_CHANNEL'): await self.login()
        self.assertIsNone(await self.vault.read('credentials'))

    async def test_missing_scope_never_stores_token(self):
        self.scope = 'openid'
        with self.assertRaisesRegex(YouTubeError, 'SCOPE_OR_TOKEN_INVALID'): await self.login()
        self.assertIsNone(await self.vault.read('credentials'))

    async def test_offline_consent_required_first_time(self):
        self.return_refresh = False
        with self.assertRaisesRegex(YouTubeError, 'OFFLINE_CONSENT_REQUIRED'): await self.login()

    async def test_preserves_refresh_token_on_same_channel_reconsent(self):
        await self.login()
        self.return_refresh = False
        await self.login()
        self.assertEqual((await self.vault.read('credentials'))[1]['refresh_token'], 'synthetic-refresh')

    async def test_refresh_preserves_previous_refresh_token(self):
        await self.login()
        self.now += 3601
        self.return_refresh = False
        self.assertEqual(await self.api.access(), 'synthetic-access')
        self.assertEqual((await self.vault.read('credentials'))[1]['refresh_token'], 'synthetic-refresh')
        self.assertIn(b'grant_type=refresh_token', self.calls[-1].content)

    async def test_refresh_invalid_grant_does_not_delete_credentials(self):
        await self.login()
        before = await self.vault.read('credentials')
        self.now += 3601
        self.fail = 400
        with self.assertRaisesRegex(YouTubeError, 'REAUTH_REQUIRED'): await self.api.access()
        self.assertEqual(before, await self.vault.read('credentials'))

    async def test_provider_secrets_not_in_errors(self):
        self.fail = 500
        with self.assertRaises(YouTubeError) as exc: await self.login()
        self.assertNotIn('private-provider-message', str(exc.exception))
        self.assertNotIn('synthetic', str(exc.exception))

    async def test_redirect_is_not_followed(self):
        self.fail = 302
        with self.assertRaisesRegex(YouTubeError, 'PROVIDER_REJECTED'): await self.login()
        self.assertEqual(len(self.calls), 1)

    async def test_store_marked_nondurable_is_rejected(self):
        self.store.durable = False
        with self.assertRaisesRegex(YouTubeError, 'DURABLE_VAULT_REQUIRED'):
            Vault(self.store, b'K' * 32, 'owner', CONFIG)

    async def test_credentials_encrypted_not_plaintext(self):
        await self.login()
        stored = str(self.store.rows)
        for secret in ('synthetic-refresh', 'synthetic-access', 'synthetic-client-secret'):
            self.assertNotIn(secret, stored)

    async def test_owner_isolation(self):
        await self.login()
        other = Vault(self.store, b'K' * 32, 'other-owner', CONFIG)
        self.assertIsNone(await other.read('credentials'))
        envelope = (await self.store.read(self.vault.name('credentials')))[1]
        await self.store.write(other.name('credentials'), None, envelope)
        with self.assertRaisesRegex(YouTubeError, 'INTEGRITY'): await other.read('credentials')

    async def test_storage_cas_conflict(self):
        await self.vault.write('test', None, {'a': 1})
        with self.assertRaisesRegex(YouTubeError, 'CAS_CONFLICT'):
            await self.vault.write('test', None, {'a': 2})

    async def test_missing_authorization_never_calls_api(self):
        with self.assertRaisesRegex(YouTubeError, 'NOT_CONNECTED'): await self.api.video(VID)
        self.assertEqual(self.calls, [])

    async def test_video_wrong_owner(self):
        await self.login()
        self.video['snippet']['channelId'] = 'UC' + 'Z' * 22
        with self.assertRaisesRegex(YouTubeError, 'WRONG_CHANNEL'): await self.api.video(VID)

    async def test_title_only_preserves_description_tags_and_privacy(self):
        prepared = prepare_update(BASE, {'title': 'After'}, CID)
        self.assertEqual(prepared['part'], 'snippet')
        self.assertNotIn('status', prepared['body'])
        self.assertEqual(prepared['body']['snippet']['description'], 'Keep description')
        self.assertEqual(prepared['body']['snippet']['tags'], ['keep'])
        self.assertNotIn('channelId', prepared['body']['snippet'])
        self.assertEqual(BASE['snippet']['title'], 'Before')

    async def test_explicit_empty_fields_are_allowed(self):
        prepared = prepare_update(BASE, {'description': '', 'tags': []}, CID)
        self.assertEqual(prepared['body']['snippet']['description'], '')
        self.assertEqual(prepared['body']['snippet']['tags'], [])

    async def test_privacy_preserves_other_status_fields(self):
        prepared = prepare_update(BASE, {'privacyStatus': 'unlisted'}, CID)
        self.assertFalse(prepared['body']['status']['embeddable'])
        self.assertFalse(prepared['body']['status']['selfDeclaredMadeForKids'])
        self.assertEqual(prepared['part'], 'status')

    async def test_unknown_fields_rejected(self):
        with self.assertRaisesRegex(YouTubeError, 'UPDATE_INVALID'):
            prepare_update(BASE, {'license': 'creativeCommon'}, CID)

    async def test_schedule_handles_polish_dst_end(self):
        date = datetime(2026, 10, 25, 8, 30, tzinfo=ZoneInfo('Europe/Warsaw'))
        prepared = prepare_update(BASE, {'publishAt': date.isoformat(), 'privacyStatus': 'private'},
                                  CID, now=1000, never_published=True)
        self.assertEqual(prepared['body']['status']['publishAt'], '2026-10-25T07:30:00Z')

    async def test_schedule_requires_explicit_unpublished_evidence(self):
        with self.assertRaisesRegex(YouTubeError, 'UNPUBLISHED_PRIVATE'):
            prepare_update(BASE, {'publishAt': '2026-10-25T07:30:00Z', 'privacyStatus': 'private'}, CID)

    async def test_schedule_rejects_naive_and_past_dates(self):
        for date in ('2026-10-25T08:30:00', '1970-01-01T00:01:00Z'):
            with self.assertRaisesRegex(YouTubeError, 'SCHEDULE_INVALID'):
                prepare_update(BASE, {'publishAt': date, 'privacyStatus': 'private'}, CID,
                               now=1000, never_published=True)

    async def test_schedule_not_cancelled_by_unrelated_privacy_change(self):
        video = copy.deepcopy(BASE)
        video['status']['publishAt'] = '2026-10-25T07:30:00Z'
        with self.assertRaisesRegex(YouTubeError, 'EXISTING_SCHEDULE_REVIEW_REQUIRED'):
            prepare_update(video, {'privacyStatus': 'unlisted'}, CID)

    async def test_exact_approval_required(self):
        await self.login()
        prepared = prepare_update(BASE, {'title': 'After'}, CID)
        with self.assertRaisesRegex(YouTubeError, 'EXACT_APPROVAL_REQUIRED'):
            await self.api.update(prepared, 'op-1', 'not-approved')
        self.assertFalse(any(r.method == 'PUT' for r in self.calls))

    async def test_update_readback_and_idempotency(self):
        await self.login()
        prepared = prepare_update(BASE, {'title': 'After'}, CID)
        result = await self.api.update(prepared, 'op-1', digest(prepared))
        self.assertEqual(result['status'], 'confirmed')
        second = await self.api.update(prepared, 'op-1', digest(prepared))
        self.assertFalse(second['executed'])
        self.assertEqual(sum(r.method == 'PUT' for r in self.calls), 1)
        self.assertEqual(next(r for r in self.calls if r.method == 'PUT').headers['if-match'], 'etag-before')

    async def test_timeout_must_verify_without_replay(self):
        await self.login()
        self.fail = 'timeout'
        prepared = prepare_update(BASE, {'title': 'After'}, CID)
        with self.assertRaisesRegex(YouTubeError, 'UNCONFIRMED'):
            await self.api.update(prepared, 'op-1', digest(prepared))
        second = await self.api.update(prepared, 'op-1', digest(prepared))
        self.assertFalse(second['executed'])
        self.assertEqual(second['status'], 'unverified')
        self.assertTrue((await self.api.verify_update(prepared, 'op-1', digest(prepared)))['verified'])
        self.assertEqual(sum(r.method == 'PUT' for r in self.calls), 1)

    async def test_concurrent_change_prevents_write(self):
        await self.login()
        prepared = prepare_update(BASE, {'title': 'After'}, CID)
        self.video['etag'] = 'changed-elsewhere'
        with self.assertRaisesRegex(YouTubeError, 'CONCURRENT_CHANGE'):
            await self.api.update(prepared, 'op-1', digest(prepared))
        self.assertFalse(any(r.method == 'PUT' for r in self.calls))

    async def test_duplicate_operation_with_different_payload_rejected(self):
        await self.login()
        one = prepare_update(BASE, {'title': 'After'}, CID)
        await self.api.update(one, 'op-1', digest(one))
        two = prepare_update(self.video, {'title': 'Second'}, CID)
        with self.assertRaisesRegex(YouTubeError, 'OPERATION_ID_REUSED'):
            await self.api.update(two, 'op-1', digest(two))

    async def test_thumbnail_requires_exact_bytes_approval(self):
        await self.login()
        image = b'\x89PNG\r\n\x1a\n' + b'synthetic-fixture'
        with self.assertRaisesRegex(YouTubeError, 'EXACT_APPROVAL_REQUIRED'):
            await self.api.thumbnail(VID, image, 'image/png', 'thumb-1', 'wrong')

    async def test_thumbnail_receipt_does_not_claim_pixel_verification(self):
        await self.login()
        image = b'\x89PNG\r\n\x1a\n' + b'synthetic-fixture'
        approval = digest({'video_id': VID, 'channel_id': CID,
                           'sha256': hashlib.sha256(image).hexdigest(), 'mime': 'image/png'})
        result = await self.api.thumbnail(VID, image, 'image/png', 'thumb-1', approval)
        self.assertEqual(result['status'], 'accepted')
        self.assertFalse(result['content_verified'])
        self.assertFalse((await self.api.thumbnail(VID, image, 'image/png', 'thumb-1', approval))['executed'])
        self.assertEqual(sum(r.url.path.endswith('/thumbnails/set') for r in self.calls), 1)

    async def test_config_and_image_validation(self):
        for url in ('http://app.example/youtube/oauth/callback', 'https://app.example/evil',
                    'https://u:p@app.example/youtube/oauth/callback',
                    'https://app.example/youtube/oauth/callback?next=evil'):
            with self.assertRaises(YouTubeError):
                Config(CONFIG.client_id, 'secret', url, CID)
        with self.assertRaisesRegex(YouTubeError, 'THUMBNAIL_INVALID'):
            await self.api.thumbnail(VID, b'not an image', 'image/png', 'x', 'x')

    async def test_no_arbitrary_destination(self):
        with self.assertRaisesRegex(YouTubeError, 'DESTINATION_REJECTED'):
            await self.api.request('GET', 'https://evil.example', access='secret')
        self.assertEqual(self.calls, [])


if __name__ == '__main__': unittest.main()
