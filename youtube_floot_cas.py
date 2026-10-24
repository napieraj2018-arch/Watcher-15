"""Fail-closed future CAS client for an owner-only Floot OAuth credential endpoint.

This DOES NOT create or change any Floot project/database. The endpoint
must exist, be independently authenticated, and implement the documented
atomic CAS protocol before this client may be used in production.

There is deliberately no fallback to task-vault, profile-vault or local files.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re

import httpx

URL = 'https://ai-browser-vault.floot.app/_api/youtube-oauth-vault'
KEY = re.compile(r'^youtube-v1:[a-f0-9]{64}:[a-f0-9]{64}$')
MAX_ENVELOPE = 150000


class CASUnconfirmed(RuntimeError):
    pass


def secret(master: str, label: str) -> bytes:
    if not isinstance(master, str) or len(master.encode()) < 32:
        raise CASUnconfirmed('YOUTUBE_MASTER_KEY_REQUIRED')
    return hmac.new(master.encode(), label.encode(), hashlib.sha256).digest()


class FlootOAuthCAS:
    """Client of a new PRIVATE Floot vault namespace, not an existing API.

    Server contract:
    POST https://ai-browser-vault.floot.app/_api/youtube-oauth-vault
    Authorization: Bearer <derived server token>
    GET JSON {action:'get', key}; response 200 {found,revision,envelope}
    PUT JSON {action:'put', key, expectedRevision: number|null, envelope};
      response 200 {revision: number}. Server must atomically INSERT for null,
      otherwise UPDATE ... WHERE revision=expectedRevision and return 409 on
      contention. Owner binding is enforced by the server, not caller JSON.
    Delete/scan/export MUST NOT be exposed by this client.
    """
    durable = True  # Protocol compatibility only, NOT evidence of a real server.

    def __init__(self, master: str, *, transport=None):
        raw = secret(master, 'youtube-floot-cas-bearer-v1')
        self._token = raw.hex()
        self._transport = transport

    async def _call(self, payload):
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=False,
                                         trust_env=False, transport=self._transport) as c:
                r = await c.post(URL, json=payload,
                    headers={'Authorization': 'Bearer ' + self._token,
                             'Content-Type': 'application/json',
                             'Cache-Control': 'no-store'})
            if r.status_code == 409:
                raise CASUnconfirmed('YOUTUBE_CAS_CONFLICT')
            if r.status_code in {401,403}:
                raise CASUnconfirmed('YOUTUBE_CAS_UNAUTHORIZED')
            if r.status_code != 200:
                raise CASUnconfirmed('YOUTUBE_CAS_UNAVAILABLE')
            if len(r.content) > 200000:
                raise CASUnconfirmed('YOUTUBE_CAS_RESPONSE_TOO_LARGE')
            data = r.json()
            if not isinstance(data, dict):
                raise ValueError('invalid payload')
            return data
        except (httpx.HTTPError, ValueError):
            raise CASUnconfirmed('YOUTUBE_CAS_UNCONFIRMED') from None

    @staticmethod
    def valid_key(key):
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise CASUnconfirmed('YOUTUBE_CAS_INVALID_KEY')
        return key

    async def read(self, key):
        key = self.valid_key(key)
        r = await self._call({'action': 'get', 'key': key})
        if r.get('found') is False:
            return None
        rev, envelope = r.get('revision'), r.get('envelope')
        if (r.get('found') is not True or not isinstance(rev, int) or isinstance(rev, bool)
                or rev < 1 or not isinstance(envelope, str)
                or not 1 <= len(envelope) <= MAX_ENVELOPE):
            raise CASUnconfirmed('YOUTUBE_CAS_RESPONSE_INVALID')
        return rev, envelope

    async def write(self, key, expected, envelope):
        key = self.valid_key(key)
        if ((expected is not None and (not isinstance(expected, int)
                                      or isinstance(expected, bool) or expected < 1))
                or not isinstance(envelope, str)
                or not 1 <= len(envelope) <= MAX_ENVELOPE):
            raise CASUnconfirmed('YOUTUBE_CAS_INVALID_WRITE')
        result = await self._call({'action': 'put', 'key': key,
                                   'expectedRevision': expected, 'envelope': envelope})
        rev = result.get('revision')
        if (not isinstance(rev, int) or isinstance(rev, bool)
                or rev != (expected + 1 if expected else 1)):
            raise CASUnconfirmed('YOUTUBE_CAS_WRITE_UNCONFIRMED')
        return rev


def build_owner_vault(master, mcp_token, config, *, transport=None):
    """Separate key hierarchy for OAuth. Does not touch Floot's current vault."""
    from youtube_oauth import Vault
    if not isinstance(mcp_token, str) or len(mcp_token) < 32:
        raise CASUnconfirmed('YOUTUBE_OWNER_TOKEN_REQUIRED')
    owner = hashlib.sha256(mcp_token.encode()).hexdigest()
    return Vault(FlootOAuthCAS(master, transport=transport),
                 secret(master, 'youtube-aesgcm-data-v1'), owner, config)
