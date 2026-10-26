"""Owner-beta Meta reply preview contract; never logs in or publishes.

Bindings and observations are PRIVATE, supplied by the authorized operator
from current browser readback. Client booleans are not authentication proof.
The existing aib_task journal, not this pure planner, fences actual writes.
"""
from __future__ import annotations
import hashlib
import json
import re
import time
from urllib.parse import urlsplit


class MetaCommandError(ValueError):
    pass


ORDINALS = {'pierwszy': 1, 'drugi': 2, 'trzeci': 3, 'czwarty': 4,
            'piąty': 5, 'piaty': 5, 'szósty': 6, 'szosty': 6,
            'siódmy': 7, 'siodmy': 7, 'ósmy': 8, 'osmy': 8,
            'dziewiąty': 9, 'dziesiąty': 10}


def parse_command(command):
    if not isinstance(command, str) or not 1 <= len(command) <= 1000:
        raise MetaCommandError('META_COMMAND_INVALID')
    pattern = (r'użyj konta meta ([1-9]|10),? znajdź '
               r'([1-9][0-9]?|pierwszy|drugi|trzeci|czwarty|piąty|piaty|szósty|szosty|'
               r'siódmy|siodmy|ósmy|osmy|dziewiąty|dziesiąty) wpis '
               r'w (?:wybranej grupie(?: spotted)?|grupie spotted),? przygotuj odpowiedź '
               r'i pokaż ją do publikacji[.!]?')
    match = re.fullmatch(pattern, ' '.join(command.casefold().split()))
    if match is None:
        raise MetaCommandError('META_COMMAND_AMBIGUOUS_OR_UNSUPPORTED')
    number = match[2]
    return {'alias': int(match[1]), 'post_ordinal': int(number) if number.isdigit() else ORDINALS[number],
            'action': 'reply_preview', 'publish_allowed': False,
            'requires_exact_group': True, 'requires_current_identity': True}


def canonical_post(url, group_id):
    try:
        p = urlsplit(url)
        if (p.scheme != 'https' or p.hostname not in {'www.facebook.com', 'facebook.com', 'm.facebook.com'}
            or p.port is not None or p.username is not None or p.password is not None
            or p.query or p.fragment):
            raise ValueError()
        match = re.fullmatch(r'/groups/([0-9]{1,30})/(?:posts|permalink)/([0-9]{1,30})/?', p.path)
        if match is None or match[1] != group_id: raise ValueError()
        return f'https://www.facebook.com/groups/{match[1]}/posts/{match[2]}/'
    except (ValueError, TypeError, AttributeError):
        raise MetaCommandError('META_EXACT_POST_REQUIRED') from None


def _identity(binding, observation, now):
    if (not isinstance(binding, dict) or binding.get('authorized') is not True
        or not all(isinstance(binding.get(k), str) and binding[k] for k in ('profile','identity_id','owner_label'))):
        raise MetaCommandError('META_PRIVATE_BINDING_REQUIRED')
    if observation.get('authenticated') is not True:
        raise MetaCommandError('META_AUTHENTICATION_REQUIRED')
    if observation.get('profile') != binding['profile'] or observation.get('identity_id') != binding['identity_id']:
        raise MetaCommandError('META_IDENTITY_MISMATCH')
    age = observation.get('observed_at')
    if type(age) not in (float, int) or not 0 <= now-age <= 300:
        raise MetaCommandError('META_FRESH_READBACK_REQUIRED')
    if observation.get('membership_verified') is not True or observation.get('can_comment') is not True:
        raise MetaCommandError('META_GROUP_PERMISSION_UNCONFIRMED')


def digest(preview):
    data = {k: preview[k] for k in ('alias','profile','identity_id','owner_label','group_id','post_url','text')}
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def prepare_preview(command, bindings, observation, text, *, now=None):
    """Trusted agent only. Evidence and resulting preview stay outside public repo."""
    parsed = parse_command(command)
    if not isinstance(bindings, dict) or not isinstance(observation, dict):
        raise MetaCommandError('META_PRIVATE_BINDING_REQUIRED')
    binding = bindings.get(parsed['alias'])
    now = time.time() if now is None else now
    _identity(binding, observation, now)
    group_id = observation.get('group_id')
    if not isinstance(group_id, str) or not re.fullmatch(r'[0-9]{1,30}', group_id):
        raise MetaCommandError('META_EXACT_GROUP_REQUIRED')
    # Ordinal is frozen against one explicit ordered readback, never reselected
    # from a changing feed after approval. Duplicate/missing links fail closed.
    posts = observation.get('ordered_post_urls')
    if not isinstance(posts, list) or not 1 <= len(posts) <= 100:
        raise MetaCommandError('META_ORDERED_POSTS_REQUIRED')
    urls = [canonical_post(url, group_id) for url in posts]
    if len(set(urls)) != len(urls) or parsed['post_ordinal'] > len(urls):
        raise MetaCommandError('META_POST_ORDINAL_UNCONFIRMED')
    if not isinstance(text, str) or not text.strip() or len(text) > 10000:
        raise MetaCommandError('META_REPLY_TEXT_REQUIRED')
    preview = {**parsed, **{k:binding[k] for k in ('profile','identity_id','owner_label')},
               'group_id':group_id, 'post_url':urls[parsed['post_ordinal']-1], 'text':text}
    preview['approval_digest'] = digest(preview)
    preview['operation_id'] = 'meta-reply-' + preview['approval_digest']
    preview['status'] = 'awaiting_exact_approval'
    return preview


def authorize_preview(preview, binding, fresh, approved_digest, *, now=None):
    """Return journal metadata only. Caller must begin -> write once -> readback.

    Fresh identity and group permission must come from current protected UI;
    changing identity, content or post invalidates the previous approval.
    """
    if approved_digest != digest(preview) or preview.get('approval_digest') != approved_digest:
        raise MetaCommandError('META_EXACT_APPROVAL_REQUIRED')
    _identity(binding, fresh, time.time() if now is None else now)
    if (any(preview.get(k) != binding[k] for k in ('profile','identity_id','owner_label'))
        or fresh.get('group_id') != preview['group_id']
        or canonical_post(fresh.get('post_url'),preview['group_id']) != preview['post_url']):
        raise MetaCommandError('META_APPROVED_TARGET_CHANGED')
    expected_id = 'meta-reply-' + approved_digest
    if preview.get('operation_id') != expected_id:
        raise MetaCommandError('META_OPERATION_ID_INVALID')
    return {'operation_id':expected_id, 'post_url':preview['post_url'],
            'identity_id':binding['identity_id'], 'approval_digest':approved_digest,
            'next_action':'aib_task_begin_before_any_write', 'published':False}


def verify_publication(preview, receipt):
    """A click acknowledgement or same text elsewhere cannot confirm publication."""
    if not isinstance(receipt, dict): return False
    try:
        return (receipt.get('identity_id') == preview['identity_id']
            and receipt.get('text') == preview['text']
            and receipt.get('observed_after_reload') is True
            and canonical_post(receipt.get('post_url'),preview['group_id']) == preview['post_url']
            and isinstance(receipt.get('comment_id'),str)
            and re.fullmatch(r'[0-9]{1,40}',receipt['comment_id']) is not None)
    except MetaCommandError:
        return False
