import html, json, re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

URL = "https://fly.pl/szukaj-wycieczek/"
TZ = ZoneInfo("Europe/Warsaw")
HEAD = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9",
}


def all_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from all_strings(item)


def response_html(text):
    parts = [text]
    try:
        obj = json.loads(text)
        parts.extend(x for x in all_strings(obj) if "<" in x or "\\u003c" in x.lower())
    except Exception:
        pass
    decoded = "\n".join(parts)
    decoded = html.unescape(decoded)
    # Fly sometimes serializes HTML in JSON with unicode escapes.
    decoded = decoded.replace("\\u003C", "<").replace("\\u003c", "<")
    decoded = decoded.replace("\\u003E", ">").replace("\\u003e", ">")
    decoded = decoded.replace("\\/", "/")
    decoded = decoded.replace('\\"', '"')
    return decoded


def money_values(text):
    out = []
    for raw in re.findall(r"(?<!\d)(\d[\d\s.]{0,9})\s*zł", text, re.I):
        digits = re.sub(r"\D", "", raw)
        if digits:
            out.append(int(digits))
    return out


def card_key(node, text):
    cur = node
    for _ in range(8):
        if cur is None:
            break
        for name in ("data-id", "data-offer-id", "data-hotel-id", "id"):
            value = cur.get(name) if hasattr(cur, "get") else None
            if value and re.search(r"\d", str(value)):
                return f"{name}:{value}"
        cur = getattr(cur, "parent", None)
    href = None
    cur = node
    for _ in range(8):
        if cur is None:
            break
        link = cur.find("a", href=True) if hasattr(cur, "find") else None
        if link:
            href = link.get("href")
            break
        cur = getattr(cur, "parent", None)
    if href:
        return "href:" + href.split("?")[0]
    clean = re.sub(r"\s+", " ", text).strip()
    return "text:" + clean[:90]


def extract_cards(text):
    soup = BeautifulSoup(response_html(text), "html.parser")
    out = []
    seen = set()
    markers = soup.select("span.for_all")
    print("FLY_TOTAL_FOR_ALL_MARKERS", len(markers))
    for marker in markers:
        cur = marker
        chosen = None
        for _ in range(9):
            cur = getattr(cur, "parent", None)
            if cur is None:
                break
            txt = " ".join(cur.get_text(" ", strip=True).split())
            prices = money_values(txt)
            # Smallest useful container containing final-total label plus package context.
            if prices and 40 <= len(txt) <= 2200:
                chosen = cur
                if any(k in txt.lower() for k in ["nocy", "all inclusive", "wylot", "tripadvisor", "hotel"]):
                    break
        if chosen is None:
            continue
        txt = " ".join(chosen.get_text(" ", strip=True).split())
        prices = money_values(txt)
        key = card_key(chosen, txt)
        rec = {
            "key": key,
            "prices": prices,
            "text": txt[:1400],
            "has_all_label": "za wszystkich" in txt.lower(),
            "has_ai": "all inclusive" in txt.lower(),
            "live_signal": any(x in txt.lower() for x in ["dostępn", "rezerw", "sprawdzamy", "aktualn"]),
        }
        fingerprint = (key, tuple(prices), rec["text"][:180])
        if fingerprint not in seen:
            seen.add(fingerprint)
            out.append(rec)
    return out


def params(family):
    today = datetime.now(TZ).date()
    start = today + timedelta(days=1)
    end = today + timedelta(days=3)
    p = {
        "filter[person]": "2",
        "filter[child]": "2" if family else "0",
        "filter[fp]": "2",  # Fly's explicit 'Cena za wszystkich' mode.
        "filter[whenFrom]": start.strftime("%d-%m-%Y"),
        "filter[whenTo]": (end + timedelta(days=8)).strftime("%d-%m-%Y"),
        "filter[duration]": "5:8",
        "durationFrom": "5",
        "durationTo": "8",
        "filter[addTransport]": "F",
        "filter[addCatering]": "1",
        "filter[forceFilter]": "1",
        "ajaxRequest": "true",
    }
    if family:
        # The live Fly serializer confirmed these fields are AGE, not DOB.
        p["filter[childAge][1]"] = "5"
        p["filter[childAge][2]"] = "7"
    return p


def fetch(label, p):
    r = requests.get(URL, params=p, headers=HEAD, timeout=40)
    print("FLY_TOTAL_REQ", label, r.status_code, r.url, len(r.content), r.headers.get("content-type"))
    r.raise_for_status()
    cards = extract_cards(r.text)
    print("FLY_TOTAL_CARD_COUNT", label, len(cards))
    for rec in cards[:12]:
        print("FLY_TOTAL_CARD", label, repr(rec))
    return cards


family = fetch("FAMILY", params(True))
adults = fetch("ADULTS", params(False))

adult_by_key = {x["key"]: x for x in adults if not x["key"].startswith("text:")}
proofs = []
for fam in family:
    other = adult_by_key.get(fam["key"])
    if not other or not fam["prices"] or not other["prices"]:
        continue
    # In all-person mode, the price adjacent to the 'za wszystkich' card is a
    # final displayed package total. Require it to differ for the same offer.
    fam_total = fam["prices"][0]
    adult_total = other["prices"][0]
    if fam_total != adult_total:
        proof = {
            "key": fam["key"],
            "family_total": fam_total,
            "adults_total": adult_total,
            "family_label": fam["has_all_label"],
            "adult_label": other["has_all_label"],
            "family_ai": fam["has_ai"],
        }
        proofs.append(proof)
        print("FLY_EXACT_FAMILY_TOTAL_PROOF", repr(proof))

print("FLY_EXACT_FAMILY_TOTAL_PROOF_COUNT", len(proofs))
print("FLY_FAMILY_GATE", bool(proofs))
