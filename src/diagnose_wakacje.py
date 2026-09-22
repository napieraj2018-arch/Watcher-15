import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys

URL = "https://www.wakacje.pl/lastminute/?samolotem,z-warszawy,z-warszawy-radom&src=fromSearch"

# Representative dates that keep the children unambiguously 5 and 7 years old
# during the monitored late-September 2026 departures.
CHILD_DOBS = ["2021-03-01", "2019-03-01"]

def compact(s: str) -> str:
    return " ".join((s or "").split())

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
        WebDriverWait(driver, 35).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
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
        wrapper = participant.find_element(
            By.XPATH, "./ancestor::div[contains(@class,'input-wrapper-clickable')][1]"
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", wrapper)
        time.sleep(0.6)
        wrapper.click()
        time.sleep(0.7)

        for _ in range(2):
            driver.find_element(By.XPATH, "//button[@aria-label='Dodaj jedno dziecko']").click()
            time.sleep(0.4)

        dob_inputs = driver.find_elements(By.CSS_SELECTOR, "input[placeholder='RRRR-MM-DD']")
        visible_dobs = [x for x in dob_inputs if x.is_displayed()]
        print("DOB_INPUT_COUNT:", len(visible_dobs))

        if len(visible_dobs) != 2:
            raise RuntimeError(f"Expected 2 visible child DOB fields, got {len(visible_dobs)}")

        for inp, dob in zip(visible_dobs, CHILD_DOBS):
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", inp)
            inp.click()
            inp.send_keys(Keys.CONTROL, "a")
            inp.send_keys(dob)
            inp.send_keys(Keys.TAB)
            time.sleep(0.8)
            print("DOB_SET:", dob, "=>", inp.get_attribute("value"))

        print("PARTICIPANT_VALUE_IN_MODAL:", participant.get_attribute("value"))
        print("PARTICIPANT_ARIA_IN_MODAL:", participant.get_attribute("aria-label"))

        # Enumerate visible modal buttons so we can find the exact confirmation action.
        print("VISIBLE_BUTTONS_AFTER_DOBS:")
        for b in driver.find_elements(By.TAG_NAME, "button"):
            try:
                if b.is_displayed():
                    txt = compact(b.text)
                    aria = compact(b.get_attribute("aria-label"))
                    if txt or aria:
                        print(repr({
                            "text": txt[:250],
                            "aria": aria[:250],
                            "type": b.get_attribute("type"),
                            "class": b.get_attribute("class"),
                            "testid": b.get_attribute("data-testid"),
                        }))
            except Exception:
                pass

        # Close the picker using Escape first; if state is persistent this should preserve it.
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(2)

        print("AFTER_ESCAPE_PARTICIPANT_VALUE:", participant.get_attribute("value"))
        print("AFTER_ESCAPE_PARTICIPANT_ARIA:", participant.get_attribute("aria-label"))
        print("CURRENT_URL_AFTER_ESCAPE:", driver.current_url)

        # Inspect likely result cards/links after participant state change.
        print("RESULT_LINKS_SAMPLE:")
        seen = set()
        for a in driver.find_elements(By.TAG_NAME, "a"):
            try:
                if not a.is_displayed():
                    continue
                href = a.get_attribute("href") or ""
                txt = compact(a.text)
                if not href or not txt:
                    continue
                blob = (href + " " + txt).lower()
                if any(k in blob for k in ["/wczasy/", "/hotel/", "all inclusive", "za wszystkich", "zł"]):
                    key = (href, txt[:500])
                    if key in seen:
                        continue
                    seen.add(key)
                    print(repr({"href": href, "text": txt[:900]}))
                    if len(seen) >= 20:
                        break
            except Exception:
                pass

        body = driver.find_element(By.TAG_NAME, "body").text
        print("BODY_PRICE_LINES:")
        for line in [x.strip() for x in body.splitlines() if x.strip()]:
            low = line.lower()
            if "zł" in low or "za wszystkich" in low or "all inclusive" in low:
                print(line)

        driver.save_screenshot("wakacje-diagnostic.png")
        with open("wakacje-diagnostic.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
