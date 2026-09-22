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
from selenium.webdriver.support.ui import WebDriverWait

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

def compact(s: str) -> str:
    return " ".join((s or "").split())

def now_local():
    return datetime.now(TZ)

def representative_dob(age: int, on_date: date) -> date:
    # Representative DOB used only to make a booking engine price the requested age.
    # It is deliberately not a real child's DOB.
    try:
        birthday = on_date.replace(year=on_date.year - age)
    except ValueError:
        birthday = on_date.replace(month=2, day=28, year=on_date.year - age)
    return birthday - timedelta(days=30)

def family_token(adults: int, child_ages: list[int], on_date: date):
    dobs = [representative_dob(age, on_date) for age in child_ages]
    if adults != 2 or len(dobs) != 2:
        raise RuntimeError("Current Wakacje.pl adapter supports 2 adults + 2 children.")
    token = "2dorosle-2dzieci-" + "-".join(d.strftime("%Y%m%d") for d in dobs)
    return token, dobs

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
                time.sleep(0.5)
                return
        except Exception:
            pass

def participant_value(driver):
    try:
        return driver.find_element(By.CSS_SELECTOR, "input[name='CalculatorPerson']").get_attribute("value") or ""
    except Exception:
        return ""

def ensure_family(driver, child_dobs):
    value = participant_value(driver).lower()
    if "2 dzieci" in value:
        return True

    try:
        participant = driver.find_element(By.CSS_SELECTOR, "input[name='CalculatorPerson']")
    except Exception:
        return False
    wrapper = participant.find_element(By.XPATH, "./ancestor::div[contains(@class,'input-wrapper-clickable')][1]")
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", wrapper)
    driver.execute_script("arguments[0].click();", wrapper)
    time.sleep(0.6)

    # Reset children when possible, then set exactly two.
    for _ in range(4):
        try:
            minus = driver.find_element(By.XPATH, "//button[@aria-label='Odejmij jedno dziecko']")
            if minus.is_enabled():
                minus.click()
                time.sleep(0.2)
            else:
                break
        except Exception:
            break
    for _ in range(2):
        driver.find_element(By.XPATH, "//button[@aria-label='Dodaj jedno dziecko']").click()
        time.sleep(0.25)

    dob_inputs = [x for x in driver.find_elements(By.CSS_SELECTOR, "input[placeholder='RRRR-MM-DD']") if x.is_displayed()]
    if len(dob_inputs) != 2:
        return False

    for inp, dob in zip(dob_inputs, child_dobs):
        inp.click()
        inp.send_keys(Keys.CONTROL, "a")
        inp.send_keys(dob.strftime("%Y-%m-%d"))
        inp.send_keys(Keys.TAB)
        time.sleep(0.35)

    choose = driver.find_element(By.XPATH, "//button[@aria-label='Wybierz' or normalize-space(.)='Wybierz']")
    driver.execute_script("arguments[0].click();", choose)
    try:
        WebDriverWait(driver, 15).until(lambda d: "2 dzieci" in participant_value(d).lower())
    except Exception:
        return False
    time.sleep(2)
    return "2 dzieci" in participant_value(driver).lower()

def search_url(dep: date, family: str, nights: int):
    # Wakacje.pl uses comma-separated filters in the query component.
    filters = [
        f"od-{dep.isoformat()}",
        f"{nights}-dni",
        "all-inclusive",
        "z-warszawy",
        "z-warszawy-radom",
        family,
    ]
    return "https://www.wakacje.pl/lastminute/?" + ",".join(filters) + "&src=fromSearch"

def parse_card(a):
    raw = a.text or ""
    lines = [compact(x) for x in raw.splitlines() if compact(x)]
    text = compact(raw)
    href = a.get_attribute("href") or ""
    if not href or "/oferty/" not in href:
        return None

    md = re.search(r"(\d{2}\.\d{2}\.\d{4})-\s*(\d{2}\.\d{2}\.\d{4})", text)
    mp = re.search(r"(?:od\s+)?([0-9][0-9 ]{2,})\s*zł\s+za wszystkich", text, re.I)
    mr = re.search(r"\b(\d[.,]\d)\s+(?:Bardzo dobry|Dobry|Średni|Znakomity|Fantastyczny|Doskonały)", text, re.I)
    mn = re.search(r"([0-9][0-9 ]*)\s+opini", text, re.I)
    if not md or not mp:
        return None

    dep = datetime.strptime(md.group(1), "%d.%m.%Y").date()
    ret = datetime.strptime(md.group(2), "%d.%m.%Y").date()
    date_line_index = next((i for i, x in enumerate(lines) if re.search(r"\d{2}\.\d{2}\.\d{4}-", x)), None)
    hotel = lines[date_line_index - 1] if date_line_index is not None and date_line_index >= 1 else "Hotel"
    region = lines[date_line_index - 2] if date_line_index is not None and date_line_index >= 2 else ""
    after = lines[date_line_index + 1:] if date_line_index is not None else lines

    airport = next((x for x in after if "Warszawa" in x or "Radom" in x or "Modlin" in x), "")
    meal = next((x for x in after if "All Inclusive" in x), "")
    operator = ""
    if meal and meal in lines:
        idx = lines.index(meal)
        if idx + 1 < len(lines):
            operator = lines[idx + 1]

    mnight = re.search(r"\(\s*\d+\s+dni\s*/\s*(\d+)\s+noc", text, re.I)
    nights = int(mnight.group(1)) if mnight else (ret - dep).days

    return {
        "hotel": hotel,
        "region": region,
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

def collect_day(driver, dep: date, cfg, family, child_dobs):
    day_offers = {}
    for requested_nights in range(cfg["min_nights"], cfg["max_nights"] + 1):
        url = search_url(dep, family, requested_nights)
        print("SEARCH", dep.isoformat(), requested_nights, "nights", url)
        driver.get(url)
        WebDriverWait(driver, 30).until(lambda d: d.execute_script("return document.readyState") == "complete")
        time.sleep(3.2)
        dismiss_cookies(driver)

        if not ensure_family(driver, child_dobs):
            print("REJECT_PAGE family not confirmed:", participant_value(driver))
            continue

        # Encourage lazy-loaded cards without spending too long on each duration.
        for _ in range(4):
            try:
                driver.execute_script("window.scrollBy(0, 1900);")
                time.sleep(0.55)
                more = driver.find_elements(By.XPATH, "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'więcej ofert')]")
                if more and more[0].is_displayed():
                    driver.execute_script("arguments[0].click();", more[0])
                    time.sleep(0.9)
            except Exception:
                pass

        for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/oferty/']"):
            try:
                item = parse_card(a)
                if not item:
                    continue
                if item["departure"] != dep:
                    continue
                if not (cfg["min_nights"] <= item["nights"] <= cfg["max_nights"]):
                    continue
                if cfg["meal_contains"].lower() not in item["meal"].lower():
                    continue
                old = day_offers.get(item["href"])
                if old is None or item["price"] < old["price"]:
                    day_offers[item["href"]] = item
            except Exception as e:
                print("CARD_PARSE_ERROR", type(e).__name__, str(e)[:160])

    offers = list(day_offers.values())
    print("DAY_CANDIDATES", dep.isoformat(), len(offers))
    return offers

def with_family_token(href: str, family: str):
    parts = urlsplit(href)
    q = parts.query
    if family in q:
        return href
    if q:
        chunks = q.split("&", 1)
        first = chunks[0]
        first = first + "," + family
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

def verify_offer(driver, offer, cfg, family, child_dobs):
    href = with_family_token(offer["href"], family)
    print("VERIFY", offer["hotel"], offer["price"], href)
    driver.get(href)
    WebDriverWait(driver, 30).until(lambda d: d.execute_script("return document.readyState") == "complete")
    time.sleep(4)
    dismiss_cookies(driver)

    if not ensure_family(driver, child_dobs):
        return None, "family_not_confirmed"

    body = driver.find_element(By.TAG_NAME, "body").text
    low = body.lower()
    if any(p in low for p in UNAVAILABLE_PHRASES):
        return None, "unavailable_phrase"

    # Best-effort live price refresh. Failure to click is okay only if the page
    # already shows a family total; we never alert from a two-person price.
    try:
        buttons = [
            b for b in driver.find_elements(By.XPATH, "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'sprawdź cenę')]")
            if b.is_displayed()
        ]
        if buttons:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", buttons[0])
            driver.execute_script("arguments[0].click();", buttons[0])
            time.sleep(6)
            body = driver.find_element(By.TAG_NAME, "body").text
            low = body.lower()
            if any(p in low for p in UNAVAILABLE_PHRASES):
                return None, "unavailable_after_price_check"
    except Exception as e:
        print("PRICE_CHECK_CLICK_WARN", type(e).__name__, str(e)[:120])

    totals = parse_totals(body)
    if totals:
        # Pick the total closest to the listing family total, which avoids
        # deposits/per-person figures if several amounts are visible.
        final_price = min(totals, key=lambda x: abs(x - offer["price"]))
        return final_price, "live_family_total"

    formatted = f"{offer['price']:,}".replace(",", " ")
    if "2 dzieci" in participant_value(driver).lower() and formatted in compact(body) and "za wszystkich" in low:
        return offer["price"], "family_page_total"

    return None, "no_confirmed_family_total"

def qualify(offer, cfg):
    return (
        offer["price"] <= cfg["max_total_price_pln"]
        and (offer["rating"] or 0) >= cfg["min_rating"]
        and (offer["reviews"] or 0) >= cfg["min_reviews"]
    )

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
    title = f"{prefix}: {offer['hotel']} — {offer['price']} zł 2+2 — {offer['departure'].strftime('%d.%m')}"

    body = f"""@{cfg['notify_github_user']}

**{drop_note}**

- **Hotel:** {offer['hotel']}
- **Region:** {offer['region']}
- **Cena łączna 2+2:** **{offer['price']} zł**
- **Dzieci:** {', '.join(str(x) for x in cfg['children_ages'])} lat
- **Termin:** {offer['departure'].strftime('%d.%m.%Y')} – {offer['return'].strftime('%d.%m.%Y')} ({offer['nights']} nocy)
- **Wylot:** {offer['airport']}
- **Wyżywienie:** {offer['meal']}
- **Organizator:** {offer['operator']}
- **Ocena:** {offer['rating']}/10 ({offer['reviews']} opinii)
- **Weryfikacja:** {verification}, {now_local().strftime('%d.%m.%Y %H:%M:%S')} Europe/Warsaw
- **Oferta:** {offer['verified_href']}

Watcher sprawdził konfigurację **2 dorosłych + 2 dzieci** i nie opiera alarmu na cenie dla dwóch osób.

<!-- watcher-offer-key:{key} -->
<!-- watcher-price:{offer['price']} -->
"""
    github_api("POST", "issues", token, repo, json={"title": title, "body": body})
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
                all_offers[offer["href"]] = offer

        candidates = [x for x in all_offers.values() if qualify(x, cfg)]
        candidates.sort(key=lambda x: (
            0 if cfg["priority_airport_contains"].lower() in x["airport"].lower() else 1,
            -(x["rating"] or 0),
            x["price"],
        ))
        print("STRICT_CANDIDATES", len(candidates))
        for x in candidates:
            print("CANDIDATE", x["hotel"], x["price"], x["rating"], x["reviews"], x["airport"], x["href"])

        token = os.getenv("GITHUB_TOKEN", "")
        repo = os.getenv("GITHUB_REPOSITORY", "")
        alerts = 0

        for offer in candidates[:12]:
            if cfg.get("second_check", True):
                final_price, verification = verify_offer(driver, offer, cfg, family, child_dobs)
                if final_price is None:
                    print("REJECT_VERIFY", offer["hotel"], verification)
                    continue
                offer["price"] = final_price
                if offer["price"] > cfg["max_total_price_pln"]:
                    print("REJECT_PRICE_AFTER_VERIFY", offer["hotel"], offer["price"])
                    continue
            else:
                verification = "listing_family_total"

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
