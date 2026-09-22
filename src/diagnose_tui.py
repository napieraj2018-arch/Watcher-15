import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL="https://www.tui.pl/last-minute-z-warszawy"

def compact(s):
    return " ".join((s or "").split())

def pick_birth_date(d, button_index, year, month, day):
    births=[b for b in d.find_elements(By.CSS_SELECTOR,"button[data-testid='birth-date-button']") if b.is_displayed()]
    d.execute_script("arguments[0].click();", births[button_index])
    time.sleep(0.5)
    cal=d.find_element(By.CSS_SELECTOR,"div[data-testid='birth-date-calendar']")

    # Navigate decade view until target year is present.
    for _ in range(4):
        years=[x for x in cal.find_elements(By.CSS_SELECTOR,".react-calendar__decade-view__years button") if x.is_displayed()]
        match=[x for x in years if compact(x.text)==str(year)]
        if match:
            d.execute_script("arguments[0].click();",match[0]); break
        label=compact(cal.find_element(By.CSS_SELECTOR,".react-calendar__navigation__label").text)
        nums=[int(x) for x in __import__("re").findall(r"\d{4}",label)]
        if nums and year < min(nums):
            prev=cal.find_element(By.CSS_SELECTOR,".react-calendar__navigation__prev-button")
            d.execute_script("arguments[0].click();",prev)
        else:
            nxt=cal.find_element(By.CSS_SELECTOR,".react-calendar__navigation__next-button")
            if nxt.is_enabled(): d.execute_script("arguments[0].click();",nxt)
        time.sleep(0.4)
    else:
        raise RuntimeError(f"Cannot select year {year}")

    time.sleep(0.4)
    months=[x for x in cal.find_elements(By.CSS_SELECTOR,".react-calendar__year-view__months button") if x.is_displayed()]
    if len(months)<12:
        raise RuntimeError(f"Expected 12 months, got {len(months)}")
    d.execute_script("arguments[0].click();",months[month-1])
    time.sleep(0.4)

    days=[x for x in cal.find_elements(By.CSS_SELECTOR,".react-calendar__month-view__days button") if x.is_displayed()]
    target=None
    for x in days:
        aria=(x.get_attribute("aria-label") or "").lower()
        txt=compact(x.text)
        if txt==str(day) and str(year) in aria:
            target=x; break
    if target is None:
        # Fallback: pick the enabled in-month day with exact visible number.
        candidates=[x for x in days if compact(x.text)==str(day) and "neighboringMonth" not in (x.get_attribute("class") or "")]
        if candidates: target=candidates[0]
    if target is None:
        raise RuntimeError(f"Cannot select day {day}")
    d.execute_script("arguments[0].click();",target)
    time.sleep(0.7)

def main():
    opts=Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1440,2800")
    opts.add_argument("--lang=pl-PL")
    d=webdriver.Chrome(options=opts)
    try:
        d.get(URL)
        WebDriverWait(d,40).until(lambda x:x.execute_script("return document.readyState")=="complete")
        time.sleep(5)
        for t in ["Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","OK"]:
            try:
                els=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
                if els and els[0].is_displayed():
                    els[0].click(); time.sleep(1); break
            except: pass
        print("TITLE",d.title)
        print("URL",d.current_url)
        print("INPUTS")
        for el in d.find_elements(By.TAG_NAME,"input"):
            try:
                if el.is_displayed():
                    print(repr({
                      "name":el.get_attribute("name"),
                      "type":el.get_attribute("type"),
                      "placeholder":el.get_attribute("placeholder"),
                      "aria":el.get_attribute("aria-label"),
                      "value":el.get_attribute("value"),
                      "data-testid":el.get_attribute("data-testid"),
                    }))
            except: pass
        # Open participant picker and inspect its controls.
        try:
            part=d.find_element(By.CSS_SELECTOR,"button[data-testid='dropdown-field--participants']")
            d.execute_script("arguments[0].click();",part)
            time.sleep(1.5)
            print("PARTICIPANT_MODAL_OPENED", True)
        except Exception as e:
            print("PARTICIPANT_MODAL_OPENED", False, type(e).__name__, str(e)[:120])

        # Add two children and inspect the newly rendered age controls.
        try:
            inc=d.find_element(By.CSS_SELECTOR,"button[data-testid='person-count-increment-children']")
            d.execute_script("arguments[0].click();",inc)
            time.sleep(0.4)
            d.execute_script("arguments[0].click();",inc)
            time.sleep(0.8)
            print("CHILDREN_AFTER_INCREMENT", d.find_element(By.CSS_SELECTOR,"span[data-testid='person-count-children']").text)
        except Exception as e:
            print("CHILDREN_AFTER_INCREMENT_ERROR", type(e).__name__, str(e)[:160])

        print("MODAL_INPUTS_AFTER_OPEN")
        for el in d.find_elements(By.TAG_NAME,"input"):
            try:
                if el.is_displayed():
                    print(repr({
                      "name":el.get_attribute("name"),
                      "type":el.get_attribute("type"),
                      "placeholder":el.get_attribute("placeholder"),
                      "aria":el.get_attribute("aria-label"),
                      "value":el.get_attribute("value"),
                      "testid":el.get_attribute("data-testid"),
                      "class":el.get_attribute("class"),
                    }))
            except: pass

        print("MODAL_TESTIDS")
        seen=set()
        for el in d.find_elements(By.CSS_SELECTOR,"[data-testid]"):
            try:
                if el.is_displayed():
                    tid=el.get_attribute("data-testid")
                    txt=compact(el.text)
                    item=(tid,txt[:180],el.tag_name)
                    if item in seen: continue
                    seen.add(item)
                    if "participant" in (tid or "").lower() or "room" in (tid or "").lower() or "child" in (tid or "").lower() or "adult" in (tid or "").lower():
                        print(repr({"tag":el.tag_name,"testid":tid,"text":txt[:300],"html":el.get_attribute("outerHTML")[:900]}))
            except: pass

        print("BUTTONS")
        n=0
        for el in d.find_elements(By.TAG_NAME,"button"):
            try:
                if el.is_displayed():
                    txt=compact(el.text); aria=compact(el.get_attribute("aria-label"))
                    if txt or aria:
                        print(repr({"text":txt[:250],"aria":aria[:250],"testid":el.get_attribute("data-testid")}))
                        n+=1
                        if n>=160: break
            except: pass
        try:
            births=[b for b in d.find_elements(By.CSS_SELECTOR,"button[data-testid='birth-date-button']") if b.is_displayed()]
            print("BIRTH_BUTTON_COUNT",len(births))
            pick_birth_date(d,0,2021,8,24)
            pick_birth_date(d,1,2019,8,24)
            print("BIRTH_VALUES",[compact(x.text) for x in d.find_elements(By.CSS_SELECTOR,"button[data-testid='birth-date-button']") if x.is_displayed()])
            submit=d.find_element(By.CSS_SELECTOR,"button[data-testid='dropdown-window-button-submit']")
            d.execute_script("arguments[0].click();",submit)
            time.sleep(1.0)
            print("PARTICIPANTS_CONFIRMED",compact(d.find_element(By.CSS_SELECTOR,"button[data-testid='dropdown-field--participants']").text))
            search=d.find_element(By.CSS_SELECTOR,"button[data-testid='global-search-button-submit']")
            d.execute_script("arguments[0].click();",search)
            time.sleep(6)
            print("SEARCHED_URL",d.current_url)
        except Exception as e:
            print("SET_FAMILY_ERROR",type(e).__name__,str(e)[:300])

        print("BIRTH_PICKER_TESTIDS")
        for el in d.find_elements(By.CSS_SELECTOR,"[data-testid]"):
            try:
                if el.is_displayed():
                    tid=(el.get_attribute("data-testid") or "")
                    if any(k in tid.lower() for k in ["birth","date","calendar","year","month","day"]):
                        print(repr({"tag":el.tag_name,"testid":tid,"text":compact(el.text)[:250],"value":el.get_attribute("value"),"html":el.get_attribute("outerHTML")[:1200]}))
            except: pass

        print("AGE_CONTROLS_AFTER_CHILDREN")
        for el in d.find_elements(By.CSS_SELECTOR,"[data-testid]"):
            try:
                if el.is_displayed():
                    tid=(el.get_attribute("data-testid") or "")
                    if any(k in tid.lower() for k in ["age","child","children"]):
                        print(repr({"tag":el.tag_name,"testid":tid,"text":compact(el.text)[:250],"value":el.get_attribute("value"),"html":el.get_attribute("outerHTML")[:1200]}))
            except: pass

        print("SELECTS")
        for el in d.find_elements(By.TAG_NAME,"select"):
            try:
                if el.is_displayed():
                    print(repr({
                      "name":el.get_attribute("name"),
                      "aria":el.get_attribute("aria-label"),
                      "value":el.get_attribute("value"),
                      "html":el.get_attribute("outerHTML")[:800],
                    }))
            except: pass

        body=d.find_element(By.TAG_NAME,"body").text
        print("LINES")
        for line in [x.strip() for x in body.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["uczest","doros","dzieci","wylot","pobyt","all inclusive","warszawa","radom"]):
                print(line)
        # TUI defaults to per-person prices. Force full family price mode.
        try:
            full_url=d.current_url.replace("fullPrice=false","fullPrice=true")
            print("FULL_PRICE_URL",full_url)
            d.get(full_url)
            WebDriverWait(d,40).until(lambda x:x.execute_script("return document.readyState")=="complete")
            time.sleep(5)
            print("FULL_PRICE_FINAL_URL",d.current_url)
        except Exception as e:
            print("FULL_PRICE_ERROR",type(e).__name__,str(e)[:200])

        print("OFFER_TILES_AFTER_FAMILY")
        tiles=d.find_elements(By.CSS_SELECTOR,"[data-testid='offer-tile']")
        print("TILE_COUNT",len(tiles))
        for tile in tiles[:12]:
            try:
                print(repr({
                  "text":compact(tile.text)[:1800],
                  "html":tile.get_attribute("outerHTML")[:2500],
                }))
            except: pass

        d.save_screenshot("tui-diagnostic.png")
    finally:
        d.quit()
if __name__=="__main__":
    main()
