import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, parse_qs, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait

TZ = ZoneInfo("Europe/Warsaw")
CONFIG_PATH = Path("config/watchers.json")
UNAVAILABLE_PHRASES = (
    "oferta niedostępna",
    "oferta nieaktualna",
    "brak miejsc",
    "wyprzedana",
    "nie znaleźliśmy tej oferty",
    "ta oferta nie jest już dostępna",
)
KNOWN_OPERATORS = (
    "Coral Travel", "Itaka", "Rainbow", "Grecos", "Exim Tours", "Join UP",
    "Sun&Fun", "Anex Poland", "Nekera", "Best Reisen", "Click&Go", "TUI",
)

def compact(s: str) -> str:
    return " ".join((s or "").split())

def now_local():
    return datetime.now(TZ)

def representative_dob(age: int, on_date: date) -> date:
    # A synthetic DOB used only to price the requested completed age.
    # Keeping it ~30 days before today's month/day prevents a birthday
    # during the imminent monitored trip.
    try:
        birthday = on_date.replace(year=on_date.year - age)
    except ValueError:
        birthday = on_date.replace(month=2, day=28, year=on_date.year - age)
    return birthday - timedelta(days=30)

def family_token(adults: int, child_ages: list[int], on_date: date):
    dobs = [representative_dob(age, on_date) for age in child_ages]
    if adults != 2 or len(dobs) != 2:
        raise RuntimeError("Current Wakacje.pl adapter supports 2 adults + 2 children.")
    return "2dorosle-2dzieci-" + "-".join(d.strftime("%Y%m%d") for d in dobs), dobs

def chrome():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1440,2600")
    opts.add_argument("--lang=pl-PL")
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(35)
    driver.set_script_timeout(20)
    return driver

def dismiss_cookies(driver):
    for text in ["Nie zezwalaj", "Akceptuję", "Akceptuj", "Zgadzam się", "Zaakceptuj wszystkie", "Zezwól na wszystkie", "OK"]:
        try:
            els = driver.find_elements(By.XPATH, f"//button[contains(normalize-space(.), '{text}')]")
            if els and els[0].is_displayed():
                els[0].click()
                time.sleep(0.4)
                return
        except Exception:
            pass

def participant_value(driver):
    try:
        return driver.find_element(
            By.CSS_SELECTOR, "input[name='CalculatorPerson']"
        ).get_attribute("value") or ""
    except Exception:
        return ""

def ensure_family(driver, child_dobs):
    value = participant_value(driver).lower()
    if "2 doros" in value and "2 dzieci" in value:
        return True

    try:
        participant = driver.find_element(By.CSS_SELECTOR, "input[name='CalculatorPerson']")
        wrapper = participant.find_element(
            By.XPATH, "./ancestor::div[contains(@class,'input-wrapper-clickable')][1]"
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", wrapper)
        driver.execute_script("arguments[0].click();", wrapper)
        time.sleep(0.6)
    except Exception:
        return False

    # Reset children to 0, then set exactly 2.
    for _ in range(4):
        try:
            minus = driver.find_element(By.XPATH, "//button[@aria-label='Odejmij jedno dziecko']")
            count = driver.find_element(
                By.XPATH, "//input[contains(@aria-label,'Aktualna liczba dzieci')]"
            ).get_attribute("value")
            if count == "0":
                break
            minus.click()
            time.sleep(0.2)
        except Exception:
            break

    try:
        for _ in range(2):
            driver.find_element(By.XPATH, "//button[@aria-label='Dodaj jedno dziecko']").click()
            time.sleep(0.25)
    except Exception:
        return False

    dob_inputs = [
        x for x in driver.find_elements(By.CSS_SELECTOR, "input[placeholder='RRRR-MM-DD']")
        if x.is_displayed()
    ]
    if len(dob_inputs) != 2:
        return False

    for inp, dob in zip(dob_inputs, child_dobs):
        inp.click()
        inp.send_keys(Keys.CONTROL, "a")
        inp.send_keys(dob.strftime("%Y-%m-%d"))
        inp.send_keys(Keys.TAB)
        time.sleep(0.3)

    try:
        choose = driver.find_element(
            By.XPATH, "//button[@aria-label='Wybierz' or normalize-space(.)='Wybierz']"
        )
        driver.execute_script("arguments[0].click();", choose)
        WebDriverWait(driver, 15).until(
            lambda d: "2 doros" in participant_value(d).lower()
            and "2 dzieci" in participant_value(d).lower()
        )
    except Exception:
        return False
    time.sleep(1.5)
    return "2 doros" in participant_value(driver).lower() and "2 dzieci" in participant_value(driver).lower()

def search_url(dep: date, family: str):
    filters = [
        f"od-{dep.isoformat()}",
        f"do-{dep.isoformat()}",
        "all-inclusive",
        "z-warszawy",
        "z-warszawy-radom",
        family,
    ]
    return "https://www.wakacje.pl/lastminute/?" + ",".join(filters) + "&src=fromSearch"

def apply_max_price_filter(driver, max_price: int):
    try:
        inp = driver.find_element(
            By.CSS_SELECTOR,
            "input[aria-label='Cena maksymalna w złotych polskich']"
        )
        current = (inp.get_attribute("value") or "").replace(" ", "")
        if current == str(max_price):
            return True
        inp.click()
        inp.send_keys(Keys.CONTROL, "a")
        inp.send_keys(str(max_price))
        inp.send_keys(Keys.TAB)
        time.sleep(2.5)
        print("PRICE_FILTER", max_price, driver.current_url)
        return True
    except Exception as e:
        print("PRICE_FILTER_WARN", type(e).__name__, str(e)[:140])
        return False

def try_sort_cheapest(driver):
    # Wakacje.pl currently exposes a sort control; use it when available.
    try:
        for sel in driver.find_elements(By.TAG_NAME, "select"):
            try:
                if "Najtańszych" in (sel.text or ""):
                    Select(sel).select_by_visible_text("Najtańszych")
                    time.sleep(2.5)
                    return True
            except Exception:
                pass
        controls = driver.find_elements(
            By.XPATH,
            "//button[contains(normalize-space(.),'Najpopularniejszych') or contains(@aria-label,'Sort')]"
        )
        for control in controls:
            if not control.is_displayed():
                continue
            driver.execute_script("arguments[0].click();", control)
            time.sleep(0.5)
            opts = driver.find_elements(
                By.XPATH,
                "//*[self::button or @role='option'][contains(normalize-space(.),'Najtańszych')]"
            )
            for opt in opts:
                if opt.is_displayed():
                    driver.execute_script("arguments[0].click();", opt)
                    time.sleep(2.5)
                    return True
    except Exception as e:
        print("SORT_WARN", type(e).__name__, str(e)[:120])
    return False

def parse_card(a):
    raw = a.text or ""
    text = compact(raw)
    href = a.get_attribute("href") or ""
    if not href or "/oferty/" not in href:
        return None

    md = re.search(r"(\d{2}\.\d{2}\.\d{4})-\s*(\d{2}\.\d{2}\.\d{4})", text)
    mp = re.search(r"(?:od\s+)?([0-9][0-9 ]{2,})\s*zł\s+za wszystkich", text, re.I)
    if not md or not mp:
        return None

    dep = datetime.strptime(md.group(1), "%d.%m.%Y").date()
    ret = datetime.strptime(md.group(2), "%d.%m.%Y").date()
    mnight = re.search(r"\(\s*\d+\s+dni\s*/\s*(\d+)\s+noc", text, re.I)
    nights = int(mnight.group(1)) if mnight else (ret - dep).days

    mr = re.search(
        r"\b(\d[.,]\d)\s+(?:Bardzo dobry|Dobry|Średni|Znakomity|Fantastyczny|Doskonały|Wyjątkowy)",
        text, re.I
    )
    mn = re.search(r"([0-9][0-9 ]*)\s+opini", text, re.I)

    if "Ultra All Inclusive" in text:
        meal = "Ultra All Inclusive"
    elif "All Inclusive" in text:
        meal = "All Inclusive"
    else:
        meal = ""

    if "Warszawa - Radom" in text:
        airport = "Warszawa - Radom"
    elif "Warszawa - Modlin" in text:
        airport = "Warszawa - Modlin"
    elif "Warszawa" in text:
        airport = "Warszawa"
    else:
        airport = ""

    operator = next((op for op in KNOWN_OPERATORS if op.lower() in text.lower()), "")

    hotel = ""
    stars = None
    try:
        for el in a.find_elements(By.XPATH, ".//*[@aria-label]"):
            aria = compact(el.get_attribute("aria-label"))
            m = re.search(r"(.+?)\s+(\d)\s+gwiazdkow", aria, re.I)
            if m:
                hotel = m.group(1).strip()
                stars = int(m.group(2))
                break
    except Exception:
        pass

    if not hotel:
        # Fallback: keep a readable identifier from URL rather than guessing from
        # flattened card text. Detail verification may replace this with H1.
        slug = urlsplit(href).path.rstrip("/").split("/")[-1]
        slug = re.sub(r"-\d+$", "", slug)
        hotel = " ".join(x.capitalize() for x in slug.split("-")) or "Hotel"

    return {
        "hotel": hotel,
        "stars": stars,
        "departure": dep,
        "return": ret,
        "nights": nights,
        "price": int(mp.group(1).replace(" ", "")),
        "rating": float(mr.group(1).replace(",", ".")) if mr else None,
        "reviews": int(mn.group(1).replace(" ", "")) if mn else None,
        "airport": airport,
        "meal": meal,
        "operator": operator,
        "href": href,
        "text": text,
    }

def load_page(driver, url, child_dobs):
    try:
        driver.get(url)
    except TimeoutException:
        print("PAGE_LOAD_TIMEOUT", url)
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass
    except WebDriverException as e:
        print("PAGE_LOAD_ERROR", type(e).__name__, str(e)[:180], url)
        return False

    try:
        WebDriverWait(driver, 15).until(
            lambda d: d.find_elements(By.TAG_NAME, "body")
        )
    except Exception:
        print("PAGE_BODY_MISSING", url)
        return False

    time.sleep(1.5)
    dismiss_cookies(driver)
    try:
        if not ensure_family(driver, child_dobs):
            print("REJECT_PAGE family not confirmed:", participant_value(driver))
            return False
    except WebDriverException as e:
        print("FAMILY_CHECK_ERROR", type(e).__name__, str(e)[:160])
        return False
    return True

def parse_current_page(driver, requested_dep: date, cfg):
    found = []
    stats = {"parsed": 0, "dep": 0, "nights": 0, "meal": 0}
    seen = set()
    for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/oferty/']"):
        try:
            item = parse_card(a)
            if not item or item["href"] in seen:
                continue
            seen.add(item["href"])
            stats["parsed"] += 1
            if item["departure"] != requested_dep:
                stats["dep"] += 1
                continue
            if not (cfg["min_nights"] <= item["nights"] <= cfg["max_nights"]):
                stats["nights"] += 1
                continue
            if cfg["meal_contains"].lower() not in item["meal"].lower():
                stats["meal"] += 1
                continue
            found.append(item)
        except Exception as e:
            print("CARD_PARSE_ERROR", type(e).__name__, str(e)[:160])
    print("PAGE_STATS", requested_dep.isoformat(), stats, "accepted", len(found))
    for x in found[:8]:
        print(
            "PAGE_MATCH", x["departure"], x["nights"], x["price"],
            x["rating"], x["reviews"], x["airport"], x["meal"], x["hotel"]
        )
    return found

def collect_for_search(driver, dep: date, cfg, family, child_dobs):
    url = search_url(dep, family)
    print("SEARCH", dep.isoformat(), url)
    if not load_page(driver, url, child_dobs):
        return []

    sorted_ok = try_sort_cheapest(driver)
    print("SORT_CHEAPEST", dep.isoformat(), sorted_ok)

    offers = []
    visited = {driver.current_url}
    queue = []

    # First page.
    offers.extend(parse_current_page(driver, dep, cfg))
    for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='str-']"):
        href = a.get_attribute("href") or ""
        if href and href not in visited and family in href:
            queue.append(href)

    # Follow a few result pages; enough after sorting by price to cover all
    # realistically relevant sub-7000 offers without turning this into a crawler.
    max_extra_pages = int(cfg.get("max_extra_pages", 3))
    extra = 0
    while queue and extra < max_extra_pages:
        page = queue.pop(0)
        if page in visited:
            continue
        visited.add(page)
        extra += 1
        print("PAGE", extra + 1, page)
        if not load_page(driver, page, child_dobs):
            continue
        offers.extend(parse_current_page(driver, dep, cfg))
        for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='str-']"):
            href = a.get_attribute("href") or ""
            if href and href not in visited and href not in queue and family in href:
                queue.append(href)

    return offers

def collect_day(driver, dep: date, cfg, family, child_dobs):
    by_href = {}
    for item in collect_for_search(driver, dep, cfg, family, child_dobs):
        old = by_href.get(item["href"])
        if old is None or item["price"] < old["price"]:
            by_href[item["href"]] = item
    offers = list(by_href.values())
    print("DAY_CANDIDATES", dep.isoformat(), len(offers))
    return offers

def with_family_token(href: str, family: str):
    parts = urlsplit(href)
    q = parts.query
    if family in q:
        return href
    if q:
        chunks = q.split("&", 1)
        first = chunks[0] + "," + family
        q = first + ("&" + chunks[1] if len(chunks) > 1 else "")
    else:
        q = family
    return urlunsplit((parts.scheme, parts.netloc, parts.path, q, parts.fragment))

def parse_totals(text: str):
    cleaned = compact(text)
    patterns = [
        r"([0-9][0-9 ]{2,})\s*zł\s*(?:za wszystkich|łącznie|razem)",
        r"(?:za wszystkich|łącznie|razem)[^0-9]{0,40}([0-9][0-9 ]{2,})\s*zł",
    ]
    vals = []
    for pat in patterns:
        for m in re.finditer(pat, cleaned, re.I):
            try:
                v = int(m.group(1).replace(" ", ""))
                if 1500 <= v <= 30000:
                    vals.append(v)
            except Exception:
                pass
    return sorted(set(vals))

def page_stars(driver):
    vals = []
    for el in driver.find_elements(By.XPATH, "//*[@aria-label]"):
        try:
            aria = compact(el.get_attribute("aria-label"))
            m = re.search(r"(\d)\s+gwiazdkow", aria, re.I)
            if m:
                vals.append(int(m.group(1)))
        except Exception:
            pass
    return max(vals) if vals else None

def verify_offer(driver, offer, cfg, family, child_dobs):
    href = with_family_token(offer["href"], family)
    print("VERIFY", offer["hotel"], offer["price"], href)
    if not load_page(driver, href, child_dobs):
        return None, "family_not_confirmed", None

    body = driver.find_element(By.TAG_NAME, "body").text
    low = body.lower()
    if any(p in low for p in UNAVAILABLE_PHRASES):
        return None, "unavailable_phrase", None

    # Confirm minimum hotel standard at detail level.
    stars = offer.get("stars") or page_stars(driver)
    if stars is None or stars < cfg.get("min_stars", 4):
        return None, f"hotel_stars_{stars}", stars

    # Confirm date and AI survived navigation.
    if offer["departure"].strftime("%d.%m.%Y") not in body:
        return None, "departure_not_confirmed", stars
    if "all inclusive" not in low:
        return None, "meal_not_confirmed", stars

    try:
        buttons = [
            b for b in driver.find_elements(
                By.XPATH,
                "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'sprawdź cenę')]"
            )
            if b.is_displayed()
        ]
        if buttons:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", buttons[0])
            driver.execute_script("arguments[0].click();", buttons[0])
            time.sleep(5)
            body = driver.find_element(By.TAG_NAME, "body").text
            low = body.lower()
            if any(p in low for p in UNAVAILABLE_PHRASES):
                return None, "unavailable_after_price_check", stars
            if not ("2 doros" in participant_value(driver).lower() and "2 dzieci" in participant_value(driver).lower()):
                return None, "family_lost_after_price_check", stars
    except Exception as e:
        print("PRICE_CHECK_CLICK_WARN", type(e).__name__, str(e)[:120])

    totals = parse_totals(body)
    if not totals:
        return None, "no_confirmed_family_total", stars

    final_price = min(totals, key=lambda x: abs(x - offer["price"]))
    return final_price, "live_family_total", stars

def qualify_listing(offer, cfg):
    price = offer.get("price")
    if price is None:
        return False
    if price < cfg.get("min_total_price_pln", 0):
        return False
    if price > cfg["max_total_price_pln"]:
        return False
    if (offer.get("rating") or 0) < cfg["min_rating"]:
        return False
    if (offer.get("reviews") or 0) < cfg["min_reviews"]:
        return False
    stars = offer.get("stars")
    if cfg.get("require_stars", True):
        if stars is None or stars < cfg.get("min_stars", 4):
            return False
    elif stars is not None and stars < cfg.get("min_stars", 4):
        return False
    return True


def departure_window_ok(offer, cfg):
    dep = offer.get("departure")
    if dep is None:
        return False, "missing_departure_date"
    local_date = now_local().date()
    allowed = [local_date + timedelta(days=int(d)) for d in cfg.get("depart_in_days", [])]
    if dep not in allowed:
        return False, "departure_outside_allowed_days"

    not_before = cfg.get("first_day_not_before")
    if not_before and allowed and dep == min(allowed):
        dep_time = None
        dt = offer.get("departure_datetime")
        if dt is not None:
            try:
                dep_time = dt.time()
            except Exception:
                dep_time = None
        if dep_time is None:
            raw = str(offer.get("departure_time") or "")
            m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", raw)
            if m:
                from datetime import time as _time
                dep_time = _time(int(m.group(1)), int(m.group(2)))
        if dep_time is None:
            return False, "thursday_evening_time_not_verified"
        hh, mm = [int(x) for x in str(not_before).split(":", 1)]
        from datetime import time as _time
        if dep_time < _time(hh, mm):
            return False, "thursday_before_evening_window"
    return True, "departure_window_verified"

def offer_key(offer):
    base = "|".join([
        offer["hotel"].lower(),
        offer["departure"].isoformat(),
        offer["return"].isoformat(),
        offer["operator"].lower(),
    ])
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]

def github_api(method, endpoint, token, repo, **kwargs):
    url = f"https://api.github.com/repos/{repo}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    r = requests.request(method, url, headers=headers, timeout=30, **kwargs)
    if r.status_code >= 300:
        raise RuntimeError(f"GitHub API {r.status_code}: {r.text[:500]}")
    return r.json() if r.text else {}

def prior_prices(token, repo, key):
    data = github_api("GET", "issues?state=all&per_page=100", token, repo)
    prices = []
    for issue in data:
        body = issue.get("body") or ""
        if f"<!-- watcher-offer-key:{key} -->" not in body:
            continue
        m = re.search(r"<!-- watcher-price:(\d+) -->", body)
        if m:
            prices.append(int(m.group(1)))
    return prices

def create_alert(token, repo, cfg, offer, verification):
    if not qualify_listing(offer, cfg):
        print("NO_ALERT_PROFILE_GATE", cfg.get("deal_profile", "default"), offer.get("hotel"), offer.get("price"))
        return False
    window_ok, window_reason = departure_window_ok(offer, cfg)
    if not window_ok:
        print("NO_ALERT_DEPARTURE_WINDOW", offer.get("hotel"), window_reason)
        return False

    key = offer_key(offer)
    previous = prior_prices(token, repo, key)
    if previous:
        best = min(previous)
        if best - offer["price"] < cfg["significant_price_drop_pln"]:
            print("NO_ALERT_DUPLICATE", offer["hotel"], offer["price"], "prior_best", best)
            return False
        drop_note = f"Spadek z najlepszego wcześniejszego alertu {best} zł."
    else:
        drop_note = "Nowa zweryfikowana oferta."

    radom = cfg["priority_airport_contains"].lower() in offer["airport"].lower()
    prefix = "🔥 RADOM" if radom else "✈️ WARSZAWA"
    deal_label = cfg.get("deal_label") or cfg.get("deal_profile") or "OFERTA"
    title = (
        f"{prefix} [{deal_label}]: {offer['hotel']} — {offer['price']} zł 2+2 — "
        f"{offer['departure'].strftime('%d.%m')}"
    )
    stars_text = f"{offer.get('stars')}★" if offer.get("stars") else "kategoria hotelu nieodczytana"
    body = f"""@{cfg['notify_github_user']}

**{drop_note}**

- **Hotel:** {offer['hotel']} ({stars_text})
- **Profil:** {cfg.get('deal_label') or cfg.get('deal_profile') or 'OFERTA'}
- **Cena łączna 2+2:** **{offer['price']} zł**
- **Dzieci:** {', '.join(str(x) for x in cfg['children_ages'])} lat
- **Termin:** {offer['departure'].strftime('%d.%m.%Y')} – {offer['return'].strftime('%d.%m.%Y')} ({offer['nights']} nocy)
- **Wylot:** {offer['airport']}
- **Wyżywienie:** {offer['meal']}
- **Organizator:** {offer['operator']}
- **Ocena:** {offer['rating']}/10 ({offer['reviews']} opinii)
- **Weryfikacja:** {verification}; {window_reason}; {now_local().strftime('%d.%m.%Y %H:%M:%S')} Europe/Warsaw
- **Oferta:** {offer['verified_href']}

Watcher potwierdził konfigurację **2 dorosłych + 2 dzieci** oraz cenę rodzinną przed alarmem.

<!-- watcher-offer-key:{key} -->
<!-- watcher-price:{offer['price']} -->
"""
    payload = {
        "title": title,
        "body": body,
        "assignees": [cfg["notify_github_user"]],
    }
    github_api("POST", "issues", token, repo, json=payload)
    print("ALERT_CREATED", title)
    return True

def run_watcher(cfg):
    local_date = now_local().date()
    family, child_dobs = family_token(cfg["adults"], cfg["children_ages"], local_date)
    target_days = [local_date + timedelta(days=d) for d in cfg["depart_in_days"]]
    print("WATCHER_DATE", local_date.isoformat())
    print("TARGET_DAYS", [d.isoformat() for d in target_days])
    print("FAMILY", f"{cfg['adults']} adults + {len(cfg['children_ages'])} children ages {cfg['children_ages']}")

    driver = chrome()
    try:
        all_offers = {}
        for dep in target_days:
            for offer in collect_day(driver, dep, cfg, family, child_dobs):
                key = (urlsplit(offer["href"]).path, offer["departure"], offer["return"], offer["operator"])
                old = all_offers.get(key)
                if old is None or offer["price"] < old["price"]:
                    all_offers[key] = offer

        candidates = [x for x in all_offers.values() if qualify_listing(x, cfg)]
        candidates.sort(key=lambda x: (
            0 if cfg["priority_airport_contains"].lower() in x["airport"].lower() else 1,
            -(x["rating"] or 0),
            x["price"],
        ))
        print("STRICT_CANDIDATES", len(candidates))
        for x in candidates:
            print(
                "CANDIDATE", x["hotel"], x["price"], x["rating"],
                x["reviews"], x["stars"], x["airport"], x["href"]
            )

        token = os.getenv("GITHUB_TOKEN", "")
        repo = os.getenv("GITHUB_REPOSITORY", "")
        alerts = 0

        for offer in candidates[:12]:
            final_price, verification, stars = verify_offer(
                driver, offer, cfg, family, child_dobs
            )
            if final_price is None:
                print("REJECT_VERIFY", offer["hotel"], verification)
                continue
            offer["price"] = final_price
            offer["stars"] = stars
            if offer["price"] > cfg["max_total_price_pln"]:
                print("REJECT_PRICE_AFTER_VERIFY", offer["hotel"], offer["price"])
                continue

            offer["verified_href"] = with_family_token(offer["href"], family)
            if token and repo:
                if create_alert(token, repo, cfg, offer, verification):
                    alerts += 1
            else:
                print("DRY_ALERT", offer)
        print("ALERTS_CREATED", alerts)
    finally:
        driver.quit()


TUI_BASE_URL = "https://www.tui.pl/last-minute-z-warszawy"

def tui_pick_birth_date(driver, button_index: int, dob: date):
    births = [
        b for b in driver.find_elements(By.CSS_SELECTOR, "button[data-testid='birth-date-button']")
        if b.is_displayed()
    ]
    if button_index >= len(births):
        raise RuntimeError("TUI birth date button missing")
    driver.execute_script("arguments[0].click();", births[button_index])
    time.sleep(0.45)
    cal = driver.find_element(By.CSS_SELECTOR, "div[data-testid='birth-date-calendar']")

    for _ in range(5):
        years = [
            x for x in cal.find_elements(
                By.CSS_SELECTOR, ".react-calendar__decade-view__years button"
            ) if x.is_displayed()
        ]
        match = [x for x in years if compact(x.text) == str(dob.year)]
        if match:
            driver.execute_script("arguments[0].click();", match[0])
            break

        label = compact(
            cal.find_element(By.CSS_SELECTOR, ".react-calendar__navigation__label").text
        )
        nums = [int(x) for x in re.findall(r"\d{4}", label)]
        if nums and dob.year < min(nums):
            btn = cal.find_element(
                By.CSS_SELECTOR, ".react-calendar__navigation__prev-button"
            )
        else:
            btn = cal.find_element(
                By.CSS_SELECTOR, ".react-calendar__navigation__next-button"
            )
        if not btn.is_enabled():
            raise RuntimeError(f"TUI cannot navigate to year {dob.year}")
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(0.35)
    else:
        raise RuntimeError(f"TUI year not found: {dob.year}")

    time.sleep(0.35)
    months = [
        x for x in cal.find_elements(
            By.CSS_SELECTOR, ".react-calendar__year-view__months button"
        ) if x.is_displayed()
    ]
    if len(months) < 12:
        raise RuntimeError("TUI month picker incomplete")
    driver.execute_script("arguments[0].click();", months[dob.month - 1])
    time.sleep(0.35)

    days = [
        x for x in cal.find_elements(
            By.CSS_SELECTOR, ".react-calendar__month-view__days button"
        ) if x.is_displayed()
    ]
    target = None
    for x in days:
        txt = compact(x.text)
        cls = x.get_attribute("class") or ""
        aria = (x.get_attribute("aria-label") or "").lower()
        if (
            txt == str(dob.day)
            and "neighboringMonth" not in cls
            and (str(dob.year) in aria or not aria)
        ):
            target = x
            break
    if target is None:
        raise RuntimeError(f"TUI day not found: {dob.isoformat()}")
    driver.execute_script("arguments[0].click();", target)
    time.sleep(0.55)

def tui_build_search_url(cfg, child_dobs):
    dob1 = child_dobs[0].strftime("%d.%m.%Y")
    dob2 = child_dobs[1].strftime("%d.%m.%Y")
    q = (
        ":price:byPlane:T"
        ":additionalType:GT03%23TUZ-LAST25"
        ":a:WAW"
        f":dF:{cfg['min_nights']}"
        f":dT:{cfg['max_nights']}"
        ":ctAdult:2"
        ":ctChild:2"
        f":birthDate:{dob1}"
        f":birthDate:{dob2}"
        f":room:2-{dob1}-{dob2}"
        ":minHotelCategory:defaultHotelCategory"
        ":tripAdvisorRating:defaultTripAdvisorRating"
        ":beach_distance:defaultBeachDistance"
        ":flightDuration:defaultFlightDuration"
        ":tripType:WS"
    )
    return f"{TUI_BASE_URL}?q={quote(q, safe='')}&fullPrice=false"

def tui_configure_family(driver, cfg, child_dobs):
    url = tui_build_search_url(cfg, child_dobs)
    driver.get(url)
    WebDriverWait(driver, 45).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    time.sleep(4.0)
    dismiss_cookies(driver)

    # Verify TUI actually accepted the encoded family parameters.
    participant_text = ""
    try:
        participant_text = compact(
            driver.find_element(
                By.CSS_SELECTOR, "button[data-testid='dropdown-field--participants']"
            ).text
        ).lower()
    except Exception:
        pass

    current = driver.current_url
    if "birthdate" not in current.lower():
        raise RuntimeError("TUI direct family URL lost birthDate parameters")
    if participant_text and (
        "2 doros" not in participant_text or "2 dzieci" not in participant_text
    ):
        raise RuntimeError(f"TUI family not confirmed: {participant_text}")

    return current

def tui_collect_tiles(driver, cfg, target_days):
    # TUI is already price-ascending on this page. Scroll until the number
    # of tiles stops increasing so imminent departures are not missed.
    stable = 0
    last = -1
    for _ in range(12):
        tiles = driver.find_elements(By.CSS_SELECTOR, "[data-testid='offer-tile']")
        count = len(tiles)
        if count == last:
            stable += 1
        else:
            stable = 0
            last = count
        if stable >= 2:
            break
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.8)

    target_set = set(target_days)
    offers = []
    seen = set()
    for tile in driver.find_elements(By.CSS_SELECTOR, "[data-testid='offer-tile']"):
        try:
            text = compact(tile.text)
            if cfg["meal_contains"].lower() not in text.lower():
                continue

            date_el = tile.find_element(
                By.CSS_SELECTOR, "[data-testid='offer-tile-departure-date']"
            )
            md = re.search(
                r"(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4}).*?\((\d+)\s+noc",
                compact(date_el.text),
                re.I,
            )
            if not md:
                continue
            dep = datetime.strptime(md.group(1), "%d.%m.%Y").date()
            ret = datetime.strptime(md.group(2), "%d.%m.%Y").date()
            nights = int(md.group(3))
            if dep not in target_set:
                continue
            if not (cfg["min_nights"] <= nights <= cfg["max_nights"]):
                continue

            mr = re.search(r"\b(\d[.,]\d)\s*/\s*5\b", text)
            mn = re.search(r"([0-9][0-9 ]*)\s+opini", text, re.I)
            rating5 = float(mr.group(1).replace(",", ".")) if mr else None
            rating10 = rating5 * 2 if rating5 is not None else None
            reviews = int(mn.group(1).replace(" ", "")) if mn else None
            if (rating10 or 0) < cfg["min_rating"]:
                continue
            if (reviews or 0) < cfg["min_reviews"]:
                continue

            anchor = tile.find_element(By.CSS_SELECTOR, "a[href*='/wypoczynek/']")
            href = anchor.get_attribute("href") or ""
            if not href or href in seen:
                continue
            seen.add(href)
            hotel = compact(anchor.get_attribute("hotelname")) or "Hotel TUI"
            region = compact(anchor.get_attribute("destination"))
            try:
                airport = compact(
                    tile.find_element(
                        By.CSS_SELECTOR, "button[data-testid='dropdown-field--same-day-offers']"
                    ).text
                )
                airport = re.sub(r"\s*\([^)]*\)\s*$", "", airport)
            except Exception:
                airport = "Warszawa-Chopina"

            offers.append({
                "hotel": hotel,
                "stars": None,
                "departure": dep,
                "return": ret,
                "nights": nights,
                "price": None,
                "rating": rating10,
                "reviews": reviews,
                "airport": airport,
                "meal": "All Inclusive",
                "operator": "TUI",
                "href": href,
                "verified_href": href,
                "region": region,
                "text": text,
            })
        except Exception as e:
            print("TUI_TILE_PARSE_WARN", type(e).__name__, str(e)[:160])

    offers.sort(key=lambda x: (-(x["rating"] or 0), -(x["reviews"] or 0)))
    print("TUI_IMMINENT_CANDIDATES", len(offers))
    for x in offers[:12]:
        print(
            "TUI_CANDIDATE", x["hotel"], x["departure"], x["nights"],
            x["rating"], x["reviews"], x["airport"], x["href"]
        )
    return offers

def tui_parse_family_total(body: str):
    lines = [compact(x) for x in body.splitlines() if compact(x)]
    for i, line in enumerate(lines):
        if line.lower().rstrip(":") == "cena razem":
            # On TUI the selected package total is the first money amount
            # immediately after the label.
            for nxt in lines[i + 1:i + 4]:
                m = re.search(r"([0-9][0-9 ]{2,})\s*zł", nxt, re.I)
                if not m:
                    continue
                value = int(m.group(1).replace(" ", ""))
                if 1500 <= value <= 30000:
                    return value
    return None

def tui_page_stars(driver):
    stars = page_stars(driver)
    if stars is not None:
        return stars
    try:
        body = compact(driver.find_element(By.TAG_NAME, "body").text)
        patterns = [
            r"\b([1-5])\s*gwiazdek\b",
            r"\b([1-5])\s*gwiazdki\b",
            r"\bhotel\s+([1-5])\s*gwiazdk",
        ]
        for pat in patterns:
            m = re.search(pat, body, re.I)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None

def tui_verify_offer(driver, offer, cfg):
    print("TUI_VERIFY", offer["hotel"], offer["href"])
    driver.get(offer["href"])
    WebDriverWait(driver, 45).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    time.sleep(5.0)
    dismiss_cookies(driver)

    body = driver.find_element(By.TAG_NAME, "body").text
    low = body.lower()
    if any(p in low for p in UNAVAILABLE_PHRASES):
        return None, "tui_unavailable", None
    if not (
        ("2 dorosłych + 2 dzieci" in low)
        or ("2 dorosłych, 2 dzieci" in low)
    ):
        return None, "tui_family_not_confirmed", None
    if offer["departure"].strftime("%d.%m.%Y") not in body:
        return None, "tui_departure_not_confirmed", None
    if "all inclusive" not in low:
        return None, "tui_meal_not_confirmed", None

    stars = tui_page_stars(driver)
    if stars is not None and stars < cfg.get("min_stars", 4):
        return None, f"tui_hotel_stars_{stars}", stars
    if cfg.get("require_stars", False) and stars is None:
        return None, "tui_stars_not_confirmed", None

    total = tui_parse_family_total(body)
    if total is None:
        return None, "tui_no_family_total", stars
    return total, "tui_detail_family_total", stars

def run_tui_watcher(cfg):
    local_date = now_local().date()
    child_dobs = [representative_dob(age, local_date) for age in cfg["children_ages"]]
    target_days = [local_date + timedelta(days=d) for d in cfg["depart_in_days"]]
    print("TUI_WATCHER_DATE", local_date.isoformat())
    print("TUI_TARGET_DAYS", [d.isoformat() for d in target_days])

    driver = chrome()
    try:
        try:
            search_url = tui_configure_family(driver, cfg, child_dobs)
        except Exception as e:
            print("TUI_SOURCE_ERROR", type(e).__name__, str(e)[:300])
            return
        print("TUI_FAMILY_SEARCH_URL", search_url)
        candidates = tui_collect_tiles(driver, cfg, target_days)

        token = os.getenv("GITHUB_TOKEN", "")
        repo = os.getenv("GITHUB_REPOSITORY", "")
        alerts = 0
        for offer in candidates[:15]:
            total, verification, stars = tui_verify_offer(driver, offer, cfg)
            if total is None:
                print("TUI_REJECT_VERIFY", offer["hotel"], verification)
                continue
            offer["price"] = total
            offer["stars"] = stars
            if total > cfg["max_total_price_pln"]:
                print("TUI_REJECT_PRICE", offer["hotel"], total)
                continue

            if token and repo:
                if create_alert(token, repo, cfg, offer, verification):
                    alerts += 1
            else:
                print("TUI_DRY_ALERT", offer)
        print("TUI_ALERTS_CREATED", alerts)
    finally:
        driver.quit()


ITAKA_BASE_URL = "https://www.itaka.pl/last-minute/"

def itaka_family_url(cfg, child_dobs):
    from urllib.parse import urlencode
    params = {
        "adults[0]": str(cfg["adults"]),
        "children[0]": ",".join(d.strftime("%d.%m.%Y") for d in child_dobs),
    }
    return ITAKA_BASE_URL + "?" + urlencode(params)

def itaka_review_count(text):
    vals=[]
    for m in re.finditer(r"(?<![/\d])(\d{1,5})\s+opini", text, re.I):
        try:
            vals.append(int(m.group(1)))
        except Exception:
            pass
    return max(vals) if vals else None

def itaka_collect_candidates(driver, cfg, target_days, family_url):
    driver.get(family_url)
    WebDriverWait(driver, 45).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    time.sleep(4)
    dismiss_cookies(driver)

    current=driver.current_url.lower()
    if "children%5b0%5d" not in current and "children[0]" not in current:
        raise RuntimeError("ITAKA lost child parameters")

    # Load more tiles by scrolling.
    last=-1
    stable=0
    for _ in range(14):
        tiles=driver.find_elements(By.CSS_SELECTOR,"[data-testid='offer-list-item']")
        n=len(tiles)
        stable = stable+1 if n==last else 0
        last=n
        if stable>=2:
            break
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.8)

    targets={d.strftime("%d.%m") for d in target_days}
    offers=[]
    seen=set()
    for tile in driver.find_elements(By.CSS_SELECTOR,"[data-testid='offer-list-item']"):
        try:
            txt=compact(tile.text)
            if not any(t in txt for t in targets):
                continue
            if cfg["meal_contains"].lower() not in txt.lower():
                continue
            if not any(ap.lower() in txt.lower() for ap in ["Warszawa","Modlin","Radom"]):
                continue

            md=re.search(
                r"(\d{2}\.\d{2})\s*-\s*(\d{1,2}\.\d{1,2}\.\d{4})\s*\((\d+)\s+dni",
                txt, re.I
            )
            if not md:
                continue
            dep=datetime.strptime(md.group(1)+f".{now_local().year}","%d.%m.%Y").date()
            ret=datetime.strptime(md.group(2),"%d.%m.%Y").date()
            nights=max(1,int(md.group(3))-1)
            if dep not in target_days:
                continue
            if not (cfg["min_nights"] <= nights <= cfg["max_nights"]):
                continue

            mr=re.search(r"(\d[.,]\d)\s*/\s*6\b",txt)
            rating6=float(mr.group(1).replace(",",".")) if mr else None
            rating10=(rating6/6*10) if rating6 is not None else None
            reviews=itaka_review_count(txt)
            if (rating10 or 0) < cfg["min_rating"] or (reviews or 0) < cfg["min_reviews"]:
                continue

            mp=re.search(r"([0-9][0-9 ]{2,})\s*zł\s*/\s*os",txt,re.I)
            pp=int(mp.group(1).replace(" ","")) if mp else None
            # A 7000 PLN family package is extremely unlikely above this /person
            # level; keep generous headroom to avoid false negatives from child discounts.
            if pp is not None and pp > cfg.get("max_listing_per_person_pln", 3200):
                continue

            a=tile.find_element(By.CSS_SELECTOR,"a[href*='/wczasy/']")
            href=a.get_attribute("href") or ""
            if not href or href in seen:
                continue
            seen.add(href)

            # The whole tile starts with destination then hotel name. Prefer link metadata,
            # fall back to URL slug without inventing a different property.
            hotel=compact(a.get_attribute("title"))
            if not hotel:
                path=urlsplit(href).path.rstrip("/").split("/")[-1]
                hotel=path.split(",")[0].replace("-"," ").title()

            airport="Warszawa"
            departure_time=None
            for ap in ["Warszawa-Radom","Warszawa-Modlin","Warszawa-Okęcie","Warszawa"]:
                if ap.lower() in txt.lower():
                    airport=ap
                    tm=re.search(re.escape(ap)+r"[^\d]{0,80}([0-2]?\d:[0-5]\d)",txt,re.I)
                    if tm:
                        departure_time=tm.group(1)
                    break

            offer_token=(parse_qs(urlsplit(href).query).get("id[0]") or [None])[0]
            offers.append({
                "hotel":hotel or "Hotel ITAKA",
                "stars":None,
                "departure":dep,
                "return":ret,
                "nights":nights,
                "price":None,
                "listing_pp":pp,
                "rating":rating10,
                "reviews":reviews,
                "airport":airport,
                "meal":"All Inclusive",
                "operator":"ITAKA",
                "departure_time":departure_time,
                "offer_token":offer_token,
                "href":href,
                "verified_href":href,
                "text":txt,
            })
        except Exception as e:
            print("ITAKA_TILE_WARN",type(e).__name__,str(e)[:180])

    offers.sort(key=lambda x:(x["listing_pp"] or 999999,-(x["rating"] or 0),-(x["reviews"] or 0)))
    print("ITAKA_CANDIDATES",len(offers))
    for x in offers[:20]:
        print("ITAKA_CANDIDATE",x["hotel"],x["departure"],x["nights"],x["listing_pp"],x["rating"],x["reviews"],x["href"])
    return offers

def itaka_parse_total(body):
    cleaned=compact(body)
    patterns=[
        r"(?:Łącznie|Lacznie)\s*:\s*([0-9][0-9 ]{2,})\s*zł",
        r"([0-9][0-9 ]{2,})\s*zł\s*(?:łącznie|lacznie)",
    ]
    vals=[]
    for pat in patterns:
        for m in re.finditer(pat,cleaned,re.I):
            try:
                v=int(m.group(1).replace(" ",""))
                if 1500 <= v <= 40000:
                    vals.append(v)
            except Exception:
                pass
    return vals[0] if vals else None

def itaka_verify_offer(driver, offer, cfg, child_dobs):
    print("ITAKA_VERIFY",offer["hotel"],offer["href"])
    driver.get(offer["href"])
    WebDriverWait(driver,45).until(
        lambda d:d.execute_script("return document.readyState")=="complete"
    )
    time.sleep(5)
    dismiss_cookies(driver)

    current=driver.current_url.lower()
    if "children%5b0%5d" not in current and "children[0]" not in current:
        return None,"itaka_family_parameters_lost",None

    # Verify both synthetic child DOBs remain encoded in the live detail URL.
    for dob in child_dobs:
        raw=dob.strftime("%d.%m.%Y").lower()
        enc=raw.replace(".","%2e")
        if raw not in current and enc not in current:
            # URL encoders usually keep dots, but fail closed if ITAKA changes this.
            return None,"itaka_child_dob_lost",None

    body=driver.find_element(By.TAG_NAME,"body").text
    source=driver.page_source
    low=body.lower()
    if any(p in low for p in UNAVAILABLE_PHRASES):
        return None,"itaka_unavailable",None

    # The result-card URL carries ITAKA's concrete offer token. Require that
    # exact token to survive navigation, then confirm the departure date in
    # either visible text or embedded page state. This avoids falsely rejecting
    # offers when the date is rendered only inside hydrated JSON.
    current_token=(parse_qs(urlsplit(driver.current_url).query).get("id[0]") or [None])[0]
    if offer.get("offer_token") and current_token != offer.get("offer_token"):
        return None,"itaka_offer_token_changed",None
    dep_markers=[
        offer["departure"].strftime("%d.%m"),
        offer["departure"].strftime("%d.%m.%Y"),
        offer["departure"].isoformat(),
    ]
    if not any(m in body or m in source for m in dep_markers):
        return None,"itaka_departure_not_confirmed",None

    # Capture the departure clock when ITAKA exposes it. Thursday offers are
    # not eligible until the clock is known and satisfies the configured
    # evening threshold; Friday/Saturday need no time restriction.
    if not offer.get("departure_time"):
        esc=re.escape(offer["departure"].strftime("%d.%m"))
        for hay in (body,compact(re.sub(r"<[^>]+>"," ",source))):
            mt=re.search(esc+r".{0,500}?([0-2]?\d:[0-5]\d)",hay,re.I)
            if mt:
                offer["departure_time"]=mt.group(1)
                print("ITAKA_DEPARTURE_TIME",offer["hotel"],offer["departure_time"])
                break

    if "all inclusive" not in low:
        return None,"itaka_meal_not_confirmed",None

    total=itaka_parse_total(body)
    if total is None:
        return None,"itaka_no_family_total",None

    stars=page_stars(driver)
    # ITAKA sometimes renders category as graphics without accessible star labels.
    if stars is not None and stars < cfg.get("min_stars",4):
        return None,f"itaka_hotel_stars_{stars}",stars

    return total,"itaka_detail_exact_2plus2_total",stars

def run_itaka_watcher(cfg):
    local_date=now_local().date()
    child_dobs=[representative_dob(age,local_date) for age in cfg["children_ages"]]
    target_days=[local_date+timedelta(days=d) for d in cfg["depart_in_days"]]
    family_url=itaka_family_url(cfg,child_dobs)
    print("ITAKA_TARGET_DAYS",[d.isoformat() for d in target_days])
    print("ITAKA_FAMILY_URL",family_url)

    driver=chrome()
    try:
        try:
            candidates=itaka_collect_candidates(driver,cfg,target_days,family_url)
        except Exception as e:
            print("ITAKA_SOURCE_ERROR",type(e).__name__,str(e)[:300])
            return

        token=os.getenv("GITHUB_TOKEN","")
        repo=os.getenv("GITHUB_REPOSITORY","")
        alerts=0
        for offer in candidates[:cfg.get("max_detail_checks",15)]:
            total,verification,stars=itaka_verify_offer(driver,offer,cfg,child_dobs)
            if total is None:
                print("ITAKA_REJECT_VERIFY",offer["hotel"],verification)
                continue
            offer["price"]=total
            offer["stars"]=stars
            if total > cfg["max_total_price_pln"]:
                print("ITAKA_REJECT_PRICE",offer["hotel"],total)
                continue
            if token and repo:
                if create_alert(token,repo,cfg,offer,verification):
                    alerts+=1
            else:
                print("ITAKA_DRY_ALERT",offer)
        print("ITAKA_ALERTS_CREATED",alerts)
    finally:
        driver.quit()


RAINBOW_BASE_URL = "https://r.pl/wyloty-z-warszawy"

def rainbow_adult_dobs(local_date):
    # Stable synthetic adult DOBs; only child completed ages matter to discounts.
    return [date(1990,1,15), date(1990,1,15)]

def rainbow_search_url(cfg, dep, adult_dobs, child_dobs):
    from urllib.parse import urlencode
    pairs=[
        ("dlugoscPobytu",f"{cfg['min_nights']}-{cfg['max_nights']}"),
        ("dlugoscPobytu.od",str(cfg["min_nights"])),
        ("dlugoscPobytu.do",str(cfg["max_nights"])),
        ("cena","avg"),("cena.od",""),("cena.do",""),
        ("ocenaKlientow","*-*"),("odlegloscLotnisko","*-*"),
        ("dlugoscPobytu.od.force","t"),("dlugoscPobytu.do.force","t"),
        ("cena.od.force","t"),("cena.do.force","t"),
        ("wybraneSkad","WAW"),("wybraneSkad","WMI"),("wybraneSkad","RDO"),
        ("typTransportu","AIR"),
        ("data",dep.isoformat()),("dataWylotu",dep.isoformat()),
    ]
    for dob in adult_dobs:
        pairs.append(("dorosli",dob.isoformat()))
    for dob in child_dobs:
        pairs.append(("dzieci",dob.isoformat()))
    pairs += [
        ("liczbaPokoi","1"),("dowolnaLiczbaPokoi","nie"),
        ("hotelUrl",""),("produktUrl",""),("sortowanie","cena-asc"),
    ]
    return RAINBOW_BASE_URL+"?"+urlencode(pairs,doseq=True)

def rainbow_collect_day(driver,cfg,dep,adult_dobs,child_dobs):
    url=rainbow_search_url(cfg,dep,adult_dobs,child_dobs)
    print("RAINBOW_SEARCH",dep.isoformat(),url)
    driver.get(url)
    WebDriverWait(driver,45).until(
        lambda d:d.execute_script("return document.readyState")=="complete"
    )
    time.sleep(4)
    dismiss_cookies(driver)

    body=driver.find_element(By.TAG_NAME,"body").text
    if "4 osoby" not in body:
        print("RAINBOW_REJECT_PAGE party_not_4")
        return []

    offers=[]
    seen=set()
    for a in driver.find_elements(By.TAG_NAME,"a"):
        try:
            href=a.get_attribute("href") or ""
            txt=compact(a.text)
            if not href or not txt or "SZCZEGÓŁY" not in txt:
                continue
            if href in seen:
                continue
            if cfg["meal_contains"].lower() not in txt.lower():
                continue
            if "objazd" in txt.lower():
                continue
            if dep.strftime("%d.%m.%Y") not in txt:
                continue

            md=re.search(r"(\d{2}\.\d{2}\.\d{4})\s*\((\d+)\s+dni\s*/\s*(\d+)\s+noc",txt,re.I)
            if not md:
                continue
            nights=int(md.group(3))
            if not (cfg["min_nights"] <= nights <= cfg["max_nights"]):
                continue

            mr=re.search(r"(\d[.,]\d)\s*/\s*6\s*\((\d+)\s+opini",txt,re.I)
            if not mr:
                continue
            rating6=float(mr.group(1).replace(",","."))
            rating10=rating6/6*10
            reviews=int(mr.group(2))
            if rating10 < cfg["min_rating"] or reviews < cfg["min_reviews"]:
                continue

            mp=re.search(r"([0-9][0-9 ]{2,})\s*zł\s*/\s*os",txt,re.I)
            pp=int(mp.group(1).replace(" ","")) if mp else None
            if pp is not None and pp > cfg.get("max_listing_per_person_pln",3000):
                continue

            path=urlsplit(href).path.rstrip("/").split("/")[-1]
            hotel=path.replace("-"," ").title()
            airport="Warszawa"
            for ap in ["Warszawa Radom","Warszawa Modlin","Warszawa Chopin","Warszawa"]:
                if ap.lower() in txt.lower():
                    airport=ap.replace(" ","-",1) if ap!="Warszawa" else ap
                    break
            ret=dep+timedelta(days=nights)

            seen.add(href)
            offers.append({
                "hotel":hotel,
                "stars":None,
                "departure":dep,
                "return":ret,
                "nights":nights,
                "price":None,
                "listing_pp":pp,
                "rating":rating10,
                "reviews":reviews,
                "airport":airport,
                "meal":"All Inclusive",
                "operator":"Rainbow",
                "href":href,
                "verified_href":href,
                "text":txt,
            })
        except Exception as e:
            print("RAINBOW_TILE_WARN",type(e).__name__,str(e)[:180])

    offers.sort(key=lambda x:(x["listing_pp"] or 999999,-(x["rating"] or 0),-(x["reviews"] or 0)))
    print("RAINBOW_DAY_CANDIDATES",dep.isoformat(),len(offers))
    return offers

def rainbow_force_family_url(detail_url,adult_dobs,child_dobs):
    from urllib.parse import parse_qsl, urlencode
    parts=urlsplit(detail_url)
    pairs=parse_qsl(parts.query,keep_blank_values=True)
    pairs=[p for p in pairs if p[0]!="wiek"]
    for dob in adult_dobs+child_dobs:
        pairs.append(("wiek",dob.isoformat()))
    if not any(k=="liczbaPokoi" for k,v in pairs):
        pairs.append(("liczbaPokoi","1"))
    return urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(pairs,doseq=True),parts.fragment))

def rainbow_parse_total(body):
    m=re.search(r"Cena\s+razem\s*:\s*([0-9][0-9 ]{2,})\s*zł",compact(body),re.I)
    if not m:
        return None
    v=int(m.group(1).replace(" ",""))
    return v if 1500 <= v <= 40000 else None

def rainbow_stars(body):
    for pat in [r"hotel(?:u)?\s+([1-5])\s*\*",r"\b([1-5])\s*\*\s*,"]:
        m=re.search(pat,body,re.I)
        if m:
            return int(m.group(1))
    return None

def rainbow_verify_offer(driver,offer,cfg,adult_dobs,child_dobs):
    print("RAINBOW_VERIFY",offer["hotel"],offer["href"])

    # Re-open the exact departure-day result page before entering the hotel.
    # Rainbow's plain hotel URL may otherwise select a different/default date.
    search=rainbow_search_url(cfg,offer["departure"],adult_dobs,child_dobs)
    driver.get(search)
    WebDriverWait(driver,45).until(
        lambda d:d.execute_script("return document.readyState")=="complete"
    )
    time.sleep(3.5)
    dismiss_cookies(driver)

    target_path=urlsplit(offer["href"]).path.rstrip("/")
    clicked=False
    for a in driver.find_elements(By.TAG_NAME,"a"):
        try:
            href=a.get_attribute("href") or ""
            txt=compact(a.text)
            if urlsplit(href).path.rstrip("/") != target_path:
                continue
            if "SZCZEGÓŁY" not in txt:
                continue
            if offer["departure"].strftime("%d.%m.%Y") not in txt:
                continue
            driver.execute_script("arguments[0].click();",a)
            clicked=True
            break
        except Exception:
            pass

    if not clicked:
        return None,"rainbow_exact_listing_link_not_found",None,None

    WebDriverWait(driver,45).until(
        lambda d:d.execute_script("return document.readyState")=="complete"
    )
    time.sleep(4)

    # The listing click gives Rainbow the concrete offer key/date; now add all
    # four DOBs explicitly so detail pricing remains exact 2+2.
    family_url=rainbow_force_family_url(driver.current_url,adult_dobs,child_dobs)
    driver.get(family_url)
    WebDriverWait(driver,45).until(
        lambda d:d.execute_script("return document.readyState")=="complete"
    )
    time.sleep(4)

    current=driver.current_url
    for dob in adult_dobs+child_dobs:
        if dob.isoformat() not in current:
            return None,"rainbow_party_parameter_lost",None,None

    body=driver.find_element(By.TAG_NAME,"body").text
    low=body.lower()
    if any(p in low for p in UNAVAILABLE_PHRASES):
        return None,"rainbow_unavailable",None,None
    if offer["departure"].strftime("%d.%m.%Y") not in body:
        return None,"rainbow_departure_not_confirmed",None,None
    if "all inclusive" not in low:
        return None,"rainbow_meal_not_confirmed",None,None

    total=rainbow_parse_total(body)
    if total is None:
        return None,"rainbow_no_family_total",None,None
    stars=rainbow_stars(body) or page_stars(driver)
    if stars is not None and stars < cfg.get("min_stars",4):
        return None,f"rainbow_hotel_stars_{stars}",stars,None
    return total,"rainbow_detail_exact_2plus2_total",stars,current

def run_rainbow_watcher(cfg):
    local_date=now_local().date()
    adult_dobs=rainbow_adult_dobs(local_date)
    child_dobs=[representative_dob(age,local_date) for age in cfg["children_ages"]]
    target_days=[local_date+timedelta(days=d) for d in cfg["depart_in_days"]]
    driver=chrome()
    try:
        offers=[]
        for dep in target_days:
            offers.extend(rainbow_collect_day(driver,cfg,dep,adult_dobs,child_dobs))
        # Deduplicate same hotel/date.
        unique={}
        for x in offers:
            key=(x["hotel"],x["departure"])
            old=unique.get(key)
            if old is None or (x["listing_pp"] or 999999)<(old["listing_pp"] or 999999):
                unique[key]=x
        candidates=list(unique.values())
        candidates.sort(key=lambda x:(x["listing_pp"] or 999999,-(x["rating"] or 0)))
        print("RAINBOW_CANDIDATES",len(candidates))

        token=os.getenv("GITHUB_TOKEN","")
        repo=os.getenv("GITHUB_REPOSITORY","")
        alerts=0
        for offer in candidates[:cfg.get("max_detail_checks",15)]:
            total,verification,stars,verified_url=rainbow_verify_offer(
                driver,offer,cfg,adult_dobs,child_dobs
            )
            if total is None:
                print("RAINBOW_REJECT_VERIFY",offer["hotel"],verification)
                continue
            offer["price"]=total
            offer["stars"]=stars
            offer["verified_href"]=verified_url or offer["href"]
            if total > cfg["max_total_price_pln"]:
                print("RAINBOW_REJECT_PRICE",offer["hotel"],total)
                continue
            if token and repo:
                if create_alert(token,repo,cfg,offer,verification):
                    alerts+=1
            else:
                print("RAINBOW_DRY_ALERT",offer)
        print("RAINBOW_ALERTS_CREATED",alerts)
    finally:
        driver.quit()

def main():
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    provider_filter = os.getenv("WATCHER_PROVIDER", "").strip()
    for cfg in data.get("watchers", []):
        if not cfg.get("enabled", False):
            continue
        if provider_filter and cfg.get("provider") != provider_filter:
            continue
        if cfg.get("provider") == "wakacje_pl":
            run_watcher(cfg)
        elif cfg.get("provider") == "tui_pl":
            run_tui_watcher(cfg)
        else:
            print("UNSUPPORTED_PROVIDER", cfg.get("provider"))

if __name__ == "__main__":
    main()
