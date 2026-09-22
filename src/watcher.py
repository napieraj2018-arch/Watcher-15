import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests
from selenium import webdriver
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
    return webdriver.Chrome(options=opts)

def dismiss_cookies(driver):
    for text in ["Akceptuję", "Akceptuj", "Zgadzam się", "Zaakceptuj wszystkie", "OK"]:
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

def search_url(dep: date, family: str, nights: int):
    filters = [
        f"od-{dep.isoformat()}",
        f"{nights}-dni",
        "all-inclusive",
        "z-warszawy",
        "z-warszawy-radom",
        family,
    ]
    return "https://www.wakacje.pl/lastminute/?" + ",".join(filters) + "&src=fromSearch"

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
    driver.get(url)
    WebDriverWait(driver, 30).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    time.sleep(3.5)
    dismiss_cookies(driver)
    if not ensure_family(driver, child_dobs):
        print("REJECT_PAGE family not confirmed:", participant_value(driver))
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

def collect_for_search(driver, dep: date, nights_token: int, cfg, family, child_dobs):
    url = search_url(dep, family, nights_token)
    print("SEARCH", dep.isoformat(), nights_token, url)
    if not load_page(driver, url, child_dobs):
        return []

    try_sort_cheapest(driver)

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
    for n in range(cfg["min_nights"], cfg["max_nights"] + 1):
        for item in collect_for_search(driver, dep, n, cfg, family, child_dobs):
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
    if offer["price"] > cfg["max_total_price_pln"]:
        return False
    if (offer["rating"] or 0) < cfg["min_rating"]:
        return False
    if (offer["reviews"] or 0) < cfg["min_reviews"]:
        return False
    if offer.get("stars") is not None and offer["stars"] < cfg.get("min_stars", 4):
        return False
    return True

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
    title = (
        f"{prefix}: {offer['hotel']} — {offer['price']} zł 2+2 — "
        f"{offer['departure'].strftime('%d.%m')}"
    )
    body = f"""@{cfg['notify_github_user']}

**{drop_note}**

- **Hotel:** {offer['hotel']} ({offer.get('stars', '?')}★)
- **Cena łączna 2+2:** **{offer['price']} zł**
- **Dzieci:** {', '.join(str(x) for x in cfg['children_ages'])} lat
- **Termin:** {offer['departure'].strftime('%d.%m.%Y')} – {offer['return'].strftime('%d.%m.%Y')} ({offer['nights']} nocy)
- **Wylot:** {offer['airport']}
- **Wyżywienie:** {offer['meal']}
- **Organizator:** {offer['operator']}
- **Ocena:** {offer['rating']}/10 ({offer['reviews']} opinii)
- **Weryfikacja:** {verification}, {now_local().strftime('%d.%m.%Y %H:%M:%S')} Europe/Warsaw
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

def main():
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for cfg in data.get("watchers", []):
        if not cfg.get("enabled", False):
            continue
        if cfg.get("provider") == "wakacje_pl":
            run_watcher(cfg)
        else:
            print("UNSUPPORTED_PROVIDER", cfg.get("provider"))

if __name__ == "__main__":
    main()
