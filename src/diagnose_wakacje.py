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
    for el in driver.find_elements(By.XPATH, "//button | //input | //select | //*[@role='button'] | //*[@role='spinbutton']"):
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
        print("PARTICIPANT_INPUT:", sig(participant))
        before = visible_interactives(driver)
        before_sigs = {s for s, _ in before}

        wrapper = participant.find_element(By.XPATH, "./ancestor::div[contains(@class,'input-wrapper-clickable')][1]")
        print("WRAPPER_HTML:", (wrapper.get_attribute("outerHTML") or "")[:3500])

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", wrapper)
        time.sleep(1)

        clicked = False
        attempts = []
        for mode in ["native-wrapper", "action-wrapper", "native-input", "js-wrapper"]:
            try:
                if mode == "native-wrapper":
                    wrapper.click()
                elif mode == "action-wrapper":
                    ActionChains(driver).move_to_element(wrapper).click().perform()
                elif mode == "native-input":
                    participant.click()
                else:
                    driver.execute_script("arguments[0].click();", wrapper)
                clicked = True
                attempts.append(mode + ":ok")
                time.sleep(2)
                body = compact(driver.find_element(By.TAG_NAME, "body").text).lower()
                if any(k in body for k in ["dorośli", "dzieci", "wiek dziecka", "wiek dzieci"]):
                    break
            except Exception as e:
                attempts.append(mode + ":" + type(e).__name__)

        print("CLICK_ATTEMPTS:", attempts)
        print("CLICKED:", clicked)

        after = visible_interactives(driver)
        after_sigs = {s for s, _ in after}
        new = [s for s, _ in after if s not in before_sigs]

        print("NEW_VISIBLE_INTERACTIVES:")
        for s in new[:120]:
            print(repr(s))

        print("ALL_RELEVANT_INTERACTIVES:")
        for s, _ in after:
            blob = " ".join(s).lower()
            if any(k in blob for k in ["doros", "doroś", "dzie", "wiek", "lat", "plus", "minus", "dodaj", "usuń", "usun", "gotowe", "zastosuj", "osób", "osob"]):
                print(repr(s))

        body_text = driver.find_element(By.TAG_NAME, "body").text
        lines = [x.strip() for x in body_text.splitlines() if x.strip()]
        keys = ("doros", "doroś", "dziec", "dzieci", "wiek", "uczest", "osób", "osoby", " lat", "gotowe", "zastosuj")
        print("VISIBLE_RELEVANT_TEXT:")
        out = []
        for i, line in enumerate(lines):
            if any(k in line.lower() for k in keys):
                lo = max(0, i - 4)
                hi = min(len(lines), i + 10)
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
