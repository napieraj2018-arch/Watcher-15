#!/usr/bin/env python3
"""Local-lead Facebook page watcher. Read-only; never clicks Like/Comment/Send.

This scanner requires pages the account may legitimately view. It does NOT
evade login checks, bot detection, rate limits, or other platform protections.
An optional Playwright storage_state is read from a secret, never written.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import smtplib
import ssl
import sys
import unicodedata
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

CONFIG = Path(__file__).resolve().parents[1] / "config" / "facebook_local_monitor.json"
STATE = Path(os.getenv("FB_WATCH_STATE", "facebook-watch-state.json"))
PERMALINK = re.compile(
    r"/(?:posts|permalink|reel)/[a-zA-Z0-9_-]+"
    r"|/groups/[^/]+/(?:posts|permalink)/[a-zA-Z0-9_-]+"
    r"|/(?:story|permalink)\.php(?:\?|$)",
    re.I,
)
LOGIN_CUES = ("log into facebook", "zaloguj sie do facebooka",
              "log in to facebook", "login to facebook")
ARCH = ("architekt", "projekt", "adaptac", "przebudow", "rozbudow",
        "podzial mieszkan", "podzielic mieszkani", "biur projekt", "pozwolenie na budow")
VET = ("weterynar", "lekarz zwierzat", "szczepien", "szczeniak", "pies", "psa",
       "kota", "kotem", "ortoped", "kulej", "okulist", "klinika wet")
INTENT = ("polec", "szukam", "poszukuj", "potrzebuj", "kto pomoze", "gdzie",
          "jaki lekarz", "jakie biuro", "ile koszt", "zna ktos",
          "macie kogos", "poradz", "prosze o kontakt", "kontakt do")

def simplify(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value.lower())
                   if not unicodedata.combining(ch))

def canonical_link(raw: str, base: str) -> str | None:
    """Keep a stable post URL. Never store secrets or tracking parameters."""
    if not raw:
        return None
    full = urljoin(base, raw.replace("&amp;", "&"))
    parsed = urlsplit(full)
    if (parsed.hostname or "").lower() not in {
        "facebook.com", "www.facebook.com", "m.facebook.com",
    }:
        return None
    if not PERMALINK.search(parsed.path):
        return None
    query = parse_qsl(parsed.query, keep_blank_values=False)
    if parsed.path.endswith(("story.php", "permalink.php")):
        query = [(k, v) for k, v in query if k in {"story_fbid", "id"}]
        if not any(k == "story_fbid" for k, _ in query):
            return None
    else:
        query = []
    clean_path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    return urlunsplit(("https", "www.facebook.com", clean_path,
                       urlencode(sorted(query)), ""))

def is_time_label(value: str) -> bool:
    """Accept post timestamp links, not unrelated page-intro URLs."""
    label = simplify(value.strip()).rstrip(" .")
    if not label or len(label) > 80 or "http" in label:
        return False
    if re.match(r"^\d+\s*(?:s|m|h|d|w|y|min|mins|hr|hrs|hours?|days?|weeks?|years?|godz|godzin|godziny|dzien|dni|tydzien|tygodnie|tyg|minuta|minuty|minut)(?:\s+ago)?$", label):
        return True
    if re.match(r"^(?:a|an)\s+(?:minute|hour|day|week|month|year)\s+ago$", label):
        return True
    if label in ("yesterday", "wczoraj", "just now", "przed chwila"):
        return True
    if re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|sty|lut|kwi|maj|cze|lip|sie|wrz|paz|lis|gru)\b", label):
        return True
    return False


def age_minutes(value: str) -> int | None:
    """Approximate relative age from a visible Facebook timestamp.
    Calendar dates are deliberately unknown (None), not guessed.
    """
    label = simplify(value.strip()).rstrip(" .")
    if label in ("just now", "przed chwila"):
        return 0
    if label in ("a day ago", "yesterday", "wczoraj"):
        return 24 * 60
    if label == "an hour ago":
        return 60
    m = re.match(r"^(\d+)\s*(\S+)(?:\s+ago)?$", label)
    if not m:
        return None
    number = int(m.group(1))
    unit = m.group(2).rstrip(".")
    if unit in ("s", "sec", "sek", "sekund"):
        return max(0, number // 60)
    if unit in ("m", "min", "mins", "minut", "minuta", "minuty"):
        return number
    if unit in ("h", "hr", "hrs", "hour", "hours",
                "godz", "godzin", "godziny"):
        return number * 60
    if unit in ("d", "day", "days", "dzien", "dni"):
        return number * 24 * 60
    if unit in ("w", "week", "weeks", "tyg", "tydzien", "tygodnie"):
        return number * 7 * 24 * 60
    if unit in ("y", "year", "years"):
        return number * 365 * 24 * 60
    return None


def classify(text: str) -> tuple[str | None, int]:
    t = simplify(text)
    if len(t) < 15:
        return None, 0
    a = sum(1 for k in ARCH if k in t)
    v = sum(1 for k in VET if k in t)
    if a == 0 and v == 0:
        return None, 0
    purpose = sum(1 for k in INTENT if k in t)
    domain = "ARCHITEKT" if a >= v else "WETERYNARZ"
    # A strong signal needs a domain phrase and at least one buying/help cue.
    score = min(10, max(a, v) * 2 + min(purpose, 2) * 2)
    return (domain, score) if purpose and score >= 4 else (None, score)

def load_state() -> tuple[set[str], bool]:
    if not STATE.exists():
        return set(), True
    try:
        raw = json.loads(STATE.read_text("utf-8"))
        if not isinstance(raw.get("hashes"), list):
            raise ValueError("Malformed state")
        return set(raw["hashes"]), False
    except (ValueError, OSError, TypeError) as exc:
        raise RuntimeError("State is invalid; refusing to resend old posts") from exc

def save_state(hashes: set[str]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "hashes": sorted(hashes),
    }, ensure_ascii=False), "utf-8")
    tmp.replace(STATE)

def digest(link: str) -> str:
    return hashlib.sha256(link.encode("utf-8")).hexdigest()

def load_session() -> dict | None:
    raw = os.environ.get("FB_STORAGE_STATE_B64", "").strip()
    if not raw:
        return None
    try:
        session = json.loads(base64.b64decode(raw, validate=True))
    except Exception as exc:
        raise RuntimeError("FB_STORAGE_STATE_B64 is invalid") from exc
    if not isinstance(session, dict) or not isinstance(session.get("cookies"), list):
        raise RuntimeError("Invalid Playwright storage_state format")
    return session

def send_email(matches: list[dict], config: dict) -> bool:
    settings = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "ALERT_TO")
    if not all(os.environ.get(k) for k in settings):
        print(f"EMAIL_NOT_CONFIGURED matches={len(matches)}")
        return False
    mail = EmailMessage()
    mail["From"] = os.environ["SMTP_USER"]
    mail["To"] = os.environ["ALERT_TO"]
    mail["Subject"] = f"Facebook Watcher: {len(matches)} potencjalnych zapytan"
    lines = [
        "Wykryto nowe, potencjalnie istotne zapytania.",
        "Odpowiedz recznie ze swojego konta; automat niczego nie publikuje.",
        "",
    ]
    for i, item in enumerate(matches, 1):
        lines.extend([
            f"{i}. {item['source']} / {item['category']} / wynik={item['score']}",
            f"Link: {item['url']}",
            f"Tresc: {item['text'][:700]}",
            "",
        ])
    mail.set_content("\n".join(lines))
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT") or "465")
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=20,
                              context=ssl.create_default_context()) as server:
            server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            server.send_message(mail)
    else:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            server.send_message(mail)
    print(f"EMAIL_SENT matches={len(matches)}")
    return True

async def inspect_page(context, source: dict, timeout_ms: int, limit: int) -> dict:
    page = await context.new_page()
    name = source["name"]
    try:
        response = await page.goto(source["url"], wait_until="domcontentloaded",
                                   timeout=timeout_ms)
        await page.wait_for_timeout(2500)
        final_url = page.url
        status_code = response.status if response else 0
        if status_code >= 400:
            return {"source": name, "status": f"http_{status_code}", "posts": []}
        if any(k in final_url.lower() for k in (
            "/login", "two_step_verification", "/checkpoint", "/recover",
        )):
            return {"source": name, "status": "login_or_verification_required", "posts": []}
        # A public Facebook page may contain a login form/footer *and* real,
        # readable post previews. Login widgets alone must not hide public posts.
        login_fields = await page.locator('input[name="email"]').count()
        password_fields = await page.locator('input[name="pass"]').count()
        body = simplify((await page.locator("body").inner_text(timeout=8000))[:3000])
        if any(phrase in body for phrase in (
            "content isn't available", "ta zawartosc jest niedostepna",
            "temporarily blocked", "czasowo zablok",
        )):
            return {"source": name, "status": "unavailable_or_blocked", "posts": []}
        # Read visible permalink anchors and their nearest post-shaped containers.
        # No likes, comments, clicks, requests for hidden posts or CAPTCHA bypass.
        candidates = await page.evaluate("""() => {
            const matches = Array.from(document.querySelectorAll('a[href]'))
              .filter(a => /\\/(posts|permalink|reel)\\/|\\/(story|permalink)\\.php|\\/groups\\/[^/]+\\/posts\\//.test(a.href));
            return matches.slice(0, 120).map(a => {
              let parent = a.closest('[role="article"]');
              if (!parent) {
                let fallback = a;
                for (let i = 0, n = a; n && i < 12; i++, n = n.parentElement) {
                  const rawText = (n.innerText || '').trim();
                  if (rawText.length >= 30 && rawText.length <= 6000) {
                    fallback = n;
                    if (/(like|comment|polub|komentarz)/i.test(rawText)) break;
                  }
                }
                parent = fallback;
              }
              return {
                url: a.href,
                timestamp_text: (a.innerText || a.getAttribute('aria-label') || '').slice(0, 110),
                text: (parent.innerText || '').slice(0, 3000),
              };
            });
        }""")
        if os.getenv("FB_PROBE_META", "") == "1":
            for sample in candidates[:8]:
                raw_label = sample.get("timestamp_text", "")
                label = "<link>" if "http" in raw_label.lower() else raw_label[:40]
                print(f"CANDIDATE_META source={source['id']} label={label!r} "
                      f"text_chars={len(sample.get('text', ''))}")
        posts = []
        seen = set()
        for candidate in candidates:
            if not is_time_label(candidate.get("timestamp_text", "")):
                continue
            link = canonical_link(candidate.get("url", ""), source["url"])
            if link is None or link in seen:
                continue
            seen.add(link)
            text = " ".join(candidate.get("text", "").split())
            if len(text) >= 15:
                posts.append({"url": link, "text": text, "timestamp_text": candidate.get("timestamp_text", "")})
            if len(posts) >= limit:
                break
        if posts:
            status = "ok_public_preview" if (login_fields and password_fields) else "ok"
        else:
            status = "login_required" if (login_fields and password_fields) or any(cue in body for cue in LOGIN_CUES) else "no_identifiable_posts"
        return {"source": name, "status": status, "posts": posts}
    except Exception as exc:
        # Error class only: no sensitive URL query strings in public logs.
        return {"source": name, "status": f"error_{type(exc).__name__}", "posts": []}
    finally:
        await page.close()

async def run(args: argparse.Namespace) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Missing playwright dependency; install playwright and Chromium")
        return 2
    config = json.loads(Path(args.config).read_text("utf-8"))
    sources = [s for s in config["sources"] if s.get("enabled", True)]
    if not sources:
        print("No sources selected")
        return 2
    session = load_session()
    hashes, first_run = load_state() if not args.probe else (set(), True)
    report = []
    matches = []
    newly_seen = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            context = await browser.new_context(
                locale="pl-PL", storage_state=session,
                viewport={"width": 1365, "height": 900})
            for source in sources:
                result = await inspect_page(context, source, 25000,
                                            int(config.get("max_posts_per_source", 12)))
                report.append(result)
                for p in result["posts"]:
                    ident = digest(p["url"])
                    if ident in hashes:
                        continue
                    newly_seen.append(ident)
                    category, score = classify(p["text"])
                    age = age_minutes(p.get("timestamp_text", ""))
                    within_window = age is None or age <= int(config.get("max_alert_age_minutes", 120))
                    if category and within_window:
                        matches.append({**p, "source": result["source"],
                                        "category": category, "score": score})
                print(f"SOURCE {source['name']}: status={result['status']} "
                      f"posts={len(result['posts'])}")
                if args.probe:
                    for item in result["posts"][:3]:
                        print(f"POST_METRIC source={source['id']} "
                              f"time={item['timestamp_text']!r} "
                              f"text_chars={len(item['text'])}")
            await context.close()
        finally:
            await browser.close()
    valid = sum(r["status"].startswith("ok") for r in report)
    print(f"SUMMARY sources={len(report)} readable={valid} "
          f"new={len(newly_seen)} matches={len(matches)} "
          f"session={'provided' if session else 'none'} "
          f"first_run={first_run} mode={'probe' if args.probe else 'monitor'}")
    if args.probe:
        # A successful process is not proof that the sources are readable.
        return 0 if valid else 3
    if not valid:
        print("NO_ACCESS: no state saved; refusing to report an empty feed as success")
        return 3
    if first_run:
        # Baseline: do not alert on historic posts, but do mark them as seen.
        hashes.update(newly_seen)
        save_state(hashes)
        print("BASELINE_CREATED; historical posts were not emailed")
        return 0
    new_matches = [p for p in matches if digest(p["url"]) not in hashes]
    if new_matches:
        try:
            delivered = send_email(new_matches, config)
            if not delivered and os.getenv("FB_GITHUB_ISSUE_ALERTS") == "true":
                # Explicit opt-in only: the GitHub issue is PUBLIC in a public repo.
                from src.facebook_notify import notify_via_github
                delivered = notify_via_github(new_matches)
            if not delivered:
                print("ALERT_PENDING; preserving matching URLs for the next run")
                seen_matched = {digest(m["url"]) for m in new_matches}
                hashes.update(h for h in newly_seen if h not in seen_matched)
                save_state(hashes)
                return 4
        except Exception as exc:
            print(f"ALERT_FAILURE: {type(exc).__name__}; preserving pending alerts")
            return 4
    hashes.update(newly_seen)
    save_state(hashes)
    return 0

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--probe", action="store_true",
                        help="Try read-only access; no alerts or state persistence")
    args = parser.parse_args()
    return asyncio.run(run(args))

if __name__ == "__main__":
    sys.exit(main())
