"""Read-only extraction of enrolled ESAVS course notes from an encrypted saved profile.

Separate from Chromium. Never exports cookies or permits arbitrary URLs.
Only the named Ophthalmology I course's resource links can be selected.
PDFs are transiently cached on private server disk, deleted after final batch.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException
from pypdf import PdfReader

HOST = "e-campus.esavs.eu"
BASE = "https://" + HOST
PROFILE = "esavs-ophthalmology-i"
COURSE = "Ophthalmology I Residential Course, 2 - 11 Nov 2026, Palma"
MAX_HTML = 8 * 1024 * 1024
MAX_PDF = 70 * 1024 * 1024
MAX_PAGES = 600
CACHE = Path(tempfile.gettempdir()) / "aib-esavs-course-readonly"


def _same_origin(base: str, href: str) -> str:
    if not isinstance(href, str) or len(href) > 12000:
        raise HTTPException(403, "Niedozwolony odsyłacz ESAVS")
    target = urljoin(base, href)
    p = urlsplit(target)
    if (p.scheme != "https" or p.hostname != HOST or p.port not in (None, 443)
            or p.username is not None or p.password is not None):
        raise HTTPException(403, "Odczyt ograniczono do oficjalnego e-Campus ESAVS")
    return target


def _state(load_state, unseal):
    row = load_state(PROFILE)
    if not row:
        raise HTTPException(404, "Brak zapisanego profilu ESAVS")
    try:
        state = json.loads(unseal(row[0]))
        if state.get("aib_profile", PROFILE) != PROFILE:
            raise ValueError("profile mismatch")
        if not isinstance(state.get("cookies"), list):
            raise ValueError("cookies missing")
    except (ValueError, TypeError, UnicodeError):
        raise HTTPException(409, "Nie można odczytać profilu ESAVS") from None
    return state


def _client(state):
    client = httpx.Client(
        follow_redirects=False,
        timeout=httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0),
        headers={"User-Agent": "Mozilla/5.0 (compatible; private ESAVS course notes reader)"})
    for item in state.get("cookies", []):
        domain = str(item.get("domain", "")).strip().lstrip(".").lower()
        if domain != HOST:
            continue
        name, value = item.get("name"), item.get("value")
        if not isinstance(name, str) or not isinstance(value, str) or not name:
            continue
        path = str(item.get("path") or "/")
        if not path.startswith("/"):
            continue
        client.cookies.set(name, value, domain=HOST, path=path)
    return client


def _request(client, start: str, *, html=True):
    url = _same_origin(BASE, start)
    for _ in range(5):
        response = client.get(url)
        if response.status_code in (301, 302, 303, 307, 308):
            url = _same_origin(url, response.headers.get("location", ""))
            response.close()
            continue
        if response.status_code != 200:
            response.close()
            raise HTTPException(502, "ESAVS nie udostępnił materiału")
        if html:
            if len(response.content) > MAX_HTML:
                response.close()
                raise HTTPException(413, "Strona ESAVS zbyt obszerna")
            if b"<html" not in response.content[:1500].lower() and b"<!doctype" not in response.content[:1500].lower():
                response.close()
                raise HTTPException(422, "ESAVS zwrócił nieoczekiwaną treść")
        return response, url
    raise HTTPException(502, "Zbyt wiele przekierowań ESAVS")


def _normal(s):
    return " ".join(str(s or "").replace("\xa0", " ").split())


def _course_resource_links(html: str, course_base: str) -> list[dict]:
    doc = BeautifulSoup(html, "html.parser")
    notes = []
    # Moodle creates section containers with a section title "Course Notes".
    for sec in doc.select("li.section, section, div.course-section"):
        heading = sec.find(["h3", "h4", "h5", "h2"], class_=re.compile("sectionname|section-title", re.I))
        if heading and _normal(heading.get_text(" ", strip=True)) == "Course Notes":
            notes.append(sec)
    if not notes:
        # Keep only resource links from this single already-verified course; the
        # caller can still select only a title from this list.
        notes = [doc]
    result, seen = [], set()
    for section in notes:
        for a in section.find_all("a", href=True):
            href = a.get("href", "")
            url = _same_origin(course_base, href)
            if urlsplit(url).path.rstrip("/") != "/mod/resource/view.php":
                continue
            label = a.find(class_=re.compile("instancename|activityname", re.I))
            raw = label.get_text(" ", strip=True) if label else a.get_text(" ", strip=True)
            title = _normal(raw)
            title = re.sub(r"\s+(File|Resource)$", "", title, flags=re.I).strip()
            if title and title not in seen:
                seen.add(title)
                result.append({"title": title, "url": url})
    return result[:100]


def _index(client) -> list[dict]:
    dashboard, dash_url = _request(client, BASE + "/my/")
    try:
        doc = BeautifulSoup(dashboard.text, "html.parser")
    finally:
        dashboard.close()
    match = None
    for a in doc.find_all("a", href=True):
        if _normal(a.get_text(" ", strip=True)) == COURSE:
            match = a
            break
    if match is None:
        raise HTTPException(401, "Kurs Ophthalmology I nie jest dostępny w zapisanej sesji")
    course_link = _same_origin(dash_url, match.get("href", ""))
    if urlsplit(course_link).path != "/course/view.php":
        raise HTTPException(403, "Oczekiwano oficjalnej strony kursu Moodle")
    page, page_url = _request(client, course_link)
    try:
        if "Course Notes" not in page.text:
            raise HTTPException(422, "Nie można odczytać sekcji Course Notes")
        links = _course_resource_links(page.text, page_url)
    finally:
        page.close()
    if not links:
        raise HTTPException(422, "Nie znaleziono linków Course Notes")
    return links


def _pdf_url(client, selected_url: str) -> str:
    page, resource_url = _request(client, selected_url)
    try:
        soup = BeautifulSoup(page.text, "html.parser")
    finally:
        page.close()
    for tag in soup.find_all(["a", "iframe", "embed", "object"]):
        href = tag.get("href") or tag.get("src") or tag.get("data")
        if not href:
            continue
        url = _same_origin(resource_url, href)
        if "/pluginfile.php/" in urlsplit(url).path:
            return url
    raise HTTPException(422, "Brak bezpośredniego pliku PDF na stronie ESAVS")


def _key(key: bytes, url: str) -> str:
    return hmac.new(key, (PROFILE + "\n" + url).encode(), hashlib.sha256).hexdigest()


def _cleanup_cache():
    CACHE.mkdir(mode=0o700, parents=True, exist_ok=True)
    for path in CACHE.glob("*.pdf"):
        try:
            if time.time() - path.stat().st_mtime > 1800:
                path.unlink()
        except OSError:
            pass


def _download(client, url: str, key: bytes) -> Path:
    cache_id = _key(key, url)
    dest = CACHE / (cache_id + ".pdf")
    if dest.exists() and 0 < dest.stat().st_size <= MAX_PDF:
        return dest
    # Write to a new private file, atomically replace. Refuse oversized input.
    tmp = None
    for _ in range(5):
        path = _same_origin(BASE, url)
        with client.stream("GET", path) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                url = _same_origin(url, resp.headers.get("location", ""))
                continue
            if resp.status_code != 200:
                raise HTTPException(502, "ESAVS odmówił dostępu do PDF")
            try:
                length = int(resp.headers.get("content-length") or 0)
            except ValueError:
                length = 0
            if length > MAX_PDF:
                raise HTTPException(413, "Ten PDF jest zbyt duży na serwer Free")
            try:
                with tempfile.NamedTemporaryFile(prefix="esavs-",suffix=".part",dir=CACHE,delete=False) as out:
                    tmp = Path(out.name)
                    os.chmod(tmp, 0o600)
                    first = True
                    copied = 0
                    for block in resp.iter_bytes(chunk_size=131072):
                        copied += len(block)
                        if copied > MAX_PDF:
                            raise HTTPException(413, "Limit wielkości PDF przekroczony")
                        if first:
                            if not block.startswith(b"%PDF"):
                                raise HTTPException(415, "Plik nie jest PDF")
                            first = False
                        out.write(block)
                os.replace(tmp, dest)
                return dest
            finally:
                if tmp is not None and tmp.exists():
                    tmp.unlink()
    raise HTTPException(502, "Zbyt wiele przekierowań PDF")


def _extract_pdf(path: Path, offset: int):
    if not isinstance(offset, int) or offset < 0:
        raise HTTPException(400, "Nieprawidłowy numer strony")
    with path.open("rb") as stream:
        try:
            reader = PdfReader(stream, strict=False)
            total = len(reader.pages)
            if total > MAX_PAGES or offset >= total:
                raise HTTPException(416, "Poza zakresem stron")
            pages, chars = [], 0
            for n in range(offset, min(offset + 6, total)):
                try:
                    t = reader.pages[n].extract_text() or ""
                except Exception:
                    t = ""
                t = t[:max(0, 20000 - chars)]
                pages.append({"page":n + 1, "text":t})
                chars += len(t)
                if chars >= 20000:
                    break
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, "Nie można przetworzyć PDF") from None
    next_start = pages[-1]["page"] if pages[-1]["page"] < total else None
    return {"total_pages":total, "pages":pages, "next_start_page":next_start,
            "text_chars":chars, "has_unreadable_pages":any(not p["text"].strip() for p in pages)}


def run(action: str, args: dict, load_state, unseal, key: bytes) -> dict:
    if args.get("name") != PROFILE:
        raise HTTPException(403, "Odczyt dostępny tylko dla profilu ESAVS")
    state = _state(load_state, unseal)
    _cleanup_cache()
    with _client(state) as client:
        links = _index(client)
        if action == "esavs_offline_index":
            return {"course":COURSE, "materials":[x["title"] for x in links]}
        title = _normal(args.get("text", ""))
        if not title:
            raise HTTPException(400, "Podaj dokładny tytuł materiału z kursu")
        target = next((x for x in links if _normal(x["title"]) == title), None)
        if not target:
            raise HTTPException(404, "Materiał nie występuje na oficjalnej liście kursu")
        url = _pdf_url(client, target["url"])
        path = _download(client, url, key)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(131072), b""):
                digest.update(block)
        offset = args.get("delta", 0)
        info = _extract_pdf(path, offset)
        if info["next_start_page"] is None:
            path.unlink(missing_ok=True)
        return {"resource":title,"file_size":path.stat().st_size if path.exists() else None,
                "file_sha256":digest.hexdigest(), **info}
