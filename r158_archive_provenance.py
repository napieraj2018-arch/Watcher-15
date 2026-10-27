"""Read-only private-vault-only archival coherence evidence for neutral R158.

The owner-trusted vault runtime (not ChatGPT or GitHub) must decrypt only
authorized protected historical rows. Never export plaintext, cookie values,
state hashes or credentials. This module has no network/DB/decrypt/save logic.
Its output contains only bounded booleans/counts; archived-state agreement
is NOT proof of live restoration, login, or present-day cookie validity.
"""
from __future__ import annotations

from dataclasses import dataclass
import hmac
import math
from typing import Any
from urllib.parse import unquote

PROFILE = "Acceptance-20261023-R158"
ORIGIN = "https://ai-browser-vault.floot.app"
HOST = "ai-browser-vault.floot.app"
COOKIE = "aibrowser_test_cookie"
COOKIE_PATH = "/browser-check"
LOCAL_KEY = "aibrowser_public_test_marker"
MAX_VERSIONS = 64


class R158EvidenceError(ValueError):
    """Return only fixed error codes, not source data."""


@dataclass(frozen=True)
class IndexedSelector:
    """Use exact verified private fixture schema, never wildcards."""
    database: str
    store: str
    key: str
    value_path: tuple[str, ...] = ()

    def __post_init__(self):
        if any(not isinstance(x, str) or not x or len(x) > 128
               for x in (self.database, self.store, self.key, *self.value_path)):
            raise R158EvidenceError("R158_INDEX_SELECTOR_INVALID")
        if len(self.value_path) > 4:
            raise R158EvidenceError("R158_INDEX_SELECTOR_INVALID")

# Exact IndexedDB structure verified from owner Floot pages/browser-check.tsx.
R158_SELECTOR = IndexedSelector(database="aibrowser_neutral_check",
                                store="markers", key="marker")


def _items(value: Any) -> list:
    return value if isinstance(value, list) and len(value) <= 1024 else []


def _one(items: list[dict], predicate) -> tuple[Any, bool]:
    matches = [x for x in _items(items) if isinstance(x, dict) and predicate(x)]
    return (matches[0], True) if len(matches) == 1 else (None, False)


def _value(value: Any) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= 2048 else None


def _extract(state: Any, selector: IndexedSelector):
    if not isinstance(state, dict):
        raise R158EvidenceError("R158_SNAPSHOT_SCHEMA_INVALID")
    cookie, cookie_unique = _one(
        state.get("cookies"), lambda c: (
            c.get("name") == COOKIE and isinstance(c.get("domain"), str)
            and c["domain"].lstrip(".").lower() == HOST
            and c.get("path") == COOKIE_PATH))
    origin, origin_unique = _one(
        state.get("origins"), lambda o: o.get("origin") == ORIGIN)
    local = db = store = record = None
    local_unique = db_unique = store_unique = record_unique = False
    if origin_unique:
        local, local_unique = _one(
            origin.get("localStorage"), lambda x: x.get("name") == LOCAL_KEY)
        db, db_unique = _one(
            origin.get("indexedDB"), lambda x: x.get("name") == selector.database)
    if db_unique:
        store, store_unique = _one(
            db.get("stores"), lambda x: x.get("name") == selector.store)
    if store_unique:
        record, record_unique = _one(
            store.get("records"), lambda x: x.get("key") == selector.key)
    indexed = record.get("value") if record_unique else None
    if record_unique:
        for field in selector.value_path:
            if not isinstance(indexed, dict):
                indexed = None
                break
            indexed = indexed.get(field)
    values = (_value(cookie.get("value")) if cookie_unique else None,
              _value(local.get("value")) if local_unique else None,
              _value(indexed))
    unique = bool(cookie_unique and origin_unique and local_unique
                  and db_unique and store_unique and record_unique)
    return values, unique, cookie if cookie_unique else None


def _cookie_fresh(cookie: dict | None, when: float) -> bool | None:
    if cookie is None:
        return False
    if cookie.get("httpOnly") is not False or cookie.get("secure") is not True:
        return False
    expiry = cookie.get("expires")
    if expiry == -1:
        return None  # Session cookie: archive cannot certify future persistence.
    if not isinstance(expiry, (int, float)) or isinstance(expiry, bool) or not math.isfinite(expiry):
        return False
    return bool(expiry > when)


def compare_protected_candidate(*, profile: str, source_updated_at: float,
                                decrypted_state: dict, selector: IndexedSelector,
                                observed_at: float) -> dict[str, bool | None]:
    """Inspect exact R158 candidate in trusted process; never output values."""
    if profile != PROFILE:
        raise R158EvidenceError("R158_PROFILE_SCOPE_DENIED")
    if selector != R158_SELECTOR:
        raise R158EvidenceError("R158_INDEX_SELECTOR_INVALID")
    if (not isinstance(selector, IndexedSelector)
            or not isinstance(source_updated_at, (int, float)) or isinstance(source_updated_at, bool)
            or not isinstance(observed_at, (int, float)) or isinstance(observed_at, bool)
            or not math.isfinite(source_updated_at) or not math.isfinite(observed_at)
            or observed_at < source_updated_at):
        raise R158EvidenceError("R158_TIME_OR_SELECTOR_INVALID")
    (c, l, d), unique, cookie = _extract(decrypted_state, selector)
    present = (c is not None, l is not None, d is not None)
    equal = bool(unique and all(present)
                 and hmac.compare_digest(c, l) and hmac.compare_digest(c, d))
    encoded_equal = bool(unique and all(present) and unquote(c) == l == d)
    valid_at_archive = _cookie_fresh(cookie, source_updated_at)
    valid_now = _cookie_fresh(cookie, observed_at)
    return {
        "cookie_present": present[0],
        "local_storage_present": present[1],
        "indexed_db_present": present[2],
        "unique_exact_source": unique,
        "exact_three_store_equal": equal,
        "decoded_cookie_equal_only": bool(encoded_equal and not equal),
        "cookie_valid_at_source": valid_at_archive,
        "cookie_valid_now": valid_now,
        "coherent_at_source": bool(equal and valid_at_archive is True),
        "live_saved_close_reopen_verified": False,
        "real_account_authenticated": False,
    }


def compare_protected_batch(candidates: list[dict], *, selector: IndexedSelector,
                            observed_at: float) -> dict[str, int | bool]:
    """Aggregate only owner-vetted source-identical protected rows, no IDs.

    The trusted caller MUST verify each row's protected provenance and equality
    to its archived encrypted source before calling. Do not expose its input.
    """
    if not isinstance(candidates, list) or len(candidates) > MAX_VERSIONS:
        raise R158EvidenceError("R158_BATCH_SIZE_INVALID")
    counts = {"candidate_count": 0, "coherent_at_source_count": 0,
              "currently_valid_coherent_count": 0,
              "unknown_cookie_lifetime_count": 0,
              "invalid_or_ambiguous_count": 0, "live_verified": False}
    for row in candidates:
        if not isinstance(row, dict) or row.get("protected") is not True:
            raise R158EvidenceError("R158_UNPROTECTED_CANDIDATE_DENIED")
        proof = compare_protected_candidate(
            profile=row.get("profile"), source_updated_at=row.get("source_updated_at"),
            decrypted_state=row.get("state"), selector=selector, observed_at=observed_at)
        counts["candidate_count"] += 1
        if proof["coherent_at_source"]:
            counts["coherent_at_source_count"] += 1
            if proof["cookie_valid_now"] is True:
                counts["currently_valid_coherent_count"] += 1
        if proof["cookie_valid_now"] is None:
            counts["unknown_cookie_lifetime_count"] += 1
        if not proof["unique_exact_source"] or not proof["exact_three_store_equal"]:
            counts["invalid_or_ambiguous_count"] += 1
    return counts
