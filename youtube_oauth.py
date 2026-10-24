"""YouTube OAuth/API backend, deliberately not installed in the live server yet.

Requires a dedicated durable CAS store. Never use browser profiles/task-vault
for credentials. The HTTP handoff must authenticate the owner, set a Secure
HttpOnly SameSite=Lax browser nonce cookie, and redact callback query logging.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AUTH = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN = 'https://oauth2.googleapis.com/token'
API = 'https://www.googleapis.com/youtube/v3/'
THUMBNAIL = 'https://www.googleapis.com/upload/youtube/v3/thumbnails/set'
SCOPE = 'https://www.googleapis.com/auth/youtube.force-ssl'
CHANNEL = re.compile(r'UC[A-Za-z0-9_-]{22}\Z')
VIDEO = re.compile(r'[A-Za-z0-9_-]{11}\Z')
OPERATION = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z')
SNIPPET = {'title', 'description', 'tags', 'categoryId', 'defaultLanguage', 'defaultAudioLanguage'}
STATUS = {'privacyStatus', 'license', 'embeddable', 'publicStatsViewable',
          'selfDeclaredMadeForKids', 'publishAt', 'containsSyntheticMedia'}
EDITABLE = {'title', 'description', 'tags', 'privacyStatus', 'publishAt'}


class YouTubeError(RuntimeError):
    """Fixed codes only. Never include Google response bodies or credentials."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class DurableCAS(Protocol):
    """Dedicated namespace; atomic compare-and-swap MUST span worker/restarts.

    read returns (revision, encrypted envelope), or None.
    write(expected=None) means INSERT ONLY; mismatches raise YouTubeError.
    No endpoint may expose plaintext, list credentials, or accept caller owner IDs.
    """
    durable: bool

    async def read(self, key: str) -> tuple[int, str] | None: ...
    async def write(self, key: str, expected: int | None, envelope: str) -> int: ...


@dataclass(frozen=True, repr=False)
class Config:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str
    channel_id: str

    def __post_init__(self):
        p = urlsplit(self.redirect_uri)
        if (not self.client_id.endswith('.apps.googleusercontent.com')
                or not self.client_secret or not CHANNEL.fullmatch(self.channel_id)
                or p.scheme != 'https' or not p.hostname or p.username or p.password
                or p.port not in (None, 443) or p.query or p.fragment
                or p.path != '/youtube/oauth/callback'):
            raise YouTubeError('YOUTUBE_CONFIG_INVALID')


class Vault:
    """AES-GCM bound to owner/client/channel; separate from browser encryption."""
    def __init__(self, store: DurableCAS, key: bytes, owner: str, config: Config):
        if store.durable is not True or len(key) != 32 or not owner:
            raise YouTubeError('YOUTUBE_DURABLE_VAULT_REQUIRED')
        self.store, self.key = store, key
        self.binding = digest(['youtube-oauth-v1', owner, config.client_id, config.channel_id])

    def name(self, key):
        return 'youtube-v1:' + self.binding + ':' + digest(key)

    def seal(self, key, value):
        nonce = secrets.token_bytes(12)
        raw = canonical(value).encode()
        if len(raw) > 100000:
            raise YouTubeError('YOUTUBE_RECORD_TOO_LARGE')
        encrypted = AESGCM(self.key).encrypt(nonce, raw, self.name(key).encode())
        return base64.urlsafe_b64encode(nonce + encrypted).decode()

    async def read(self, key):
        row = await self.store.read(self.name(key))
        if row is None:
            return None
        try:
            raw = base64.urlsafe_b64decode(row[1])
            value = json.loads(AESGCM(self.key).decrypt(raw[:12], raw[12:], self.name(key).encode()))
            if not isinstance(value, dict):
                raise ValueError()
            return row[0], value
        except Exception:
            raise YouTubeError('YOUTUBE_VAULT_INTEGRITY') from None

    async def write(self, key, revision, value):
        return await self.store.write(self.name(key), revision, self.seal(key, value))


class YouTube:
    def __init__(self, config: Config, vault: Vault, *, transport=None, clock=time.time):
        self.config, self.vault, self.clock = config, vault, clock
        self.transport = transport

    async def request(self, method, url, *, access=None, **kwargs):
        # No arbitrary destinations, redirect following, retries or raw error text.
        if url not in {TOKEN, API + 'channels', API + 'videos', THUMBNAIL}:
            raise YouTubeError('YOUTUBE_DESTINATION_REJECTED')
        headers = kwargs.pop('headers', {})
        if access:
            headers['Authorization'] = 'Bearer ' + access
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False,
                                         trust_env=False, transport=self.transport) as client:
                response = await client.request(method, url, headers=headers, **kwargs)
            if response.status_code == 412:
                raise YouTubeError('YOUTUBE_CONCURRENT_CHANGE')
            if response.status_code == 401:
                raise YouTubeError('YOUTUBE_REAUTH_REQUIRED')
            if response.status_code == 403:
                raise YouTubeError('YOUTUBE_PERMISSION_OR_QUOTA_DENIED')
            if response.status_code == 429:
                raise YouTubeError('YOUTUBE_RATE_LIMITED')
            if not 200 <= response.status_code < 300:
                if url == TOKEN and response.status_code == 400:
                    raise YouTubeError('YOUTUBE_REAUTH_REQUIRED')
                raise YouTubeError('YOUTUBE_PROVIDER_REJECTED')
            if len(response.content) > 2_000_000:
                raise YouTubeError('YOUTUBE_RESPONSE_TOO_LARGE')
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (httpx.HTTPError, ValueError):
            raise YouTubeError('YOUTUBE_RESPONSE_UNCONFIRMED') from None

    async def begin(self, browser_nonce: str):
        """Called ONLY after owner authentication in the system-browser handoff."""
        if not isinstance(browser_nonce, str) or len(browser_nonce) < 32:
            raise YouTubeError('YOUTUBE_BROWSER_BINDING_REQUIRED')
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        await self.vault.write('state:' + state, None, {
            'browser_hash': digest(browser_nonce), 'verifier': verifier,
            'expires': self.clock() + 600, 'used': False})
        return AUTH + '?' + urlencode({
            'client_id': self.config.client_id, 'redirect_uri': self.config.redirect_uri,
            'response_type': 'code', 'scope': SCOPE, 'access_type': 'offline',
            'prompt': 'consent select_account', 'state': state,
            'code_challenge': challenge, 'code_challenge_method': 'S256'})

    async def finish(self, state: str, code: str, browser_nonce: str):
        if (not isinstance(state, str) or not 32 <= len(state) <= 128
                or not isinstance(code, str) or not 1 <= len(code) <= 4096
                or not isinstance(browser_nonce, str) or len(browser_nonce) < 32):
            raise YouTubeError('YOUTUBE_CALLBACK_INVALID')
        row = await self.vault.read('state:' + state)
        if not row:
            raise YouTubeError('YOUTUBE_STATE_INVALID')
        revision, pending = row
        if (pending.get('used') is not False or pending.get('expires', 0) <= self.clock()
                or not hmac.compare_digest(pending.get('browser_hash', ''), digest(browser_nonce))):
            raise YouTubeError('YOUTUBE_STATE_INVALID')
        # Consume BEFORE code exchange. An uncertain callback is never replayed.
        await self.vault.write('state:' + state, revision, {'used': True})
        token = await self.request('POST', TOKEN, data={
            'client_id': self.config.client_id, 'client_secret': self.config.client_secret,
            'code': code, 'code_verifier': pending['verifier'],
            'grant_type': 'authorization_code', 'redirect_uri': self.config.redirect_uri})
        bundle = self.token_bundle(token)
        channels = await self.request('GET', API + 'channels', access=bundle['access_token'],
                                      params={'part': 'id,snippet', 'mine': 'true', 'maxResults': 50})
        items = channels.get('items', [])
        if not any(x.get('id') == self.config.channel_id for x in items):
            raise YouTubeError('YOUTUBE_WRONG_CHANNEL')
        prior = await self.vault.read('credentials')
        if not bundle['refresh_token']:
            bundle['refresh_token'] = prior[1].get('refresh_token', '') if prior else ''
        if not bundle['refresh_token']:
            raise YouTubeError('YOUTUBE_OFFLINE_CONSENT_REQUIRED')
        await self.vault.write('credentials', prior[0] if prior else None, bundle)
        return {'connected': True, 'channel_id': self.config.channel_id, 'scope': SCOPE}

    def token_bundle(self, token, previous_refresh=''):
        if (not isinstance(token.get('access_token'), str) or not token['access_token']
                or str(token.get('token_type', '')).lower() != 'bearer'
                or SCOPE not in str(token.get('scope', '')).split()):
            raise YouTubeError('YOUTUBE_SCOPE_OR_TOKEN_INVALID')
        try:
            seconds = int(token['expires_in'])
        except (KeyError, ValueError, TypeError):
            raise YouTubeError('YOUTUBE_TOKEN_LIFETIME_INVALID') from None
        if not 60 <= seconds <= 86400:
            raise YouTubeError('YOUTUBE_TOKEN_LIFETIME_INVALID')
        return {'access_token': token['access_token'],
                'refresh_token': token.get('refresh_token') or previous_refresh,
                'expires': self.clock() + seconds, 'scope': SCOPE}

    async def access(self):
        row = await self.vault.read('credentials')
        if not row:
            raise YouTubeError('YOUTUBE_NOT_CONNECTED')
        revision, token = row
        if token['expires'] > self.clock() + 60:
            return token['access_token']
        response = await self.request('POST', TOKEN, data={
            'client_id': self.config.client_id, 'client_secret': self.config.client_secret,
            'refresh_token': token['refresh_token'], 'grant_type': 'refresh_token'})
        # OAuth permits omission of scope on refresh; retain the previously granted scope.
        response.setdefault('scope', token['scope'])
        fresh = self.token_bundle(response, token['refresh_token'])
        await self.vault.write('credentials', revision, fresh)
        return fresh['access_token']

    async def video(self, video_id):
        if not isinstance(video_id, str) or not VIDEO.fullmatch(video_id):
            raise YouTubeError('YOUTUBE_VIDEO_ID_INVALID')
        data = await self.request('GET', API + 'videos', access=await self.access(),
                                  params={'part': 'snippet,status', 'id': video_id})
        items = data.get('items', [])
        if len(items) != 1 or items[0].get('id') != video_id:
            raise YouTubeError('YOUTUBE_VIDEO_NOT_FOUND')
        if items[0].get('snippet', {}).get('channelId') != self.config.channel_id:
            raise YouTubeError('YOUTUBE_WRONG_CHANNEL')
        return items[0]

    async def update(self, prepared, operation_id, approved_digest):
        if (not OPERATION.fullmatch(operation_id or '')
                or not hmac.compare_digest(digest(prepared), approved_digest or '')):
            raise YouTubeError('YOUTUBE_EXACT_APPROVAL_REQUIRED')
        key = 'operation:' + operation_id
        prior = await self.vault.read(key)
        if prior:
            if prior[1]['digest'] != approved_digest:
                raise YouTubeError('YOUTUBE_OPERATION_ID_REUSED')
            return {'executed': False, 'status': prior[1]['status']}
        # Validate the exact approved request again; do not accept arbitrary API bodies.
        current = await self.video(prepared['body']['id'])
        checked = prepare_update(current, prepared['patch'], self.config.channel_id,
                                 now=self.clock(), never_published=prepared['never_published'])
        if checked != prepared:
            raise YouTubeError('YOUTUBE_CONCURRENT_CHANGE')
        revision = await self.vault.write(key, None, {'digest': approved_digest, 'status': 'unverified'})
        await self.request('PUT', API + 'videos', access=await self.access(),
                           params={'part': prepared['part']}, json=prepared['body'],
                           headers={'If-Match': prepared['etag']})
        actual = await self.video(prepared['body']['id'])
        for part in prepared['part'].split(','):
            for key_name, value in prepared['body'][part].items():
                if actual.get(part, {}).get(key_name) != value:
                    raise YouTubeError('YOUTUBE_WRITE_READBACK_UNCONFIRMED')
        await self.vault.write(key, revision, {'digest': approved_digest, 'status': 'confirmed'})
        return {'executed': True, 'status': 'confirmed', 'video_id': actual['id']}


    async def verify_update(self, prepared, operation_id, approved_digest):
        """Read-only reconciliation after a timeout; NEVER resend the update."""
        if (not OPERATION.fullmatch(operation_id or '')
                or not hmac.compare_digest(digest(prepared), approved_digest or '')):
            raise YouTubeError('YOUTUBE_EXACT_APPROVAL_REQUIRED')
        row = await self.vault.read('operation:' + operation_id)
        if not row or row[1]['digest'] != approved_digest:
            raise YouTubeError('YOUTUBE_OPERATION_ID_REUSED')
        actual = await self.video(prepared['body']['id'])
        matches = all(actual.get(part, {}).get(k) == v
                      for part in prepared['part'].split(',')
                      for k, v in prepared['body'][part].items())
        if not matches:
            return {'verified': False, 'retry_allowed': False}
        await self.vault.write('operation:' + operation_id, row[0],
                               {'digest': approved_digest, 'status': 'confirmed'})
        return {'verified': True, 'executed': False, 'video_id': actual['id']}

    async def thumbnail(self, video_id, image: bytes, mime, operation_id, approved_digest):
        """Existing video only; provider acceptance is NOT exact-pixel verification."""
        if (not isinstance(image, bytes) or not 12 <= len(image) <= 2 * 1024 * 1024
                or mime not in {'image/png', 'image/jpeg'}
                or (mime == 'image/png' and not image.startswith(b'\x89PNG\r\n\x1a\n'))
                or (mime == 'image/jpeg' and not image.startswith(b'\xff\xd8\xff'))):
            raise YouTubeError('YOUTUBE_THUMBNAIL_INVALID')
        intent = {'video_id': video_id, 'channel_id': self.config.channel_id,
                  'sha256': hashlib.sha256(image).hexdigest(), 'mime': mime}
        if (not OPERATION.fullmatch(operation_id or '')
                or not hmac.compare_digest(digest(intent), approved_digest or '')):
            raise YouTubeError('YOUTUBE_EXACT_APPROVAL_REQUIRED')
        key = 'operation:' + operation_id
        row = await self.vault.read(key)
        if row:
            if row[1]['digest'] != approved_digest:
                raise YouTubeError('YOUTUBE_OPERATION_ID_REUSED')
            return {'executed': False, 'status': row[1]['status']}
        await self.video(video_id)
        revision = await self.vault.write(key, None, {'digest': approved_digest, 'status': 'unverified'})
        result = await self.request('POST', THUMBNAIL, access=await self.access(),
                                    params={'videoId': video_id}, content=image,
                                    headers={'Content-Type': mime})
        if not isinstance(result.get('items'), list) or not result['items']:
            raise YouTubeError('YOUTUBE_THUMBNAIL_RECEIPT_UNCONFIRMED')
        await self.vault.write(key, revision, {'digest': approved_digest, 'status': 'accepted'})
        return {'executed': True, 'status': 'accepted', 'video_id': video_id,
                'content_verified': False}


def prepare_update(video, patch, channel_id, *, now=None, never_published=False):
    """Read/merge/write only explicitly approved fields, preserving other values."""
    if (not isinstance(patch, dict) or not patch or set(patch) - EDITABLE
            or not VIDEO.fullmatch(video.get('id', '')) or not video.get('etag')
            or video.get('snippet', {}).get('channelId') != channel_id):
        raise YouTubeError('YOUTUBE_UPDATE_INVALID')
    if 'title' in patch and (not isinstance(patch['title'], str)
                            or not 1 <= len(patch['title']) <= 100
                            or any(c in patch['title'] for c in '<>')):
        raise YouTubeError('YOUTUBE_TITLE_INVALID')
    if 'description' in patch and (not isinstance(patch['description'], str)
                                   or len(patch['description'].encode()) > 5000
                                   or any(c in patch['description'] for c in '<>')):
        raise YouTubeError('YOUTUBE_DESCRIPTION_INVALID')
    if 'tags' in patch:
        tags = patch['tags']
        if (not isinstance(tags, list) or any(not isinstance(t, str) or not t for t in tags)
                or sum(len(t) + (2 if ' ' in t else 0) for t in tags) + max(0, len(tags)-1) > 500):
            raise YouTubeError('YOUTUBE_TAGS_INVALID')
    if 'privacyStatus' in patch and patch['privacyStatus'] not in {'private', 'public', 'unlisted'}:
        raise YouTubeError('YOUTUBE_PRIVACY_INVALID')
    body = {'id': video['id']}
    for part, allowed in (('snippet', SNIPPET), ('status', STATUS)):
        changes = {k: v for k, v in patch.items() if k in allowed}
        if changes:
            body[part] = {k: copy.deepcopy(v) for k, v in video.get(part, {}).items() if k in allowed}
            body[part].update(copy.deepcopy(changes))
    if 'snippet' in body and not all(body['snippet'].get(k) for k in ('title', 'categoryId')):
        raise YouTubeError('YOUTUBE_INCOMPLETE_SNIPPET')
    if 'status' in body and 'privacyStatus' not in body['status']:
        raise YouTubeError('YOUTUBE_INCOMPLETE_STATUS')
    if 'publishAt' in patch:
        if (never_published is not True or video.get('status', {}).get('privacyStatus') != 'private'
                or patch.get('privacyStatus') != 'private'):
            raise YouTubeError('YOUTUBE_SCHEDULE_REQUIRES_UNPUBLISHED_PRIVATE')
        try:
            dt = datetime.fromisoformat(patch['publishAt'].replace('Z', '+00:00'))
            if dt.tzinfo is None or dt.timestamp() <= (time.time() if now is None else now):
                raise ValueError()
        except (AttributeError, ValueError, TypeError):
            raise YouTubeError('YOUTUBE_SCHEDULE_INVALID') from None
        body['status']['publishAt'] = dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    elif 'status' in body and body['status'].get('publishAt'):
        # A privacy change can cancel an existing schedule; require a separate explicit workflow.
        raise YouTubeError('YOUTUBE_EXISTING_SCHEDULE_REVIEW_REQUIRED')
    return {'body': body, 'part': ','.join(p for p in ('snippet', 'status') if p in body),
            'etag': video['etag'], 'patch': copy.deepcopy(patch), 'never_published': never_published}
