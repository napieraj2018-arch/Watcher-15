import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL = "https://www.wakacje.pl/lastminute/?samolotem,z-warszawy,z-warszawy-radom&src=fromSearch"

def compact(s: str) -> str:
    return " ".join((s or "").split())

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

        # Best-effort cookie dismissal.
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

        # Print only compact elements related to participant selection.
        matches = []
        xpath = (
            "//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZĄĆĘŁŃÓŚŹŻ','abcdefghijklmnopqrstuvwxyząćęłńóśźż'),'ile osób') "
            "or contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZĄĆĘŁŃÓŚŹŻ','abcdefghijklmnopqrstuvwxyząćęłńóśźż'),'uczest') "
            "or contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZĄĆĘŁŃÓŚŹŻ','abcdefghijklmnopqrstuvwxyząćęłńóśźż'),'doros') "
            "or contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZĄĆĘŁŃÓŚŹŻ','abcdefghijklmnopqrstuvwxyząćęłńóśźż'),'dziec')]"
        )
        for el in driver.find_elements(By.XPATH, xpath):
            try:
                txt = compact(el.text)
                if txt and len(txt) < 260:
                    matches.append((
                        el.tag_name,
                        el.get_attribute("role"),
                        el.get_attribute("aria-label"),
                        el.get_attribute("data-testid"),
                        txt
                    ))
            except Exception:
                pass

        print("PARTICIPANT_RELATED_ELEMENTS:")
        seen = set()
        for item in matches[:150]:
            if item not in seen:
                seen.add(item)
                print(repr(item))

        # Try to open participant picker.
        clicked = False
        candidates = driver.find_elements(
            By.XPATH,
            "//*[contains(normalize-space(.),'Ile osób?') or contains(normalize-space(.),'Uczestnicy') or contains(normalize-space(.),'2 osoby')]"
        )
        for el in candidates:
            try:
                if el.is_displayed():
                    driver.execute_script("arguments[0].click();", el)
                    print("CLICKED:", el.tag_name, compact(el.get_attribute("aria-label")), compact(el.text)[:200])
                    clicked = True
                    time.sleep(2)
                    break
            except Exception:
                pass
        print("PARTICIPANT_PICKER_CLICKED:", clicked)

        body_text = driver.find_element(By.TAG_NAME, "body").text
        lines = [x.strip() for x in body_text.splitlines() if x.strip()]
        keys = ("doros", "dziec", "wiek", "uczest", "osób", "osoby", " lat")
        print("VISIBLE_RELEVANT_TEXT:")
        out = []
        for i, line in enumerate(lines):
            if any(k in line.lower() for k in keys):
                lo = max(0, i - 2)
                hi = min(len(lines), i + 5)
                out.extend(lines[lo:hi])
        for line in out[:300]:
            print(line)

        driver.save_screenshot("wakacje-diagnostic.png")
        with open("wakacje-diagnostic.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
