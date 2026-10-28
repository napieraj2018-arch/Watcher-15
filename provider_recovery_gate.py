"""Read-only provider reconciliation before admitting browser work after maintenance.

The incident and protected-backup fingerprint live in the owner's private vault.
No keys, provider URLs or identifiers are logged. A failed gate prevents startup;
no provider session is created, released or changed by this module.
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import uuid
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

VAULT = 'https://ai-browser-vault.floot.app/_api/provider-recovery'
STEEL = 'https://api.steel.dev/v1'
MAX_PAGES = 100
MAX_RESPONSE = 2_000_000
MIN_RATE_LIMIT_WAIT = 900
MAX_RATE_LIMIT_WAIT = 604800  # one week: fail closed on an unusually long provider pause


def retry_after_seconds(value, *, now=None):
    """Parse bounded HTTP Retry-After without logging or exposing provider details."""
    if not isinstance(value, str) or not (1 <= len(value) <= 96):
        return MIN_RATE_LIMIT_WAIT
    raw = value.strip()
    seconds = None
    if raw.isascii() and raw.isdecimal():
        try:
            seconds = int(raw)
        except ValueError:
            pass
    else:
        try:
            deadline = parsedate_to_datetime(raw)
            if deadline.tzinfo is None:
                return MIN_RATE_LIMIT_WAIT
            clock = now if now is not None else datetime.now(timezone.utc)
            if clock.tzinfo is None:
                return MIN_RATE_LIMIT_WAIT
            seconds = math.ceil((deadline - clock).total_seconds())
        except (TypeError, ValueError, OverflowError):
            pass
    if seconds is None or seconds <= 0:
        return MIN_RATE_LIMIT_WAIT
    return max(MIN_RATE_LIMIT_WAIT, min(MAX_RATE_LIMIT_WAIT, seconds))


class RecoveryGateError(RuntimeError):
    """Static codes only."""


class RecoveryRateLimited(RecoveryGateError):
    """Typed HTTP 429; caller may wait but must never admit an unverified browser."""

    def __init__(self, wait_seconds=MIN_RATE_LIMIT_WAIT):
        self.retry_after_seconds = retry_after_seconds(str(wait_seconds))
        super().__init__("RECOVERY_HTTP_429")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def fixed_uuid(value):
    try:
        result = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise RecoveryGateError('RECOVERY_INVALID_BINDING') from None
    if result != value:
        raise RecoveryGateError('RECOVERY_INVALID_BINDING')
    return result


def timestamp(value):
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if d.tzinfo is None:
            raise ValueError()
        return d.timestamp()
    except (ValueError, TypeError, AttributeError):
        raise RecoveryGateError('RECOVERY_INVALID_TIMESTAMP') from None


class RecoveryGate:
    def __init__(self, client, store_token, steel_key):
        if not store_token or not steel_key:
            raise RecoveryGateError('RECOVERY_CREDENTIALS_NOT_CONFIGURED')
        self.client = client
        self.store_headers = {'authorization': 'Bearer ' + store_token}
        self.steel_headers = {'steel-api-key': steel_key}

    def request(self, method, url, **kwargs):
        if not (url == VAULT or url.startswith(STEEL + '/')):
            raise RecoveryGateError('RECOVERY_DESTINATION_INVALID')
        try:
            response = self.client.request(method, url, follow_redirects=False, **kwargs)
        except (httpx.HTTPError, OSError):
            raise RecoveryGateError('RECOVERY_CONNECTION_UNCONFIRMED') from None
        if response.status_code == 429:
            raise RecoveryRateLimited(retry_after_seconds(
                response.headers.get("Retry-After"))) from None
        if response.status_code != 200:
            raise RecoveryGateError('RECOVERY_HTTP_' + str(response.status_code))
        if len(response.content) > MAX_RESPONSE:
            raise RecoveryGateError('RECOVERY_RESPONSE_TOO_LARGE')
        try:
            value = response.json()
        except ValueError:
            raise RecoveryGateError('RECOVERY_RESPONSE_INVALID') from None
        if not isinstance(value, dict):
            raise RecoveryGateError('RECOVERY_RESPONSE_INVALID')
        return value

    def inspect(self):
        return self.request('POST', VAULT, headers=self.store_headers,
                            json={'action': 'inspect'})

    def steel(self, path, **kwargs):
        return self.request('GET', STEEL + path, headers=self.steel_headers, **kwargs)

    def exact(self, plan):
        value = self.steel('/sessions/' + fixed_uuid(plan['session_id']))
        if (value.get('id') != plan['session_id']
                or value.get('profileId') != plan['profile_id']
                or value.get('status') != 'released'
                or value.get('persistProfile') is not True):
            raise RecoveryGateError('RECOVERY_EXACT_SESSION_NOT_VERIFIED')
        if not timestamp(plan['window_start']) <= timestamp(value.get('createdAt')) <= timestamp(plan['window_end']):
            raise RecoveryGateError('RECOVERY_EXACT_SESSION_TIME_MISMATCH')
        return value

    def inventory(self, plan):
        cursor = None
        seen = set()
        summaries = []
        found = False
        for _ in range(MAX_PAGES):
            params = {'limit': 100}
            if cursor:
                params['cursorId'] = cursor
            value = self.steel('/sessions', params=params)
            rows = value.get('sessions')
            if not isinstance(rows, list) or len(rows) > 100:
                raise RecoveryGateError('RECOVERY_INVENTORY_INVALID')
            if not rows:
                if not found:
                    raise RecoveryGateError('RECOVERY_EXACT_SESSION_NOT_IN_INVENTORY')
                return summaries
            for row in rows:
                if not isinstance(row, dict):
                    raise RecoveryGateError('RECOVERY_INVENTORY_INVALID')
                sid = fixed_uuid(row.get('id'))
                state = row.get('status')
                if sid in seen:
                    raise RecoveryGateError('RECOVERY_INVENTORY_PAGINATION_CONFLICT')
                if state not in {'released', 'failed'}:
                    raise RecoveryGateError('RECOVERY_ACTIVE_OR_UNKNOWN_PROVIDER_SESSION')
                if sid == plan['session_id']:
                    if state != 'released':
                        raise RecoveryGateError('RECOVERY_EXACT_SESSION_NOT_VERIFIED')
                    found = True
                seen.add(sid)
                summaries.append([sid, state])
            cursor = fixed_uuid(rows[-1]['id'])
        raise RecoveryGateError('RECOVERY_INVENTORY_LIMIT_REACHED')

    def run(self):
        before = self.inspect()
        if before.get('ok') is not True or type(before.get('pending')) is not bool:
            raise RecoveryGateError('RECOVERY_GATE_STATE_INVALID')
        if before['pending'] is False:
            return {'status': 'no_pending_gate', 'verified_this_boot': False}
        plan = before.get('gate')
        if not isinstance(plan, dict) or plan.get('version') != 1:
            raise RecoveryGateError('RECOVERY_GATE_STATE_INVALID')
        for key in ('gate_id', 'session_id', 'profile_id'):
            fixed_uuid(plan.get(key))
        if before.get('local', {}).get('safe') is not True:
            raise RecoveryGateError('RECOVERY_LOCAL_BACKUP_OR_TASK_STATE_CHANGED')
        self.exact(plan)
        profile = self.steel('/profiles/' + plan['profile_id'])
        if (profile.get('id', plan['profile_id']) != plan['profile_id']
                or str(profile.get('status', profile.get('state', ''))).upper() != 'READY'):
            raise RecoveryGateError('RECOVERY_NATIVE_PROFILE_NOT_READY')
        inventory = self.inventory(plan)
        current = self.steel('/sessions', params={'status': 'live', 'limit': 100})
        if current.get('sessions') != []:
            raise RecoveryGateError('RECOVERY_PROVIDER_CHANGED_DURING_CHECK')
        self.exact(plan)
        after = self.inspect()
        if (after.get('pending') is not True or after.get('gate') != plan
                or after.get('local', {}).get('safe') is not True):
            raise RecoveryGateError('RECOVERY_LOCAL_STATE_CHANGED_DURING_CHECK')
        proof = {'exact_session_released': True, 'profile_ready': True,
                 'inventory_complete': True, 'live_sessions': 0,
                 'inventory_total': len(inventory),
                 'evidence_sha256': hashlib.sha256(canonical({
                    'gate': plan, 'sessions': inventory,
                    'local': after['local']}).encode()).hexdigest()}
        receipt = self.request('POST', VAULT, headers=self.store_headers,
                               json={'action': 'attest', 'gate_id': plan['gate_id'], 'proof': proof})
        if not (receipt.get('ok') is True and receipt.get('verified') is True
                and receipt.get('pending') is False and receipt.get('gate_id') == plan['gate_id']):
            raise RecoveryGateError('RECOVERY_RECEIPT_UNCONFIRMED')
        return {'status': 'verified', 'verified_this_boot': True,
                'inventory_total': len(inventory), 'live_sessions': 0,
                'protected_profiles': after['local']['profile_count']}


def run_boot_gate():
    if os.environ.get('AI_BROWSER_ENGINE', '').lower() != 'steel':
        return
    previous = logging.getLogger('httpx').level
    logging.getLogger('httpx').setLevel(logging.WARNING)
    try:
        with httpx.Client(timeout=httpx.Timeout(15, connect=8)) as client:
            result = RecoveryGate(client, os.environ.get('AI_BROWSER_PROFILE_STORE_TOKEN', ''),
                                  os.environ.get('STEEL_API_KEY', '').strip()).run()
        print('AI_BROWSER_RECOVERY_GATE ' + canonical(result), flush=True)
    except RecoveryRateLimited:
        print('AI_BROWSER_RECOVERY_GATE_BLOCKED RECOVERY_HTTP_429', flush=True)
        raise
    except RecoveryGateError as exc:
        print('AI_BROWSER_RECOVERY_GATE_BLOCKED ' + str(exc), flush=True)
        if str(exc) == 'RECOVERY_HTTP_429':
            raise RecoveryRateLimited() from None
        raise RuntimeError('AI_BROWSER_RECOVERY_GATE_BLOCKED') from None
    except Exception:
        print('AI_BROWSER_RECOVERY_GATE_BLOCKED RECOVERY_UNEXPECTED_STATE', flush=True)
        raise RuntimeError('AI_BROWSER_RECOVERY_GATE_BLOCKED') from None
    finally:
        logging.getLogger('httpx').setLevel(previous)
