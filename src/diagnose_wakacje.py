import re
import time
from datetime import date, datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys

URL = "https://www.wakacje.pl/lastminute/?samolotem,z-warszawy,z-warszawy-radom&src=fromSearch"
CHILD_DOBS = ["2021-03-01", "2019-03-01"]

def compact(s: str) -> str:
    return " ".join((s or "").split())

def parse_pl_date(s):
    return datetime.strptime(s, "%d.%m.%Y").date()

def main():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1440,2800")
    opts.add_argument("--lang=pl-PL")
    driver = webdriver.Chrome(options=opts)
    try:
        driver.get(URL)
        WebDriverWait(driver, 35).until(lambda d: d.execute_script("return document.readyState") == "complete")
        time.sleep(4)

        for text in ["Akceptuję", "Akceptuj", "Zgadzam się", "Zaakceptuj wszystkie", "OK"]:
            try:
                els = driver.find_elements(By.XPATH, f"//button[contains(normalize-space(.), '{text}')]")
                if els:
                    els[0].click()
                    time.sleep(0.7)
                    break
            except Exception:
                pass

        participant = driver.find_element(By.CSS_SELECTOR, "input[name='CalculatorPerson']")
        wrapper = participant.find_element(By.XPATH, "./ancestor::div[contains(@class,'input-wrapper-clickable')][1]")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", wrapper)
        time.sleep(0.5)
        wrapper.click()
        time.sleep(0.6)

        for _ in range(2):
            driver.find_element(By.XPATH, "//button[@aria-label='Dodaj jedno dziecko']").click()
            time.sleep(0.35)

        dob_inputs = [x for x in driver.find_elements(By.CSS_SELECTOR, "input[placeholder='RRRR-MM-DD']") if x.is_displayed()]
        if len(dob_inputs) != 2:
            raise RuntimeError(f"Expected 2 DOB inputs, got {len(dob_inputs)}")

        for inp, dob in zip(dob_inputs, CHILD_DOBS):
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", inp)
            inp.click()
            inp.send_keys(Keys.CONTROL, "a")
            inp.send_keys(dob)
            inp.send_keys(Keys.TAB)
            time.sleep(0.5)
            print("DOB_SET:", dob, "=>", inp.get_attribute("value"))

        choose = driver.find_element(By.XPATH, "//button[normalize-space(.)='Wybierz' and @aria-label='Wybierz']")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", choose)
        choose.click()

        WebDriverWait(driver, 20).until(
            lambda d: "dzie" in (d.find_element(By.CSS_SELECTOR, "input[name='CalculatorPerson']").get_attribute("value") or "").lower()
        )
        time.sleep(5)

        participant = driver.find_element(By.CSS_SELECTOR, "input[name='CalculatorPerson']")
        print("CONFIRMED_PARTICIPANT_VALUE:", participant.get_attribute("value"))
        print("CONFIRMED_PARTICIPANT_ARIA:", participant.get_attribute("aria-label"))
        print("URL_AFTER_CONFIRM:", driver.current_url)

        # Verify direct date-filter URL syntax for imminent departures.
        family_token = "2dorosle-2dzieci-20210301-20190301"
        test_day = (date.today() + timedelta(days=2)).isoformat()
        date_url = (
            f"https://www.wakacje.pl/lastminute/?od-{test_day},7-dni,all-inclusive,"
            f"z-warszawy,z-warszawy-radom,{family_token}&src=fromSearch"
        )
        print("DATE_FILTER_TEST_URL:", date_url)
        driver.get(date_url)
        WebDriverWait(driver, 30).until(lambda d: d.execute_script("return document.readyState") == "complete")
        time.sleep(5)
        print("DATE_FILTER_FINAL_URL:", driver.current_url)
        print("DATE_FILTER_RESULT_SAMPLE:")
        count = 0
        for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/oferty/']"):
            try:
                txt = compact(a.text)
                href = a.get_attribute("href") or ""
                if txt and href:
                    print(repr({"href": href, "text": txt[:1000]}))
                    count += 1
                    if count >= 12:
                        break
            except Exception:
                pass

        print("SEARCH_INPUTS:")
        for inp in driver.find_elements(By.TAG_NAME, "input"):
            try:
                if inp.is_displayed():
                    print(repr({
                        "name": inp.get_attribute("name"),
                        "type": inp.get_attribute("type"),
                        "placeholder": inp.get_attribute("placeholder"),
                        "aria": inp.get_attribute("aria-label"),
                        "value": inp.get_attribute("value"),
                    }))
            except Exception:
                pass

        # Lazy-load more result cards.
        for _ in range(8):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.1)

        today = date.today()
        start_min = today + timedelta(days=1)
        start_max = today + timedelta(days=4)
        print("RUN_DATE:", today.isoformat())
        print("TARGET_START_WINDOW:", start_min.isoformat(), start_max.isoformat())

        seen = set()
        parsed = []
        for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/oferty/']"):
            try:
                href = a.get_attribute("href") or ""
                txt = compact(a.text)
                if not href or not txt or href in seen:
                    continue
                seen.add(href)

                md = re.search(r"(\d{2}\.\d{2}\.\d{4})-\s*(\d{2}\.\d{2}\.\d{4})", txt)
                mp = re.search(r"(?:od\s+)?([0-9][0-9 ]{2,})\s*zł\s+za wszystkich", txt, re.I)
                mr = re.search(r"\b(\d[\.,]\d)\s+(?:Bardzo dobry|Dobry|Średni|Znakomity|Fantastyczny|Doskonały)", txt, re.I)
                mn = re.search(r"(\d+)\s+opini", txt, re.I)
                if not md or not mp:
                    continue

                dep = parse_pl_date(md.group(1))
                ret = parse_pl_date(md.group(2))
                price = int(mp.group(1).replace(" ", ""))
                rating = float(mr.group(1).replace(",", ".")) if mr else None
                reviews = int(mn.group(1)) if mn else None
                nights = (ret - dep).days

                parsed.append({
                    "departure": dep,
                    "return": ret,
                    "nights": nights,
                    "price": price,
                    "rating": rating,
                    "reviews": reviews,
                    "all_inclusive": "all inclusive" in txt.lower(),
                    "radom": "radom" in txt.lower(),
                    "href": href,
                    "text": txt,
                })
            except Exception as e:
                print("PARSE_ERR:", type(e).__name__, str(e)[:200])

        print("PARSED_COUNT:", len(parsed))

        # Broad diagnostic window around the imminent departure dates.
        imminent = [
            x for x in parsed
            if start_min <= x["departure"] <= start_max
            and x["all_inclusive"]
            and 5 <= x["nights"] <= 9
        ]
        imminent.sort(key=lambda x: (x["price"], -(x["rating"] or 0)))
        print("IMMINENT_2PLUS2_CANDIDATES:")
        for x in imminent[:40]:
            print(repr({
                "departure": x["departure"].isoformat(),
                "return": x["return"].isoformat(),
                "nights": x["nights"],
                "price": x["price"],
                "rating": x["rating"],
                "reviews": x["reviews"],
                "radom": x["radom"],
                "href": x["href"],
                "text": x["text"][:1100],
            }))

        strict = [
            x for x in imminent
            if x["price"] <= 7000
            and (x["rating"] or 0) >= 8.0
            and (x["reviews"] or 0) >= 30
        ]
        print("STRICT_MATCHES:", len(strict))
        for x in strict[:20]:
            print("STRICT:", repr(x))

        driver.save_screenshot("wakacje-diagnostic.png")
        with open("wakacje-diagnostic.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
