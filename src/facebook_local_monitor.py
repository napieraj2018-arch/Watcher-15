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
    r"|/story\.php(?:\?|$)"
    r"|/photo(?:\.php)?(?:\?|$)",
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
    if parsed.path.endswith("story.php"):
        query = [(k, v) for k, v in query if k in {"story_fbid", "id"}]
        if not any(k == "story_fbid" for k, _ in query):
            return None
    elif parsed.path.endswith("photo.php") or parsed.path.endswith("/photo"):
        query = [(k, v) for k, v in query if k in {"fbid", "id"}]
        if not query:
            return None
    else:
        query = []
    clean_path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    return urlunsplit(("https", "www.facebook.com", clean_path,
                       urlencode(sorted(query)), ""))

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
    port = int(os.environ.get("SMTP_PORT", "465"))
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
        # Reading the login indicator is not a login attempt.
        login_fields = await page.locator('input[name="email"]').count()
        password_fields = await page.locator('input[name="pass"]').count()
        body = simplify((await page.locator("body").inner_text(timeout=8000))[:3000])
        if (login_fields and password_fields) or any(cue in body for cue in LOGIN_CUES):
            return {"source": name, "status": "login_required", "posts": []}
        if any(phrase in body for phrase in (
            "content isn't available", "ta zawartosc jest niedostepna",
            "temporarily blocked", "czasowo zablok",
        )):
            return {"source": name, "status": "unavailable_or_blocked", "posts": []}
        # Extract anchors and ONLY text near the linking post, not the entire page.
        # This is a read-only DOM inspection, with no interaction or anti-bot measures.
        candidates = await page.evaluate("""() => {
            const matches = Array.from(document.querySelectorAll('a[href]'))
              .filter(a => /\\/(posts|permalink|reel)\\/|\\/story\\.php|\\/photo\\.php|\\/groups\\/[^/]+\\/posts\\//.test(a.href));
            return matches.slice(0, 120).map(a => {
              let parent = a.closest('[role="article"]');
              if (!parent) {
                parent = a;
                for (let i=0; i<4 && parent.parentElement; i++) parent = parent.parentElement;
              }
              return {url: a.href, text: (parent.innerText || '').slice(0, 2000)};
            });
        }""")
        posts = []
        seen = set()
        for candidate in candidates:
            link = canonical_link(candidate.get("url", ""), source["url"])
            if link is None or link in seen:
                continue
            seen.add(link)
            text = " ".join(candidate.get("text", "").split())
            if len(text) >= 15:
                posts.append({"url": link, "text": text})
            if len(posts) >= limit:
                break
        status = "ok" if posts else "no_identifiable_posts"
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
                    if category:
                        matches.append({**p, "source": result["source"],
                                        "category": category, "score": score})
                print(f"SOURCE {source['name']}: status={result['status']} "
                      f"posts={len(result['posts'])}")
            await context.close()
        finally:
            await browser.close()
    valid = sum(r["status"] == "ok" for r in report)
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
            if not send_email(new_matches, config):
                print("ALERT_PENDING; preserving unmatched URLs for the next run")
                # Save unrelated seen posts, leave matching unsent records unseen.
                seen_matched = {digest(m["url"]) for m in new_matches}
                hashes.update(h for h in newly_seen if h not in seen_matched)
                save_state(hashes)
                return 4
        except Exception as exc:
            print(f"EMAIL_FAILURE: {type(exc).__name__}; preserving pending alerts")
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
