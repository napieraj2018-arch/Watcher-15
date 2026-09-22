import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL = "https://www.wakacje.pl/lastminute/?samolotem,z-warszawy,z-warszawy-radom&src=fromSearch"

def compact(s: str) -> str:
    return " ".join((s or "").split())

def sig(el):
    try:
        return {
            "tag": el.tag_name,
            "type": el.get_attribute("type"),
            "role": el.get_attribute("role"),
            "name": el.get_attribute("name"),
            "value": el.get_attribute("value"),
            "aria": el.get_attribute("aria-label"),
            "testid": el.get_attribute("data-testid"),
            "class": el.get_attribute("class"),
            "text": compact(el.text)[:500],
        }
    except Exception:
        return {}

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
                    time.sleep(1)
                    break
            except Exception:
                pass

        participant = driver.find_element(By.CSS_SELECTOR, "input[name='CalculatorPerson']")
        wrapper = participant.find_element(By.XPATH, "./ancestor::div[contains(@class,'input-wrapper-clickable')][1]")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", wrapper)
        time.sleep(0.8)
        wrapper.click()
        time.sleep(0.8)

        for _ in range(2):
            driver.find_element(By.XPATH, "//button[@aria-label='Dodaj jedno dziecko']").click()
            time.sleep(0.5)

        child_count = driver.find_element(By.XPATH, "//input[contains(@aria-label,'Aktualna liczba dzieci')]")
        print("CHILD_COUNT:", sig(child_count))

        cur = child_count
        for level in range(1, 9):
            try:
                cur = cur.find_element(By.XPATH, "..")
                html = cur.get_attribute("outerHTML") or ""
                print(f"CHILD_ANCESTOR_{level}_TAG:", cur.tag_name)
                print(f"CHILD_ANCESTOR_{level}_TEXT:", compact(cur.text)[:2500])
                print(f"CHILD_ANCESTOR_{level}_HTML:", html[:18000])
            except Exception:
                break

        print("ALL_VISIBLE_BUTTONS_INPUTS_SELECTS_AFTER_2_CHILDREN:")
        for el in driver.find_elements(By.XPATH, "//button | //input | //select | //*[@role='button'] | //*[@role='combobox'] | //*[@role='listbox'] | //*[@role='option']"):
            try:
                if el.is_displayed():
                    print(repr(sig(el)))
            except Exception:
                pass

        print("VISIBLE_TEXT_LINES_AFTER_2_CHILDREN:")
        for line in [x.strip() for x in driver.find_element(By.TAG_NAME, "body").text.splitlines() if x.strip()]:
            print(line)

        driver.save_screenshot("wakacje-diagnostic.png")
        with open("wakacje-diagnostic.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
