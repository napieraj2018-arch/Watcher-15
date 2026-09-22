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

        labels = driver.find_elements(By.XPATH, "//label[normalize-space(.)='Ile osób?']")
        print("EXACT_LABEL_COUNT:", len(labels))
        if labels:
            label = labels[0]
            print("LABEL_OUTER_HTML:", label.get_attribute("outerHTML"))
            cur = label
            for level in range(1, 6):
                try:
                    cur = cur.find_element(By.XPATH, "..")
                    print(f"ANCESTOR_{level}_TAG:", cur.tag_name)
                    print(f"ANCESTOR_{level}_TEXT:", compact(cur.text)[:700])
                    html = cur.get_attribute("outerHTML") or ""
                    print(f"ANCESTOR_{level}_HTML:", html[:7000])
                except Exception:
                    break

            # Inspect nearby interactive elements.
            try:
                block = label.find_element(By.XPATH, "../..")
            except Exception:
                block = label

            print("NEARBY_INTERACTIVE:")
            for el in block.find_elements(By.XPATH, ".//button | .//input | .//*[@role='button']"):
                try:
                    print(repr({
                        "tag": el.tag_name,
                        "type": el.get_attribute("type"),
                        "role": el.get_attribute("role"),
                        "aria": el.get_attribute("aria-label"),
                        "testid": el.get_attribute("data-testid"),
                        "class": el.get_attribute("class"),
                        "text": compact(el.text)[:300],
                    }))
                except Exception:
                    pass

            # Prefer the nearest button/input after the label.
            candidates = []
            xpaths = [
                "./following::button[1]",
                "./following::input[1]",
                "../following-sibling::*[1]//button[1]",
                "../following-sibling::*[1]//*[@role='button'][1]",
            ]
            for xp in xpaths:
                try:
                    el = label.find_element(By.XPATH, xp)
                    if el.is_displayed():
                        candidates.append(el)
                except Exception:
                    pass

            clicked = False
            seen = set()
            for el in candidates:
                key = (el.tag_name, el.get_attribute("class"), compact(el.text))
                if key in seen:
                    continue
                seen.add(key)
                try:
                    print("CLICK_CANDIDATE:", repr({
                        "tag": el.tag_name,
                        "type": el.get_attribute("type"),
                        "role": el.get_attribute("role"),
                        "aria": el.get_attribute("aria-label"),
                        "class": el.get_attribute("class"),
                        "text": compact(el.text)[:300],
                    }))
                    driver.execute_script("arguments[0].click();", el)
                    time.sleep(2)
                    print("CLICKED_CANDIDATE:", key)
                    clicked = True
                    break
                except Exception as e:
                    print("CLICK_ERROR:", type(e).__name__, str(e)[:300])

            print("PICKER_CLICKED:", clicked)

        body_text = driver.find_element(By.TAG_NAME, "body").text
        lines = [x.strip() for x in body_text.splitlines() if x.strip()]
        keys = ("doros", "dziec", "wiek", "uczest", "osób", "osoby", " lat")
        print("VISIBLE_RELEVANT_TEXT_AFTER_CLICK:")
        out = []
        for i, line in enumerate(lines):
            if any(k in line.lower() for k in keys):
                lo = max(0, i - 3)
                hi = min(len(lines), i + 7)
                out.extend(lines[lo:hi])
        for line in out[:350]:
            print(line)

        driver.save_screenshot("wakacje-diagnostic.png")
        with open("wakacje-diagnostic.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
