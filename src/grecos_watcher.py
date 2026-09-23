import hashlib
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from watcher import create_alert

TZ = ZoneInfo("Europe/Warsaw")
API = "https://www.grecos.pl/api/sitecore/OffersList/LoadMoreOffers"
BASE = "https://www.grecos.pl"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.7",
    "Referer": "https://www.grecos.pl/last-minute",
}


def _num(value):
    raw = re.sub(r"\D", "", str(value or ""))
    return int(raw) if raw else None


def _float(value):
    m = re.search(r"([0-9]+(?:[.,][0-9]+)?)", str(value or ""))
    return float(m.group(1).replace(",", ".")) if m else None


def _stars(value):
    text = str(value or "").lower()
    names = {"five-stars": 5, "four-stars": 4, "three-stars": 3, "two-stars": 2, "one-star": 1}
    for name, number in names.items():
        if name in text:
            return number
    m = re.search(r"\b([1-5])\b", text)
    return int(m.group(1)) if m else None


def _departure(value):
    text = str(value or "")
    full = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if full:
        return datetime(int(full.group(3)), int(full.group(2)), int(full.group(1))).date()
    short = re.search(r"(\d{1,2})\.(\d{1,2})", text)
    if not short:
        return None
    today = datetime.now(TZ).date()
    day, month = int(short.group(1)), int(short.group(2))
    candidates = []
    for year in (today.year, today.year + 1):
        try:
            candidates.append(datetime(year, month, day).date())
        except ValueError:
            pass
    future = [d for d in candidates if d >= today]
    return min(future) if future else None


def _quality(row):
    rating = _float(row.get("Hotel_AverageRating"))
    reviews = None
    for key, value in row.items():
        low = str(key).lower()
        if reviews is None and ("review" in low or "opinion" in low) and any(x in low for x in ("count", "number", "amount", "total")):
            reviews = _num(value)
        if (rating is None or rating == 0) and ("rating" in low or "rate" in low) and "average" in low:
            rating = _float(value)
    return rating, reviews


def _exact_party(row, child1, child2):
    expected = f"&Adults=2&Children=2&Child1={child1}&Child2={child2}"
    return (row.get("Query_AdultsChildenQueryString") or "") == expected


def _offer_url(row):
    value = row.get("Hotel_OfferUrlWithOfferCode") or row.get("Hotel_Url") or row.get("Hotel_Link") or row.get("Hotel_FriendlyUrl") or ""
    if value.startswith("http"):
        return value
    if value:
        return BASE + "/" + value.lstrip("/")
    return BASE + "/last-minute"


def _airport_ok(name, configured):
    value = " ".join(str(name or "").lower().replace("-", " ").split())
    for wanted in configured:
        w = " ".join(str(wanted).lower().replace("-", " ").split())
        if w and (w in value or value in w):
            return wanted
    return None


def _params(cfg):
    today = datetime.now(TZ).date()
    deltas = sorted(int(x) for x in cfg["depart_in_days"])
    start = today + timedelta(days=deltas[0])
    end = today + timedelta(days=deltas[-1])
    # Jan 1 keeps the requested ages stable for the whole short departure window.
    child1 = f"{end.year - 5}0101"
    child2 = f"{end.year - 7}0101"
    params = {
        "Adults": "2",
        "Children": "2",
        "Child1": child1,
        "Child2": child2,
        "DurationInterval": f"{cfg['min_nights']}:{cfg['max_nights']}",
        "DateOfDeparture": start.strftime("%Y%m%d"),
        # Return can be up to max_nights after the last allowed departure.
        # Departure is validated separately against the exact 1–3 day set.
        "DateOfReturn": (end + timedelta(days=int(cfg["max_nights"]))).strftime("%Y%m%d"),
        "PriceFrom": "0",
        "PriceTo": str(max(50000, int(cfg["max_total_price_pln"]))),
        "PriceType": "man",
        "OfferType": "L,S",
        "ObjectType": "H,R,AP",
        "pageFrom": "0",
        "setFilters": "true",
    }
    allowed = {today + timedelta(days=d) for d in deltas}
    return params, child1, child2, allowed


def _comparison_key(row):
    return (
        row.get("Merlin_HotelCode"),
        row.get("Merlin_ParsedStartDate"),
        row.get("Merlin_Duration"),
        row.get("Merlin_BoardStandardDesc"),
        row.get("Merlin_FlightFrom"),
    )


def _fetch_pages(params, label, max_pages=6):
    rows = []
    fingerprints = set()
    for page in range(0, max_pages):
        page_params = dict(params)
        page_params["pageFrom"] = str(page)
        response = requests.get(API, params=page_params, headers=HEADERS, timeout=35)
        print("GRECOS_LIVE_REQUEST", label, page, response.url)
        print("GRECOS_LIVE_STATUS", label, page, response.status_code, response.headers.get("content-type"), len(response.content))
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            print("GRECOS_FAIL_CLOSED_NON_LIST", label, page, type(data).__name__)
            return []
        print("GRECOS_LIVE_PAGE_ROWS", label, page, len(data))
        if not data:
            break
        fingerprint = tuple(
            str(x.get("Merlin_Id") or x.get("Merlin_HotelCode") or "")
            for x in data
            if isinstance(x, dict)
        )
        if fingerprint and fingerprint in fingerprints:
            print("GRECOS_DUPLICATE_PAGE_STOP", label, page)
            break
        fingerprints.add(fingerprint)
        rows.extend(data)
    return rows


def _fetch(cfg):
    params, child1, child2, allowed = _params(cfg)
    offers = []
    seen = set()

    family_rows = _fetch_pages(params, "FAMILY")
    if not family_rows:
        return []

    # Independent same-offer control: never trust Merlin_FullPriceParsed merely
    # because it is larger than the per-adult amount. Compare it against a
    # separate adults-only query and require the exact same package to price
    # differently for 2+2 than for 2 adults.
    adults_params = dict(params)
    adults_params["Children"] = "0"
    adults_params.pop("Child1", None)
    adults_params.pop("Child2", None)
    adult_rows = _fetch_pages(adults_params, "ADULTS")
    adult_totals = {}
    for row in adult_rows:
        if not isinstance(row, dict):
            continue
        total = _num(row.get("Merlin_FullPriceParsed"))
        if total is not None:
            adult_totals[_comparison_key(row)] = total

    for row in family_rows:
        if not isinstance(row, dict) or not _exact_party(row, child1, child2):
            continue
        if not row.get("Merlin_Id"):
            continue
        total = _num(row.get("Merlin_FullPriceParsed"))
        adult_unit = _num(row.get("Merlin_AdultPrice"))
        if total is None or adult_unit is None or total == adult_unit:
            continue

        comparison_key = _comparison_key(row)
        adults_only_total = adult_totals.get(comparison_key)
        if adults_only_total is not None:
            if adults_only_total == total:
                print("GRECOS_FAMILY_PRICE_PROOF_REJECT", comparison_key, total, adults_only_total)
                continue
            family_price_proof = "same-offer-adults-only-comparison"
            print("GRECOS_FAMILY_PRICE_PROOF", comparison_key, "family", total, "adults_only", adults_only_total)
        else:
            # If the adults-only result set does not expose the same package,
            # still refuse any value that could merely be the two-adult total.
            # Exact Children=2 is already required above; this arithmetic guard
            # deliberately sacrifices child-free edge cases rather than risk a
            # false family price.
            if total <= (2 * adult_unit):
                print("GRECOS_FAMILY_PRICE_PROOF_REJECT_NO_COMPARISON", comparison_key, total, adult_unit)
                continue
            family_price_proof = "exact-party-plus-greater-than-two-adult-units"
            print("GRECOS_FAMILY_PRICE_PROOF_FALLBACK", comparison_key, "family", total, "adult_unit", adult_unit)

        dep = _departure(row.get("Merlin_ParsedStartFullDate") or row.get("Merlin_ParsedStartDate"))
        if dep not in allowed:
            continue
        nights = _num(row.get("Merlin_Duration"))
        if nights is None or not (cfg["min_nights"] <= nights <= cfg["max_nights"]):
            continue
        meal = str(row.get("Merlin_BoardStandardDesc") or "")
        if cfg["meal_contains"].lower() not in meal.lower():
            continue
        airport_raw = str(row.get("Merlin_FlightFrom") or "")
        airport = _airport_ok(airport_raw, cfg["airports"])
        if not airport:
            continue
        stars = _stars(row.get("Hotel_Standard_Stars_Css"))
        rating, reviews = _quality(row)
        hotel = str(row.get("Hotel_Name") or row.get("Merlin_HotelName") or row.get("Merlin_HotelCode") or "Grecos")
        href = _offer_url(row)
        stable = "|".join([
            str(row.get("Merlin_HotelCode") or hotel),
            dep.isoformat(),
            str(nights),
            airport_raw,
            meal,
        ])
        key = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:16]
        if key in seen:
            continue
        seen.add(key)
        offer = {
            "key": key,
            "hotel": hotel,
            "href": href,
            "verified_href": href,
            "price": total,
            "adult_only_total": adults_only_total,
            "family_price_proof": family_price_proof,
            "departure": dep,
            "return": dep + timedelta(days=nights),
            "nights": nights,
            "airport": airport,
            "meal": meal,
            "operator": "Grecos",
            "rating": rating,
            "reviews": reviews,
            "stars": stars,
        }
        offers.append(offer)
        print("GRECOS_EXACT_LIVE_CARD", offer)
    print("GRECOS_EXACT_LIVE_COUNT", len(offers))
    return offers

def _quality_ok(offer, cfg):
    # Fail closed. We never substitute a listing/per-person price or borrow
    # quality metadata from another hotel/card.
    return (
        offer["price"] <= cfg["max_total_price_pln"]
        and offer["stars"] is not None
        and offer["stars"] >= cfg["min_stars"]
        and offer["rating"] is not None
        and offer["rating"] >= cfg["min_rating"]
        and offer["reviews"] is not None
        and offer["reviews"] >= cfg["min_reviews"]
    )


def run_grecos_watcher(cfg):
    if cfg.get("adults") != 2 or cfg.get("children_ages") != [5, 7]:
        raise RuntimeError("Grecos production adapter is locked to exact 2+2 ages 5/7")

    first = _fetch(cfg)
    qualified = [x for x in first if _quality_ok(x, cfg)]
    print("GRECOS_QUALIFIED", len(qualified))
    if first and not qualified:
        print("GRECOS_QUALITY_FAIL_CLOSED")

    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    for candidate in qualified[:10]:
        # A fresh API call is the live-availability/price second check.
        fresh = _fetch(cfg)
        confirmed = next(
            (
                x
                for x in fresh
                if x["key"] == candidate["key"]
                and x["price"] <= cfg["max_total_price_pln"]
                and _quality_ok(x, cfg)
            ),
            None,
        )
        if not confirmed:
            print("GRECOS_RECHECK_REJECT", candidate["key"])
            continue
        print("GRECOS_RECHECK_VERIFIED", confirmed["hotel"], confirmed["price"])
        if token and repo:
            create_alert(
                token,
                repo,
                cfg,
                confirmed,
                "Grecos exact 2+2 ages 5/7 + live Merlin offer + party-sensitive Merlin_FullPriceParsed; second API recheck",
            )
        else:
            print("GRECOS_DRY_ALERT", confirmed)
