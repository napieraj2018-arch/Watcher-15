import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL = "https://www.wakacje.pl/lastminute/?samolotem,z-warszawy,z-warszawy-radom&src=fromSearch"

def compact(s: str) -> str:
    return " ".join((s or "").split())

def dump_element(el, prefix="EL"):
    try:
        print(prefix, repr({
            "tag": el.tag_name,
            "type": el.get_attribute("type"),
            "role": el.get_attribute("role"),
            "name": el.get_attribute("name"),
            "value": el.get_attribute("value"),
            "aria": el.get_attribute("aria-label"),
            "aria_expanded": el.get_attribute("aria-expanded"),
            "testid": el.get_attribute("data-testid"),
            "class": el.get_attribute("class"),
            "text": compact(el.text)[:400],
        }))
    except Exception as e:
        print(prefix, "ERR", type(e).__name__, str(e)[:200])

def main():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1440,2400")
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
                    time.sleep(1)
                    break
            except Exception:
                pass

        print("TITLE:", driver.title)
        print("URL:", driver.current_url)

        participant = driver.find_element(By.CSS_SELECTOR, "input[name='CalculatorPerson']")
        dump_element(participant, "PARTICIPANT_INPUT_BEFORE")
        driver.execute_script("arguments[0].click();", participant)
        time.sleep(2)
        dump_element(participant, "PARTICIPANT_INPUT_AFTER")

        # Print visible dialogs/popovers.
        print("VISIBLE_DIALOGS:")
        dialogs = driver.find_elements(By.XPATH, "//*[@role='dialog'] | //*[contains(@class,'modal')] | //*[contains(@class,'popover')]")
        for i, el in enumerate(dialogs[:80]):
            try:
                if el.is_displayed():
                    txt = compact(el.text)
                    print(f"DIALOG_{i}_TAG:", el.tag_name)
                    print(f"DIALOG_{i}_TEXT:", txt[:3500])
                    print(f"DIALOG_{i}_HTML:", (el.get_attribute("outerHTML") or "")[:12000])
            except Exception:
                pass

        print("VISIBLE_RELEVANT_INTERACTIVE:")
        interactives = driver.find_elements(By.XPATH, "//button | //input | //select | //*[@role='button'] | //*[@role='spinbutton']")
        for el in interactives:
            try:
                if not el.is_displayed():
                    continue
                blob = " ".join([
                    compact(el.text),
                    compact(el.get_attribute("aria-label")),
                    compact(el.get_attribute("name")),
                    compact(el.get_attribute("value")),
                    compact(el.get_attribute("data-testid")),
                ]).lower()
                if any(k in blob for k in ("doros", "dzie", "wiek", "osob", "lat", "plus", "minus", "dodaj", "usuń", "usun", "gotowe", "zastosuj")):
                    dump_element(el, "INTERACTIVE")
            except Exception:
                pass

        body_text = driver.find_element(By.TAG_NAME, "body").text
        lines = [x.strip() for x in body_text.splitlines() if x.strip()]
        keys = ("doros", "dziec", "wiek", "uczest", "osób", "osoby", " lat", "gotowe", "zastosuj")
        print("VISIBLE_RELEVANT_TEXT:")
        out = []
        for i, line in enumerate(lines):
            if any(k in line.lower() for k in keys):
                lo = max(0, i - 3)
                hi = min(len(lines), i + 8)
                out.extend(lines[lo:hi])
        for line in out[:450]:
            print(line)

        driver.save_screenshot("wakacje-diagnostic.png")
        with open("wakacje-diagnostic.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
