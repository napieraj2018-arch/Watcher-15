"""Read-only Facebook group pilot adapter for the existing Watcher-15.

Consumes *already authorized* post evidence, records candidate questions that
an individual account holder may choose to answer, and deduplicates them locally.
It does not compose company-branded replies or comments in a patient's voice,
login, fetch a group, call Meta APIs, publish or impersonate people.
No private post body/author is persisted or echoed in output. Production
requires an authenticated ingestion adapter and private durable database;
SQLite here is a functional pilot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

GROUP_ID = "3046642772082014"
PROFILE = "Watcher - Operator - Pilot"
MAX_POSTS = 30
MAX_AGE = timedelta(hours=48)
MAX_TEXT_CHARS = 6000
TRIGGERS = {
    "chirurgia": ("operacj", "chirurg", "zabieg", "sterylizacj"),
    "okulistyka": ("oko", "ocz", "rogówk", "okulist"),
    "ortopedia": ("kulaw", "łap", "staw", "ortoped"),
    "diagnostyka": ("rtg", "usg", "tomograf", "badani", "rezonans"),
    "weterynaria": ("weterynarz", "weteryn", "lekarza dla psa", "lekarza dla kota"),
}
ASK_MARKERS = ("?", "szukam", "poleci", "doradzi", "gdzie", "czy ktoś", "kogo", "potrzebuj", "pomoc")
URGENT_MARKERS = ("duszno", "nie oddych", "krwawi", "drgawk", "połkn", "wymiotuje krwią")
EXCLUDE = ("sprzedam", "oddam za darmo", "szukam pracy", "kupię", "kupię psa")
ALLOWED_STATES = {"ok", "partial", "authentication_required", "source_unavailable"}


class PilotInputError(ValueError):
    """Stable public error code; no private input is included in messages."""


def parse_time(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise PilotInputError("INVALID_TIMESTAMP")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PilotInputError("INVALID_TIMESTAMP") from None
    if instant.tzinfo is None:
        raise PilotInputError("TIMESTAMP_MUST_HAVE_OFFSET")
    return instant.astimezone(timezone.utc)


def canonical_group_post(url: object) -> tuple[str, str]:
    if not isinstance(url, str) or len(url) > 300:
        raise PilotInputError("INVALID_POST_URL")
    try:
        parts = urlsplit(url)
    except ValueError:
        raise PilotInputError("INVALID_POST_URL") from None
    if (parts.scheme != "https" or parts.hostname not in ("www.facebook.com", "m.facebook.com")
            or parts.port not in (None, 443) or parts.username or parts.password
            or parts.query or parts.fragment):
        raise PilotInputError("UNTRUSTED_POST_URL")
    match = re.fullmatch(rf"/groups/{GROUP_ID}/(?:posts|permalink)/(\d{{5,25}})/?", parts.path)
    if not match:
        raise PilotInputError("POST_OUTSIDE_PILOT_GROUP")
    post_id = match.group(1)
    return post_id, f"https://www.facebook.com/groups/{GROUP_ID}/posts/{post_id}/"


def topic_for(text: object) -> tuple[str, str] | None:
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
        raise PilotInputError("INVALID_POST_TEXT")
    lower = " ".join(text.casefold().split())
    if any(word in lower for word in EXCLUDE):
        return None
    if not any(word in lower for word in ASK_MARKERS):
        return None
    urgent = any(word in lower for word in URGENT_MARKERS)
    for topic, words in TRIGGERS.items():
        if any(word in lower for word in words):
            return topic, "urgent" if urgent else "ordinary"
    if urgent:
        return "pilna_konsultacja", "urgent"
    return None


class CandidateStore:
    """SQLite for OFFLINE pilot only; do not use ephemeral Render FS in production."""

    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS facebook_pilot_candidates (
          event_key TEXT PRIMARY KEY,
          group_id TEXT NOT NULL,
          post_id TEXT NOT NULL,
          post_url TEXT NOT NULL,
          seen_at TEXT NOT NULL,
          topic TEXT NOT NULL,
          priority TEXT NOT NULL,
          state TEXT NOT NULL CHECK(state='awaiting_individual_author')
        )""")
        self.conn.commit()

    def insert(self, post_id: str, url: str, seen_at: str, topic: str, priority: str) -> bool:
        digest = hashlib.sha256(f"{GROUP_ID}:{post_id}".encode("ascii")).hexdigest()
        with self.conn:
            cur = self.conn.execute("""INSERT OR IGNORE INTO facebook_pilot_candidates
                (event_key, group_id, post_id, post_url, seen_at, topic, priority, state)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'awaiting_individual_author')""",
                (digest, GROUP_ID, post_id, url, seen_at, topic, priority))
        return cur.rowcount == 1

    def counts(self) -> tuple[int, int]:
        r = self.conn.execute("SELECT COUNT(*), SUM(priority='urgent') FROM facebook_pilot_candidates").fetchone()
        return r[0], r[1] or 0

    def close(self):
        self.conn.close()


def ingest_evidence(payload: object, store: CandidateStore, *, now: datetime | None = None) -> dict:
    """Ingest externally supplied authorized evidence; NEVER authenticate or publish.

    An ingestion endpoint must independently establish identity and group access.
    The boolean fields here are a claim from its caller, not a substitute for it.
    """
    if not isinstance(payload, dict):
        raise PilotInputError("INVALID_BATCH")
    if payload.get("profile") != PROFILE or payload.get("group_id") != GROUP_ID:
        raise PilotInputError("WRONG_PILOT_PROFILE_OR_GROUP")
    state = payload.get("status")
    if state not in ALLOWED_STATES:
        raise PilotInputError("INVALID_SOURCE_STATE")
    if state in ("authentication_required", "source_unavailable"):
        return {"source_status": state, "coverage": "none", "new_candidates": 0,
                "duplicates": 0, "auto_published": 0, "comments_generated": 0}
    if payload.get("identity_verified") is not True or payload.get("membership_verified") is not True:
        return {"source_status": "authentication_required", "coverage": "none",
                "new_candidates": 0, "duplicates": 0, "auto_published": 0, "comments_generated": 0}
    observed = parse_time(payload.get("observed_at"))
    utc_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if observed > utc_now + timedelta(minutes=5) or utc_now - observed > timedelta(days=2):
        raise PilotInputError("STALE_OR_FUTURE_OBSERVATION")
    posts = payload.get("posts")
    if not isinstance(posts, list) or len(posts) > MAX_POSTS:
        raise PilotInputError("INVALID_POST_LIST")
    new = dupes = skipped = 0
    for post in posts:
        if not isinstance(post, dict):
            raise PilotInputError("INVALID_POST")
        post_id, canonical = canonical_group_post(post.get("url"))
        posted = parse_time(post.get("published_at"))
        if posted > observed + timedelta(minutes=5) or observed - posted > MAX_AGE:
            skipped += 1
            continue
        match = topic_for(post.get("text"))
        if match is None:
            skipped += 1
            continue
        topic, priority = match
        if store.insert(post_id, canonical, observed.isoformat(), topic, priority):
            new += 1
        else:
            dupes += 1
    return {"source_status": state, "coverage": "partial" if state == "partial" else "reported_complete",
            "scanned": len(posts), "new_candidates": new, "duplicates": dupes,
            "skipped": skipped, "auto_published": 0, "comments_generated": 0}


def main():
    parser = argparse.ArgumentParser(description="Watcher FB pilot: import authorized observations into reply candidates only")
    parser.add_argument("--input", required=True, help="Private JSON with source evidence, never committed")
    parser.add_argument("--db", required=True, help="Private SQLite file for local pilot (not Render Free)")
    args = parser.parse_args()
    if args.db == ":memory:":
        parser.error("--db must be durable for a real run")
    store = CandidateStore(args.db)
    try:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        receipt = ingest_evidence(data, store)
    except (ValueError, OSError, UnicodeError):
        print(json.dumps({"status": "error", "code": "PILOT_INPUT_REJECTED"}))
        raise SystemExit(2)
    finally:
        store.close()
    print(json.dumps({"status": "ok", **receipt}, ensure_ascii=False))


if __name__ == "__main__":
    main()
