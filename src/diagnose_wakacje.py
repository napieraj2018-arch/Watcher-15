import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.action_chains import ActionChains

URL = "https://www.wakacje.pl/lastminute/?samolotem,z-warszawy,z-warszawy-radom&src=fromSearch"

def compact(s: str) -> str:
    return " ".join((s or "").split())

def sig(el):
    try:
        return (
            el.tag_name,
            el.get_attribute("type") or "",
            el.get_attribute("role") or "",
            el.get_attribute("name") or "",
            el.get_attribute("aria-label") or "",
            el.get_attribute("value") or "",
            compact(el.text)[:250],
        )
    except Exception:
        return None

def visible_interactives(driver):
    out = []
    for el in driver.find_elements(By.XPATH, "//button | //input | //select | //*[@role='button'] | //*[@role='spinbutton'] | //*[@role='combobox']"):
        try:
            if el.is_displayed():
                s = sig(el)
                if s:
                    out.append((s, el))
        except Exception:
            pass
    return out

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

        participant = driver.find_element(By.CSS_SELECTOR, "input[name='CalculatorPerson']")
        wrapper = participant.find_element(By.XPATH, "./ancestor::div[contains(@class,'input-wrapper-clickable')][1]")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", wrapper)
        time.sleep(1)
        wrapper.click()
        time.sleep(1)

        print("AFTER_OPEN:")
        for s, _ in visible_interactives(driver):
            blob = " ".join(s).lower()
            if any(k in blob for k in ["doros", "doroś", "dzie", "wiek", "lat", "osób", "osob"]):
                print(repr(s))

        add_child = driver.find_element(By.XPATH, "//button[@aria-label='Dodaj jedno dziecko']")
        add_child.click()
        time.sleep(0.6)
        add_child = driver.find_element(By.XPATH, "//button[@aria-label='Dodaj jedno dziecko']")
        add_child.click()
        time.sleep(1.2)

        print("AFTER_TWO_CHILDREN:")
        for s, _ in visible_interactives(driver):
            blob = " ".join(s).lower()
            if any(k in blob for k in ["doros", "doroś", "dzie", "wiek", "lat", "osób", "osob", "rok", "mies"]):
                print(repr(s))

        # Print compact DOM around all elements that mention child age.
        age_nodes = driver.find_elements(
            By.XPATH,
            "//*[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZĄĆĘŁŃÓŚŹŻ','abcdefghijklmnopqrstuvwxyząćęłńóśźż'),'wiek') or contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZĄĆĘŁŃÓŚŹŻ','abcdefghijklmnopqrstuvwxyząćęłńóśźż'),'wiek dziecka')]"
        )
        print("AGE_NODES:", len(age_nodes))
        for i, el in enumerate(age_nodes[:40]):
            try:
                if el.is_displayed():
                    print(f"AGE_{i}:", repr(sig(el)))
                    print(f"AGE_{i}_HTML:", (el.get_attribute("outerHTML") or "")[:5000])
            except Exception:
                pass

        body_text = driver.find_element(By.TAG_NAME, "body").text
        lines = [x.strip() for x in body_text.splitlines() if x.strip()]
        keys = ("doros", "doroś", "dziec", "dzieci", "wiek", " lat", "rok", "mies", "gotowe", "zastosuj")
        print("VISIBLE_RELEVANT_TEXT:")
        out = []
        for i, line in enumerate(lines):
            if any(k in line.lower() for k in keys):
                lo = max(0, i - 4)
                hi = min(len(lines), i + 12)
                out.extend(lines[lo:hi])
        for line in out[:500]:
            print(line)

        driver.save_screenshot("wakacje-diagnostic.png")
        with open("wakacje-diagnostic.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
